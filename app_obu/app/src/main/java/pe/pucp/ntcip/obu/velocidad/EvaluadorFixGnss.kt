package pe.pucp.ntcip.obu.velocidad

/**
 * Lógica pura (sin `android.location.Location`) de "¿este fix GNSS es
 * válido, y qué MuestraPosicion le corresponde?" -- separada de
 * [FuenteGnss] a propósito, para poder probarla con un test JVM normal
 * (`app/src/test/`), sin Robolectric ni un dispositivo/emulador. Ver el
 * criterio completo (por qué no se exige velocidad ni rumbo) en el
 * comentario de [FuenteGnss].
 *
 * Con estado: recuerda el último rumbo medido entre llamadas, para
 * heredarlo cuando un fix válido no trae rumbo propio (vehículo
 * detenido). Una instancia por misión -- igual que [FuenteGnss], que es
 * quien la crea.
 *
 * `velocidadKmh` de la [MuestraPosicion] resultante distingue (ítem P2 de
 * `prompt_cierre_repo_2026-11-02.md`, docs/CONTRATO_OBU.md §MP) "sin dato
 * de velocidad" de "detenido, medido": sin lectura de velocidad
 * (`!tieneVelocidad`) es `null` + `fuenteVelocidad="respaldo"`; con
 * lectura y ésta por debajo de [umbralDetenidoKmh] (ruido del GNSS a
 * velocidad casi nula) es `0.0` + `fuenteVelocidad="gps"` -- el servidor
 * usa esa distinción para no seguir re-pidiendo prioridad por ETA
 * mientras el vehículo está genuinamente detenido lejos de la RSU (antes
 * ambos casos llegaban como `0.0`+`"gps"` y el servidor no podía
 * diferenciarlos).
 */
class EvaluadorFixGnss(
    private val precisionMaximaM: Float = FuenteGnss.PRECISION_MAXIMA_DEFECTO_M,
    private val antiguedadMaximaMs: Long = FuenteGnss.ANTIGUEDAD_MAXIMA_DEFECTO_MS,
    private val umbralDetenidoKmh: Double = FuenteGnss.UMBRAL_DETENIDO_KMH_DEFECTO,
) {
    private var ultimoRumboConocido: Double? = null

    /**
     * Mismo criterio que [evaluar], pero para el indicador de la UI: una
     * lectura vieja cuenta como "buscando" (no hay señal ahora), una
     * lectura actual con mala precisión como [EstadoGnss.PrecisionInsuficiente].
     */
    fun clasificar(tienePrecision: Boolean, precisionM: Float, tsFixMs: Long, ahoraMs: Long): EstadoGnss = when {
        ahoraMs - tsFixMs > antiguedadMaximaMs -> EstadoGnss.Buscando
        !tienePrecision -> EstadoGnss.PrecisionInsuficiente(null, precisionMaximaM)
        precisionM > precisionMaximaM -> EstadoGnss.PrecisionInsuficiente(precisionM, precisionMaximaM)
        else -> EstadoGnss.Listo(precisionM)
    }

    /** `null` si el fix no pasa el criterio de validez (se descarta, no se publica). */
    fun evaluar(
        lat: Double,
        lon: Double,
        tieneVelocidad: Boolean,
        velocidadMs: Float,
        tieneRumbo: Boolean,
        rumboDeg: Float,
        tienePrecision: Boolean,
        precisionM: Float,
        tsFixMs: Long,
        ahoraMs: Long,
    ): MuestraPosicion? {
        if (!tienePrecision || precisionM > precisionMaximaM) return null
        if (ahoraMs - tsFixMs > antiguedadMaximaMs) return null

        val rumboMedido = tieneRumbo
        if (rumboMedido) ultimoRumboConocido = rumboDeg.toDouble()

        val velocidadMedidaKmh = if (tieneVelocidad) velocidadMs * 3.6 else null

        return MuestraPosicion(
            lat = lat,
            lon = lon,
            velocidadKmh = velocidadMedidaKmh?.let { if (it <= umbralDetenidoKmh) 0.0 else it },
            rumboDeg = ultimoRumboConocido ?: FuenteGnss.RUMBO_POR_DEFECTO_SIN_HISTORIA,
            fuenteVelocidad = if (tieneVelocidad) "gps" else "respaldo",
            tsMs = tsFixMs,
            rumboMedido = rumboMedido,
            precisionM = precisionM,
        )
    }
}
