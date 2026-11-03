package pe.pucp.ntcip.obu.velocidad

import kotlinx.coroutines.flow.Flow

data class MuestraPosicion(
    val lat: Double,
    val lon: Double,
    // null = sin dato de velocidad (fuenteVelocidad="respaldo"); 0.0 con
    // fuenteVelocidad="gps" = detenido, medido -- ver EvaluadorFixGnss.
    val velocidadKmh: Double?,
    val rumboDeg: Double,
    val fuenteVelocidad: String, // "gps" | "respaldo" | "simulada" -- ver nota sobre el enum del contrato en app_obu/README.md
    val tsMs: Long,
    // rumboMedido=false cuando rumboDeg viene heredado del último rumbo
    // real conocido (o del valor por defecto si nunca hubo uno) -- ver
    // FuenteGnss. precisionM=null cuando no aplica (FuenteSimulada).
    val rumboMedido: Boolean = true,
    val precisionM: Float? = null,
)

/**
 * Fuente de posición+velocidad+rumbo para el MP (docs/CONTRATO_OBU.md).
 * Dos implementaciones hoy: [pe.pucp.ntcip.obu.velocidad.FuenteGnss] (GNSS
 * real) y [pe.pucp.ntcip.obu.velocidad.FuenteSimulada] (trayectoria CSV,
 * para pruebas en mesa sin GNSS). Esta interfaz queda como punto de
 * extensión para otras fuentes de velocidad.
 */
interface FuentePosicion {
    val muestras: Flow<MuestraPosicion>
}
