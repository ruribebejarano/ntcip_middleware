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
 */
class EvaluadorFixGnss(
    private val precisionMaximaM: Float = FuenteGnss.PRECISION_MAXIMA_DEFECTO_M,
    private val antiguedadMaximaMs: Long = FuenteGnss.ANTIGUEDAD_MAXIMA_DEFECTO_MS,
) {
    private var ultimoRumboConocido: Double? = null

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

        return MuestraPosicion(
            lat = lat,
            lon = lon,
            velocidadKmh = if (tieneVelocidad) velocidadMs * 3.6 else 0.0,
            rumboDeg = ultimoRumboConocido ?: FuenteGnss.RUMBO_POR_DEFECTO_SIN_HISTORIA,
            fuenteVelocidad = "gps",
            tsMs = tsFixMs,
            rumboMedido = rumboMedido,
            precisionM = precisionM,
        )
    }
}
