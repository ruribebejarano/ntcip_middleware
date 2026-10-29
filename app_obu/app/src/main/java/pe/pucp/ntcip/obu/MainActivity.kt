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
        actualizarBotonAccion()
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

        pedirPermisosSiFalta()
        if (BateriaUtils.tieneRestriccion(this)) mostrarAvisoBateria()
    }

    override fun onResume() {
        super.onResume()
        binding.mapa.onResume()
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

        binding.avisoSimulado.visibility = if (Prefs(this).modoSimulado) View.VISIBLE else View.GONE
        binding.avisoSinConexion.visibility = if (estado.misionActiva && estado.sinConexionServidor) View.VISIBLE else View.GONE
        binding.avisoSinFix.visibility = if (estado.misionActiva && estado.sinFixGnss) View.VISIBLE else View.GONE

        // Nada más en pantalla mientras hay misión (docs/CONTRATO_OBU.md §6).
        binding.botonAjustes.visibility = if (estado.misionActiva) View.GONE else View.VISIBLE
        binding.textoPedirDestino.visibility = if (!estado.misionActiva && destinoElegido == null) View.VISIBLE else View.GONE

        actualizarBotonAccion(estado)
    }

    private fun actualizarBotonAccion(estado: EstadoSesion = ObuSessionRepository.estado.value) {
        if (estado.misionActiva) {
            binding.botonAccion.text = getString(R.string.boton_terminar)
            binding.botonAccion.setBackgroundColor(ContextCompat.getColor(this, R.color.boton_terminar))
            binding.botonAccion.isEnabled = true
        } else {
            binding.botonAccion.text = getString(R.string.boton_iniciar)
            binding.botonAccion.setBackgroundColor(ContextCompat.getColor(this, R.color.boton_iniciar))
            binding.botonAccion.isEnabled = destinoElegido != null && estado.ultimaPosicion != null && permisosOk()
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
