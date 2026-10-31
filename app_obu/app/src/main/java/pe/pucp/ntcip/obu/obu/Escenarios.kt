package pe.pucp.ntcip.obu.obu

import android.content.Context
import android.net.Uri
import kotlinx.serialization.Serializable
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada

@Serializable
data class Destino(val nombre: String, val lat: Double, val lon: Double)

/** Trayectoria + destino de una prueba en "Ruta emulada" (assets/escenarios/escenarios.json). */
@Serializable
data class Escenario(val id: String, val nombre: String, val trayectoria: String, val destino: Destino)

@Serializable
private data class CatalogoEscenarios(val escenarios: List<Escenario>, val destinos: List<Destino> = emptyList())

/** Qué CSV reproduce la "Ruta emulada": un asset (escenario incluido) o un archivo elegido en Ajustes. */
data class TrayectoriaElegida(val asset: String?, val uri: Uri?, val nombreVisible: String)

object Escenarios {
    /** Valor de Prefs.escenarioId cuando la trayectoria es un archivo propio (Ajustes > Elegir archivo). */
    const val ID_ARCHIVO = "archivo"
    const val ID_POR_DEFECTO = "hospital_nino"

    private var catalogo: CatalogoEscenarios? = null

    private fun cargar(context: Context): CatalogoEscenarios = catalogo ?: context.assets
        .open("escenarios/escenarios.json").bufferedReader().use { it.readText() }
        .let { jsonObu.decodeFromString(CatalogoEscenarios.serializer(), it) }
        .also { catalogo = it }

    fun lista(context: Context): List<Escenario> = cargar(context).escenarios

    fun destinos(context: Context): List<Destino> = cargar(context).destinos

    fun porId(context: Context, id: String?): Escenario? = lista(context).firstOrNull { it.id == id }

    /** El escenario guardado, o el de por defecto si el guardado ya no existe. null = archivo propio. */
    fun actual(context: Context, prefs: Prefs): Escenario? {
        if (prefs.escenarioId == ID_ARCHIVO && prefs.trayectoriaUri != null) return null
        return porId(context, prefs.escenarioId) ?: porId(context, ID_POR_DEFECTO) ?: lista(context).first()
    }

    fun trayectoria(context: Context, prefs: Prefs): TrayectoriaElegida {
        val esc = actual(context, prefs)
        if (esc != null) return TrayectoriaElegida(esc.trayectoria, null, esc.nombre)
        val uri = Uri.parse(prefs.trayectoriaUri)
        return TrayectoriaElegida(null, uri, FuenteSimulada.nombreVisible(context, uri))
    }

    fun fuente(context: Context, prefs: Prefs, factor: Double = 1.0): FuenteSimulada {
        val t = trayectoria(context, prefs)
        return FuenteSimulada(context, t.uri, t.asset ?: FuenteSimulada.TRAYECTORIA_INTEGRADA, factor)
    }
}
