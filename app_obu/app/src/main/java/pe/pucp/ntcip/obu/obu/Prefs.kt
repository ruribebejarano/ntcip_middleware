package pe.pucp.ntcip.obu.obu

import android.content.Context

/** Nada hardcodeado (ver docs/CONTRATO_OBU.md): host/puerto/clase se configuran en Ajustes. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("obu_prefs", Context.MODE_PRIVATE)

    var brokerHost: String
        get() = sp.getString(CLAVE_HOST, "") ?: ""
        set(v) = sp.edit().putString(CLAVE_HOST, v).apply()

    var brokerPuerto: Int
        get() = sp.getInt(CLAVE_PUERTO, 1883)
        set(v) = sp.edit().putInt(CLAVE_PUERTO, v).apply()

    var clase: Int
        get() = sp.getInt(CLAVE_CLASE, 1)
        set(v) = sp.edit().putInt(CLAVE_CLASE, v).apply()

    var modoSimulado: Boolean
        get() = sp.getBoolean(CLAVE_MODO_SIMULADO, false)
        set(v) = sp.edit().putBoolean(CLAVE_MODO_SIMULADO, v).apply()

    /** URI (SAF) de la trayectoria elegida; null = usar la incluida en assets/. */
    var trayectoriaUri: String?
        get() = sp.getString(CLAVE_TRAYECTORIA_URI, null)
        set(v) = sp.edit().putString(CLAVE_TRAYECTORIA_URI, v).apply()

    private companion object {
        const val CLAVE_HOST = "broker_host"
        const val CLAVE_PUERTO = "broker_puerto"
        const val CLAVE_CLASE = "clase"
        const val CLAVE_MODO_SIMULADO = "modo_simulado"
        const val CLAVE_TRAYECTORIA_URI = "trayectoria_uri"
    }
}
