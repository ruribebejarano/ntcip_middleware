"""Suscriptor MQTT 5 de la consola: escucha rsu/# y veh/# (M1/M2/M3 y el
tema legado) exactamente como centro_control/panel/pages/1_Lazo_V2I_en_vivo.py,
pero empuja cada mensaje al estado compartido y al bus de SSE en vez de a
un fragmento de Streamlit. No publica nada: es un suscriptor mas, igual
que el panel."""

from __future__ import annotations

import json
import threading
import time

import paho.mqtt.client as mqtt

from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

ICONO_TIPO = {"M1": "M1", "M2": "M2", "M3": "M3"}


def _origen_destino(topic: str, tipo: str | None) -> tuple[str, str]:
    if topic.startswith("rsu/") and topic.endswith("/solicitudes"):
        rsu_id = topic.split("/")[1]
        return "OBU", f"RSU {rsu_id}"
    if topic.startswith("veh/") and topic.endswith("/respuestas"):
        return "RSU", "OBU"
    return "?", "?"


class _Escucha:
    def __init__(self) -> None:
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="consola-web",
                                   protocol=mqtt.MQTTv5)
        self.cliente.on_connect = self._on_connect
        self.cliente.on_disconnect = self._on_disconnect
        self.cliente.on_message = self._on_message

    def _on_connect(self, client, _u, _f, reason_code, _p=None) -> None:
        ok = not reason_code.is_failure
        ESTADO.set_mqtt_conexion(ok, None if ok else str(reason_code))
        BUS.publicar("mqtt_estado", {"conectado": ok})
        client.subscribe([("rsu/#", 0), ("veh/#", 0)])

    def _on_disconnect(self, *_a, **_k) -> None:
        ESTADO.set_mqtt_conexion(False, "desconectado")
        BUS.publicar("mqtt_estado", {"conectado": False})

    def _on_message(self, _c, _u, msg) -> None:
        try:
            datos = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            datos = {"crudo": msg.payload[:120].decode("utf-8", errors="replace")}
        tipo = datos.get("tipo") if isinstance(datos, dict) else None
        if tipo is None and msg.topic == "rsu/v2i/solicitud_prioridad":
            tipo = "legado"
        entrada = {"t": time.time(), "tema": msg.topic, "tipo": tipo or "?", "datos": datos}
        ESTADO.agregar_mensaje_mqtt(entrada)
        BUS.publicar("mqtt", entrada)

        origen, destino = _origen_destino(msg.topic, tipo)
        REGISTRO.registrar(origen, destino, "MQTT", {"tema": msg.topic, "payload": datos}, None,
                           id_solicitud=str(datos.get("id_solicitud")) if isinstance(datos, dict) else None)

    def correr(self) -> None:
        while True:
            try:
                self.cliente.connect(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=30)
                self.cliente.loop_forever(retry_first_connection=True)
            except OSError as exc:
                ESTADO.set_mqtt_conexion(False, str(exc))
                BUS.publicar("mqtt_estado", {"conectado": False, "error": str(exc)})
                time.sleep(5)


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_Escucha().correr, name="mqtt-consola", daemon=True)
    hilo.start()
    return hilo
