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
 * Resuelto (item 2b, prompt_integracion_app_obu.md): el mismatch entre un
 * `obu_id` aleatorio por misión y un CN fijo de certificado se resuelve
 * fijando la identidad por DISPOSITIVO. Con TLS activado,
 * `ObuSessionService` usa [commonNameCliente] como `obu_id` -- el
 * certificado es la única fuente de verdad, no `Prefs.obuId` (que solo
 * aplica sin TLS, broker de desarrollo). Así el certificado nunca puede
 * quedar desincronizado del `obu_id` que de verdad se usa.
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
    /** Common Name (CN) del certificado de cliente: el `obu_id` fijo de
     * este dispositivo mientras TLS esté activado (ver clase arriba). */
    fun commonNameCliente(): String {
        val principal = parseCert(clientCertPem).subjectX500Principal.name // RFC 2253: "CN=obu-tab-01,..."
        return principal.split(",")
            .firstOrNull { it.trim().startsWith("CN=", ignoreCase = true) }
            ?.substringAfter("=")
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?: error("El certificado de cliente no tiene Common Name (CN)")
    }

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

    /** Fin de validez del certificado de cliente (para mostrarlo en Ajustes). */
    fun venceCliente(): java.util.Date = parseCert(clientCertPem).notAfter

    /** Verifica los tres archivos de una vez (CN, llave y CA), para fallar
     * al iniciar la misión con un mensaje claro y no dentro de la conexión. */
    fun validar() {
        commonNameCliente()
        keyManagerFactory()
        trustManagerFactory()
    }

    private fun parseCert(pem: ByteArray): X509Certificate =
        CertificateFactory.getInstance("X.509")
            .generateCertificate(ByteArrayInputStream(bloquePem(pem, "CERTIFICATE").toByteArray(Charsets.US_ASCII)))
            as X509Certificate

    private fun parseKeyPkcs8(pem: ByteArray) = bloquePem(pem, "PRIVATE KEY")
        .lines()
        .filterNot { it.startsWith("-----") }
        .joinToString("") { it.trim() }
        .let { Base64.getDecoder().decode(it) }
        .let { der -> KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(der)) }

    companion object {
        /** Solo el bloque PEM `-----BEGIN <tipo>----- ... -----END <tipo>-----`.
         * `openssl ca` deja por defecto el certificado en texto legible
         * ("Certificate: Data: ...") antes del bloque, y el lector de
         * certificados de Android puede rechazar ese texto. Acepta CRLF. */
        fun bloquePem(pem: ByteArray, tipo: String): String {
            val texto = String(pem, Charsets.US_ASCII).replace("\r", "")
            val inicio = texto.indexOf("-----BEGIN $tipo-----")
            val marcaFin = "-----END $tipo-----"
            val fin = texto.indexOf(marcaFin, startIndex = maxOf(inicio, 0))
            require(inicio >= 0 && fin > inicio) { "No hay un bloque «$tipo» en el archivo" }
            return texto.substring(inicio, fin + marcaFin.length) + "\n"
        }

        // KeyStore en memoria, nunca persistido a disco: la "contraseña"
        // solo protege el acceso en RAM dentro de este proceso, no hace
        // falta que sea secreta.
        private val PASSWORD_ALMACEN_EN_MEMORIA = "obu".toCharArray()
    }
}
