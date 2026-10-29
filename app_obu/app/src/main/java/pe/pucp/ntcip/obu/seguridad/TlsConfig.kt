package pe.pucp.ntcip.obu.seguridad

/**
 * Gancho para la Etapa 3 (TLS 1.3 + mTLS, docs/CONTRATO_OBU.md §1): hoy
 * SIEMPRE null en [pe.pucp.ntcip.obu.obu.MqttObuClient] (sin TLS, broker
 * de desarrollo plano, sin autenticación -- permitido por §1 del contrato
 * para esta etapa). Cuando se implemente, este data class llevaría la ruta
 * (o bytes) del certificado de CA, el certificado del cliente OBU y su
 * llave privada, emitidos por `scripts/seguridad/generar_ca.py emitir
 * --tipo obu --id <obu_id>` -- el Common Name DEBE coincidir exactamente
 * con `obu_id`. No se implementa aquí: es trabajo de otra etapa.
 */
data class TlsConfig(
    val caCertPem: ByteArray,
    val clientCertPem: ByteArray,
    val clientKeyPem: ByteArray,
)
