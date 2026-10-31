package pe.pucp.ntcip.obu.velocidad

import org.junit.Assert.assertEquals
import org.junit.Test

class RecorridoTest {
    // L: ~100 m al este y luego ~100 m al norte.
    private val e = 0.000918 // ~100 m de longitud a -12°
    private val n = 0.000898 // ~100 m de latitud
    private val r = Recorrido(listOf(-12.0 to -77.0, -12.0 to -77.0 + e, -12.0 + n to -77.0 + e))

    @Test
    fun `punto a mitad de cada tramo y rumbo del tramo`() {
        assertEquals(200.0, r.longitudM, 1.0)
        val p1 = r.punto(50.0)
        assertEquals(-77.0 + e / 2, p1.lon, 1e-5)
        assertEquals(90.0, p1.rumboDeg, 0.5)
        val p2 = r.punto(150.0)
        assertEquals(-12.0 + n / 2, p2.lat, 1e-5)
        assertEquals(0.0, p2.rumboDeg, 0.5)
    }

    @Test
    fun `fuera de rango se queda en los extremos`() {
        assertEquals(-77.0, r.punto(-10.0).lon, 1e-9)
        assertEquals(-12.0 + n, r.punto(500.0).lat, 1e-9)
    }

    @Test
    fun `proyectar una posicion vuelve a su distancia sobre la ruta`() {
        // 10 m al sur del primer tramo, a 70 m del inicio
        assertEquals(70.0, r.proyectar(-12.0 - 0.00009, -77.0 + e * 0.7), 1.5)
        assertEquals(150.0, r.proyectar(-12.0 + n / 2, -77.0 + e + 0.00005), 1.5)
    }
}
