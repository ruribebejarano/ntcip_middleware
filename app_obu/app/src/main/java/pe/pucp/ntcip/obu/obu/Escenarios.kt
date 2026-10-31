package pe.pucp.ntcip.obu.obu

import android.content.Context
import android.net.Uri
import kotlinx.serialization.Serializable
import pe.pucp.ntcip.obu.velocidad.FuenteSimulada

@Serializable
data class Destino(val nombre: String, val lat: Double, val lon: Double)

/** Trayectoria grabada + destino de una prueba en "Ruta emulada" (assets/escenarios/escenarios.json). */
@Serializable
data class Escenario(val id: String, val nombre: String, val trayectoria: String, val destino: Destino)

/** Caja del grafo de calles del servidor (data/grafo_san_miguel_real.graphml): fuera de ella no hay rutas reales. */
@Serializable
data class Cobertura(val sur: Double, val norte: Double, val oeste: Double, val este: Double) {
    fun contiene(lat: Double, lon: Double) = lat in sur..norte && lon in oeste..este
}

@Serializable
private data class CatalogoEscenarios(val escenarios: List<Escenario>, val cobertura_grafo: Cobertura)

@Serializable
data class Hospital(val nombre: String, val tipo: String, val lat: Double, val lon: Double, val emergencia: Boolean = false)

@Serializable
private data class CatalogoHospitales(val base: Destino, val hospitales: List<Hospital>)

@Serializable
data class CentroRsu(val lat: Double, val lon: Double)

@Serializable
data class RsuZona(val rsu_id: String, val interseccion_id: String, val nombre: String = "", val centro: CentroRsu)

@Serializable
private data class RegistroZona(val rsu: List<RsuZona>)

/** Qué CSV reproduce la "Ruta emulada": un asset (escenario incluido) o un archivo elegido en Ajustes. */
data class TrayectoriaElegida(val asset: String?, val uri: Uri?, val nombreVisible: String)

object Escenarios {
    /** Valor de Prefs.escenarioId cuando la trayectoria es un archivo propio (Ajustes > Elegir archivo). */
    const val ID_ARCHIVO = "archivo"

    /** Origen y destino elegidos en el mapa; el vehículo sigue la ruta del MR (FuenteRutaServidor). */
    const val ID_RUTA_LIBRE = "ruta_libre"
    const val ID_POR_DEFECTO = ID_RUTA_LIBRE

    private var catalogo: CatalogoEscenarios? = null
    private var hospitales: CatalogoHospitales? = null
    private var rsuZona: List<RsuZona>? = null

    private fun leer(context: Context, asset: String) =
        context.assets.open(asset).bufferedReader().use { it.readText() }

    private fun cargar(context: Context): CatalogoEscenarios = catalogo
        ?: jsonObu.decodeFromString(CatalogoEscenarios.serializer(), leer(context, "escenarios/escenarios.json"))
            .also { catalogo = it }

    private fun cargarHospitales(context: Context): CatalogoHospitales = hospitales
        ?: jsonObu.decodeFromString(CatalogoHospitales.serializer(), leer(context, "zona/hospitales_zona_pucp.json"))
            .also { hospitales = it }

    fun lista(context: Context): List<Escenario> = cargar(context).escenarios

    fun cobertura(context: Context): Cobertura = cargar(context).cobertura_grafo

    /** Hospitales y clínicas con emergencia de OSM (app_obu/pruebas/generar_zona_pucp.py). */
    fun hospitales(context: Context): List<Hospital> = cargarHospitales(context).hospitales

    /** Origen por defecto de la ruta libre: la base de la zona (PUCP, Av. Universitaria). */
    fun base(context: Context): Destino = cargarHospitales(context).base

    /**
     * RSU del registro "zona PUCP" -- SOLO para dibujarlas en el mapa: el
     * registro que vale es el que carga el servidor (ssec:registro); la
     * misión usa las paradas del MR.
     */
    fun rsuZona(context: Context): List<RsuZona> = rsuZona
        ?: jsonObu.decodeFromString(RegistroZona.serializer(), leer(context, "zona/registro_rsu_zona_pucp.json")).rsu
            .also { rsuZona = it }

    fun porId(context: Context, id: String?): Escenario? = lista(context).firstOrNull { it.id == id }

    fun esRutaLibre(prefs: Prefs): Boolean =
        prefs.escenarioId == null || prefs.escenarioId == ID_RUTA_LIBRE ||
            (prefs.escenarioId == ID_ARCHIVO && prefs.trayectoriaUri == null)

    /** El escenario grabado elegido; null = ruta libre o archivo propio. */
    fun actual(context: Context, prefs: Prefs): Escenario? {
        if (esRutaLibre(prefs) || prefs.escenarioId == ID_ARCHIVO) return null
        return porId(context, prefs.escenarioId)
    }

    /** Id efectivo (para marcar el chip): ruta libre si el guardado ya no existe. */
    fun idActual(context: Context, prefs: Prefs): String = when {
        esRutaLibre(prefs) -> ID_RUTA_LIBRE
        prefs.escenarioId == ID_ARCHIVO -> ID_ARCHIVO
        actual(context, prefs) != null -> prefs.escenarioId!!
        else -> ID_RUTA_LIBRE
    }

    fun trayectoria(context: Context, prefs: Prefs): TrayectoriaElegida {
        val esc = actual(context, prefs)
        if (esc != null) return TrayectoriaElegida(esc.trayectoria, null, esc.nombre)
        val uri = prefs.trayectoriaUri?.let(Uri::parse)
        return if (uri != null) TrayectoriaElegida(null, uri, FuenteSimulada.nombreVisible(context, uri))
        else TrayectoriaElegida(FuenteSimulada.TRAYECTORIA_INTEGRADA, null, "avenida_ab_s1")
    }

    fun fuente(context: Context, prefs: Prefs, factor: Double = 1.0): FuenteSimulada {
        val t = trayectoria(context, prefs)
        return FuenteSimulada(context, t.uri, t.asset ?: FuenteSimulada.TRAYECTORIA_INTEGRADA, factor)
    }
}
