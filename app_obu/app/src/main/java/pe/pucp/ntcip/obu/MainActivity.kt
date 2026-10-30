package pe.pucp.ntcip.obu

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import pe.pucp.ntcip.obu.databinding.ActivityMainBinding
import pe.pucp.ntcip.obu.obu.BateriaUtils
import pe.pucp.ntcip.obu.obu.EstadoSesion
import pe.pucp.ntcip.obu.obu.ObuSessionRepository
import pe.pucp.ntcip.obu.obu.ObuSessionService
import pe.pucp.ntcip.obu.obu.Prefs
import pe.pucp.ntcip.obu.obu.textoEstadoNatural
import pe.pucp.ntcip.obu.velocidad.EstadoGnss
import pe.pucp.ntcip.obu.velocidad.FuenteGnss
import pe.pucp.ntcip.obu.velocidad.FuentePosicion
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada

/**
 * Pantalla única (docs/CONTRATO_OBU.md §6: nada más mientras hay misión).
 * Mientras no hay misión, esta Activity trackea su propia posición (para
 * centrar el mapa y permitir elegir destino); al iniciar, esa tarea pasa a
 * ObuSessionService y esta Activity solo observa ObuSessionRepository.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var destinoMarker: Marker? = null
    private var posicionMarker: Marker? = null
    private var rutaPolyline: Polyline? = null
    private var destinoElegido: GeoPoint? = null
    private var jobFuenteIdle: Job? = null

    private val pedirPermisos = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (!ObuSessionRepository.estado.value.misionActiva) iniciarSeguimientoIdle()
        aplicarEstado(ObuSessionRepository.estado.value)
    }

    // Mismo selector de archivo que Ajustes (misma preferencia trayectoriaUri).
    private val elegirTrayectoria = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            Prefs(this).trayectoriaUri = uri.toString()
            actualizarTextoTrayectoria()
            reiniciarPosicionIdle()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.mapa.setTileSource(TileSourceFactory.MAPNIK)
        binding.mapa.setMultiTouchControls(true)
        binding.mapa.controller.setZoom(16.0)
        binding.mapa.controller.setCenter(GeoPoint(-12.0931, -77.0865)) // San Miguel, Lima -- solo posición inicial de la cámara

        val eventosMapa = object : MapEventsReceiver {
            override fun singleTapConfirmedHelper(p: GeoPoint): Boolean {
                if (!ObuSessionRepository.estado.value.misionActiva) elegirDestino(p)
                return true
            }
            override fun longPressHelper(p: GeoPoint) = false
        }
        binding.mapa.overlays.add(MapEventsOverlay(eventosMapa))

        binding.botonAjustes.setOnClickListener { startActivity(Intent(this, AjustesActivity::class.java)) }
        binding.botonAccion.setOnClickListener { onBotonAccion() }
        binding.selectorFuente.addOnButtonCheckedListener { _, id, marcado ->
            if (marcado) cambiarFuente(simulado = id == R.id.opcionEmulada)
        }
        binding.botonCambiarTrayectoria.setOnClickListener { elegirTrayectoria.launch(arrayOf("*/*")) }

        pedirPermisosSiFalta()
        if (BateriaUtils.tieneRestriccion(this)) mostrarAvisoBateria()
    }

    override fun onResume() {
        super.onResume()
        binding.mapa.onResume()
        // La preferencia también se cambia desde Ajustes ("Modo simulado").
        binding.selectorFuente.check(if (Prefs(this).modoSimulado) R.id.opcionEmulada else R.id.opcionGps)
        actualizarTextoTrayectoria()
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                ObuSessionRepository.estado.collect { aplicarEstado(it) }
            }
        }
        if (!ObuSessionRepository.estado.value.misionActiva) iniciarSeguimientoIdle()
    }

    override fun onPause() {
        super.onPause()
        binding.mapa.onPause()
        jobFuenteIdle?.cancel()
    }

    // --- Fuente de posición: Ruta emulada / GPS real ----------------------

    private fun cambiarFuente(simulado: Boolean) {
        val prefs = Prefs(this)
        if (prefs.modoSimulado == simulado) return // check() programático desde onResume
        prefs.modoSimulado = simulado
        if (!simulado && !permisosUbicacionOk()) pedirPermisosSiFalta()
        reiniciarPosicionIdle()
    }

    /** La posición de la fuente anterior no sirve como origen de la nueva. */
    private fun reiniciarPosicionIdle() {
        if (ObuSessionRepository.estado.value.misionActiva) return
        jobFuenteIdle?.cancel()
        ObuSessionRepository.actualizar { it.copy(ultimaPosicion = null, estadoGnss = EstadoGnss.Inactivo) }
        iniciarSeguimientoIdle()
    }

    private fun actualizarTextoTrayectoria() {
        val uri = Prefs(this).trayectoriaUri?.let(Uri::parse)
        binding.textoTrayectoria.text = getString(R.string.trayectoria_actual, FuenteSimulada.nombreVisible(this, uri))
    }

    // --- Posición mientras no hay misión ---------------------------------

    private fun iniciarSeguimientoIdle() {
        jobFuenteIdle?.cancel()
        val prefs = Prefs(this)
        // El permiso de ubicación solo hace falta para el GNSS real: el
        // modo simulado (sin GNSS, ver Ajustes) no debe depender de él --
        // si se exigiera aquí, un permiso denegado o todavía no concedido
        // dejaría la trayectoria simulada sin arrancar nunca, y el botón
        // "Iniciar emergencia" nunca se habilitaría pese a estar en modo
        // simulado.
        val fuente: FuentePosicion = if (prefs.modoSimulado) {
            FuenteSimulada(this, prefs.trayectoriaUri?.let(Uri::parse))
        } else {
            if (!permisosUbicacionOk()) return
            FuenteGnss(this)
        }
        jobFuenteIdle = lifecycleScope.launch {
            if (fuente is FuenteGnss) {
                launch { fuente.estado.collect { e -> ObuSessionRepository.actualizar { it.copy(estadoGnss = e) } } }
            }
            fuente.muestras.collect { m ->
                ObuSessionRepository.actualizar { it.copy(ultimaPosicion = m.lat to m.lon) }
            }
        }
    }

    // --- Mapa --------------------------------------------------------------

    private fun elegirDestino(p: GeoPoint) {
        destinoElegido = p
        destinoMarker?.let { binding.mapa.overlays.remove(it) }
        val marcador = Marker(binding.mapa).apply {
            position = p
            title = "Destino"
        }
        binding.mapa.overlays.add(marcador)
        destinoMarker = marcador
        binding.mapa.invalidate()
        actualizarBotonAccion()
        binding.textoPedirDestino.visibility = View.GONE
    }

    private fun aplicarEstado(estado: EstadoSesion) {
        if (estado.ultimaPosicion == null) {
            posicionMarker?.let { binding.mapa.overlays.remove(it); binding.mapa.invalidate() }
            posicionMarker = null
        }
        estado.ultimaPosicion?.let { (lat, lon) ->
            val p = GeoPoint(lat, lon)
            val marcador = posicionMarker ?: Marker(binding.mapa).also {
                it.title = "Posición actual"
                binding.mapa.overlays.add(it)
                posicionMarker = it
            }
            marcador.position = p
            binding.mapa.controller.animateTo(p)
            binding.mapa.invalidate()
        }

        estado.ultimaRuta?.let { mr ->
            rutaPolyline?.let { binding.mapa.overlays.remove(it) }
            val linea = Polyline().apply { setPoints(mr.geometria.map { GeoPoint(it[0], it[1]) }) }
            binding.mapa.overlays.add(linea)
            rutaPolyline = linea
            binding.mapa.invalidate()
        }

        val proximo = estado.ultimoEstado?.proximo
        when {
            proximo != null -> {
                binding.tarjetaProximo.visibility = View.VISIBLE
                binding.proximoTitulo.text = "RSU ${proximo.rsu_id} · ${proximo.interseccion_id} (${proximo.acceso_id})"
                binding.proximoEstado.text = textoEstadoNatural(proximo.estado)
                binding.proximoEstado.setBackgroundColor(colorEstado(proximo.estado))
                binding.proximoEta.text = proximo.eta_s?.let { "ETA %.0f s".format(it) } ?: ""
            }
            estado.misionActiva -> {
                binding.tarjetaProximo.visibility = View.VISIBLE
                binding.proximoTitulo.text = ""
                binding.proximoEstado.text = getString(R.string.sin_proximo_semaforo)
                binding.proximoEstado.setBackgroundColor(ContextCompat.getColor(this, R.color.estado_desconocido))
                binding.proximoEta.text = ""
            }
            else -> binding.tarjetaProximo.visibility = View.GONE
        }

        binding.avisoSinConexion.visibility = if (estado.misionActiva && estado.sinConexionServidor) View.VISIBLE else View.GONE
        binding.avisoSinFix.visibility = if (estado.misionActiva && estado.sinFixGnss) View.VISIBLE else View.GONE

        // Nada más en pantalla mientras hay misión (docs/CONTRATO_OBU.md §6).
        binding.botonAjustes.visibility = if (estado.misionActiva) View.GONE else View.VISIBLE
        aplicarIndicadoresFuente(estado)
        binding.textoPedirDestino.visibility = if (!estado.misionActiva && destinoElegido == null) View.VISIBLE else View.GONE

        actualizarBotonAccion(estado)
    }

    /** Selector + estado GNSS sin misión; indicador discreto con misión. */
    private fun aplicarIndicadoresFuente(estado: EstadoSesion) {
        val simulado = Prefs(this).modoSimulado
        binding.panelFuente.visibility = if (estado.misionActiva) View.GONE else View.VISIBLE
        binding.filaTrayectoria.visibility = if (simulado) View.VISIBLE else View.GONE
        binding.textoEstadoGnss.visibility = if (simulado) View.GONE else View.VISIBLE
        if (!simulado) {
            val (texto, color) = if (!permisosUbicacionOk()) {
                getString(R.string.gnss_sin_permiso) to R.color.estado_cancelada
            } else {
                when (val e = estado.estadoGnss) {
                    is EstadoGnss.Listo -> getString(R.string.gnss_listo, e.precisionM) to R.color.gnss_listo
                    is EstadoGnss.PrecisionInsuficiente -> {
                        val t = if (e.precisionM == null) getString(R.string.gnss_sin_precision, e.maximaM)
                        else getString(R.string.gnss_precision_insuficiente, e.precisionM, e.maximaM)
                        t to R.color.gnss_esperando
                    }
                    EstadoGnss.Buscando, EstadoGnss.Inactivo -> getString(R.string.gnss_buscando) to R.color.gnss_buscando
                }
            }
            binding.textoEstadoGnss.text = texto
            binding.textoEstadoGnss.setBackgroundColor(ContextCompat.getColor(this, color))
        }

        binding.indicadorFuente.visibility = if (estado.misionActiva) View.VISIBLE else View.GONE
        if (estado.misionActiva) {
            val gnss = estado.estadoGnss
            val (texto, color) = when {
                simulado -> getString(R.string.indicador_emulada) to R.color.fuente_emulada
                gnss is EstadoGnss.Listo -> getString(R.string.indicador_gps, gnss.precisionM) to R.color.gnss_listo
                gnss is EstadoGnss.PrecisionInsuficiente && gnss.precisionM != null ->
                    getString(R.string.indicador_gps, gnss.precisionM) to R.color.gnss_esperando
                else -> getString(R.string.indicador_gps_sin_fix) to R.color.estado_cancelada
            }
            binding.indicadorFuente.text = texto
            binding.indicadorFuente.setBackgroundColor(ContextCompat.getColor(this, color))
        }
    }

    private fun actualizarBotonAccion(estado: EstadoSesion = ObuSessionRepository.estado.value) {
        if (estado.misionActiva) {
            binding.botonAccion.text = getString(R.string.boton_terminar)
            binding.botonAccion.setBackgroundColor(ContextCompat.getColor(this, R.color.boton_terminar))
            binding.botonAccion.isEnabled = true
        } else {
            // Con GPS real, solo con un fix que pase el criterio de
            // EvaluadorFixGnss AHORA -- ultimaPosicion sola no basta: se
            // queda con el último fix bueno aunque la señal ya se haya perdido.
            val fuenteLista = Prefs(this).modoSimulado || estado.estadoGnss is EstadoGnss.Listo
            val habilitado = destinoElegido != null && estado.ultimaPosicion != null && permisosOk() && fuenteLista
            binding.botonAccion.text = getString(R.string.boton_iniciar)
            binding.botonAccion.setBackgroundColor(
                ContextCompat.getColor(this, if (habilitado) R.color.boton_iniciar else R.color.estado_desconocido),
            )
            binding.botonAccion.isEnabled = habilitado
        }
    }

    private fun onBotonAccion() {
        val estado = ObuSessionRepository.estado.value
        if (estado.misionActiva) {
            startService(Intent(this, ObuSessionService::class.java).setAction(ObuSessionService.ACCION_TERMINAR))
            destinoElegido = null
            destinoMarker?.let { binding.mapa.overlays.remove(it) }
            destinoMarker = null
        } else {
            val origen = estado.ultimaPosicion ?: return
            val destino = destinoElegido ?: return
            jobFuenteIdle?.cancel() // a partir de aquí, la posición la sigue ObuSessionService
            val intent = Intent(this, ObuSessionService::class.java).apply {
                action = ObuSessionService.ACCION_INICIAR
                putExtra(ObuSessionService.EXTRA_ORIGEN_LAT, origen.first)
                putExtra(ObuSessionService.EXTRA_ORIGEN_LON, origen.second)
                putExtra(ObuSessionService.EXTRA_DESTINO_LAT, destino.latitude)
                putExtra(ObuSessionService.EXTRA_DESTINO_LON, destino.longitude)
            }
            ContextCompat.startForegroundService(this, intent)
        }
    }

    private fun colorEstado(estado: String): Int = ContextCompat.getColor(
        this,
        when (estado) {
            "concedida" -> R.color.estado_concedida
            "en_cola", "solicitada" -> R.color.estado_en_cola
            "cancelada", "rechazada" -> R.color.estado_cancelada
            else -> R.color.estado_pendiente
        },
    )

    // --- Permisos y batería ------------------------------------------------

    private fun permisosUbicacionOk() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun permisosOk(): Boolean {
        val notifOk = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        return permisosUbicacionOk() && notifOk
    }

    private fun pedirPermisosSiFalta() {
        val faltan = mutableListOf<String>()
        if (!permisosUbicacionOk()) faltan += Manifest.permission.ACCESS_FINE_LOCATION
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            faltan += Manifest.permission.POST_NOTIFICATIONS
        }
        if (faltan.isNotEmpty()) pedirPermisos.launch(faltan.toTypedArray()) else iniciarSeguimientoIdle()
    }

    private fun mostrarAvisoBateria() {
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.ajustes_bateria_titulo))
            .setMessage(getString(R.string.ajustes_bateria_resumen))
            .setPositiveButton(getString(R.string.ajustes_bateria_boton)) { _, _ ->
                runCatching { startActivity(BateriaUtils.intentPedirSinRestricciones(this)) }
                    .onFailure { startActivity(BateriaUtils.intentDetalleApp(this)) }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }
}
