#!/usr/bin/env python3
"""Fase 4, prueba 1 con la RSU física: observador que corre EN la Raspberry
Pi durante una repetición de inyección de fallos.

A 10 Hz, con el reloj de la Pi (time.time_ns):
  - consulta el controlador emulado (127.0.0.1:9000, su propio protocolo,
    igual que la RSU): fase y prioridad_activa;
  - lee el estado de la interfaz del módem (/sys/class/net/<if>/operstate;
    "ausente" si la interfaz desapareció, p. ej. al desconectar el módem USB);
  - lee su dirección IPv4 (vacía mientras el módem no tenga red): separa,
    dentro del tiempo de recuperación, el re-registro del módem en la red
    celular de lo que tarda después la conexión MQTT.
Escribe un CSV y termina tras --duracion segundos. No cambia nada en la Pi.

Uso (en la Pi): python3 scripts/evaluacion/observador_rsu.py --salida /tmp/obs.csv --duracion 240 --interfaz usb0
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path


def ipv4_interfaz(nombre: str) -> str:
    """IPv4 de la interfaz por ioctl SIOCGIFADDR (sin lanzar procesos, para
    no perturbar el muestreo a 10 Hz); "" si no tiene o no existe."""
    try:
        import fcntl
        import struct
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            r = fcntl.ioctl(sk.fileno(), 0x8915, struct.pack("256s", nombre[:15].encode()))
        return socket.inet_ntoa(r[20:24])
    except (OSError, ImportError):
        return ""


def estado_interfaz(nombre: str) -> str:
    p = Path(f"/sys/class/net/{nombre}/operstate")
    try:
        return p.read_text().strip()
    except OSError:
        return "ausente"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True)
    ap.add_argument("--duracion", type=float, default=240.0)
    ap.add_argument("--interfaz", default="usb0")
    ap.add_argument("--puerto", type=int, default=9000)
    args = ap.parse_args()
    fin = time.monotonic() + args.duracion
    s = f = None
    with open(args.salida, "w", encoding="utf-8", buffering=1) as out:
        out.write("ts_ns,prioridad_activa,fase,interfaz,ipv4\n")
        while time.monotonic() < fin:
            prio, fase = "", ""
            try:
                if s is None:
                    s = socket.create_connection(("127.0.0.1", args.puerto), timeout=1)
                    f = s.makefile("r", encoding="utf-8")
                s.sendall(b'{"cmd": "get_status"}\n')
                e = json.loads(f.readline())
                prio, fase = int(bool(e["prioridad_activa"])), e["fase"]
            except (OSError, ValueError):
                s = None
            out.write(f"{time.time_ns()},{prio},{fase},{estado_interfaz(args.interfaz)},"
                      f"{ipv4_interfaz(args.interfaz)}\n")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
