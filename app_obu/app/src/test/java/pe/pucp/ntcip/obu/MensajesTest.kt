package pe.pucp.ntcip.obu

import org.junit.Assert.assertEquals
import org.junit.Test
import pe.pucp.ntcip.obu.obu.textoEstadoNatural

/** Prueba de la traducción a español natural de docs/CONTRATO_OBU.md §4 (ME). */
class MensajesTest {
    @Test
    fun `en_espera se traduce al texto exigido por el contrato`() {
        assertEquals("en espera por otra unidad", textoEstadoNatural("en_espera"))
    }

    @Test
    fun `en_cola usa espacio en vez de guion bajo`() {
        assertEquals("en cola", textoEstadoNatural("en_cola"))
    }

    @Test
    fun `un estado desconocido se devuelve tal cual, nunca se oculta`() {
        assertEquals("algo_nuevo", textoEstadoNatural("algo_nuevo"))
    }
}
