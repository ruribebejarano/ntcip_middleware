#!/usr/bin/env python3
"""Linea de tiempo LEGIBLE de una prueba del lazo: junta los eventos de la
OBU (laptop), la RSU y el controlador (Raspberry Pi) y los cuenta en orden,
en espanol, una linea por paso.

Lo usa scripts/demo_lazo.sh despues de cada prueba. Tambien se puede correr a
mano:

    python scripts/demo/linea_tiempo.py --desde 1792430000 \\
        --obu resultados/eventos/eventos_obu.csv \\
        --rsu /tmp/eventos_rsu_1.csv --ctrl /tmp/eventos_ctrl_1.csv

Las horas de la OBU vienen del reloj de la laptop y las de la RSU y el
controlador del reloj de la Pi (diferencia medida: unas decenas de ms como
maximo), por eso dos pasos separados por pocos ms pueden verse en orden
invertido.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.traduccion_eventos import describir  # noqa: E402

# Colores ANSI (Git Bash los muestra). --sin-color para guardar en archivo.
COL = {"OBU": "\033[1;34m", "RSU": "\033[1;35m", "CTRL": "\033[1;33m", "fin": "\033[0m",
       "gris": "\033[2m", "ok": "\033[1;32m", "mal": "\033[1;31m"}
QUIEN = {"OBU": "OBU (laptop)       ", "RSU": "RSU (Raspberry Pi) ", "CTRL": "Controlador (Pi)   "}


def leer(ruta: str | None, desde_ns: int) -> list[dict]:
    if not ruta or not Path(ruta).exists():
        return []
    filas = []
    with open(ruta, newline="", encoding="utf-8") as fh:
        for f in csv.DictReader(fh):
            try:
                ts = int(f["ts_ns"])
            except (KeyError, ValueError):
                continue
            if ts < desde_ns:
                continue
            try:
                extra = json.loads(f.get("extra_json") or "{}")
            except json.JSONDecodeError:
                extra = {}
            filas.append({"ts": ts, "tipo": f["tipo_evento"], "id": f["id_solicitud"], "x": extra})
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--desde", type=float, required=True, help="epoch en segundos: inicio de la prueba")
    ap.add_argument("--obu")
    ap.add_argument("--rsu")
    ap.add_argument("--ctrl")
    ap.add_argument("--sin-color", action="store_true")
    args = ap.parse_args()
    if args.sin_color or not (sys.stdout.isatty() or os.environ.get("DEMO_COLOR")):
        for k in COL:
            COL[k] = ""

    desde_ns = int(args.desde * 1e9)
    todos = ([("OBU", e) for e in leer(args.obu, desde_ns)] + [("RSU", e) for e in leer(args.rsu, desde_ns)]
             + [("CTRL", e) for e in leer(args.ctrl, desde_ns)])
    todos.sort(key=lambda p: p[1]["ts"])
    if not todos:
        print("  (no hay eventos desde el inicio de esta prueba)")
        return

    pendientes_upd = 0
    ultimo_upd_ts = None
    lineas = 0

    def volcar_actualizaciones():
        nonlocal pendientes_upd
        if pendientes_upd:
            hora = datetime.fromtimestamp(ultimo_upd_ts / 1e9).strftime("%H:%M:%S")
            print(f"  {COL['gris']}{hora}      ...  {pendientes_upd} actualizaciones M1 mas (una por segundo) "
                  f"y sus respuestas M2, sin cambios{COL['fin']}")
            pendientes_upd = 0

    ultimo_estado = None
    for origen, e in todos:
        t, x = e["tipo"], e["x"]
        # Resumir lo repetitivo: actualizaciones M1 y M2 que no cambian el estado
        if origen == "OBU" and t == "M1_tx" and x.get("seq", 1) > 1:
            pendientes_upd += 1
            ultimo_upd_ts = e["ts"]
            continue
        if origen == "OBU" and t == "M2_rx":
            clave = (e["id"], x.get("estado"))
            if clave == ultimo_estado:
                continue
            ultimo_estado = clave
        if origen == "CTRL" and "Prioridad" in str(x):
            continue
        frase = describir(origen, e)
        if frase is None:
            continue
        volcar_actualizaciones()
        hora = datetime.fromtimestamp(e["ts"] / 1e9).strftime("%H:%M:%S.%f")[:-3]
        print(f"  {hora}  {COL[origen]}{QUIEN[origen]}{COL['fin']} {frase}")
        lineas += 1
    volcar_actualizaciones()


if __name__ == "__main__":
    main()
