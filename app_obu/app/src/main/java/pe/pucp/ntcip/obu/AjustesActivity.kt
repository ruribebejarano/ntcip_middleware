package pe.pucp.ntcip.obu

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import pe.pucp.ntcip.obu.databinding.ActivityAjustesBinding
import pe.pucp.ntcip.obu.obu.BateriaUtils
import pe.pucp.ntcip.obu.obu.Escenarios
import pe.pucp.ntcip.obu.obu.EventoLogger
import pe.pucp.ntcip.obu.obu.Prefs
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada

/** Nada hardcodeado (docs/CONTRATO_OBU.md): host/puerto/clase/modo simulado se configuran aquí. */
class AjustesActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAjustesBinding
    private lateinit var prefs: Prefs

    // Avanzado: un CSV propio en vez de los escenarios incluidos (assets/escenarios/).
    private val elegirTrayectoria = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            prefs.trayectoriaUri = uri.toString()
            prefs.escenarioId = Escenarios.ID_ARCHIVO
            binding.textoTrayectoriaElegida.text = FuenteSimulada.nombreVisible(this, uri)
        }
    }

    // Etapa 3 (TLS 1.3 + mTLS): los tres PEM de scripts/seguridad/generar_ca.py.
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
        binding.textoTrayectoriaElegida.text = prefs.trayectoriaUri?.let { FuenteSimulada.nombreVisible(this, Uri.parse(it)) }
            ?: getString(R.string.ajustes_sin_archivo)

        binding.botonElegirTrayectoria.setOnClickListener { elegirTrayectoria.launch(arrayOf("*/*")) }
        binding.botonUsarIntegrada.setOnClickListener {
            prefs.trayectoriaUri = null
            if (prefs.escenarioId == Escenarios.ID_ARCHIVO) prefs.escenarioId = Escenarios.ID_POR_DEFECTO
            binding.textoTrayectoriaElegida.text = getString(R.string.ajustes_sin_archivo)
        }

        binding.interruptorTls.isChecked = prefs.tlsActivado
        actualizarEstadoTls()
        binding.botonElegirTlsCa.setOnClickListener { elegirTlsCa.launch(arrayOf("*/*")) }
        binding.botonElegirTlsCert.setOnClickListener { elegirTlsCert.launch(arrayOf("*/*")) }
        binding.botonElegirTlsKey.setOnClickListener { elegirTlsKey.launch(arrayOf("*/*")) }

        binding.botonGuardar.setOnClickListener { guardar() }
        binding.botonExportarEventos.setOnClickListener { exportarEventos() }
        binding.botonRevisarBateria.setOnClickListener {
            runCatching { startActivity(BateriaUtils.intentPedirSinRestricciones(this)) }
                .onFailure { startActivity(BateriaUtils.intentDetalleApp(this)) }
        }
    }

    private fun guardar() {
        val host = binding.campoHost.text.toString().trim()
        val puerto = binding.campoPuerto.text.toString().toIntOrNull()
        val clase = binding.campoClase.text.toString().toIntOrNull()
        val obuId = binding.campoObuId.text.toString().trim()
        if (host.isEmpty() || puerto == null || clase == null || obuId.isEmpty()) {
            Toast.makeText(this, "Revisa host/puerto/clase/obu_id", Toast.LENGTH_SHORT).show()
            return
        }
        prefs.brokerHost = host
        prefs.brokerPuerto = puerto
        prefs.clase = clase
        prefs.obuId = obuId
        prefs.modoSimulado = binding.interruptorModoSimulado.isChecked
        prefs.vibrarAlVerde = binding.interruptorVibrar.isChecked
        prefs.tlsActivado = binding.interruptorTls.isChecked
        Toast.makeText(this, "Guardado", Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun actualizarEstadoTls() {
        val nombres = listOfNotNull(
            prefs.tlsCaUri?.let { "CA: " + FuenteSimulada.nombreVisible(this, Uri.parse(it)) },
            prefs.tlsCertUri?.let { "certificado: " + FuenteSimulada.nombreVisible(this, Uri.parse(it)) },
            prefs.tlsKeyUri?.let { "llave: " + FuenteSimulada.nombreVisible(this, Uri.parse(it)) },
        )
        binding.textoTlsEstado.text = if (nombres.isEmpty()) {
            getString(R.string.ajustes_tls_sin_archivos)
        } else {
            nombres.joinToString(" · ")
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
