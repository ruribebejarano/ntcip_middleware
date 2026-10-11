#!/usr/bin/env python3
"""Simulador de OBU (unidad de a bordo) -- lado V2I del lazo EVP.

*** SIMULADOR, NO ES LA OBU REAL ***
Publica por MQTT una solicitud de prioridad semaforica hacia la RSU, tal
como haria mas adelante la aplicacion del operador (OE5, ver CLAUDE.md) una
vez que el lector OBD-II calcule el ETA real a partir de velocidad y
posicion. Por ahora el vehiculo y el ETA se pasan a mano por argumento -- no
hay lectura OBD-II ni calculo cinematico en este script.

Requiere que la RSU (Raspberry Pi) tenga agent/rsu_middleware.py corriendo
y un broker mosquitto accesible en la red (puerto 1883). Ver
docs/GUIA_COMANDOS.md para la configuracion minima de mosquitto que permite
conexiones desde otra maquina.

Uso:
    python3 gateway/obu_simulator.py --broker-host 192.168.18.163 \\
        --vehiculo-id ambulancia-1 --eta-seg 12
"""

from __future__ import annotations

import argparse
import json
import time

import paho.mqtt.client as mqtt

TOPIC = "rsu/v2i/solicitud_prioridad"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--broker-host", required=True, help="IP de la RSU (broker mosquitto)")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--vehiculo-id", required=True, help="Identificador del vehiculo, ej. ambulancia-1")
    parser.add_argument("--eta-seg", type=float, required=True, help="Tiempo estimado de llegada, en segundos")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"obu-{args.vehiculo_id}")
    client.connect(args.broker_host, args.broker_port, keepalive=10)
    client.loop_start()

    payload = json.dumps({"vehiculo_id": args.vehiculo_id, "eta_seg": args.eta_seg})
    info = client.publish(TOPIC, payload, qos=1)
    info.wait_for_publish(timeout=5)
    print(f"Solicitud de prioridad publicada en '{TOPIC}' ({args.broker_host}:{args.broker_port}): {payload}")

    time.sleep(1)  # margen para que el ack de QoS1 se procese antes de cerrar
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
