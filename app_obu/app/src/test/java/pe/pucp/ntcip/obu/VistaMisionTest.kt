package pe.pucp.ntcip.obu

import org.junit.Assert.assertEquals
import org.junit.Test
import pe.pucp.ntcip.obu.obu.EstadoVisual
import pe.pucp.ntcip.obu.obu.GeometriaRuta
import pe.pucp.ntcip.obu.obu.ParadaEstado
import pe.pucp.ntcip.obu.obu.VistaMision

class VistaMisionTest {

    // Recta hacia el este, ~100 m entre vértices (0.000917° de lon a -12°).
    private val puntos = (0..4).map { -12.0 to -77.0 + it * 0.000918 }

    @Test
    fun `cada RSU se ubica en el vertice de su distancia, reescalando a longitud_total_m`() {
        // Las aristas del grafo miden un 10 % más que la línea recta (curvas):
        val g = GeometriaRuta(puntos, longitudTotalM = 440.0)
        assertEquals(puntos[2], g.puntoEnDistancia(220.0))
        assertEquals(puntos[4], g.puntoEnDistancia(440.0))
        assertEquals(220.0, g.progresoM(-12.0001, -77.0 + 2 * 0.000918)!!, 1.0)
    }

    @Test
    fun `cancelada con el vehiculo ya pasado el cruce es cruzada, antes es cancelada`() {
        assertEquals(EstadoVisual.CRUZADA, VistaMision.estadoVisual("cancelada", progresoM = 310.0, distanciaLlegadaM = 300.0))
        assertEquals(EstadoVisual.CRUZADA, VistaMision.estadoVisual("cancelada", progresoM = 285.0, distanciaLlegadaM = 300.0))
        assertEquals(EstadoVisual.CANCELADA, VistaMision.estadoVisual("cancelada", progresoM = 150.0, distanciaLlegadaM = 300.0))
        assertEquals(EstadoVisual.CANCELADA, VistaMision.estadoVisual("cancelada", progresoM = null, distanciaLlegadaM = 300.0))
    }

    @Test
    fun `estados del ME a estados visuales`() {
        assertEquals(EstadoVisual.VERDE, VistaMision.estadoVisual("concedida", 0.0, 300.0))
        assertEquals(EstadoVisual.VERDE, VistaMision.estadoVisual("concedida", 0.0, 300.0, fase = "verde"))
        assertEquals(EstadoVisual.CAMBIANDO, VistaMision.estadoVisual("concedida", 0.0, 300.0, fase = "todo_rojo"))
        assertEquals(EstadoVisual.CAMBIANDO, VistaMision.estadoVisual("concedida", 0.0, 300.0, fase = "amarillo"))
        assertEquals(EstadoVisual.SOLICITANDO, VistaMision.estadoVisual("solicitada", 0.0, 300.0))
        assertEquals(EstadoVisual.DESPEJE, VistaMision.estadoVisual("en_cola", 0.0, 300.0))
        assertEquals(EstadoVisual.EN_ESPERA, VistaMision.estadoVisual("en_espera", 0.0, 300.0))
        assertEquals(EstadoVisual.PENDIENTE, VistaMision.estadoVisual("pendiente", 0.0, 300.0))
        assertEquals(EstadoVisual.OMITIDA, VistaMision.estadoVisual("pendiente", 400.0, 300.0))
    }

    private fun parada(estado: String = "concedida", fase: String? = null, accion: String? = null,
                       tHastaVerdeMs: Long? = null, anticipacionS: Double? = null) =
        ParadaEstado("OSM-1", "4", "A", estado, fase = fase, accion = accion,
            t_hasta_verde_ms = tHastaVerdeMs, anticipacion_s = anticipacionS)

    @Test
    fun `detalle con los campos nuevos del ME`() {
        assertEquals("Extensión de verde · 12.0 s", VistaMision.textoDetalle(parada(accion = "extension", anticipacionS = 12.0)))
        assertEquals("Esperó despeje · 3.5 s", VistaMision.textoDetalle(parada(accion = "en_cola_despeje", tHastaVerdeMs = 3500)))
        assertEquals("Verde adelantado · 6.0 s", VistaMision.textoDetalle(parada(accion = "verde_adelantado", tHastaVerdeMs = 6000)))
    }

    @Test
    fun `detalle sin los campos nuevos muestra solo estado y fase`() {
        assertEquals("Estado: concedida · fase verde", VistaMision.textoDetalle(parada(fase = "verde")))
        assertEquals("Estado: en cola", VistaMision.textoDetalle(parada(estado = "en_cola")))
    }
}
