#!/usr/bin/env python3
"""Testigo del broker: mide t_up y t_down con un suscriptor en la MISMA
maquina que Mosquitto (ssec:metricas de main.tex).

*** COTA SUPERIOR, NO EL TIEMPO REAL DEL BROKER ***
Este script es un cliente MQTT mas: se suscribe a todo el trafico del lazo
(rsu/# y veh/#) y registra, con el reloj de la MAQUINA DEL BROKER, el
instante en que le llega cada mensaje. Como el testigo comparte reloj con el
broker, permite estimar sin depender de sincronizar relojes entre maquinas:

    t_up   ~= broker_rx(M1) - M1_tx      (reloj de la OBU, reloj del broker)
    t_down ~= M1_rx(RSU)    - broker_rx(M1)  (reloj del broker, reloj de la RSU)

pero el camino que mide el testigo (recibir, deserializar JSON, escribir el
evento) se SUMA al de Mosquitto: el "broker_rx" del testigo llega un poco
despues de que Mosquitto reenvio el mensaje al resto de suscriptores, nunca
antes. t_up y t_down calculados asi son, por eso, una COTA SUPERIOR del
tiempo real de cada tramo, no una medicion exacta.

t_broker (el procesamiento interno de Mosquitto entre el PUBLISH que entra y
el que sale) no es medible con este testigo ni con ningun cliente MQTT: solo
se puede estimar con una captura de paquetes (p. ej. Wireshark) corrida en la
propia maquina del broker, comparando el instante del PUBLISH entrante
(OBU -> broker) con el del PUBLISH saliente (broker -> RSU) del mismo
mensaje. Mientras tanto, t_broker queda incluido dentro de t_up + t_down
(docs/MEDICION_LATENCIA.md).

Agrega un suscriptor mas al broker (impacto marginal con el trafico de esta
etapa, pero a tener en cuenta si se corre junto con otras mediciones de
carga).

Uso (correr en la MISMA maquina que Mosquitto, ANTES de lanzar la campana):
    python3 scripts/testigo_broker.py --broker-host 127.0.0.1
    # con RSU_EVENTOS_DIR apuntando a la carpeta de la corrida, igual que el
    # resto de procesos (ver scripts/campanas/lazo_emulado.py):
    RSU_EVENTOS_DIR=resultados/lazo_emulado/<corrida> python3 scripts/testigo_broker.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import EVT_BROKER_RX, EventLogger  # noqa: E402

TEMAS = [("rsu/#", 1), ("veh/#", 1)]


def _tipo_de(data: dict, topic: str) -> str:
    """El JSON ya trae "tipo" para M1/M3 (ver gateway/obu_emulada.py); M2 lo
    trae tambien (agent/rsu_middleware.py). Si faltara, se infiere del tema
    como ultimo recurso."""
    tipo = data.get("tipo")
    if tipo:
        return str(tipo)
    return "M2" if topic.startswith("veh/") else "M1_o_M3"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker-host", default="127.0.0.1",
                    help="SIEMPRE localhost o la IP local de la propia maquina del broker")
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--nodo", default="testigo", help="nodo del registro de eventos (eventos_<nodo>.csv)")
    args = ap.parse_args()

    eventos = EventLogger(args.nodo)
    print(f"Testigo del broker: eventos en {eventos.path}")
    print(f"Suscrito a {[t for t, _ in TEMAS]} en {args.broker_host}:{args.broker_port}")
    print("Ctrl+C para detener.\n")

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        print(f"[testigo] Conectado ({reason_code}); suscribiendo...")
        client.subscribe(TEMAS)

    def on_message(_client, _userdata, msg) -> None:
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        id_solicitud = str(data.get("id_solicitud", "-"))
        tipo = _tipo_de(data, msg.topic)
        seq = data.get("seq") if tipo != "M2" else data.get("seq_ref")
        eventos.log(EVT_BROKER_RX, id_solicitud, tipo=tipo, seq=seq, topic=msg.topic)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="testigo-broker", protocol=mqtt.MQTTv5)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker_host, args.broker_port, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo testigo...")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
