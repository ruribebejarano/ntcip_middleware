package pe.pucp.ntcip.obu.obu

import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.provider.Settings

/**
 * Samsung/One UI puede matar el proceso en segundo plano aunque el
 * foreground service esté corriendo correctamente, si la app tiene
 * restricción de batería. Esto es aparte del foreground service (que ya
 * resuelve el límite de Android "puro") -- ver app_obu/README.md, sección
 * "Batería en Samsung/One UI".
 */
object BateriaUtils {
    fun tieneRestriccion(context: Context): Boolean {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return !pm.isIgnoringBatteryOptimizations(context.packageName)
    }

    /** Abre el diálogo del sistema para pedir "sin restricciones" directamente. */
    fun intentPedirSinRestricciones(context: Context): Intent =
        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
            data = android.net.Uri.parse("package:${context.packageName}")
        }

    /** Alternativa si el diálogo directo falla en algún One UI: la pantalla de detalle de la app. */
    fun intentDetalleApp(context: Context): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = android.net.Uri.parse("package:${context.packageName}")
        }
}
