package pe.pucp.ntcip.obu.obu

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * Puerto a Kotlin de common/events.py::EventLogger. Mismo esquema de
 * columnas (ts_ns,nodo,tipo_evento,id_solicitud,extra_json) y mismo nombre
 * de archivo (eventos_<nodo>.csv) para que los scripts de scripts/analisis/
 * lo lean sin cambios -- ver app_obu/README.md, sección "Reloj y eventos", sobre por
 * qué `ts_ns` aquí tiene resolución real de milisegundos, no nanosegundos.
 */
object EventosObu {
    const val MI_TX = "MI_tx"
    const val MP_TX = "MP_tx"
    const val MF_TX = "MF_tx"
    const val MR_RX = "MR_rx"
    const val ME_RX = "ME_rx"
    const val MUESTRA = "muestra"

    // Eventos propios de la app Android, sin equivalente en common/events.py
    // (no se tocó ese archivo -- fuera de app_obu/, ver instrucciones de la
    // sesión). Documentados aquí y en app_obu/README.md.
    const val CONEXION_MQTT = "conexion_mqtt"   // extra: estado=conectado|desconectado|reconectando
    const val RELOJ_SNTP = "reloj_sntp"         // extra: servidor, offset_ms, rtt_ms, momento=inicio|fin
    const val BATERIA_RESTRINGIDA = "bateria_restringida" // extra: ignorando_optimizacion (bool)
}

class EventoLogger(context: Context, private val nodo: String) {
    private val lock = ReentrantLock()
    val archivo: File = File(directorio(context), "eventos_$nodo.csv").also(::asegurarCabecera)

    companion object {
        fun directorio(context: Context): File =
            File(context.filesDir, "eventos").apply { mkdirs() }

        private fun asegurarCabecera(f: File) {
            if (!f.exists() || f.length() == 0L) {
                f.writeText("ts_ns,nodo,tipo_evento,id_solicitud,extra_json\n")
            }
        }

        private fun valorJson(v: Any?): Any = when (v) {
            null -> JSONObject.NULL
            is Map<*, *> -> JSONObject().apply { v.forEach { (k, vv) -> put(k.toString(), valorJson(vv)) } }
            is List<*> -> JSONArray().apply { v.forEach { put(valorJson(it)) } }
            else -> v
        }

        private fun campoCsv(valor: String): String =
            if (valor.contains(',') || valor.contains('"') || valor.contains('\n')) {
                "\"" + valor.replace("\"", "\"\"") + "\""
            } else valor
    }

    /** Equivalente a EventLogger.log() de Python: kwargs -> `extra` como JSON. */
    fun log(tipoEvento: String, idSolicitud: String?, extra: Map<String, Any?> = emptyMap()) {
        val tsNs = System.currentTimeMillis() * 1_000_000L
        val obj = JSONObject()
        extra.forEach { (k, v) -> obj.put(k, valorJson(v)) }
        val fila = listOf(
            tsNs.toString(),
            nodo,
            tipoEvento,
            idSolicitud?.takeIf { it.isNotBlank() } ?: "-",
            obj.toString(),
        ).joinToString(",") { campoCsv(it) }
        lock.withLock {
            archivo.appendText(fila + "\n")
        }
    }
}
