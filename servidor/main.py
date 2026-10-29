#!/usr/bin/env python3
"""Proceso del servidor central: MQTT 5 + servidor/gestor_mision.py, análogo
a agent/rsu_middleware.py del lado de la RSU.

Temas (tab:mensajes de la sección 1.2 del prompt de arquitectura
centralizada):

  MI  <- obu/{obu_id}/mision      {tipo:"MI", obu_id, clase, destino:{lat,lon},
                                    origen:{lat,lon} opcional, ts_ms}
  MF  <- obu/{obu_id}/mision      {tipo:"MF", obu_id, motivo, ts_ms}
  MP  <- obu/{obu_id}/posicion    {tipo:"MP", obu_id, lat, lon, velocidad_kmh,
                                    rumbo_deg, fuente_velocidad, ts_ms, seq}
  MR  -> obu/{obu_id}/ruta        (servidor/gestor_mision.py::_cuerpo_mr)
  ME  -> obu/{obu_id}/estado      (servidor/gestor_mision.py::_cuerpo_me)
  M1  -> rsu/{rsu_id}/solicitudes (servidor/gestor_mision.py::_cuerpo_m1),
         con Response Topic = TOPIC_RESPUESTAS_SERVIDOR y Correlation Data
         = id_solicitud, para que la RSU (agent/rsu_middleware.py, sin
         cambios en esa mecánica) responda M2 al servidor.
  M3  -> rsu/{rsu_id}/solicitudes
  M2  <- TOPIC_RESPUESTAS_SERVIDOR (Response Topic de MQTT 5, no un tema fijo
         por RSU: lo decide el propio M1/M3 que lo originó)

*** Si no hay "origen" en el MI *** (el mensaje mínimo de tab:mensajes no lo
exige, solo "obu_id, clase, destino, marca de tiempo"): el servidor no
puede calcular la ruta hasta tener una posición. Se guarda la misión como
"pendiente" y se arma con la PRIMERA muestra MP que llegue de esa OBU (ver
_mi_pendiente abajo). Esto es una decisión de implementación, no está en el
prompt original -- documentarla en docs/CONTRATO_OBU.md.

*** Seguridad (P4, servidor/gestor_mision.py no decide esto) ***
La identidad del servidor (único publicador autorizado en
`rsu/+/solicitudes`) y la identidad de cada OBU (autorizada solo en sus
propios `obu/{obu_id}/mision` y `obu/{obu_id}/posicion`) se hacen cumplir en
el BROKER (ACL de Mosquitto + mTLS, ver scripts/seguridad/), no en este
proceso: este código confía en que, si el mensaje llegó, el broker ya
validó quién lo podía publicar. Ver docs/bitacora/2026-10-22_arquitectura-centralizada.md
para el estado real de esa configuración en este entorno.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from common.events import EventLogger  # noqa: E402
from gateway.geometria import cargar_registro  # noqa: E402
from servidor import rutas as rutas_mod  # noqa: E402
from servidor.gestor_mision import GestorMision  # noqa: E402

MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
SERVIDOR_ID = os.environ.get("SERVIDOR_ID", "central")
TOPIC_RESPUESTAS_SERVIDOR = f"servidor/{SERVIDOR_ID}/respuestas"

REGISTRO_RSU_PATH = os.environ.get("REGISTRO_RSU_PATH", str(RAIZ / "config" / "registro_rsu.json"))
GRAFO_PATH = os.environ.get("GRAFO_PATH", str(RAIZ / "data" / "grafo_san_miguel_real.graphml"))
# "0"/"" (real, data/*.graphml) | "1" o "recta" (recta sintetica, pruebas/demo
# de lazo simple) | "cruce" (cruce sintetico, demo del arbitraje de
# conflictos -- ver evidencia/2026-10-22_arquitectura-centralizada/)
GRAFO_SINTETICO = os.environ.get("GRAFO_SINTETICO", "0").strip().lower()

# mTLS opcional (P4, ver scripts/seguridad/generar_ca.py). Si no se definen
# estas tres variables, se conecta sin TLS (como hoy agent/rsu_middleware.py).
TLS_CA_CERT = os.environ.get("SERVIDOR_TLS_CA")
TLS_CERTFILE = os.environ.get("SERVIDOR_TLS_CERT")
TLS_KEYFILE = os.environ.get("SERVIDOR_TLS_KEY")

EVENTOS = EventLogger("servidor")

# Misiones con MI recibido pero sin "origen": clase y destino en espera de
# la primera muestra MP para poder calcular la ruta (ver docstring del
# módulo).
_mi_pendiente: dict[str, dict] = {}

_MQTT_CLIENT: mqtt.Client | None = None
GESTOR: GestorMision | None = None


# --- Publicación hacia RSU / OBU -------------------------------------------


def _enviar_m1(rsu_id: str, cuerpo: dict) -> None:
    _publicar_con_respuesta(f"rsu/{rsu_id}/solicitudes", cuerpo)


def _enviar_m3(rsu_id: str, cuerpo: dict) -> None:
    _publicar_con_respuesta(f"rsu/{rsu_id}/solicitudes", cuerpo)


def _publicar_con_respuesta(topic: str, cuerpo: dict) -> None:
    if _MQTT_CLIENT is None:
        return
    props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
    props.ResponseTopic = TOPIC_RESPUESTAS_SERVIDOR
    props.CorrelationData = str(cuerpo["id_solicitud"]).encode("utf-8")
    _MQTT_CLIENT.publish(topic, json.dumps(cuerpo), qos=1, properties=props)


def _enviar_mr(obu_id: str, cuerpo: dict) -> None:
    if _MQTT_CLIENT is not None:
        _MQTT_CLIENT.publish(f"obu/{obu_id}/ruta", json.dumps(cuerpo), qos=1)


def _enviar_me(obu_id: str, cuerpo: dict) -> None:
    if _MQTT_CLIENT is not None:
        _MQTT_CLIENT.publish(f"obu/{obu_id}/estado", json.dumps(cuerpo), qos=1)


# --- Suscripción desde OBU / RSU -------------------------------------------


def _on_connect(client: mqtt.Client, _userdata, _flags, reason_code, _properties=None) -> None:
    print(f"[servidor] Conectado al broker ({MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}), reason_code={reason_code}")
    client.subscribe([
        ("obu/+/mision", 1),
        ("obu/+/posicion", 1),
        (TOPIC_RESPUESTAS_SERVIDOR, 1),
    ])


def _on_message(_client, _userdata, msg) -> None:
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[servidor] Mensaje inválido en '{msg.topic}': {exc}")
        return

    if msg.topic == TOPIC_RESPUESTAS_SERVIDOR:
        _procesar_m2(data)
        return

    partes = msg.topic.split("/")
    if len(partes) != 3 or partes[0] != "obu":
        print(f"[servidor] Tema no reconocido: {msg.topic}")
        return
    obu_id, canal = partes[1], partes[2]

    if canal == "mision":
        tipo = data.get("tipo")
        if tipo == "MI":
            _procesar_mi(obu_id, data)
        elif tipo == "MF":
            _procesar_mf(obu_id, data)
        else:
            print(f"[servidor] tipo desconocido en obu/{obu_id}/mision: {tipo!r}")
    elif canal == "posicion":
        _procesar_mp(obu_id, data)
    else:
        print(f"[servidor] canal desconocido: {msg.topic}")


def _procesar_mi(obu_id: str, data: dict) -> None:
    try:
        clase = int(data["clase"])
        destino = data["destino"]
        destino_t = (float(destino["lat"]), float(destino["lon"]))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[servidor] MI inválido de '{obu_id}': {exc}")
        return

    origen = data.get("origen")
    if origen is not None:
        origen_t = (float(origen["lat"]), float(origen["lon"]))
        GESTOR.armar_mision(obu_id, clase, origen_t, destino_t)
    else:
        _mi_pendiente[obu_id] = {"clase": clase, "destino": destino_t}
        print(f"[servidor] MI de '{obu_id}' sin posición inicial: se arma la misión con la primera MP")


def _procesar_mf(obu_id: str, data: dict) -> None:
    motivo = data.get("motivo", "boton")
    GESTOR.desarmar_mision(obu_id, motivo=motivo)
    _mi_pendiente.pop(obu_id, None)


def _procesar_mp(obu_id: str, data: dict) -> None:
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        velocidad_kmh = float(data.get("velocidad_kmh", 0.0))
        rumbo_deg = float(data.get("rumbo_deg", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[servidor] MP inválido de '{obu_id}': {exc}")
        return

    pendiente = _mi_pendiente.pop(obu_id, None)
    if pendiente is not None and obu_id not in GESTOR.misiones:
        GESTOR.armar_mision(obu_id, pendiente["clase"], (lat, lon), pendiente["destino"])

    GESTOR.procesar_mp(obu_id, lat, lon, velocidad_kmh, rumbo_deg, seq=data.get("seq"))


def _procesar_m2(data: dict) -> None:
    GESTOR.procesar_m2(data)


# --- Arranque ---------------------------------------------------------


def _cargar_grafo():
    if GRAFO_SINTETICO in ("1", "recta"):
        print("[servidor] GRAFO_SINTETICO=recta: usando el grafo sintético recto de pruebas (coordenadas inventadas)")
        return rutas_mod.construir_grafo_sintetico()
    if GRAFO_SINTETICO == "cruce":
        print("[servidor] GRAFO_SINTETICO=cruce: usando el grafo sintético de cruce (demo de conflictos)")
        return rutas_mod.construir_grafo_cruce_sintetico()
    ruta = Path(GRAFO_PATH)
    if not ruta.exists():
        raise SystemExit(
            f"[servidor] No se encontró el grafo cacheado en '{ruta}'. "
            "Corre scripts/datos/regenerar_grafo.py (requiere osmnx e internet), "
            "o arranca con GRAFO_SINTETICO=1 para usar el grafo sintético de pruebas."
        )
    print(f"[servidor] Cargando grafo cacheado desde '{ruta}'")
    return rutas_mod.cargar_grafo(ruta)


def _tls_kwargs() -> dict | None:
    if not (TLS_CA_CERT and TLS_CERTFILE and TLS_KEYFILE):
        return None
    return {
        "ca_certs": TLS_CA_CERT, "certfile": TLS_CERTFILE, "keyfile": TLS_KEYFILE,
        "tls_version": ssl.PROTOCOL_TLS_CLIENT,
    }


def main() -> None:
    global _MQTT_CLIENT, GESTOR

    print("=== Servidor central (arquitectura centralizada) ===")
    print(f"SERVIDOR_ID={SERVIDOR_ID} -- registro de eventos en {EVENTOS.path}")

    registro = cargar_registro(REGISTRO_RSU_PATH)
    grafo = _cargar_grafo()

    GESTOR = GestorMision(
        grafo, registro,
        enviar_m1=_enviar_m1, enviar_m3=_enviar_m3, enviar_mr=_enviar_mr, enviar_me=_enviar_me,
        eventos=EVENTOS,
    )

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"servidor-{SERVIDOR_ID}",
                         protocol=mqtt.MQTTv5)
    client.on_connect = _on_connect
    client.on_message = _on_message

    tls_kwargs = _tls_kwargs()
    if tls_kwargs:
        client.tls_set(**tls_kwargs)
        print("[servidor] mTLS habilitado (CA/cert/key provistos por variables de entorno)")
    else:
        print("[servidor] AVISO: sin mTLS -- variables SERVIDOR_TLS_CA/CERT/KEY no definidas "
              "(ver scripts/seguridad/generar_ca.py y docs/bitacora/2026-10-22_arquitectura-centralizada.md)")

    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
    _MQTT_CLIENT = client
    print(f"[servidor] Escuchando en mqtt://{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} "
          f"(obu/+/mision, obu/+/posicion, {TOPIC_RESPUESTAS_SERVIDOR})")
    print("Ctrl+C para detener.\n")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[servidor] Deteniendo...")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
