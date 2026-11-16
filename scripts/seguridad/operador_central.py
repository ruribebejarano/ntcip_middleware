#!/usr/bin/env python3
"""Operador de la central (rol humano, emulado para las pruebas de
seguridad operativa; ver servidor/seguridad.py y
docs/PRUEBA_SEGURIDAD_OPERATIVA.md).

Se conecta con la identidad "operador-central" (mTLS), recibe las alertas
del servidor y, para cada una que corresponda, envía un comando tras un
retardo que representa el tiempo de respuesta humana: leer la alerta,
llamar a la central de despacho de la institución dueña del vehículo y
decidir. Ese tiempo NO se mide en el banco; es un parámetro de la prueba.

Política emulada:
  - verificacion_despacho: el despacho confirma solo las OBU de
    --despacho-confirma; las demás no tienen una emergencia en curso ->
    suspender_obu (misión falsa).
  - salto_posicion, inundacion, misiones_repetidas: suspender_obu.

Uso en una prueba (lo lanza scripts/seguridad/prueba_seguridad_operativa.py):
    python scripts/seguridad/operador_central.py --broker-port 8884 --tls deploy/pki \\
        --retardo-s 30 --despacho-confirma obu-legit-r01

Uso manual, un solo comando (p. ej. desde la consola de la central):
    python scripts/seguridad/operador_central.py --broker-port 8883 --tls deploy/pki \\
        --comando suspender_obu --obu-id obu-tab-01
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import EventLogger  # noqa: E402
from common.mqtt_tls import aplicar_tls  # noqa: E402
from scripts.seguridad import generar_ca  # noqa: E402

TOPIC_ALERTAS = "servidor/central/alertas"
TOPIC_COMANDOS = "servidor/central/comandos"
ALERTAS_QUE_SUSPENDEN = ("salto_posicion", "inundacion", "misiones_repetidas")


def _tls(tls_dir: Path) -> tuple[str, str, str]:
    generar_ca.PKI = tls_dir
    generar_ca.CA_DIR = tls_dir / "ca"
    _cn, nombre, out = generar_ca._nombre("operador", None)
    if not (out / f"{nombre}.crt").exists():
        generar_ca.emitir("operador", None)
    return str(generar_ca.CA_DIR / "ca.crt"), str(out / f"{nombre}.crt"), str(out / f"{nombre}.key")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker-host", default="127.0.0.1")
    ap.add_argument("--broker-port", type=int, default=8883)
    ap.add_argument("--tls", required=True, help="carpeta de la PKI (deploy/pki)")
    ap.add_argument("--retardo-s", type=float, default=30.0, help="tiempo de respuesta humana emulado")
    ap.add_argument("--despacho-confirma", default="", help="obu_id con emergencia real, separados por coma")
    ap.add_argument("--sin-accion", action="store_true", help="solo registra las alertas (sin operador)")
    ap.add_argument("--comando", choices=["suspender_obu", "reanudar_obu", "suspender_mision", "confirmar_mision"])
    ap.add_argument("--obu-id")
    args = ap.parse_args()
    confirmadas = {x.strip() for x in args.despacho_confirma.split(",") if x.strip()}

    eventos = EventLogger("operador")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="operador-central", protocol=mqtt.MQTTv5)
    aplicar_tls(client, *_tls(Path(args.tls)), puerto=args.broker_port)

    def enviar(accion: str, obu_id: str, motivo: str) -> None:
        cuerpo = {"accion": accion, "obu_id": obu_id, "motivo": motivo, "ts_ms": int(time.time() * 1000)}
        client.publish(TOPIC_COMANDOS, json.dumps(cuerpo), qos=1)
        eventos.log("comando_tx", obu_id, accion=accion, obu_id=obu_id, motivo=motivo)
        print(f"[operador] -> {accion} {obu_id} ({motivo})")

    if args.comando:
        if not args.obu_id:
            raise SystemExit("--comando requiere --obu-id")
        listo = threading.Event()
        client.on_connect = lambda c, *_a: (enviar(args.comando, args.obu_id, "manual"), listo.set())
        client.connect(args.broker_host, args.broker_port)
        client.loop_start()
        listo.wait(10)
        time.sleep(1.0)
        client.loop_stop()
        client.disconnect()
        return

    atendidas: set[tuple[str, str]] = set()

    def decidir(alerta: dict) -> None:
        tipo, obu_id = alerta.get("alerta"), alerta.get("obu_id")
        if args.sin_accion or not obu_id or (tipo, obu_id) in atendidas:
            return
        if tipo == "verificacion_despacho":
            accion, motivo = (("confirmar_mision", "despacho_confirma") if obu_id in confirmadas
                              else ("suspender_obu", "despacho_sin_emergencia"))
        elif tipo in ALERTAS_QUE_SUSPENDEN:
            accion, motivo = "suspender_obu", f"alerta_{tipo}"
        else:
            return
        atendidas.add((tipo, obu_id))
        threading.Timer(args.retardo_s, enviar, args=(accion, obu_id, motivo)).start()

    def on_connect(c, _u, _f, rc, _p=None):
        print(f"[operador] conectado ({rc}); retardo de respuesta {args.retardo_s:.0f} s")
        c.subscribe(TOPIC_ALERTAS, qos=1)

    def on_message(_c, _u, msg):
        try:
            alerta = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        eventos.log("alerta_rx", alerta.get("obu_id", "-"), alerta=alerta.get("alerta"),
                    obu_id=alerta.get("obu_id"), severidad=alerta.get("severidad"))
        print(f"[operador] <- alerta {alerta.get('severidad')}: {alerta.get('alerta')} de {alerta.get('obu_id')}")
        decidir(alerta)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker_host, args.broker_port)
    print("[operador] escuchando alertas (Ctrl+C para salir)")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
