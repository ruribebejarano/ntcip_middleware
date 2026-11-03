package pe.pucp.ntcip.obu.obu

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Espejo en Kotlin de docs/CONTRATO_OBU.md y gateway/obu_emulada.py. Los
 * nombres de propiedad son snake_case a propósito, idénticos a los campos
 * JSON del contrato: evita cualquier mapeo manual que pueda desalinearse
 * en silencio con el servidor (servidor/gestor_mision.py).
 */

/**
 * Serializador único de MqttObuClient, expuesto aquí (no privado dentro de
 * esa clase) para que MensajesTest.kt pueda verificar sin mocks que el JSON
 * que de verdad se publica trae "tipo" y el resto de campos con valor por
 * defecto. `encodeDefaults = true` es obligatorio: sin él,
 * kotlinx.serialization omite "tipo" (y "paradas"/"conflicto"/etc. en
 * MR/ME) porque coinciden con su valor por defecto, y
 * servidor/main.py::_on_message imprime "tipo desconocido en
 * obu/{obu_id}/mision: None" para ese MI sin "tipo" -- bug real visto
 * contra el servidor el 2026-10-29 con el APK de las 11:44.
 */
val jsonObu: Json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

@Serializable
data class Coordenada(val lat: Double, val lon: Double)

@Serializable
data class MensajeMI(
    val tipo: String = "MI",
    val obu_id: String,
    val clase: Int,
    val origen: Coordenada,
    val destino: Coordenada,
    val ts_ms: Long,
)

@Serializable
data class MensajeMP(
    val tipo: String = "MP",
    val obu_id: String,
    val lat: Double,
    val lon: Double,
    // null = sin dato de velocidad (fuente_velocidad="respaldo"); 0.0 con
    // fuente_velocidad="gps" = detenido, medido (docs/CONTRATO_OBU.md §MP).
    val velocidad_kmh: Double?,
    val rumbo_deg: Double,
    val fuente_velocidad: String,
    val ts_ms: Long,
    val seq: Int,
)

@Serializable
data class MensajeMF(
    val tipo: String = "MF",
    val obu_id: String,
    val motivo: String,
    val ts_ms: Long,
)

@Serializable
data class MensajeMR(
    val tipo: String = "MR",
    val mision_id: String,
    val version: Int,
    val longitud_total_m: Double,
    val geometria: List<List<Double>>,
    val paradas: List<ParadaRuta> = emptyList(),
    val ts_ms: Long = 0L,
)

@Serializable
data class ParadaRuta(
    val rsu_id: String,
    val interseccion_id: String,
    val acceso_id: String,
    val distancia_llegada_m: Double,
)

@Serializable
data class MensajeME(
    val tipo: String = "ME",
    val mision_id: String,
    val paradas: List<ParadaEstado> = emptyList(),
    val proximo: ParadaEstado? = null,
    val conflicto: Boolean = false,
    val ts_ms: Long = 0L,
    // Campos NO implementados todavía por servidor/gestor_mision.py -- ver
    // app_obu/PROPUESTA_FIN_MISION.md. Mientras el servidor no los envíe,
    // llegan como null y la app NO debe asumir que la misión terminó.
    val mision_activa: Boolean? = null,
    val motivo_fin: String? = null,
)

@Serializable
data class ParadaEstado(
    val interseccion_id: String,
    val rsu_id: String,
    val acceso_id: String,
    val estado: String,
    val eta_s: Double? = null,
    val fase: String? = null,
    // Cómo se consiguió el verde -- campos que agregará el servidor (otra
    // sesión); mientras no lleguen quedan null y la app muestra solo
    // estado y fase (ver VistaMision.textoDetalle).
    val fase_al_recibir: String? = null,
    val accion: String? = null,
    val t_hasta_verde_ms: Long? = null,
    val anticipacion_s: Double? = null,
)

/** `estado` de una parada, en español natural (docs/CONTRATO_OBU.md §4, ME). */
fun textoEstadoNatural(estado: String): String = when (estado) {
    "pendiente" -> "pendiente"
    "solicitada" -> "solicitada"
    "en_cola" -> "en cola"
    "concedida" -> "concedida"
    "cancelada" -> "cancelada"
    "rechazada" -> "rechazada"
    "en_espera" -> "en espera por otra unidad"
    else -> estado
}
