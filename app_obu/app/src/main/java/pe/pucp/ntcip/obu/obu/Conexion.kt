package pe.pucp.ntcip.obu.obu

import android.content.Context
import android.net.Uri
import com.hivemq.client.mqtt.MqttClientSslConfig
import com.hivemq.client.mqtt.mqtt5.Mqtt5Client
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import pe.pucp.ntcip.obu.R
import pe.pucp.ntcip.obu.seguridad.TlsConfig
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.TimeUnit

/** Resultado de leer y verificar los tres PEM elegidos en Ajustes. */
sealed interface CargaTls {
    data class Ok(val config: TlsConfig) : CargaTls
    data class Error(val mensaje: String) : CargaTls
}

/**
 * Lo comparten ObuSessionService (al iniciar la misión), Ajustes (al elegir
 * los archivos) y la comprobación de conexión de la pantalla principal:
 * los tres dicen lo mismo y con el mismo mensaje si algo falta o no sirve.
 */
object Conexion {

    fun cargarTls(context: Context, prefs: Prefs): CargaTls {
        val faltan = listOfNotNull(
            "CA".takeIf { prefs.tlsCaUri == null },
            "Certificado".takeIf { prefs.tlsCertUri == null },
            "Llave".takeIf { prefs.tlsKeyUri == null },
        )
        if (faltan.isNotEmpty()) return CargaTls.Error(context.getString(R.string.error_tls_faltan, faltan.joinToString(", ")))
        val leidos = mutableMapOf<String, ByteArray>()
        for ((nombre, uri) in listOf("CA" to prefs.tlsCaUri!!, "Certificado" to prefs.tlsCertUri!!, "Llave" to prefs.tlsKeyUri!!)) {
            leidos[nombre] = runCatching {
                context.contentResolver.openInputStream(Uri.parse(uri))!!.use { it.readBytes() }
            }.getOrElse { return CargaTls.Error(context.getString(R.string.error_tls_no_se_lee, nombre)) }
        }
        val config = TlsConfig(caCertPem = leidos["CA"]!!, clientCertPem = leidos["Certificado"]!!, clientKeyPem = leidos["Llave"]!!)
        return runCatching { config.validar(); CargaTls.Ok(config) }
            .getOrElse { CargaTls.Error(context.getString(R.string.error_tls_invalido, it.message ?: it.javaClass.simpleName)) }
    }

    /** "obu-tab-01, válido hasta el 06/02/2029", para mostrar en Ajustes. */
    fun describir(config: TlsConfig): String =
        "${config.commonNameCliente()}, válido hasta el " +
            SimpleDateFormat("dd/MM/yyyy", Locale.getDefault()).format(config.venceCliente())

    sealed interface Prueba {
        data class Ok(val detalle: String) : Prueba
        data class Error(val mensaje: String) : Prueba
    }

    /**
     * Conecta un momento al broker con los ajustes actuales y se desconecta,
     * sin publicar nada (el servidor no se entera). Client ID distinto del de
     * la misión ("…-prueba") para no desplazar una sesión real. Detecta lo
     * que antes solo se veía al iniciar: puerto o host equivocado, Tailscale
     * apagado, TLS mal configurado o certificado rechazado.
     */
    suspend fun probar(context: Context, prefs: Prefs, timeoutS: Long = 6): Prueba = withContext(Dispatchers.IO) {
        val tls = if (prefs.tlsActivado) {
            when (val r = cargarTls(context, prefs)) {
                is CargaTls.Ok -> r.config
                is CargaTls.Error -> return@withContext Prueba.Error(r.mensaje)
            }
        } else null
        val obuId = tls?.commonNameCliente() ?: prefs.obuId
        var builder = Mqtt5Client.builder()
            .identifier("obu-$obuId-prueba")
            .serverHost(prefs.brokerHost)
            .serverPort(prefs.brokerPuerto)
        if (tls != null) {
            builder = builder.sslConfig(
                MqttClientSslConfig.builder()
                    .keyManagerFactory(tls.keyManagerFactory())
                    .trustManagerFactory(tls.trustManagerFactory())
                    .handshakeTimeout(timeoutS, TimeUnit.SECONDS)
                    .build(),
            )
        }
        val cliente = builder.buildAsync()
        val destino = "${prefs.brokerHost}:${prefs.brokerPuerto}"
        runCatching {
            cliente.connect().get(timeoutS, TimeUnit.SECONDS)
        }.fold(
            onSuccess = {
                runCatching { cliente.disconnect().get(2, TimeUnit.SECONDS) }
                Prueba.Ok(context.getString(if (tls != null) R.string.conexion_ok_tls else R.string.conexion_ok_sin_tls, destino, obuId))
            },
            onFailure = { e ->
                runCatching { cliente.disconnect() }
                val causa = generateSequence(e) { it.cause }.last()
                val mensaje = when {
                    e is java.util.concurrent.TimeoutException -> context.getString(R.string.conexion_sin_respuesta, destino)
                    causa is java.net.ConnectException -> context.getString(R.string.conexion_rechazada, destino)
                    causa is javax.net.ssl.SSLException || causa is java.security.cert.CertificateException ->
                        context.getString(R.string.conexion_tls_rechazada, destino)
                    else -> context.getString(R.string.conexion_error, destino, causa.message ?: causa.javaClass.simpleName)
                }
                Prueba.Error(mensaje)
            },
        )
    }
}
