package pe.pucp.ntcip.obu.obu

import com.hivemq.client.mqtt.MqttClientSslConfig
import com.hivemq.client.mqtt.MqttGlobalPublishFilter
import com.hivemq.client.mqtt.datatypes.MqttQos
import com.hivemq.client.mqtt.mqtt5.Mqtt5BlockingClient
import com.hivemq.client.mqtt.mqtt5.Mqtt5Client
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import pe.pucp.ntcip.obu.seguridad.TlsConfig
import java.nio.charset.StandardCharsets

/**
 * Wrapper delgado sobre HiveMQ MQTT Client (MQTT 5, QoS 1) que publica/
 * recibe exactamente los mensajes de docs/CONTRATO_OBU.md -- equivalente
 * Android de gateway/obu_emulada.py. Client ID "obu-{obu_id}" (§1 del
 * contrato).
 */
class MqttObuClient(
    private val host: String,
    private val port: Int,
    private val obuId: String,
    private val tls: TlsConfig? = null, // Etapa 3 (docs/CONTRATO_OBU.md §1); null = sin TLS (broker de desarrollo)
    private val onRuta: (MensajeMR) -> Unit,
    private val onEstado: (MensajeME) -> Unit,
    private val onConexion: (conectado: Boolean) -> Unit,
) {
    private val json = jsonObu
    private var cliente: Mqtt5BlockingClient? = null

    // El cliente existe desde ANTES de conectar: con reconexión automática,
    // connect() puede quedarse reintentando (broker inalcanzable) y, si la
    // misión termina en ese lapso, hay que poder cerrarlo -- si no, sigue
    // reintentando en segundo plano y se conecta más tarde como una sesión
    // fantasma (visto el 2026-10-31 con Tailscale en otra cuenta).
    @Volatile private var construido: Mqtt5BlockingClient? = null

    suspend fun conectar() = withContext(Dispatchers.IO) {
        // automaticReconnectWithDefaultConfig(): NO hace falta volver a
        // suscribir a mano en el callback de reconexion. Verificado contra
        // un mosquitto real (prompt_integracion_app_obu.md, item 2a.1): el
        // MqttClientReconnector interno de HiveMQ trae
        // DEFAULT_RESUBSCRIBE_IF_SESSION_EXPIRED = true, y con
        // sessionExpiryInterval = 0 (por defecto) cada reconexion cuenta
        // como sesion expirada -- la libreria reenvia el SUBSCRIBE sola.
        var builder = Mqtt5Client.builder()
            .identifier("obu-$obuId")
            .serverHost(host)
            .serverPort(port)
            .automaticReconnectWithDefaultConfig()
            .addConnectedListener { onConexion(true) }
            .addDisconnectedListener { onConexion(false) }
        // tls == null: sin TLS, broker de desarrollo plano, permitido por
        // §1 del contrato para esta etapa (ver seguridad/TlsConfig.kt).
        // Reasignar `builder`, no descartar el valor de retorno: los
        // builders de HiveMQ no garantizan mutar la misma instancia.
        val tlsActual = tls
        if (tlsActual != null) {
            builder = builder.sslConfig(
                MqttClientSslConfig.builder()
                    .keyManagerFactory(tlsActual.keyManagerFactory())
                    .trustManagerFactory(tlsActual.trustManagerFactory())
                    .build(),
            )
        }
        val c = builder.buildBlocking()
        construido = c

        c.connect()

        c.toAsync().publishes(MqttGlobalPublishFilter.ALL) { publish ->
            val topico = publish.topic.toString()
            val cuerpo = String(publish.payloadAsBytes, StandardCharsets.UTF_8)
            when {
                topico.endsWith("/ruta") ->
                    runCatching { json.decodeFromString<MensajeMR>(cuerpo) }.getOrNull()?.let(onRuta)
                topico.endsWith("/estado") ->
                    runCatching { json.decodeFromString<MensajeME>(cuerpo) }.getOrNull()?.let(onEstado)
            }
        }

        c.subscribeWith().topicFilter("obu/$obuId/ruta").qos(MqttQos.AT_LEAST_ONCE).send()
        c.subscribeWith().topicFilter("obu/$obuId/estado").qos(MqttQos.AT_LEAST_ONCE).send()

        cliente = c
    }

    suspend fun enviarMI(mi: MensajeMI) = publicar("obu/$obuId/mision", json.encodeToString(mi))
    suspend fun enviarMP(mp: MensajeMP) = publicar("obu/$obuId/posicion", json.encodeToString(mp))
    suspend fun enviarMF(mf: MensajeMF) = publicar("obu/$obuId/mision", json.encodeToString(mf))

    private suspend fun publicar(topico: String, cuerpoJson: String) = withContext(Dispatchers.IO) {
        // runCatching: con la conexión caída (reconectando) HiveMQ lanza
        // excepción en vez de encolar; perder un MP es preferible a cerrar la app.
        runCatching {
            cliente?.publishWith()
                ?.topic(topico)
                ?.qos(MqttQos.AT_LEAST_ONCE)
                ?.payload(cuerpoJson.toByteArray(StandardCharsets.UTF_8))
                ?.send()
        }
    }

    suspend fun desconectar() = withContext(Dispatchers.IO) {
        // disconnect() también detiene la reconexión automática en curso.
        runCatching { (cliente ?: construido)?.disconnect() }
        cliente = null
        construido = null
    }
}
