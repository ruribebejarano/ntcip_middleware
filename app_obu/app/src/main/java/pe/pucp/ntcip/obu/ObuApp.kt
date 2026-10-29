package pe.pucp.ntcip.obu

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import org.osmdroid.config.Configuration

class ObuApp : Application() {
    override fun onCreate() {
        super.onCreate()

        // Política de uso de tiles de OpenStreetMap: exige un User-Agent que
        // identifique la app (no el valor por defecto de osmdroid), para no
        // ser bloqueados por el servidor de tiles.
        Configuration.getInstance().userAgentValue = packageName
        Configuration.getInstance().load(this, getSharedPreferences("osmdroid", MODE_PRIVATE))

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val canal = NotificationChannel(
                CANAL_MISION,
                getString(R.string.notificacion_canal_mision),
                NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(canal)
        }
    }

    companion object {
        const val CANAL_MISION = "obu_mision"
    }
}
