package pe.pucp.ntcip.obu.velocidad

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import pe.pucp.ntcip.obu.obu.MensajeMR

/**
 * "Ruta libre" en ruta emulada: el vehículo recorre la geometría del MR que
 * calculó el servidor (servidor/rutas.py sobre el grafo de OSM) para el
 * origen y el destino elegidos en el mapa, a [velocidadKmh] -- sin
 * trayectoria pregrabada. Antes de que llegue el MR no emite nada (el MP
 * espera, igual que sin fix GNSS). Si llega un MR con otra versión
 * (recálculo), sigue desde su posición proyectada sobre la ruta nueva.
 *
 * Emite cada [PASO_MS] para que el mapa se mueva fluido; el MP sigue a 1 Hz
 * (ObuSessionService toma la última muestra). [factor] acelera solo el
 * reloj (demo), igual que en [FuenteSimulada]. El flujo termina al llegar
 * al final de la ruta: ObuSessionService cierra la misión (MF "destino").
 */
class FuenteRutaServidor(
    private val rutaActual: () -> MensajeMR?,
    private val velocidadKmh: Double = VELOCIDAD_POR_DEFECTO_KMH,
    private val factor: Double = 1.0,
) : FuentePosicion {

    override val muestras: Flow<MuestraPosicion> = flow {
        var version = -1
        var recorrido: Recorrido? = null
        var avanceM = 0.0
        val avancePorPasoM = velocidadKmh / 3.6 * factor * PASO_MS / 1000.0
        while (true) {
            val mr = rutaActual()
            if (mr != null && mr.version != version && mr.geometria.size >= 2) {
                val nuevo = Recorrido(mr.geometria.map { it[0] to it[1] })
                avanceM = recorrido?.punto(avanceM)?.let { nuevo.proyectar(it.lat, it.lon) } ?: 0.0
                recorrido = nuevo
                version = mr.version
            }
            val r = recorrido
            if (r != null) {
                val p = r.punto(avanceM)
                val alFinal = avanceM >= r.longitudM
                emit(
                    MuestraPosicion(
                        lat = p.lat, lon = p.lon,
                        velocidadKmh = if (alFinal) 0.0 else velocidadKmh,
                        rumboDeg = p.rumboDeg, fuenteVelocidad = "simulada",
                        tsMs = System.currentTimeMillis(),
                    ),
                )
                if (alFinal) return@flow
                avanceM += avancePorPasoM
            }
            delay(PASO_MS)
        }
    }

    companion object {
        const val VELOCIDAD_POR_DEFECTO_KMH = 40.0
        const val PASO_MS = 200L
    }
}
