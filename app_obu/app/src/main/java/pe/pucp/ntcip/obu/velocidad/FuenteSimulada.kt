package pe.pucp.ntcip.obu.velocidad

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Trayectoria pregrabada para probar en mesa sin GNSS: mismo formato CSV
 * que produce scripts/trayectorias/generar.py y que lee
 * gateway/obu_emulada.py (columnas t_s, lat, lon, rumbo_deg,
 * velocidad_kmh, leídas por nombre de cabecera, no por posición -- la
 * trayectoria de referencia trae columnas extra de verdad de terreno que
 * se ignoran aquí).
 *
 * [factor] acelera la reproducción (1 = tiempo real), igual que --factor de
 * obu_emulada.py: solo el reloj, la velocidad_kmh de cada fila no se
 * escala (el servidor ve la misma geometría y velocidades que a x1, solo
 * más rápido). Es solo para demos -- ver EventosObu.DEMO.
 *
 * El flujo TERMINA al llegar a la última fila: ObuSessionService lo usa
 * para cerrar la misión sola (MF motivo="destino", como obu_emulada.py).
 *
 * `fuente_velocidad` va como "simulada" en el MP -- valor NO contemplado
 * en el enum de docs/CONTRATO_OBU.md ("obd2"|"gps"|"respaldo"); es un
 * campo informativo que el servidor no valida, pero el contrato debería
 * documentarlo (ver app_obu/README.md, sección "Modo simulado").
 */
class FuenteSimulada(
    private val context: Context,
    private val uriTrayectoria: Uri?,
    private val assetTrayectoria: String = TRAYECTORIA_INTEGRADA,
    private val factor: Double = 1.0,
) : FuentePosicion {

    /**
     * Primera fila de la trayectoria, sin reproducir nada: antes de iniciar
     * la misión el vehículo queda quieto ahí (y esa es la posición que va
     * como origen del MI, coherente con donde arranca la reproducción).
     */
    fun primerPunto(): MuestraPosicion? = leerFilas().firstOrNull()?.let { muestraDe(it) }

    override val muestras: Flow<MuestraPosicion> = flow {
        val filas = leerFilas()
        if (filas.isEmpty()) return@flow
        val t0Mono = System.nanoTime()
        val t0Tray = filas[0].tS
        for (fila in filas) {
            val objetivoNs = t0Mono + ((fila.tS - t0Tray) / factor * 1_000_000_000.0).toLong()
            val esperaMs = (objetivoNs - System.nanoTime()) / 1_000_000L
            if (esperaMs > 0) delay(esperaMs)
            emit(muestraDe(fila))
        }
    }

    private fun muestraDe(fila: FilaCsv) = MuestraPosicion(
        lat = fila.lat,
        lon = fila.lon,
        velocidadKmh = fila.velocidadKmh,
        rumboDeg = fila.rumboDeg,
        fuenteVelocidad = "simulada",
        tsMs = System.currentTimeMillis(),
    )

    private data class FilaCsv(
        val tS: Double,
        val lat: Double,
        val lon: Double,
        val velocidadKmh: Double,
        val rumboDeg: Double,
    )

    private fun leerFilas(): List<FilaCsv> {
        val lector: BufferedReader = if (uriTrayectoria != null) {
            BufferedReader(InputStreamReader(context.contentResolver.openInputStream(uriTrayectoria)))
        } else {
            BufferedReader(InputStreamReader(context.assets.open(assetTrayectoria)))
        }
        return lector.use { r ->
            val cabecera = r.readLine()?.removePrefix("\uFEFF")?.split(",") ?: return emptyList()
            val idx = cabecera.withIndex().associate { (i, n) -> n.trim() to i }
            r.lineSequence()
                .filter { it.isNotBlank() }
                .map { linea ->
                    val c = linea.split(",")
                    FilaCsv(
                        tS = c[idx.getValue("t_s")].toDouble(),
                        lat = c[idx.getValue("lat")].toDouble(),
                        lon = c[idx.getValue("lon")].toDouble(),
                        velocidadKmh = c[idx.getValue("velocidad_kmh")].toDouble(),
                        rumboDeg = c[idx.getValue("rumbo_deg")].toDouble(),
                    )
                }
                .toList()
        }
    }

    companion object {
        // avenida_ab_s1.csv cruza las dos RSU del registro (OSM-C24 y
        // OSM-C902, rsu_id 1 y 2) -- a propósito la misma trayectoria que
        // recomienda app_obu/README.md para la prueba en mesa con
        // pruebas/registro_rsu_mesa.json (solo RSU 2): así el modo
        // simulado por defecto y la prueba en mesa documentada son la
        // misma corrida, sin tener que elegir un archivo.
        const val TRAYECTORIA_INTEGRADA = "trayectorias/avenida_ab_s1.csv"

        /**
         * Nombre de archivo para mostrar en la UI ("trayectoria_casa.csv"),
         * no el URI de SAF ("primary:Download/..."). null = la integrada.
         */
        fun nombreVisible(context: Context, uriTrayectoria: Uri?): String {
            if (uriTrayectoria == null) return TRAYECTORIA_INTEGRADA.substringAfterLast('/') + " (incluida)"
            val nombre = runCatching {
                context.contentResolver.query(uriTrayectoria, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                    ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
            }.getOrNull()
            return nombre ?: uriTrayectoria.lastPathSegment?.substringAfterLast('/') ?: uriTrayectoria.toString()
        }
    }
}
