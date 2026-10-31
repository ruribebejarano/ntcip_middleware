package pe.pucp.ntcip.obu.obu

import java.util.Locale
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot

/**
 * Lógica pura (sin Android) de la pantalla de misión, separada para
 * probarla con tests JVM: dónde está cada RSU sobre la polilínea del MR,
 * cuánto avanzó el vehículo, y qué color/texto le toca a cada parada.
 */

/** Cómo se dibuja una parada (tarjeta grande, chips de la tira y marcadores del mapa). */
enum class EstadoVisual { PENDIENTE, SOLICITANDO, VERDE, DESPEJE, EN_ESPERA, CRUZADA, OMITIDA, CANCELADA }

/**
 * Polilínea del MR con distancia acumulada. El MR trae, por parada, solo
 * `distancia_llegada_m` (longitud de las aristas del grafo, que siguen la
 * curva real de la calle), no lat/lon; aquí se acumula en línea recta entre
 * vértices y se reescala a `longitud_total_m` para que ambas escalas
 * coincidan, y cada RSU se ubica en el vértice más cercano a su distancia
 * (cruzar_con_registro siempre la asigna a un nodo de la ruta).
 */
class GeometriaRuta(private val puntos: List<Pair<Double, Double>>, longitudTotalM: Double) {
    private val acumulada: DoubleArray

    init {
        val cruda = DoubleArray(puntos.size)
        for (i in 1 until puntos.size) cruda[i] = cruda[i - 1] + distanciaM(puntos[i - 1], puntos[i])
        val escala = if (cruda.isNotEmpty() && cruda.last() > 0 && longitudTotalM > 0) longitudTotalM / cruda.last() else 1.0
        acumulada = DoubleArray(cruda.size) { cruda[it] * escala }
    }

    fun puntoEnDistancia(distanciaM: Double): Pair<Double, Double>? {
        if (puntos.isEmpty()) return null
        val i = acumulada.indices.minByOrNull { abs(acumulada[it] - distanciaM) } ?: return null
        return puntos[i]
    }

    /** Distancia acumulada del vértice de la ruta más cercano a (lat, lon). */
    fun progresoM(lat: Double, lon: Double): Double? {
        if (puntos.isEmpty()) return null
        val i = puntos.indices.minByOrNull { distanciaM(puntos[it], lat to lon) } ?: return null
        return acumulada[i]
    }

    companion object {
        fun distanciaM(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
            val latMedia = (a.first + b.first) / 2 * PI / 180
            val dy = (b.first - a.first) * 111_320.0
            val dx = (b.second - a.second) * 111_320.0 * cos(latMedia)
            return hypot(dx, dy)
        }
    }
}

object VistaMision {
    /** Mismo margen que MARGEN_CRUCE_M de servidor/gestor_mision.py. */
    const val MARGEN_CRUCE_M = 20.0

    /**
     * `progresoM`/`distanciaLlegadaM` null = no se sabe dónde va el
     * vehículo: no se marca nada como cruzada/omitida. El ME no distingue
     * "cancelada por cruce" de "cancelada por desvío o rumbo": se decide
     * por posición -- cancelada con el vehículo ya pasado el cruce = cruzada.
     */
    fun estadoVisual(estado: String, progresoM: Double?, distanciaLlegadaM: Double?): EstadoVisual {
        val pasada = progresoM != null && distanciaLlegadaM != null && progresoM >= distanciaLlegadaM - MARGEN_CRUCE_M
        val claramentePasada = progresoM != null && distanciaLlegadaM != null && progresoM > distanciaLlegadaM + MARGEN_CRUCE_M
        return when (estado) {
            "concedida" -> EstadoVisual.VERDE
            "solicitada" -> EstadoVisual.SOLICITANDO
            "en_cola" -> EstadoVisual.DESPEJE
            "en_espera" -> EstadoVisual.EN_ESPERA
            "cancelada", "rechazada" -> if (pasada) EstadoVisual.CRUZADA else EstadoVisual.CANCELADA
            else -> if (claramentePasada) EstadoVisual.OMITIDA else EstadoVisual.PENDIENTE
        }
    }

    /**
     * "Cómo se logró" el verde, en letra pequeña bajo la tarjeta. Usa los
     * campos nuevos del ME (accion, t_hasta_verde_ms, anticipacion_s) si
     * llegan; si no, solo estado y fase.
     */
    fun textoDetalle(p: ParadaEstado): String {
        val tHastaVerdeS = p.t_hasta_verde_ms?.let { it / 1000.0 }
        val accion = p.accion?.lowercase()
        val (etiqueta, segundos) = when {
            accion == null -> null to null
            "exten" in accion -> "Extensión de verde" to (p.anticipacion_s ?: tHastaVerdeS)
            "despeje" in accion || "cola" in accion || "esper" in accion -> "Esperó despeje" to (tHastaVerdeS ?: p.anticipacion_s)
            "adelant" in accion || "anticip" in accion || "temprano" in accion -> "Verde adelantado" to (tHastaVerdeS ?: p.anticipacion_s)
            else -> p.accion to (tHastaVerdeS ?: p.anticipacion_s)
        }
        if (etiqueta != null) {
            return if (segundos != null) String.format(Locale.ROOT, "%s · %.1f s", etiqueta, segundos) else etiqueta
        }
        val base = "Estado: ${textoEstadoNatural(p.estado)}"
        return if (p.fase != null) "$base · fase ${p.fase}" else base
    }
}
