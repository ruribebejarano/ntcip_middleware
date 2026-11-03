package pe.pucp.ntcip.obu.velocidad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * El vehículo detenido en una cola o en un semáforo en rojo es el caso
 * que motivó este criterio (ver el comentario de FuenteGnss): Android
 * normalmente deja de reportar velocidad/rumbo ahí, y el fix no debe
 * descartarse por eso.
 */
class EvaluadorFixGnssTest {

    private fun evaluador() = EvaluadorFixGnss(precisionMaximaM = 30f, antiguedadMaximaMs = 5000L)

    @Test
    fun `fix bueno con velocidad y rumbo medidos se acepta tal cual`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 10f,
            tieneRumbo = true, rumboDeg = 90f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 1000L, ahoraMs = 1500L,
        )
        assertEquals(36.0, r!!.velocidadKmh!!, 0.01) // 10 m/s * 3.6
        assertEquals("gps", r.fuenteVelocidad)
        assertEquals(90.0, r.rumboDeg, 0.01)
        assertEquals(true, r.rumboMedido)
    }

    @Test
    fun `sin lectura de velocidad (no detenido necesariamente), velocidadKmh null y fuente respaldo`() {
        val ev = evaluador()
        // primero un fix en movimiento, para dejar un rumbo conocido
        ev.evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 10f,
            tieneRumbo = true, rumboDeg = 123.0f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 1000L, ahoraMs = 1000L,
        )
        // luego Android deja de reportar speed/bearing, pero el fix sigue siendo bueno
        val sinDato = ev.evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = false, velocidadMs = 0f,
            tieneRumbo = false, rumboDeg = 0f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 2000L, ahoraMs = 2000L,
        )
        assertNull(sinDato!!.velocidadKmh) // sin dato, NO "detenido medido" (item P2)
        assertEquals("respaldo", sinDato.fuenteVelocidad)
        assertEquals(123.0, sinDato.rumboDeg, 0.01) // heredado, no inventado
        assertEquals(false, sinDato.rumboMedido)
    }

    @Test
    fun `velocidad medida por debajo del umbral de ruido es detenido medido, no sin dato`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 0.1f, // 0.36 km/h, bajo el umbral por defecto (1.0 km/h)
            tieneRumbo = true, rumboDeg = 90f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 1000L, ahoraMs = 1000L,
        )
        assertEquals(0.0, r!!.velocidadKmh!!, 0.01)
        assertEquals("gps", r.fuenteVelocidad) // medido, no "sin dato" -- distinción clave del item P2
    }

    @Test
    fun `sin ningun rumbo previo, usa el valor por defecto documentado`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = false, velocidadMs = 0f,
            tieneRumbo = false, rumboDeg = 0f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 1000L, ahoraMs = 1000L,
        )
        assertEquals(FuenteGnss.RUMBO_POR_DEFECTO_SIN_HISTORIA, r!!.rumboDeg, 0.01)
        assertEquals(false, r.rumboMedido)
    }

    @Test
    fun `precision peor que el umbral descarta el fix`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 10f,
            tieneRumbo = true, rumboDeg = 90f,
            tienePrecision = true, precisionM = 45f, // > 30 m
            tsFixMs = 1000L, ahoraMs = 1000L,
        )
        assertNull(r)
    }

    @Test
    fun `sin precision reportada se descarta (no se puede evaluar la calidad)`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 10f,
            tieneRumbo = true, rumboDeg = 90f,
            tienePrecision = false, precisionM = 0f,
            tsFixMs = 1000L, ahoraMs = 1000L,
        )
        assertNull(r)
    }

    @Test
    fun `fix demasiado antiguo se descarta aunque la precision sea buena`() {
        val r = evaluador().evaluar(
            lat = -12.10, lon = -77.03,
            tieneVelocidad = true, velocidadMs = 10f,
            tieneRumbo = true, rumboDeg = 90f,
            tienePrecision = true, precisionM = 5f,
            tsFixMs = 1000L, ahoraMs = 1000L + 5001L,
        )
        assertNull(r)
    }

    @Test
    fun `clasificar distingue buscando, precision insuficiente y listo`() {
        val ev = evaluador()
        assertEquals(EstadoGnss.Listo(8f), ev.clasificar(true, 8f, tsFixMs = 1000L, ahoraMs = 1500L))
        assertEquals(EstadoGnss.Listo(30f), ev.clasificar(true, 30f, tsFixMs = 1000L, ahoraMs = 1500L))
        assertEquals(EstadoGnss.PrecisionInsuficiente(45f, 30f), ev.clasificar(true, 45f, tsFixMs = 1000L, ahoraMs = 1500L))
        assertEquals(EstadoGnss.PrecisionInsuficiente(null, 30f), ev.clasificar(false, 0f, tsFixMs = 1000L, ahoraMs = 1500L))
        // lectura vieja: no hay señal ahora, aunque su precisión fuera buena
        assertEquals(EstadoGnss.Buscando, ev.clasificar(true, 5f, tsFixMs = 1000L, ahoraMs = 1000L + 5001L))
    }
}
