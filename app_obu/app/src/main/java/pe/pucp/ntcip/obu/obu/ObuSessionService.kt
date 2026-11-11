package pe.pucp.ntcip.obu.obu

import android.app.Notification
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import pe.pucp.ntcip.obu.MainActivity
import pe.pucp.ntcip.obu.ObuApp
import pe.pucp.ntcip.obu.R
import pe.pucp.ntcip.obu.seguridad.TlsConfig
import pe.pucp.ntcip.obu.velocidad.EstadoGnss
import pe.pucp.ntcip.obu.velocidad.FuenteGnss
import pe.pucp.ntcip.obu.velocidad.FuenteRutaServidor
import pe.pucp.ntcip.obu.velocidad.FuentePosicion
import pe.pucp.ntcip.obu.velocidad.MuestraPosicion

/**
 * Foreground service (tipo "location") que arma/desarma la misión y
 * publica MP a 1 Hz mientras está activa -- equivalente Android de
 * gateway/obu_emulada.py. No pide ACCESS_BACKGROUND_LOCATION: un
 * foreground service de tipo location, iniciado por acción del usuario,
 * basta para seguir recibiendo ubicación con la pantalla apagada (ver
 * app_obu/README.md).
 */
class ObuSessionService : LifecycleService() {

    private var mqtt: MqttObuClient? = null
    private var eventos: EventoLogger? = null
    private var obuId: String? = null
    private var misionId: String? = null

    private var seq = 0
    private var ultimoMiEnviado: MensajeMI? = null
    private var ultimaMuestra: MuestraPosicion? = null
    private var ultimaMuestraEnMs = 0L
    private var ultimoMeEnMs = 0L
    private var ultimaVersionMrAplicada = -1
    private var ultimoTsMeAplicado = -1L

    private var jobFuente: Job? = null
    private var jobEstadoGnss: Job? = null
    private var jobIndicador: Job? = null
    private var factorDemo = 1
    private var terminando = false // botón, fin de trayectoria y fin del servidor pueden coincidir: un solo cierre
    private var jobTicker: Job? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACCION_INICIAR -> iniciarMision(intent)
            ACCION_TERMINAR -> terminarPorBoton()
        }
        return START_NOT_STICKY
    }

    // --- Inicio ------------------------------------------------------------

    private fun iniciarMision(intent: Intent) {
        // Lo primero, antes de cualquier validación: un servicio lanzado con
        // startForegroundService() que no llama a startForeground() en unos
        // segundos hace que Android cierre la app
        // (ForegroundServiceDidNotStartInTimeException). Si algo falla más
        // abajo, abortarInicio() quita la notificación y explica el motivo.
        iniciarNotificacionPrimerPlano()

        val destinoLat = intent.getDoubleExtra(EXTRA_DESTINO_LAT, Double.NaN)
        val destinoLon = intent.getDoubleExtra(EXTRA_DESTINO_LON, Double.NaN)
        val origenLat = intent.getDoubleExtra(EXTRA_ORIGEN_LAT, Double.NaN)
        val origenLon = intent.getDoubleExtra(EXTRA_ORIGEN_LON, Double.NaN)
        if (destinoLat.isNaN() || destinoLon.isNaN() || origenLat.isNaN() || origenLon.isNaN()) {
            abortarInicio(null, getString(R.string.error_inicio_sin_origen_destino))
            return
        }

        val prefs = Prefs(this)

        // Etapa 3 (TLS 1.3 + mTLS, docs/CONTRATO_OBU.md §1): si está
        // activado en Ajustes pero algún PEM falta o no se puede usar, no se
        // arranca la misión sin cifrar por un error de configuración.
        val tls: TlsConfig? = if (prefs.tlsActivado) {
            when (val r = Conexion.cargarTls(this, prefs)) {
                is CargaTls.Ok -> r.config
                is CargaTls.Error -> {
                    abortarInicio(prefs, r.mensaje)
                    return
                }
            }
        } else null

        // obu_id: identidad FIJA del dispositivo (item 2b,
        // prompt_integracion_app_obu.md), igual al CN del certificado de
        // cliente -- no un id al azar por misión, que chocaba con el CN
        // fijo del certificado mTLS (ACL del broker por
        // use_identity_as_username, ver scripts/seguridad/mosquitto_acl.conf).
        // Sin TLS (broker de desarrollo), se usa el valor fijo de Ajustes.
        val nuevoObuId = tls?.commonNameCliente() ?: prefs.obuId
        obuId = nuevoObuId
        terminando = false
        misionId = null
        seq = 0
        ultimoMiEnviado = null
        ultimaMuestra = null
        ultimaVersionMrAplicada = -1
        ultimoTsMeAplicado = -1L
        ultimoMeEnMs = SystemClock.elapsedRealtime()

        val eventoLogger = EventoLogger(this, nuevoObuId)
        eventos = eventoLogger

        ObuSessionRepository.reiniciar()
        ObuSessionRepository.actualizar { it.copy(misionActiva = true, obuId = nuevoObuId, ultimaPosicion = origenLat to origenLon) }

        val cliente = MqttObuClient(
            host = prefs.brokerHost,
            port = prefs.brokerPuerto,
            obuId = nuevoObuId,
            tls = tls,
            // onRuta/onEstado llegan en un hilo interno de HiveMQ: se
            // despachan a lifecycleScope para que las mutaciones de
            // ultimaVersionMrAplicada/ultimoTsMeAplicado/ultimoMeEnMs (sin
            // lock propio) ocurran siempre en el mismo hilo, sin carreras.
            onRuta = { mr -> lifecycleScope.launch { onMensajeRuta(mr) } },
            onEstado = { me -> lifecycleScope.launch { onMensajeEstado(me) } },
            onConexion = { conectado ->
                eventoLogger.log(EventosObu.CONEXION_MQTT, "-", mapOf("estado" to if (conectado) "conectado" else "desconectado"))
                // Reconexión tras una caída (no la primera conexión: ahí
                // ultimoMiEnviado todavía es null porque el MI se envía
                // después de conectar() más abajo). El servidor ya trata un
                // MI repetido del mismo obu_id como no-op, sin duplicar la
                // misión (servidor/gestor_mision.py::armar_mision,
                // docs/CONTRATO_OBU.md §2) -- ver bitácora
                // 2026-10-29_app-obu-fix-serializacion-y-pucp.md §2.
                if (conectado && !terminando) {
                    ultimoMiEnviado?.let { mi -> lifecycleScope.launch { reenviarMiTrasReconexion(mi) } }
                }
            },
        )
        mqtt = cliente

        // Factor de demo: solo en ruta emulada. Cualquier corrida acelerada
        // queda marcada en el CSV (evento "demo" + "demo_factor" en cada
        // MP_tx) para no mezclarla con las mediciones.
        factorDemo = if (prefs.modoSimulado) prefs.factorDemo.coerceIn(1, 4) else 1
        if (factorDemo != 1) eventoLogger.log(EventosObu.DEMO, "-", mapOf("factor" to factorDemo))

        // GNSS: arranca ya (no después de conectar): conectar() puede
        // tardar varios segundos sin red, y mientras tanto el indicador de
        // la UI quedaría en "sin fix" aunque el GNSS esté listo. No publica
        // nada por sí sola -- el ticker de MP arranca después del MI. La
        // ruta emulada, en cambio, espera al MI: si arrancara antes, el
        // vehículo ya habría avanzado al publicarse el primer MP.
        if (!prefs.modoSimulado) iniciarFuentePosicion(prefs)

        // Indicador de conexión desde ya, no recién después del MI: con
        // reconexión automática, conectar() espera hasta que el broker
        // responda (sin Tailscale, broker caído...) y sin esto la pantalla
        // solo diría "Esperando la ruta" sin explicar por qué.
        jobIndicador = lifecycleScope.launch {
            while (isActive) {
                actualizarIndicadorConexion()
                delay(1000)
            }
        }

        lifecycleScope.launch {
            runCatching { cliente.conectar() }
            if (terminando) return@launch // se terminó mientras conectaba: no se arma nada
            val ahora = System.currentTimeMillis()
            val mi = MensajeMI(
                obu_id = nuevoObuId, clase = prefs.clase,
                origen = Coordenada(origenLat, origenLon),
                destino = Coordenada(destinoLat, destinoLon),
                ts_ms = ahora,
            )
            cliente.enviarMI(mi)
            ultimoMiEnviado = mi
            eventoLogger.log(EventosObu.MI_TX, "-", mapOf("clase" to prefs.clase, "destino_lat" to destinoLat, "destino_lon" to destinoLon))
            medirReloj("inicio")

            if (prefs.modoSimulado) iniciarFuentePosicion(prefs)
            iniciarTickerPublicacion()
        }
    }

    /** La misión no puede arrancar: deja constancia, avisa a la pantalla y
     * cierra el servicio limpiamente (ya está en primer plano). */
    private fun abortarInicio(prefs: Prefs?, mensaje: String) {
        prefs?.let { EventoLogger(this, it.obuId).log(EventosObu.CONEXION_MQTT, "-", mapOf("estado" to "error_tls_config", "detalle" to mensaje)) }
        ObuSessionRepository.actualizar { it.copy(misionActiva = false, errorInicio = mensaje) }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun iniciarFuentePosicion(prefs: Prefs) {
        val fuente: FuentePosicion = if (prefs.modoSimulado) {
            if (Escenarios.esRutaLibre(prefs)) {
                FuenteRutaServidor({ ObuSessionRepository.estado.value.ultimaRuta }, factor = factorDemo.toDouble())
            } else {
                Escenarios.fuente(this, prefs, factorDemo.toDouble())
            }
        } else {
            FuenteGnss(this)
        }
        jobEstadoGnss = (fuente as? FuenteGnss)?.let { gnss ->
            lifecycleScope.launch {
                launch { gnss.estado.collect { e -> ObuSessionRepository.actualizar { it.copy(estadoGnss = e) } } }
                gnss.satelites.collect { s -> ObuSessionRepository.actualizar { it.copy(satelitesGnss = s) } }
            }
        }
        jobFuente = fuente.muestras.onEach { muestra ->
            ultimaMuestra = muestra
            ultimaMuestraEnMs = SystemClock.elapsedRealtime()
            ObuSessionRepository.actualizar { it.copy(ultimaPosicion = muestra.lat to muestra.lon) }
        }.onCompletion { causa ->
            // Fin natural de la trayectoria emulada (no cancelación): la
            // misión termina sola, como gateway/obu_emulada.py.
            if (causa == null && fuente !is FuenteGnss) terminarPorFinTrayectoria()
        }.launchIn(lifecycleScope)
    }

    private fun iniciarTickerPublicacion() {
        jobTicker = lifecycleScope.launch {
            while (isActive) {
                publicarMpSiHayFix()
                delay(1000)
            }
        }
    }

    private suspend fun publicarMpSiHayFix() {
        val muestra = ultimaMuestra
        val vigente = muestra != null && (SystemClock.elapsedRealtime() - ultimaMuestraEnMs) <= UMBRAL_FIX_MS
        ObuSessionRepository.actualizar { it.copy(sinFixGnss = !vigente) }
        if (muestra == null || !vigente) return // sin fix válido: no se inventa una posición (docs/CONTRATO_OBU.md MP)

        val idActual = obuId ?: return
        seq += 1
        val mp = MensajeMP(
            obu_id = idActual, lat = muestra.lat, lon = muestra.lon,
            velocidad_kmh = muestra.velocidadKmh, rumbo_deg = muestra.rumboDeg,
            fuente_velocidad = muestra.fuenteVelocidad, ts_ms = System.currentTimeMillis(), seq = seq,
        )
        mqtt?.enviarMP(mp)
        eventos?.log(
            EventosObu.MP_TX, "-",
            mapOf(
                "seq" to seq, "lat" to mp.lat, "lon" to mp.lon,
                "velocidad_kmh" to mp.velocidad_kmh, "rumbo_deg" to mp.rumbo_deg,
                // No van en el MP del contrato (solo informativos, en el
                // registro de eventos de la app): precision_m del fix GNSS
                // (null en modo simulado) y si el rumbo de este MP fue
                // medido o heredado del último real conocido -- ver
                // FuenteGnss/EvaluadorFixGnss.
                "precision_m" to muestra.precisionM, "rumbo_medido" to muestra.rumboMedido,
            ) + (if (factorDemo != 1) mapOf("demo_factor" to factorDemo) else emptyMap()),
        )
    }

    private suspend fun reenviarMiTrasReconexion(mi: MensajeMI) {
        val miReenviado = mi.copy(ts_ms = System.currentTimeMillis())
        mqtt?.enviarMI(miReenviado)
        eventos?.log(
            EventosObu.MI_TX, "-",
            mapOf("clase" to miReenviado.clase, "destino_lat" to miReenviado.destino.lat,
                "destino_lon" to miReenviado.destino.lon, "reenvio" to true),
        )
        // Los MP se reanudan solos: el ticker de iniciarTickerPublicacion()
        // nunca se detuvo (sigue en su propio while(isActive)) y
        // MqttObuClient ya vuelve a publicar en cuanto HiveMQ reconecta.
    }

    private fun actualizarIndicadorConexion() {
        val sinConexion = (SystemClock.elapsedRealtime() - ultimoMeEnMs) > UMBRAL_SIN_CONEXION_MS
        ObuSessionRepository.actualizar { it.copy(sinConexionServidor = sinConexion) }
    }

    // --- MR / ME -------------------------------------------------------

    private fun onMensajeRuta(mr: MensajeMR) {
        if (mr.mision_id != misionId) {
            // mision_id distinto (p. ej. el servidor cerro la anterior por
            // un MI con otro destino, ver gestor_mision.py::armar_mision):
            // su version empieza de nuevo en 1, así que el guardado de la
            // misión vieja no debe compararse contra ella.
            ultimaVersionMrAplicada = -1
        }
        misionId = mr.mision_id
        eventos?.log(EventosObu.MR_RX, mr.mision_id, mapOf("n_paradas" to mr.paradas.size, "longitud_m" to mr.longitud_total_m))
        // Un MR nuevo reemplaza al anterior (docs/CONTRATO_OBU.md §4): se
        // ignora si llega una versión igual o anterior a la ya aplicada.
        if (mr.version <= ultimaVersionMrAplicada) return
        ultimaVersionMrAplicada = mr.version
        ObuSessionRepository.actualizar { it.copy(ultimaRuta = mr) }
    }

    private fun onMensajeEstado(me: MensajeME) {
        ultimoMeEnMs = SystemClock.elapsedRealtime()
        eventos?.log(
            EventosObu.ME_RX, me.mision_id,
            mapOf("proximo" to me.proximo?.let {
                mapOf("interseccion_id" to it.interseccion_id, "rsu_id" to it.rsu_id, "estado" to it.estado, "eta_s" to it.eta_s, "fase" to it.fase)
            }, "conflicto" to me.conflicto),
        )
        // ts_ms no sube si es un ME repetido/desordenado -- a diferencia de
        // MR no hay campo "version", así que se descarta por marca de tiempo.
        if (me.ts_ms <= ultimoTsMeAplicado) return
        ultimoTsMeAplicado = me.ts_ms
        ObuSessionRepository.actualizar { it.copy(ultimoEstado = me) }

        // mision_activa/motivo_fin: implementados en servidor/gestor_mision.py
        // desde B3 (app_obu/PROPUESTA_FIN_MISION.md) -- cierre por destino o
        // tiempo máximo, reflejado aquí. terminarPorServidor() ya es
        // idempotente (guard `terminando`): si el usuario pulsa "Terminar"
        // justo después de un cierre automático, no envía un MF de más.
        if (me.mision_activa == false) {
            terminarPorServidor(me.motivo_fin ?: "desconocido")
        }
    }

    // --- Fin de misión ---------------------------------------------------

    private fun terminarPorBoton() {
        if (terminando) return
        terminando = true
        val idActual = obuId ?: run { stopSelf(); return }
        lifecycleScope.launch {
            mqtt?.enviarMF(MensajeMF(obu_id = idActual, motivo = "boton", ts_ms = System.currentTimeMillis()))
            eventos?.log(EventosObu.MF_TX, "-", mapOf("motivo" to "boton"))
            medirReloj("fin")
            finalizarLocal()
        }
    }

    private fun terminarPorFinTrayectoria() {
        if (terminando) return
        terminando = true
        val idActual = obuId ?: return
        lifecycleScope.launch {
            // Unos MP más en la última posición (sigue "vigente" por
            // UMBRAL_FIX_MS) para que el servidor procese el cruce final.
            delay(ESPERA_FIN_TRAYECTORIA_MS)
            mqtt?.enviarMF(MensajeMF(obu_id = idActual, motivo = "destino", ts_ms = System.currentTimeMillis()))
            eventos?.log(EventosObu.MF_TX, "-", mapOf("motivo" to "destino"))
            ObuSessionRepository.actualizar { it.copy(motivoFinReciente = "destino") }
            medirReloj("fin")
            finalizarLocal()
        }
    }

    private fun terminarPorServidor(motivo: String) {
        if (terminando) return
        terminando = true
        ObuSessionRepository.actualizar { it.copy(motivoFinReciente = motivo) }
        lifecycleScope.launch {
            medirReloj("fin")
            finalizarLocal()
        }
    }

    private suspend fun finalizarLocal() {
        jobTicker?.cancel()
        jobFuente?.cancel()
        jobEstadoGnss?.cancel()
        jobIndicador?.cancel()
        mqtt?.desconectar()
        // Ruta, estados y GNSS de esta misión ya no sirven en la pantalla de
        // inicio; motivoFinReciente se conserva para avisarlo.
        ObuSessionRepository.actualizar {
            it.copy(misionActiva = false, ultimaRuta = null, ultimoEstado = null, sinFixGnss = false,
                sinConexionServidor = false, estadoGnss = EstadoGnss.Inactivo, ultimaPosicion = null)
        }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun medirReloj(momento: String) {
        val logger = eventos ?: return
        lifecycleScope.launch {
            val r = SntpCliente.consultar()
            if (r != null) {
                logger.log(EventosObu.RELOJ_SNTP, "-", mapOf("servidor" to r.servidor, "offset_ms" to r.offsetMs, "rtt_ms" to r.rttMs, "momento" to momento))
            }
        }
    }

    // --- Notificación ----------------------------------------------------

    private fun iniciarNotificacionPrimerPlano() {
        val abrirApp = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val notificacion: Notification = NotificationCompat.Builder(this, ObuApp.CANAL_MISION)
            .setContentTitle(getString(R.string.notificacion_titulo))
            .setContentText(getString(R.string.notificacion_cuerpo))
            .setSmallIcon(R.drawable.ic_notificacion)
            .setContentIntent(abrirApp)
            .setOngoing(true)
            .build()
        ServiceCompat.startForeground(
            this, NOTIFICACION_ID, notificacion,
            android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
        )
    }

    override fun onDestroy() {
        jobTicker?.cancel()
        jobFuente?.cancel()
        jobEstadoGnss?.cancel()
        jobIndicador?.cancel()
        super.onDestroy()
    }

    companion object {
        const val ACCION_INICIAR = "pe.pucp.ntcip.obu.INICIAR"
        const val ACCION_TERMINAR = "pe.pucp.ntcip.obu.TERMINAR"
        const val EXTRA_DESTINO_LAT = "destino_lat"
        const val EXTRA_DESTINO_LON = "destino_lon"
        const val EXTRA_ORIGEN_LAT = "origen_lat"
        const val EXTRA_ORIGEN_LON = "origen_lon"

        private const val NOTIFICACION_ID = 1
        private const val UMBRAL_FIX_MS = 2500L
        private const val UMBRAL_SIN_CONEXION_MS = 5000L
        private const val ESPERA_FIN_TRAYECTORIA_MS = 2000L
    }
}
