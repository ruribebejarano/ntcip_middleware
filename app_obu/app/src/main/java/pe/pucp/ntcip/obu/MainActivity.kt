package pe.pucp.ntcip.obu

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import pe.pucp.ntcip.obu.databinding.ActivityMainBinding
import pe.pucp.ntcip.obu.obu.BateriaUtils
import pe.pucp.ntcip.obu.obu.Destino
import pe.pucp.ntcip.obu.obu.Escenarios
import pe.pucp.ntcip.obu.obu.EstadoSesion
import pe.pucp.ntcip.obu.obu.EstadoVisual
import pe.pucp.ntcip.obu.obu.GeometriaRuta
import pe.pucp.ntcip.obu.obu.Hospital
import pe.pucp.ntcip.obu.obu.MensajeMR
import pe.pucp.ntcip.obu.obu.ObuSessionRepository
import pe.pucp.ntcip.obu.obu.ObuSessionService
import pe.pucp.ntcip.obu.obu.ParadaEstado
import pe.pucp.ntcip.obu.obu.Prefs
import pe.pucp.ntcip.obu.obu.VistaMision
import pe.pucp.ntcip.obu.velocidad.EstadoGnss
import pe.pucp.ntcip.obu.velocidad.FuenteGnss
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada
import pe.pucp.ntcip.obu.velocidad.Recorrido

/**
 * Pantalla única (docs/CONTRATO_OBU.md §6: nada más mientras hay misión).
 * Mapa a la izquierda y panel a la derecha (en vertical, panel debajo).
 * Mientras no hay misión, esta Activity sigue su propia posición (GNSS
 * real, o el primer punto quieto de la ruta emulada) para centrar el mapa
 * y servir de origen; al iniciar, esa tarea pasa a ObuSessionService y
 * esta Activity solo observa ObuSessionRepository.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var destinoMarker: Marker? = null
    private var posicionMarker: Marker? = null
    private var rutaPolyline: Polyline? = null
    private val marcadoresRsu = mutableMapOf<String, Marker>()
    private var geometria: GeometriaRuta? = null
    private var rutaDibujada: MensajeMR? = null
    private var destinoElegido: Destino? = null
    private var jobFuenteIdle: Job? = null
    private var siguiendo = true
    private var misionActivaAntes = false
    private val verdesAvisados = mutableSetOf<String>()
    private val marcadoresZona = mutableListOf<Marker>()
    private var aproximadaMarker: Marker? = null
    private var ubicacionAproximada: Pair<Double, Double>? = null
    private var firmaTira: List<Pair<String, EstadoVisual>>? = null

    private val pedirPermisos = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (!ObuSessionRepository.estado.value.misionActiva) iniciarSeguimientoIdle()
        aplicarEstado(ObuSessionRepository.estado.value)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = Prefs(this)
        aplicarOrientacion(resources.configuration)

        binding.mapa.setTileSource(TileSourceFactory.MAPNIK)
        binding.mapa.setMultiTouchControls(true)
        binding.mapa.controller.setZoom(16.0)
        binding.mapa.controller.setCenter(GeoPoint(-12.0931, -77.0865)) // San Miguel, Lima -- solo posición inicial de la cámara

        val eventosMapa = object : MapEventsReceiver {
            override fun singleTapConfirmedHelper(p: GeoPoint) = false
            override fun longPressHelper(p: GeoPoint): Boolean {
                if (!ObuSessionRepository.estado.value.misionActiva) alPulsarMapa(p)
                return true
            }
        }
        binding.mapa.overlays.add(MapEventsOverlay(eventosMapa))
        dibujarCapasZona()
        configurarSeguimientoMapa()

        binding.botonAjustes.setOnClickListener { startActivity(Intent(this, AjustesActivity::class.java)) }
        binding.botonAccion.setOnClickListener { onBotonAccion() }
        binding.botonCentrar.setOnClickListener { volverASeguir() }
        binding.botonDestinos.setOnClickListener { elegirDestinoPredefinido() }
        binding.selectorFuente.addOnButtonCheckedListener { _, id, marcado ->
            if (marcado) cambiarFuente(simulado = id == R.id.opcionEmulada)
        }
        binding.selectorFactor.addOnButtonCheckedListener { _, id, marcado ->
            if (marcado) prefs.factorDemo = when (id) { R.id.factor2 -> 2; R.id.factor4 -> 4; else -> 1 }
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                ObuSessionRepository.estado.collect { aplicarEstado(it) }
            }
        }

        pedirPermisosSiFalta()
        if (BateriaUtils.tieneRestriccion(this)) mostrarAvisoBateria()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        aplicarOrientacion(newConfig)
    }

    override fun onResume() {
        super.onResume()
        binding.mapa.onResume()
        // Ajustes puede haber cambiado el modo o la trayectoria.
        binding.selectorFuente.check(if (prefs.modoSimulado) R.id.opcionEmulada else R.id.opcionGps)
        binding.selectorFactor.check(when (prefs.factorDemo) { 2 -> R.id.factor2; 4 -> R.id.factor4; else -> R.id.factor1 })
        construirChipsEscenario()
        if (prefs.modoSimulado && destinoElegido == null) Escenarios.actual(this, prefs)?.let { fijarDestino(it.destino) }
        actualizarTextoOrigen()
        if (!ObuSessionRepository.estado.value.misionActiva) iniciarSeguimientoIdle()
    }

    override fun onPause() {
        super.onPause()
        binding.mapa.onPause()
        jobFuenteIdle?.cancel()
    }

    /** Panel a la derecha en horizontal, debajo en vertical. */
    private fun aplicarOrientacion(config: Configuration) {
        val horizontal = config.orientation == Configuration.ORIENTATION_LANDSCAPE
        binding.raiz.orientation = if (horizontal) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
        binding.contenedorMapa.layoutParams = if (horizontal) {
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f)
        } else {
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        binding.panelLateral.layoutParams = if (horizontal) {
            LinearLayout.LayoutParams(dp(380), LinearLayout.LayoutParams.MATCH_PARENT)
        } else {
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (resources.displayMetrics.heightPixels * 0.45).toInt())
        }
    }

    // --- Fuente de posición: Ruta emulada / GPS real ----------------------

    private fun cambiarFuente(simulado: Boolean) {
        if (prefs.modoSimulado == simulado) return // check() programático desde onResume
        prefs.modoSimulado = simulado
        if (!simulado && !permisosUbicacionOk()) pedirPermisosSiFalta()
        if (simulado) Escenarios.actual(this, prefs)?.let { fijarDestino(it.destino) }
        reiniciarPosicionIdle()
    }

    private fun construirChipsEscenario() {
        val grupo = binding.grupoEscenarios
        grupo.setOnCheckedStateChangeListener(null)
        grupo.removeAllViews()
        val actual = Escenarios.idActual(this, prefs)
        val opciones = (listOf(Escenarios.ID_RUTA_LIBRE to getString(R.string.escenario_ruta_libre)) +
            Escenarios.lista(this).map { it.id to it.nombre }).toMutableList()
        if (prefs.trayectoriaUri != null) {
            val nombreArchivo = FuenteSimulada.nombreVisible(this, Uri.parse(prefs.trayectoriaUri))
            opciones += Escenarios.ID_ARCHIVO to getString(R.string.escenario_archivo, nombreArchivo)
        }
        for ((id, nombre) in opciones) {
            val chip = Chip(this).apply {
                text = nombre
                isCheckable = true
                tag = id
                this.id = View.generateViewId()
                isChecked = id == actual
            }
            grupo.addView(chip)
        }
        grupo.setOnCheckedStateChangeListener { g, ids ->
            val id = ids.firstOrNull()?.let { g.findViewById<Chip>(it)?.tag as? String } ?: return@setOnCheckedStateChangeListener
            if (id == Escenarios.idActual(this, prefs)) return@setOnCheckedStateChangeListener
            prefs.escenarioId = id
            Escenarios.porId(this, id)?.let { fijarDestino(it.destino); centrarEn(GeoPoint(it.destino.lat, it.destino.lon)) }
            actualizarTextoOrigen()
            reiniciarPosicionIdle()
        }
    }

    /** La posición de la fuente anterior no sirve como origen de la nueva. */
    private fun reiniciarPosicionIdle() {
        if (ObuSessionRepository.estado.value.misionActiva) return
        jobFuenteIdle?.cancel()
        ObuSessionRepository.actualizar { it.copy(ultimaPosicion = null, estadoGnss = EstadoGnss.Inactivo) }
        siguiendo = true
        iniciarSeguimientoIdle()
    }

    // --- Posición mientras no hay misión ---------------------------------

    private fun iniciarSeguimientoIdle() {
        jobFuenteIdle?.cancel()
        // Ruta emulada: el vehículo queda QUIETO en el primer punto hasta
        // "Iniciar emergencia" (ObuSessionService reproduce desde ahí). No
        // depende del permiso de ubicación.
        quitarUbicacionAproximada()
        if (prefs.modoSimulado && Escenarios.esRutaLibre(prefs)) {
            val o = origenLibre()
            ObuSessionRepository.actualizar { it.copy(ultimaPosicion = o.lat to o.lon) }
            return
        }
        if (prefs.modoSimulado) {
            jobFuenteIdle = lifecycleScope.launch {
                val inicio = withContext(Dispatchers.IO) {
                    runCatching { Escenarios.fuente(this@MainActivity, prefs).primerPunto() }.getOrNull()
                }
                if (inicio == null) {
                    Toast.makeText(this@MainActivity, "No se pudo leer la trayectoria", Toast.LENGTH_LONG).show()
                } else {
                    ObuSessionRepository.actualizar { it.copy(ultimaPosicion = inicio.lat to inicio.lon) }
                }
            }
            return
        }
        if (!permisosUbicacionOk()) return
        val fuente = FuenteGnss(this)
        jobFuenteIdle = lifecycleScope.launch {
            launch { fuente.estado.collect { e -> ObuSessionRepository.actualizar { it.copy(estadoGnss = e) } } }
            launch { fuente.satelites.collect { s -> ObuSessionRepository.actualizar { it.copy(satelitesGnss = s) } } }
            fuente.muestras.collect { m ->
                ObuSessionRepository.actualizar { it.copy(ultimaPosicion = m.lat to m.lon) }
            }
        }
        seguirUbicacionAproximada(jobFuenteIdle!!)
    }

    /**
     * Ubicación aproximada por red (Wi-Fi/antenas), SOLO para mostrar en el
     * mapa mientras el GPS busca señal: nunca es origen del MI ni va en un
     * MP (el contrato exige GNSS real, ver FuenteGnss).
     */
    @SuppressLint("MissingPermission") // solo se llama con ACCESS_FINE_LOCATION concedido
    private fun seguirUbicacionAproximada(job: Job) {
        val lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (!lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) return
        val listener = LocationListener { loc: Location -> mostrarUbicacionAproximada(loc.latitude, loc.longitude) }
        lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { mostrarUbicacionAproximada(it.latitude, it.longitude) }
        lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 5000L, 0f, listener)
        job.invokeOnCompletion { lm.removeUpdates(listener) }
    }

    private fun mostrarUbicacionAproximada(lat: Double, lon: Double) {
        ubicacionAproximada = lat to lon
        val m = aproximadaMarker ?: Marker(binding.mapa).also {
            it.title = getString(R.string.ubicacion_aproximada)
            it.icon = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.argb(90, 120, 120, 120))
                setStroke(dp(2), Color.GRAY)
                setSize(dp(40), dp(40))
            }
            it.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
            binding.mapa.overlays.add(it)
            aproximadaMarker = it
        }
        m.position = GeoPoint(lat, lon)
        // Sin fix GPS todavía: centrar en la aproximada para que se vea dónde está la tablet.
        if (siguiendo && ObuSessionRepository.estado.value.ultimaPosicion == null) binding.mapa.controller.animateTo(m.position)
        binding.mapa.invalidate()
        aplicarPanelInicio(ObuSessionRepository.estado.value)
    }

    private fun quitarUbicacionAproximada() {
        aproximadaMarker?.let { binding.mapa.overlays.remove(it) }
        aproximadaMarker = null
        ubicacionAproximada = null
    }

    // --- Ruta libre: origen elegido en el mapa ------------------------------

    private fun origenLibre(): Destino = prefs.origenLibre ?: Escenarios.base(this)

    private fun actualizarTextoOrigen() {
        val libre = Escenarios.esRutaLibre(prefs)
        binding.textoOrigen.visibility = if (libre) View.VISIBLE else View.GONE
        if (libre) binding.textoOrigen.text = getString(R.string.origen_libre, origenLibre().nombre)
    }

    private fun alPulsarMapa(p: GeoPoint) {
        val punto = Destino(getString(R.string.destino_punto, p.latitude, p.longitude), p.latitude, p.longitude)
        if (!(prefs.modoSimulado && Escenarios.esRutaLibre(prefs))) {
            confirmarDestino(p)
            return
        }
        AlertDialog.Builder(this)
            .setTitle(punto.nombre)
            .setItems(arrayOf(getString(R.string.destino_aqui), getString(R.string.origen_aqui))) { _, i ->
                if (i == 0) fijarDestino(punto) else fijarOrigenLibre(punto)
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun fijarOrigenLibre(o: Destino) {
        prefs.origenLibre = o
        actualizarTextoOrigen()
        reiniciarPosicionIdle()
    }

    // --- Hospitales y RSU de la zona (assets/zona/) ------------------------

    private fun dibujarCapasZona() {
        val cruz = ContextCompat.getDrawable(this, R.drawable.ic_hospital)
        for (h in Escenarios.hospitales(this)) {
            binding.mapa.overlays.add(Marker(binding.mapa).apply {
                position = GeoPoint(h.lat, h.lon)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                icon = cruz
                title = h.nombre
                setOnMarkerClickListener { _, _ -> alTocarHospital(h); true }
            })
        }
        for (r in Escenarios.rsuZona(this)) {
            val m = Marker(binding.mapa).apply {
                position = GeoPoint(r.centro.lat, r.centro.lon)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                icon = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(color(R.color.semaforo_pendiente))
                    setStroke(dp(2), Color.WHITE)
                    setSize(dp(16), dp(16))
                }
                title = "RSU ${r.rsu_id}"
                snippet = r.nombre
            }
            marcadoresZona += m
            binding.mapa.overlays.add(m)
        }
    }

    private fun alTocarHospital(h: Hospital) {
        if (ObuSessionRepository.estado.value.misionActiva) return
        AlertDialog.Builder(this)
            .setTitle(h.nombre)
            .setMessage(getString(R.string.hospital_ir_a, distanciaTexto(h.lat, h.lon)))
            .setPositiveButton(R.string.destino_confirmar_si) { _, _ -> fijarDestino(Destino(h.nombre, h.lat, h.lon)) }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun distanciaTexto(lat: Double, lon: Double): String {
        val desde = ObuSessionRepository.estado.value.ultimaPosicion ?: ubicacionAproximada ?: return ""
        return "%.1f km en línea recta".format(Recorrido.distanciaM(desde, lat to lon) / 1000)
    }

    // --- Mapa: seguir / centrar ------------------------------------------

    @SuppressLint("ClickableViewAccessibility") // no consume el evento: el mapa sigue recibiendo el toque
    private fun configurarSeguimientoMapa() {
        binding.mapa.setOnTouchListener { _, ev ->
            if (ev.action == MotionEvent.ACTION_DOWN && siguiendo) {
                siguiendo = false
                binding.botonCentrar.visibility = View.VISIBLE
            }
            false
        }
    }

    private fun volverASeguir() {
        siguiendo = true
        binding.botonCentrar.visibility = View.GONE
        ObuSessionRepository.estado.value.ultimaPosicion?.let { (lat, lon) -> binding.mapa.controller.animateTo(GeoPoint(lat, lon)) }
    }

    private fun centrarEn(p: GeoPoint) {
        siguiendo = false
        binding.botonCentrar.visibility = View.VISIBLE
        binding.mapa.controller.animateTo(p)
    }

    // --- Destino -----------------------------------------------------------

    private fun confirmarDestino(p: GeoPoint) {
        val destino = Destino(getString(R.string.destino_punto, p.latitude, p.longitude), p.latitude, p.longitude)
        AlertDialog.Builder(this)
            .setTitle(R.string.destino_confirmar_titulo)
            .setMessage(destino.nombre)
            .setPositiveButton(R.string.destino_confirmar_si) { _, _ -> fijarDestino(destino) }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun elegirDestinoPredefinido() {
        val desde = ObuSessionRepository.estado.value.ultimaPosicion ?: ubicacionAproximada
        val hospitales = Escenarios.hospitales(this).let { lista ->
            if (desde == null) lista else lista.sortedBy { Recorrido.distanciaM(desde, it.lat to it.lon) }
        }
        val destinos = hospitales.map { Destino(it.nombre, it.lat, it.lon) }
        val etiquetas = hospitales.map { h ->
            val km = desde?.let { " · %.1f km".format(Recorrido.distanciaM(it, h.lat to h.lon) / 1000) } ?: ""
            h.nombre + km
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.destinos_predefinidos)
            .setItems(etiquetas.toTypedArray()) { _, i ->
                fijarDestino(destinos[i])
                centrarEn(GeoPoint(destinos[i].lat, destinos[i].lon))
            }
            .show()
    }

    private fun fijarDestino(d: Destino) {
        destinoElegido = d
        destinoMarker?.let { binding.mapa.overlays.remove(it) }
        val marcador = Marker(binding.mapa).apply {
            position = GeoPoint(d.lat, d.lon)
            title = d.nombre
        }
        binding.mapa.overlays.add(marcador)
        destinoMarker = marcador
        binding.mapa.invalidate()
        binding.textoDestino.text = d.nombre
        actualizarBotonAccion()
    }

    private fun quitarDestino() {
        destinoElegido = null
        destinoMarker?.let { binding.mapa.overlays.remove(it) }
        destinoMarker = null
        binding.textoDestino.setText(R.string.pedir_destino)
    }

    // --- Estado -> pantalla ----------------------------------------------

    private fun aplicarEstado(estado: EstadoSesion) {
        if (misionActivaAntes && !estado.misionActiva) alTerminarMision(estado)
        if (!misionActivaAntes && estado.misionActiva) {
            verdesAvisados.clear()
            firmaTira = null
        }
        misionActivaAntes = estado.misionActiva

        // Pantalla siempre encendida durante la misión.
        if (estado.misionActiva) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        if (estado.ultimaPosicion == null) {
            posicionMarker?.let { binding.mapa.overlays.remove(it); binding.mapa.invalidate() }
            posicionMarker = null
        }
        estado.ultimaPosicion?.let { (lat, lon) ->
            val p = GeoPoint(lat, lon)
            val marcador = posicionMarker ?: Marker(binding.mapa).also {
                it.title = "Posición actual"
                // Punto azul (el alfiler queda para el destino).
                it.icon = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(color(R.color.primario))
                    setStroke(dp(4), Color.WHITE)
                    setSize(dp(24), dp(24))
                }
                it.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                binding.mapa.overlays.add(it)
                posicionMarker = it
            }
            marcador.position = p
            // Las fuentes emiten a ~5 Hz: animación corta para un seguimiento fluido.
            if (siguiendo) binding.mapa.controller.animateTo(p, null, ANIMACION_SEGUIR_MS)
            binding.mapa.invalidate()
        }

        dibujarRuta(estado.ultimaRuta)

        binding.avisoSinConexion.visibility = if (estado.misionActiva && estado.sinConexionServidor) View.VISIBLE else View.GONE
        binding.avisoSinFix.visibility = if (estado.misionActiva && estado.sinFixGnss && !prefs.modoSimulado) View.VISIBLE else View.GONE
        // RSU de la zona: referencia con GPS real o ruta libre (el servidor
        // corre registro_rsu_zona_pucp.json); en misión mandan las del MR.
        val verZona = !estado.misionActiva && (!prefs.modoSimulado || Escenarios.esRutaLibre(prefs))
        marcadoresZona.forEach { it.setVisible(verZona) }

        // Nada más en pantalla mientras hay misión (docs/CONTRATO_OBU.md §6).
        binding.botonAjustes.visibility = if (estado.misionActiva) View.GONE else View.VISIBLE
        binding.panelInicio.visibility = if (estado.misionActiva) View.GONE else View.VISIBLE
        binding.panelMision.visibility = if (estado.misionActiva) View.VISIBLE else View.GONE
        if (destinoElegido == null) binding.textoDestino.setText(R.string.pedir_destino)

        aplicarPanelInicio(estado)
        if (estado.misionActiva) aplicarPanelMision(estado)
        actualizarBotonAccion(estado)
    }

    private fun alTerminarMision(estado: EstadoSesion) {
        estado.motivoFinReciente?.let { Toast.makeText(this, getString(R.string.mision_terminada, it), Toast.LENGTH_LONG).show() }
        ObuSessionRepository.actualizar { it.copy(motivoFinReciente = null) }
        // Vuelve al inicio con el escenario listo para repetir: en ruta
        // emulada, destino del escenario y vehículo otra vez en el primer punto.
        firmaTira = null
        if (prefs.modoSimulado && !Escenarios.esRutaLibre(prefs)) {
            quitarDestino()
            Escenarios.actual(this, prefs)?.let { fijarDestino(it.destino) }
        } else if (!prefs.modoSimulado) {
            quitarDestino()
        } // ruta libre: se conservan origen y destino, listo para repetir
        siguiendo = true
        binding.botonCentrar.visibility = View.GONE
        iniciarSeguimientoIdle()
    }

    private fun dibujarRuta(mr: MensajeMR?) {
        if (mr === rutaDibujada) return
        rutaDibujada = mr
        rutaPolyline?.let { binding.mapa.overlays.remove(it) }
        rutaPolyline = null
        marcadoresRsu.values.forEach { binding.mapa.overlays.remove(it) }
        marcadoresRsu.clear()
        geometria = null
        if (mr != null) {
            val puntos = mr.geometria.map { it[0] to it[1] }
            val linea = Polyline().apply { setPoints(puntos.map { GeoPoint(it.first, it.second) }) }
            binding.mapa.overlays.add(1, linea) // debajo de los marcadores
            rutaPolyline = linea
            val g = GeometriaRuta(puntos, mr.longitud_total_m)
            geometria = g
            for (p in mr.paradas) {
                val (lat, lon) = g.puntoEnDistancia(p.distancia_llegada_m) ?: continue
                marcadoresRsu[p.interseccion_id] = Marker(binding.mapa).apply {
                    position = GeoPoint(lat, lon)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    title = "RSU ${p.rsu_id} · ${p.interseccion_id}"
                    icon = iconoRsu(EstadoVisual.PENDIENTE)
                    binding.mapa.overlays.add(this)
                }
            }
        }
        binding.mapa.invalidate()
    }

    private fun aplicarPanelInicio(estado: EstadoSesion) {
        val simulado = prefs.modoSimulado
        binding.panelEmulada.visibility = if (simulado) View.VISIBLE else View.GONE
        binding.textoEstadoGnss.visibility = if (simulado) View.GONE else View.VISIBLE
        binding.textoGnssDetalle.visibility = View.GONE
        if (simulado) return
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
        binding.textoEstadoGnss.setBackgroundColor(color(color))

        val detalle = mutableListOf<String>()
        estado.satelitesGnss?.let { (vistos, usados) -> detalle += getString(R.string.gnss_satelites, vistos, usados) }
        if (estado.estadoGnss !is EstadoGnss.Listo) detalle += getString(R.string.gnss_consejo)
        val donde = estado.ultimaPosicion ?: ubicacionAproximada
        if (donde != null && !Escenarios.cobertura(this).contiene(donde.first, donde.second)) {
            detalle += getString(R.string.gnss_fuera_cobertura)
        }
        if (estado.ultimaPosicion == null && ubicacionAproximada != null) detalle += getString(R.string.gnss_aproximada_visible)
        binding.textoGnssDetalle.text = detalle.joinToString("\n")
        binding.textoGnssDetalle.visibility = if (detalle.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun aplicarPanelMision(estado: EstadoSesion) {
        val simulado = prefs.modoSimulado
        val gnss = estado.estadoGnss
        val (textoFuente, colorFuente) = when {
            simulado -> getString(R.string.indicador_emulada) to R.color.fuente_emulada
            gnss is EstadoGnss.Listo -> getString(R.string.indicador_gps, gnss.precisionM) to R.color.gnss_listo
            gnss is EstadoGnss.PrecisionInsuficiente && gnss.precisionM != null ->
                getString(R.string.indicador_gps, gnss.precisionM) to R.color.gnss_esperando
            else -> getString(R.string.indicador_gps_sin_fix) to R.color.estado_cancelada
        }
        binding.indicadorFuente.text = textoFuente
        binding.indicadorFuente.setBackgroundColor(color(colorFuente))
        val factor = if (simulado) prefs.factorDemo else 1
        binding.indicadorDemo.visibility = if (factor != 1) View.VISIBLE else View.GONE
        binding.indicadorDemo.text = getString(R.string.indicador_demo, factor)

        val mr = estado.ultimaRuta
        val distancias = mr?.paradas?.associate { it.interseccion_id to it.distancia_llegada_m } ?: emptyMap()
        val progreso = estado.ultimaPosicion?.let { (lat, lon) -> geometria?.progresoM(lat, lon) }
        val paradas: List<ParadaEstado> = estado.ultimoEstado?.paradas?.takeIf { it.isNotEmpty() }
            ?: mr?.paradas?.map { ParadaEstado(it.interseccion_id, it.rsu_id, it.acceso_id, "pendiente") }
            ?: emptyList()
        fun visual(p: ParadaEstado) = VistaMision.estadoVisual(p.estado, progreso, distancias[p.interseccion_id], p.fase)

        // Tarjeta grande: el próximo semáforo.
        val proximo = estado.ultimoEstado?.proximo
        when {
            proximo != null -> {
                val v = visual(proximo)
                pintarTarjeta(v, textoEstadoVisual(v), "RSU ${proximo.rsu_id} · ${proximo.interseccion_id} (${proximo.acceso_id})")
                binding.semaforoEta.text = proximo.eta_s?.let { "%.0f s".format(it) } ?: ""
                binding.semaforoDetalle.text = VistaMision.textoDetalle(proximo)
            }
            mr == null -> {
                val espera = if (estado.sinConexionServidor) R.string.sem_conectando else R.string.sem_esperando_ruta
                pintarTarjeta(EstadoVisual.PENDIENTE, getString(espera), "")
                binding.semaforoEta.text = ""
                binding.semaforoDetalle.text = ""
            }
            else -> {
                pintarTarjeta(EstadoVisual.OMITIDA, getString(R.string.sem_ninguno), "")
                binding.semaforoEta.text = ""
                binding.semaforoDetalle.text = ""
            }
        }

        // Vibración corta al pasar a verde (una vez por intersección).
        for (p in paradas) {
            if (visual(p) == EstadoVisual.VERDE && verdesAvisados.add(p.interseccion_id) && prefs.vibrarAlVerde) vibrarCorto()
        }

        // Tira de chips y marcadores del mapa: solo si cambió algún estado
        // (la posición llega a ~5 Hz; rehacer los chips cada vez parpadea).
        val firma = paradas.map { it.interseccion_id to visual(it) }
        if (firma == firmaTira) return
        firmaTira = firma
        binding.tiraRsu.removeAllViews()
        for (p in paradas) {
            val v = visual(p)
            binding.tiraRsu.addView(Chip(this).apply {
                text = if (v == EstadoVisual.CRUZADA) "✓ RSU ${p.rsu_id}" else "RSU ${p.rsu_id}"
                isClickable = false
                chipBackgroundColor = android.content.res.ColorStateList.valueOf(color(colorEstadoVisual(v)))
                setTextColor(Color.WHITE)
            })
            marcadoresRsu[p.interseccion_id]?.let {
                it.icon = iconoRsu(v)
                it.snippet = textoEstadoVisual(v)
            }
        }
        binding.mapa.invalidate()
    }

    private fun pintarTarjeta(v: EstadoVisual, estadoTexto: String, titulo: String) {
        binding.tarjetaSemaforo.setBackgroundColor(color(colorEstadoVisual(v)))
        binding.semaforoEstado.text = estadoTexto
        binding.semaforoTitulo.text = titulo
    }

    private fun textoEstadoVisual(v: EstadoVisual): String = getString(
        when (v) {
            EstadoVisual.PENDIENTE -> R.string.sem_pendiente
            EstadoVisual.SOLICITANDO -> R.string.sem_solicitando
            EstadoVisual.VERDE -> R.string.sem_verde
            EstadoVisual.CAMBIANDO -> R.string.sem_cambiando
            EstadoVisual.DESPEJE -> R.string.sem_despeje
            EstadoVisual.EN_ESPERA -> R.string.sem_en_espera
            EstadoVisual.CRUZADA -> R.string.sem_cruzada
            EstadoVisual.OMITIDA -> R.string.sem_omitida
            EstadoVisual.CANCELADA -> R.string.sem_cancelada
        },
    )

    private fun colorEstadoVisual(v: EstadoVisual): Int = when (v) {
        EstadoVisual.PENDIENTE -> R.color.semaforo_pendiente
        EstadoVisual.SOLICITANDO -> R.color.semaforo_solicitando
        EstadoVisual.VERDE -> R.color.semaforo_verde
        EstadoVisual.CAMBIANDO -> R.color.semaforo_cambiando
        EstadoVisual.DESPEJE -> R.color.semaforo_despeje
        EstadoVisual.EN_ESPERA -> R.color.semaforo_en_espera
        EstadoVisual.CRUZADA -> R.color.semaforo_cruzada
        EstadoVisual.OMITIDA -> R.color.semaforo_omitida
        EstadoVisual.CANCELADA -> R.color.semaforo_cancelada
    }

    /** Círculo del color del estado con borde blanco: marcador de RSU en el mapa. */
    private fun iconoRsu(v: EstadoVisual) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL
        setColor(color(colorEstadoVisual(v)))
        setStroke(dp(3), Color.WHITE)
        setSize(dp(26), dp(26))
    }

    private fun vibrarCorto() {
        val vibrador: Vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }
        if (vibrador.hasVibrator()) vibrador.vibrate(VibrationEffect.createOneShot(250, VibrationEffect.DEFAULT_AMPLITUDE))
    }

    // --- Botón principal -------------------------------------------------

    private fun actualizarBotonAccion(estado: EstadoSesion = ObuSessionRepository.estado.value) {
        if (estado.misionActiva) {
            binding.botonAccion.text = getString(R.string.boton_terminar)
            binding.botonAccion.setBackgroundColor(color(R.color.boton_terminar))
            binding.botonAccion.isEnabled = true
        } else {
            // Con GPS real, solo con un fix que pase el criterio de
            // EvaluadorFixGnss AHORA -- ultimaPosicion sola no basta: se
            // queda con el último fix bueno aunque la señal ya se haya perdido.
            val fuenteLista = prefs.modoSimulado || estado.estadoGnss is EstadoGnss.Listo
            val habilitado = destinoElegido != null && estado.ultimaPosicion != null && permisosOk() && fuenteLista
            binding.botonAccion.text = getString(R.string.boton_iniciar)
            binding.botonAccion.setBackgroundColor(color(if (habilitado) R.color.boton_iniciar else R.color.estado_desconocido))
            binding.botonAccion.isEnabled = habilitado
        }
    }

    private fun onBotonAccion() {
        val estado = ObuSessionRepository.estado.value
        if (estado.misionActiva) {
            AlertDialog.Builder(this)
                .setTitle(R.string.terminar_confirmar_titulo)
                .setMessage(R.string.terminar_confirmar_cuerpo)
                .setPositiveButton(R.string.boton_terminar) { _, _ ->
                    startService(Intent(this, ObuSessionService::class.java).setAction(ObuSessionService.ACCION_TERMINAR))
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        } else {
            val origen = estado.ultimaPosicion ?: return
            val destino = destinoElegido ?: return
            jobFuenteIdle?.cancel() // a partir de aquí, la posición la sigue ObuSessionService
            siguiendo = true
            binding.botonCentrar.visibility = View.GONE
            val intent = Intent(this, ObuSessionService::class.java).apply {
                action = ObuSessionService.ACCION_INICIAR
                putExtra(ObuSessionService.EXTRA_ORIGEN_LAT, origen.first)
                putExtra(ObuSessionService.EXTRA_ORIGEN_LON, origen.second)
                putExtra(ObuSessionService.EXTRA_DESTINO_LAT, destino.lat)
                putExtra(ObuSessionService.EXTRA_DESTINO_LON, destino.lon)
            }
            ContextCompat.startForegroundService(this, intent)
        }
    }

    // --- Permisos y batería ------------------------------------------------

    private fun color(id: Int) = ContextCompat.getColor(this, id)

    private companion object {
        const val ANIMACION_SEGUIR_MS = 250L
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

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
