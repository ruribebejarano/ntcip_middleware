package pe.pucp.ntcip.obu.obu

import android.content.Context

/** Nada hardcodeado (ver docs/CONTRATO_OBU.md): host/puerto/clase se configuran en Ajustes. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("obu_prefs", Context.MODE_PRIVATE)

    var brokerHost: String
        get() = sp.getString(CLAVE_HOST, HOST_TAILSCALE) ?: HOST_TAILSCALE
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

    /** URI (SAF) del archivo propio elegido en Ajustes; solo se usa con escenarioId = [Escenarios.ID_ARCHIVO]. */
    var trayectoriaUri: String?
        get() = sp.getString(CLAVE_TRAYECTORIA_URI, null)
        set(v) = sp.edit().putString(CLAVE_TRAYECTORIA_URI, v).apply()

    /** Último escenario elegido (assets/escenarios/escenarios.json), o [Escenarios.ID_ARCHIVO]. */
    var escenarioId: String?
        get() = sp.getString(CLAVE_ESCENARIO, null)
        set(v) = sp.edit().putString(CLAVE_ESCENARIO, v).apply()

    /** Velocidad de reproducción de la ruta emulada (1, 2 o 4). Solo demo: se marca en el CSV de eventos. */
    var factorDemo: Int
        get() = sp.getInt(CLAVE_FACTOR_DEMO, 1)
        set(v) = sp.edit().putInt(CLAVE_FACTOR_DEMO, v).apply()

    var vibrarAlVerde: Boolean
        get() = sp.getBoolean(CLAVE_VIBRAR, true)
        set(v) = sp.edit().putBoolean(CLAVE_VIBRAR, v).apply()

    companion object {
        // Hosts predefinidos de Ajustes. Tailscale: IP de la laptop en el
        // tailnet (la tablet ya está en él, ver app_obu/README.md "Probar en
        // la tablet real"); Emulador: la laptop vista desde el emulador de Android.
        const val HOST_TAILSCALE = "100.121.77.97"
        const val HOST_EMULADOR = "10.0.2.2"

        private const val CLAVE_HOST = "broker_host"
        private const val CLAVE_PUERTO = "broker_puerto"
        private const val CLAVE_CLASE = "clase"
        private const val CLAVE_MODO_SIMULADO = "modo_simulado"
        private const val CLAVE_TRAYECTORIA_URI = "trayectoria_uri"
        private const val CLAVE_ESCENARIO = "escenario_id"
        private const val CLAVE_FACTOR_DEMO = "factor_demo"
        private const val CLAVE_VIBRAR = "vibrar_al_verde"
    }
}
