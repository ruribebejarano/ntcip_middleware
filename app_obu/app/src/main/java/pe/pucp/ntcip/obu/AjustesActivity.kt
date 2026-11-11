package pe.pucp.ntcip.obu

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import pe.pucp.ntcip.obu.databinding.ActivityAjustesBinding
import pe.pucp.ntcip.obu.obu.BateriaUtils
import pe.pucp.ntcip.obu.obu.CargaTls
import pe.pucp.ntcip.obu.obu.Conexion
import pe.pucp.ntcip.obu.obu.Escenarios
import pe.pucp.ntcip.obu.obu.EventoLogger
import pe.pucp.ntcip.obu.obu.Prefs
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada

/**
 * Nada hardcodeado (docs/CONTRATO_OBU.md): host/puerto/clase/modo simulado
 * se configuran aquí. Los cambios se guardan solos al salir de la pantalla
 * (atrás o "Listo"); los archivos elegidos, al momento de elegirlos.
 */
class AjustesActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAjustesBinding
    private lateinit var prefs: Prefs

    // Avanzado: un CSV propio en vez de los escenarios incluidos (assets/escenarios/).
    // Solo .csv: el selector del sistema muestra cualquier archivo y en la
    // tablet llegó a quedar la llave TLS cargada como "trayectoria".
    private val elegirTrayectoria = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@registerForActivityResult
        val nombre = FuenteSimulada.nombreVisible(this, uri)
        if (!nombre.endsWith(".csv", ignoreCase = true)) {
            Toast.makeText(this, getString(R.string.trayectoria_no_csv, nombre), Toast.LENGTH_LONG).show()
            return@registerForActivityResult
        }
        contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        prefs.trayectoriaUri = uri.toString()
        prefs.escenarioId = Escenarios.ID_ARCHIVO
        binding.textoTrayectoriaElegida.text = nombre
    }

    // Conexión segura: los tres PEM de scripts/seguridad/generar_ca.py. Se
    // verifican apenas se elige cada uno (actualizarEstadoTls).
    private val elegirTlsCa = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            prefs.tlsCaUri = uri.toString()
            actualizarEstadoTls()
        }
    }
    private val elegirTlsCert = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            prefs.tlsCertUri = uri.toString()
            actualizarEstadoTls()
        }
    }
    private val elegirTlsKey = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            prefs.tlsKeyUri = uri.toString()
            actualizarEstadoTls()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityAjustesBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = Prefs(this)

        binding.campoHost.setText(prefs.brokerHost)
        binding.grupoHost.check(
            when (prefs.brokerHost) {
                Prefs.HOST_TAILSCALE -> R.id.hostTailscale
                Prefs.HOST_EMULADOR -> R.id.hostEmulador
                else -> R.id.hostManual
            },
        )
        binding.campoHost.isEnabled = binding.grupoHost.checkedRadioButtonId == R.id.hostManual
        binding.grupoHost.setOnCheckedChangeListener { _, id ->
            when (id) {
                R.id.hostTailscale -> binding.campoHost.setText(Prefs.HOST_TAILSCALE)
                R.id.hostEmulador -> binding.campoHost.setText(Prefs.HOST_EMULADOR)
            }
            binding.campoHost.isEnabled = id == R.id.hostManual
            if (id == R.id.hostManual) binding.campoHost.requestFocus()
        }

        binding.campoPuerto.setText(prefs.brokerPuerto.toString())
        binding.campoClase.setText(prefs.clase.toString())
        binding.campoObuId.setText(prefs.obuId)
        binding.interruptorModoSimulado.isChecked = prefs.modoSimulado
        binding.interruptorVibrar.isChecked = prefs.vibrarAlVerde

        // Una trayectoria que no es CSV (p. ej. la llave cargada por error)
        // se descarta al abrir Ajustes: así desaparece también el chip.
        prefs.trayectoriaUri?.let { uri ->
            if (!FuenteSimulada.nombreVisible(this, Uri.parse(uri)).endsWith(".csv", ignoreCase = true)) quitarTrayectoria()
        }
        binding.textoTrayectoriaElegida.text = prefs.trayectoriaUri?.let { FuenteSimulada.nombreVisible(this, Uri.parse(it)) }
            ?: getString(R.string.ajustes_sin_archivo)
        binding.botonElegirTrayectoria.setOnClickListener { elegirTrayectoria.launch(arrayOf("*/*")) }
        binding.botonUsarIntegrada.setOnClickListener {
            quitarTrayectoria()
            binding.textoTrayectoriaElegida.text = getString(R.string.ajustes_sin_archivo)
        }

        binding.interruptorTls.isChecked = prefs.tlsActivado
        binding.interruptorTls.setOnCheckedChangeListener { _, activado ->
            prefs.tlsActivado = activado
            // Puerto por defecto de cada broker, si el usuario no puso otro.
            val puerto = binding.campoPuerto.text.toString()
            if (activado && puerto == "1883") binding.campoPuerto.setText("8883")
            if (!activado && puerto == "8883") binding.campoPuerto.setText("1883")
            actualizarEstadoTls()
        }
        actualizarEstadoTls()
        binding.botonElegirTlsCa.setOnClickListener { elegirTlsCa.launch(arrayOf("*/*")) }
        binding.botonElegirTlsCert.setOnClickListener { elegirTlsCert.launch(arrayOf("*/*")) }
        binding.botonElegirTlsKey.setOnClickListener { elegirTlsKey.launch(arrayOf("*/*")) }
        binding.botonProbarConexion.setOnClickListener { probarConexion() }

        binding.botonGuardar.setOnClickListener { finish() }
        binding.botonExportarEventos.setOnClickListener { exportarEventos() }
        binding.botonRevisarBateria.setOnClickListener {
            runCatching { startActivity(BateriaUtils.intentPedirSinRestricciones(this)) }
                .onFailure { startActivity(BateriaUtils.intentDetalleApp(this)) }
        }
    }

    /** Guardado automático: al salir (atrás, "Listo" o ir a otra app). */
    override fun onPause() {
        super.onPause()
        guardar(avisar = isFinishing)
    }

    private fun guardar(avisar: Boolean): Boolean {
        val host = binding.campoHost.text.toString().trim()
        val puerto = binding.campoPuerto.text.toString().toIntOrNull()
        val clase = binding.campoClase.text.toString().toIntOrNull()
        val obuId = binding.campoObuId.text.toString().trim()
        prefs.modoSimulado = binding.interruptorModoSimulado.isChecked
        prefs.vibrarAlVerde = binding.interruptorVibrar.isChecked
        prefs.tlsActivado = binding.interruptorTls.isChecked
        if (host.isEmpty() || puerto == null || puerto !in 1..65535 || clase == null) {
            if (avisar) Toast.makeText(this, R.string.ajustes_revisar_campos, Toast.LENGTH_LONG).show()
            return false
        }
        prefs.brokerHost = host
        prefs.brokerPuerto = puerto
        prefs.clase = clase
        if (obuId.isNotEmpty()) prefs.obuId = obuId
        if (avisar) Toast.makeText(this, R.string.ajustes_guardado, Toast.LENGTH_SHORT).show()
        return true
    }

    private fun quitarTrayectoria() {
        prefs.trayectoriaUri = null
        if (prefs.escenarioId == Escenarios.ID_ARCHIVO) prefs.escenarioId = Escenarios.ID_POR_DEFECTO
    }

    /** Estado de TLS en una línea: qué falta, qué está mal, o "✓ CN, válido
     * hasta…". Con TLS apagado no se muestran los archivos. */
    private fun actualizarEstadoTls() {
        val activado = binding.interruptorTls.isChecked
        binding.panelTls.visibility = if (activado) View.VISIBLE else View.GONE
        binding.panelObuId.visibility = if (activado) View.GONE else View.VISIBLE
        binding.textoObuIdTls.visibility = View.GONE
        if (!activado) return
        when (val r = Conexion.cargarTls(this, prefs)) {
            is CargaTls.Ok -> {
                val descripcion = Conexion.describir(r.config)
                binding.textoTlsEstado.text = getString(R.string.tls_valido, descripcion)
                binding.textoTlsEstado.setTextColor(ContextCompat.getColor(this, R.color.gnss_listo))
                binding.textoObuIdTls.text = getString(R.string.ajustes_obu_id_con_tls, r.config.commonNameCliente())
                binding.textoObuIdTls.visibility = View.VISIBLE
            }
            is CargaTls.Error -> {
                binding.textoTlsEstado.text = "✗ " + r.mensaje
                binding.textoTlsEstado.setTextColor(ContextCompat.getColor(this, R.color.estado_cancelada))
            }
        }
    }

    /** Conecta un momento al broker con lo que hay en pantalla (se guarda
     * antes) y muestra el resultado, sin tener que iniciar una misión. */
    private fun probarConexion() {
        if (!guardar(avisar = false)) {
            Toast.makeText(this, R.string.ajustes_revisar_campos, Toast.LENGTH_LONG).show()
            return
        }
        binding.botonProbarConexion.isEnabled = false
        binding.textoPruebaConexion.visibility = View.VISIBLE
        binding.textoPruebaConexion.text = getString(R.string.conexion_comprobando)
        binding.textoPruebaConexion.setTextColor(ContextCompat.getColor(this, R.color.gnss_buscando))
        lifecycleScope.launch {
            val r = Conexion.probar(this@AjustesActivity, prefs)
            binding.botonProbarConexion.isEnabled = true
            val (texto, color) = when (r) {
                is Conexion.Prueba.Ok -> r.detalle to R.color.gnss_listo
                is Conexion.Prueba.Error -> r.mensaje to R.color.estado_cancelada
            }
            binding.textoPruebaConexion.text = texto
            binding.textoPruebaConexion.setTextColor(ContextCompat.getColor(this@AjustesActivity, color))
        }
    }

    private fun exportarEventos() {
        val archivo = EventoLogger.directorio(this).listFiles()?.maxByOrNull { it.lastModified() }
        if (archivo == null) {
            Toast.makeText(this, "Todavía no hay eventos registrados", Toast.LENGTH_SHORT).show()
            return
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", archivo)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/csv"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(intent, getString(R.string.ajustes_exportar_eventos)))
    }
}
