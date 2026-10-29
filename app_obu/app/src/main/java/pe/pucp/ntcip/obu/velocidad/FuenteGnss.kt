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
 * red/wifi como hace la fusión de FusedLocationProvider), y la que permite
 * decidir "sin fix GNSS válido, no publicar" sin ambigüedad sobre el
 * origen de la posición.
 *
 * Etapa 2 (lector OBD-II ELM327 por Bluetooth, velocidad PID 0x0D a 1 Hz
 * con GPS de respaldo): reemplazaría solo `velocidadKmh` de cada muestra
 * aquí (manteniendo lat/lon/rumbo de este GNSS), cayendo a esta misma
 * velocidad si el ELM327 no responde -- no haría falta otra
 * implementación de FuentePosicion completa.
 */
class FuenteGnss(context: Context) : FuentePosicion {
    private val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    @SuppressLint("MissingPermission") // el llamador ya pidió ACCESS_FINE_LOCATION antes de usar esta clase
    override val muestras: Flow<MuestraPosicion> = callbackFlow {
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (!location.hasSpeed() || !location.hasBearing()) return
                trySend(
                    MuestraPosicion(
                        lat = location.latitude,
                        lon = location.longitude,
                        velocidadKmh = location.speed * 3.6,
                        rumboDeg = location.bearing.toDouble(),
                        fuenteVelocidad = "gps",
                        tsMs = location.time,
                    )
                )
            }

            @Deprecated("Deprecated in Java, pero sigue siendo parte de la interfaz LocationListener")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
        }
        lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener)
        awaitClose { lm.removeUpdates(listener) }
    }
}
