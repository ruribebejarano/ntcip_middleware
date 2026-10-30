package pe.pucp.ntcip.obu.velocidad

/**
 * Estado del GNSS para la UI (indicador antes de iniciar y durante la
 * misión) -- independiente de [MuestraPosicion]: una muestra solo existe
 * si el fix pasó el criterio de [EvaluadorFixGnss], pero el indicador
 * también tiene que poder decir "hay fix, pero con 45 m de precisión".
 */
sealed interface EstadoGnss {
    /** Modo "Ruta emulada", o todavía sin fuente GNSS arrancada. */
    data object Inactivo : EstadoGnss

    /** Sin ninguna lectura del proveedor GPS reciente. */
    data object Buscando : EstadoGnss

    /** Hay lectura, pero no pasa el criterio (precisión peor que el máximo, o sin precisión). */
    data class PrecisionInsuficiente(val precisionM: Float?, val maximaM: Float) : EstadoGnss

    /** Fix válido: es el único estado que habilita "Iniciar emergencia" con GPS real. */
    data class Listo(val precisionM: Float) : EstadoGnss
}
