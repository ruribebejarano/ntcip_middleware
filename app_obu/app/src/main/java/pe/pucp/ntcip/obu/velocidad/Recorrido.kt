package pe.pucp.ntcip.obu.velocidad

import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot

/**
 * Polilínea (lat, lon) recorrida por distancia: punto y rumbo a X metros
 * del inicio, y proyección de una posición sobre ella. Lógica pura (test
 * JVM). La usa [FuenteRutaServidor] para que el vehículo emulado siga la
 * geometría del MR, y para retomar desde la misma posición si el servidor
 * envía una ruta nueva.
 */
class Recorrido(private val puntos: List<Pair<Double, Double>>) {
    private val acumulada = DoubleArray(puntos.size).also { a ->
        for (i in 1 until puntos.size) a[i] = a[i - 1] + distanciaM(puntos[i - 1], puntos[i])
    }

    val longitudM: Double get() = acumulada.lastOrNull() ?: 0.0

    data class Punto(val lat: Double, val lon: Double, val rumboDeg: Double)

    fun punto(distanciaM: Double): Punto {
        require(puntos.isNotEmpty())
        if (puntos.size == 1) return Punto(puntos[0].first, puntos[0].second, 0.0)
        val d = distanciaM.coerceIn(0.0, longitudM)
        var i = 1
        while (i < puntos.size - 1 && acumulada[i] < d) i++
        val (a, b) = puntos[i - 1] to puntos[i]
        val tramo = acumulada[i] - acumulada[i - 1]
        val f = if (tramo > 0) (d - acumulada[i - 1]) / tramo else 0.0
        return Punto(a.first + f * (b.first - a.first), a.second + f * (b.second - a.second), rumbo(a, b))
    }

    /** Distancia desde el inicio del punto de la polilínea más cercano a (lat, lon). */
    fun proyectar(lat: Double, lon: Double): Double {
        var mejorD = Double.MAX_VALUE
        var mejorS = 0.0
        for (i in 1 until puntos.size) {
            val a = puntos[i - 1]
            val b = puntos[i]
            val (bx, by) = local(a, b)
            val (px, py) = local(a, lat to lon)
            val largo2 = bx * bx + by * by
            val t = if (largo2 > 0) ((px * bx + py * by) / largo2).coerceIn(0.0, 1.0) else 0.0
            val d = hypot(px - t * bx, py - t * by)
            if (d < mejorD) {
                mejorD = d
                mejorS = acumulada[i - 1] + t * (acumulada[i] - acumulada[i - 1])
            }
        }
        return mejorS
    }

    companion object {
        private const val M_POR_GRADO = 111_320.0

        private fun local(origen: Pair<Double, Double>, p: Pair<Double, Double>): Pair<Double, Double> {
            val x = (p.second - origen.second) * M_POR_GRADO * cos(origen.first * PI / 180)
            val y = (p.first - origen.first) * M_POR_GRADO
            return x to y
        }

        fun distanciaM(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
            val (x, y) = local(a, b)
            return hypot(x, y)
        }

        fun rumbo(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
            val (x, y) = local(a, b)
            return (atan2(x, y) * 180 / PI + 360) % 360
        }
    }
}
