package pe.pucp.ntcip.obu.velocidad

import kotlinx.coroutines.flow.Flow

data class MuestraPosicion(
    val lat: Double,
    val lon: Double,
    val velocidadKmh: Double,
    val rumboDeg: Double,
    val fuenteVelocidad: String, // "gps" | "simulada" -- ver nota sobre el enum del contrato en app_obu/README.md
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
 * para pruebas en mesa sin GNSS). La Etapa 2 (lector OBD-II ELM327, PID
 * 0x0D) no necesitaría una tercera implementación completa: reemplazaría
 * solo `velocidadKmh` dentro de FuenteGnss, con el GPS como respaldo si el
 * ELM327 no responde -- ver el comentario en FuenteGnss.
 */
interface FuentePosicion {
    val muestras: Flow<MuestraPosicion>
}
