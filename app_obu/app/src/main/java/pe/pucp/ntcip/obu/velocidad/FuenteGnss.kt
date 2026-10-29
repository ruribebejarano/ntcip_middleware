package pe.pucp.ntcip.obu.velocidad

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/**
 * GNSS real vía `LocationManager.GPS_PROVIDER` directo -- sin Google Play
 * Services ni FusedLocationProvider: es la única fuente que cuenta como
 * GNSS real para `fuente_velocidad="gps"` del contrato (no se mezcla con
 * red/wifi como hace la fusión de FusedLocationProvider).
 *
 * **Criterio de "fix válido"** (aplicado en [EvaluadorFixGnss], que
 * concentra la lógica pura y probada por unidad): proveedor GPS,
 * precisión horizontal (`Location.accuracy`, radio en metros) dentro de
 * [precisionMaximaM], y antigüedad de la lectura (`Location.time`, reloj
 * del propio GNSS) menor a [antiguedadMaximaMs]. Deliberadamente NO se
 * exige velocidad ni rumbo: con el vehículo detenido (cola, semáforo en
 * rojo) Android normalmente deja de reportar `speed`/`bearing` aunque el
 * fix siga siendo bueno, y descartar esas muestras congelaría la misión
 * en el servidor justo en el momento más importante (ver
 * `gateway/geometria.py::SeguidorAcceso`: usa el `rumbo_deg` reportado
 * para decidir si la OBU sigue "con el rumbo correcto" hacia el acceso ya
 * asignado -- un rumbo por defecto en vez del último real podría disparar
 * una cancelación por `MOTIVO_RUMBO` mientras el vehículo solo está
 * parado en la cola, no desviado).
 * - Sin velocidad (`!hasSpeed()`): se envía `velocidadKmh = 0.0`.
 * - Sin rumbo (`!hasBearing()`): se hereda el último rumbo real conocido
 *   de esta misma misión; si nunca hubo uno todavía (vehículo detenido
 *   antes de moverse por primera vez), se usa 0.0° como mejor esfuerzo
 *   sin mejor alternativa -- `rumbo_deg` es obligatorio en el MP del
 *   contrato, no tiene valor "desconocido", y
 *   `servidor/gestor_mision.py::procesar_mp` pasa este valor directo
 *   (sin recalcularlo él mismo) a `SeguidorAcceso.actualizar()`. El
 *   riesgo de ese 0.0° por defecto es bajo: para que importe, el
 *   vehículo ya tendría que estar dentro del radio de detección de una
 *   RSU sin haberse movido nunca desde el arranque de la misión -- con
 *   el espaciado real entre RSU de este proyecto (cientos de metros) no
 *   pasa en la práctica.
 *
 * Etapa 2 (lector OBD-II ELM327 por Bluetooth, velocidad PID 0x0D a 1 Hz
 * con GPS de respaldo): reemplazaría solo `velocidadKmh` de cada muestra
 * aquí (manteniendo lat/lon/rumbo de este GNSS), cayendo a esta misma
 * velocidad si el ELM327 no responde -- no haría falta otra
 * implementación de FuentePosicion completa.
 */
class FuenteGnss(
    context: Context,
    precisionMaximaM: Float = PRECISION_MAXIMA_DEFECTO_M,
    antiguedadMaximaMs: Long = ANTIGUEDAD_MAXIMA_DEFECTO_MS,
) : FuentePosicion {
    private val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val evaluador = EvaluadorFixGnss(precisionMaximaM, antiguedadMaximaMs)

    @SuppressLint("MissingPermission") // el llamador ya pidió ACCESS_FINE_LOCATION antes de usar esta clase
    override val muestras: Flow<MuestraPosicion> = callbackFlow {
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (location.provider != LocationManager.GPS_PROVIDER) return
                val muestra = evaluador.evaluar(
                    lat = location.latitude,
                    lon = location.longitude,
                    tieneVelocidad = location.hasSpeed(),
                    velocidadMs = location.speed,
                    tieneRumbo = location.hasBearing(),
                    rumboDeg = location.bearing,
                    tienePrecision = location.hasAccuracy(),
                    precisionM = location.accuracy,
                    tsFixMs = location.time,
                    ahoraMs = System.currentTimeMillis(),
                ) ?: return
                trySend(muestra)
            }

            @Deprecated("Deprecated in Java, pero sigue siendo parte de la interfaz LocationListener")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
        }
        lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener)
        awaitClose { lm.removeUpdates(listener) }
    }

    companion object {
        const val PRECISION_MAXIMA_DEFECTO_M = 30f
        const val ANTIGUEDAD_MAXIMA_DEFECTO_MS = 5000L
        const val RUMBO_POR_DEFECTO_SIN_HISTORIA = 0.0
    }
}
