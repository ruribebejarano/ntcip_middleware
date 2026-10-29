package pe.pucp.ntcip.obu

import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import pe.pucp.ntcip.obu.obu.Coordenada
import pe.pucp.ntcip.obu.obu.MensajeMF
import pe.pucp.ntcip.obu.obu.MensajeMI
import pe.pucp.ntcip.obu.obu.MensajeMP
import pe.pucp.ntcip.obu.obu.jsonObu

/**
 * Prueba de regresión del bug real visto el 2026-10-29 contra
 * servidor/main.py (APK de las 11:44, sin `encodeDefaults`): el servidor
 * imprimía "tipo desconocido en obu/{obu_id}/mision: None" porque
 * kotlinx.serialization, con `encodeDefaults` en su valor por defecto,
 * omite un campo del JSON cuando coincide con el valor por defecto de la
 * data class -- y "tipo" SIEMPRE coincide (es un valor fijo por tipo de
 * mensaje, p. ej. `val tipo: String = "MI"`). Usa `jsonObu`, el MISMO
 * serializador de MqttObuClient.kt (no una copia local), para que esta
 * prueba de verdad vigile la configuración que se publica por MQTT.
 */
class JsonObuTest {

    @Test
    fun `MI serializado trae tipo y todos los campos del contrato (docs-CONTRATO_OBU)`() {
        val mi = MensajeMI(
            obu_id = "ses-abc123",
            clase = 1,
            origen = Coordenada(lat = -12.1100, lon = -77.0320),
            destino = Coordenada(lat = -12.1022, lon = -77.0320),
            ts_ms = 1_761_144_000_000L,
        )
        val obj = jsonObu.parseToJsonElement(jsonObu.encodeToString(mi)).jsonObject

        assertEquals("MI", obj["tipo"]?.jsonPrimitive?.content)
        assertEquals("ses-abc123", obj["obu_id"]?.jsonPrimitive?.content)
        assertEquals("1", obj["clase"]?.jsonPrimitive?.content)
        assertTrue("falta 'origen'", obj.containsKey("origen"))
        assertEquals(-12.11, obj["origen"]!!.jsonObject["lat"]!!.jsonPrimitive.content.toDouble(), 1e-9)
        assertEquals(-77.032, obj["origen"]!!.jsonObject["lon"]!!.jsonPrimitive.content.toDouble(), 1e-9)
        assertTrue("falta 'destino'", obj.containsKey("destino"))
        assertEquals("1761144000000", obj["ts_ms"]?.jsonPrimitive?.content)
    }

    @Test
    fun `MP serializado trae tipo y todos los campos del contrato (docs-CONTRATO_OBU)`() {
        val mp = MensajeMP(
            obu_id = "ses-abc123",
            lat = -12.1100,
            lon = -77.0320,
            velocidad_kmh = 36.0,
            rumbo_deg = 0.0,
            fuente_velocidad = "obd2",
            ts_ms = 1_761_144_002_000L,
            seq = 2,
        )
        val obj = jsonObu.parseToJsonElement(jsonObu.encodeToString(mp)).jsonObject

        assertEquals("MP", obj["tipo"]?.jsonPrimitive?.content)
        assertEquals("ses-abc123", obj["obu_id"]?.jsonPrimitive?.content)
        assertEquals(-12.11, obj["lat"]?.jsonPrimitive?.content?.toDouble()!!, 1e-9)
        assertEquals(-77.032, obj["lon"]?.jsonPrimitive?.content?.toDouble()!!, 1e-9)
        // rumbo_deg = 0.0 es el caso que de verdad expone el bug: 0.0 NO es
        // el default de la data class (no tiene uno), pero velocidad_kmh y
        // rumbo_deg sí pueden coincidir con 0.0 en reposo -- deben seguir
        // viajando en el JSON igual (encodeDefaults no distingue "default
        // de la clase" de "valor que casualmente puesto por el llamador").
        assertEquals("0.0", obj["rumbo_deg"]?.jsonPrimitive?.content)
        assertEquals("36.0", obj["velocidad_kmh"]?.jsonPrimitive?.content)
        assertEquals("obd2", obj["fuente_velocidad"]?.jsonPrimitive?.content)
        assertEquals("1761144002000", obj["ts_ms"]?.jsonPrimitive?.content)
        assertEquals("2", obj["seq"]?.jsonPrimitive?.content)
    }

    @Test
    fun `MF serializado trae tipo y todos los campos del contrato (docs-CONTRATO_OBU)`() {
        val mf = MensajeMF(obu_id = "ses-abc123", motivo = "boton", ts_ms = 1_761_144_090_000L)
        val obj = jsonObu.parseToJsonElement(jsonObu.encodeToString(mf)).jsonObject

        assertEquals("MF", obj["tipo"]?.jsonPrimitive?.content)
        assertEquals("ses-abc123", obj["obu_id"]?.jsonPrimitive?.content)
        assertEquals("boton", obj["motivo"]?.jsonPrimitive?.content)
        assertEquals("1761144090000", obj["ts_ms"]?.jsonPrimitive?.content)
    }
}
