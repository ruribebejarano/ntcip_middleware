package pe.pucp.ntcip.obu.obu

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Estado compartido entre [pe.pucp.ntcip.obu.obu.ObuSessionService] y la
 * UI (MainActivity), en el mismo proceso -- no hace falta Binder/Messenger
 * porque Activity y Service viven en la misma app. Invariante: solo UNO de
 * los dos escribe `ultimaPosicion` a la vez (la Activity mientras no hay
 * misión activa, para centrar el mapa; el Service mientras hay una misión,
 * que es cuando manda la posición real que se publica).
 */
data class EstadoSesion(
    val misionActiva: Boolean = false,
    val obuId: String? = null,
    val ultimaRuta: MensajeMR? = null,
    val ultimoEstado: MensajeME? = null,
    val ultimaPosicion: Pair<Double, Double>? = null,
    val sinFixGnss: Boolean = false,
    val sinConexionServidor: Boolean = false,
    val motivoFinReciente: String? = null,
)

object ObuSessionRepository {
    private val _estado = MutableStateFlow(EstadoSesion())
    val estado: StateFlow<EstadoSesion> = _estado

    fun actualizar(transformacion: (EstadoSesion) -> EstadoSesion) {
        _estado.value = transformacion(_estado.value)
    }

    fun reiniciar() {
        _estado.value = EstadoSesion()
    }
}
