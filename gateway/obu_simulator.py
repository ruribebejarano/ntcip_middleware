#!/usr/bin/env python3
"""Simulador de OBU (unidad de a bordo) -- lado V2I del lazo EVP.

*** LEGADO (P0-P3, pre-arquitectura centralizada, 2026-10-22) ***
Publica un M1 directo a la RSU (`rsu/v2i/solicitud_prioridad`) con un ETA a
mano, sin pasar por el servidor central ni por una misión armada. Sigue
funcionando (agent/rsu_middleware.py mantiene ese camino sin cambios, ver
`_procesar_m1_legado`), pero ya NO representa el diseño vigente de la OBU:
ver gateway/obu_emulada.py para el cliente delgado (MI/MP/MF hacia el
servidor, que es quien decide a qué RSU y cuándo). Se conserva solo para
las pruebas que ya dependían de este camino directo (demo_asesor.sh).

*** SIMULADOR, NO ES LA OBU REAL ***
Publica por MQTT una solicitud de prioridad semaforica hacia la RSU, tal
como haria mas adelante la aplicacion del operador (OE4, ver CLAUDE.md) una
vez que el lector OBD-II calcule el ETA real a partir de velocidad y
posicion. Por ahora el vehiculo y el ETA se pasan a mano por argumento -- no
hay lectura OBD-II ni calculo cinematico en este script.

Requiere que la RSU (Raspberry Pi) tenga agent/rsu_middleware.py corriendo
y un broker mosquitto accesible en la red (puerto 1883). Ver
docs/GUIA_COMANDOS.md para la configuracion minima de mosquitto que permite
conexiones desde otra maquina.

Registra un evento M1_tx (ver common/events.py, RF-10) con el
id_solicitud generado para esta corrida, para poder cruzarlo despues con
los eventos del lado de la RSU y del controlador
(scripts/analisis/latencia_tramos.py).

Uso:
    python3 gateway/obu_simulator.py --broker-host 192.168.18.175 \\
        --vehiculo-id ambulancia-1 --eta-seg 12
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import EVT_M1_TX, EventLogger  # noqa: E402

TOPIC = "rsu/v2i/solicitud_prioridad"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--broker-host", required=True, help="IP de la RSU (broker mosquitto)")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--vehiculo-id", required=True, help="Identificador del vehiculo, ej. ambulancia-1")
    parser.add_argument("--eta-seg", type=float, required=True, help="Tiempo estimado de llegada, en segundos")
    parser.add_argument(
        "--clase-tipo", type=int, default=1,
        help="priorityRequestVehicleClassType de NTCIP 1211 (1-10, 1=maxima precedencia). "
             "Default 1 (reconocido como emergencia, ver RF-05 y agent/ntcip1211.py). "
             "Usar un valor fuera de CLASES_EMERGENCIA_RECONOCIDAS para probar el rechazo.",
    )
    parser.add_argument(
        "--obu-id",
        default="obu",
        help="Nodo para el registro de eventos (default: 'obu'). Usar un valor "
             "distinto por instancia si se corren varias OBU simuladas a la vez "
             "(cada una escribe su propio eventos_<obu-id>.csv).",
    )
    args = parser.parse_args()

    eventos = EventLogger(args.obu_id)
    id_solicitud = f"{args.vehiculo_id}-{uuid.uuid4().hex[:8]}"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"obu-{args.vehiculo_id}")
    client.connect(args.broker_host, args.broker_port, keepalive=10)
    client.loop_start()

    payload = json.dumps({
        "id_solicitud": id_solicitud,
        "vehiculo_id": args.vehiculo_id,
        "eta_seg": args.eta_seg,
        "clase_tipo": args.clase_tipo,
    })
    info = client.publish(TOPIC, payload, qos=1)
    info.wait_for_publish(timeout=5)
    eventos.log(
        EVT_M1_TX,
        id_solicitud,
        vehiculo_id=args.vehiculo_id,
        eta_seg=args.eta_seg,
        clase_tipo=args.clase_tipo,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        topic=TOPIC,
    )
    print(f"Solicitud de prioridad publicada en '{TOPIC}' ({args.broker_host}:{args.broker_port}): {payload}")
    print(f"id_solicitud={id_solicitud} (evento M1_tx registrado en {eventos.path})")

    time.sleep(1)  # margen para que el ack de QoS1 se procese antes de cerrar
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
