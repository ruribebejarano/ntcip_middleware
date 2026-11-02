package pe.pucp.ntcip.obu.seguridad

import java.io.ByteArrayInputStream
import java.security.KeyFactory
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Base64
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.TrustManagerFactory

/**
 * Etapa 3 (TLS 1.3 + mTLS, docs/CONTRATO_OBU.md §1): los tres PEM
 * emitidos por `scripts/seguridad/generar_ca.py emitir --tipo obu --id
 * <obu_id>` -- el Common Name del certificado DEBE coincidir exactamente
 * con `obu_id` (ACL del broker por `use_identity_as_username`, ver
 * `scripts/seguridad/mosquitto_acl.conf`).
 *
 * [REVISAR con asesor] -- mismatch sin resolver con el `obu_id` actual de
 * la app: `ObuSessionService.iniciarMision()` genera un `obu_id` AL AZAR
 * en cada misión, pero un certificado de cliente es de larga duración con
 * un CN fijo. Para probar mTLS de verdad hay que emitir el certificado con
 * un `obu_id` de prueba fijo y usarlo solo en banco (no en una campaña con
 * `obu_id` aleatorio); fijar el `obu_id` por dispositivo en vez de por
 * misión queda como decisión de diseño pendiente, fuera de este cambio.
 *
 * La llave privada DEBE estar en formato PKCS#8 (`-----BEGIN PRIVATE
 * KEY-----`), no PKCS#1 (`-----BEGIN RSA PRIVATE KEY-----`): este parser
 * usa solo `javax.crypto`/`java.security`, sin BouncyCastle.
 * `scripts/seguridad/generar_ca.py` ya emite las llaves así (`openssl
 * genpkey`, no `genrsa`).
 */
data class TlsConfig(
    val caCertPem: ByteArray,
    val clientCertPem: ByteArray,
    val clientKeyPem: ByteArray,
) {
    fun keyManagerFactory(): KeyManagerFactory {
        val cert = parseCert(clientCertPem)
        val key = parseKeyPkcs8(clientKeyPem)
        val keyStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            setKeyEntry("obu-cliente", key, PASSWORD_ALMACEN_EN_MEMORIA, arrayOf(cert))
        }
        return KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply {
            init(keyStore, PASSWORD_ALMACEN_EN_MEMORIA)
        }
    }

    fun trustManagerFactory(): TrustManagerFactory {
        val ca = parseCert(caCertPem)
        val trustStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            setCertificateEntry("ca-proyecto", ca)
        }
        return TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
            init(trustStore)
        }
    }

    private fun parseCert(pem: ByteArray): X509Certificate =
        CertificateFactory.getInstance("X.509")
            .generateCertificate(ByteArrayInputStream(pem)) as X509Certificate

    private fun parseKeyPkcs8(pem: ByteArray) = String(pem, Charsets.US_ASCII)
        .lines()
        .filterNot { it.startsWith("-----") }
        .joinToString("")
        .let { Base64.getDecoder().decode(it) }
        .let { der -> KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(der)) }

    companion object {
        // KeyStore en memoria, nunca persistido a disco: la "contraseña"
        // solo protege el acceso en RAM dentro de este proceso, no hace
        // falta que sea secreta.
        private val PASSWORD_ALMACEN_EN_MEMORIA = "obu".toCharArray()
    }
}
