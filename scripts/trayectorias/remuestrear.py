#!/usr/bin/env python3
"""Remuestrea un CSV de trayectoria a un paso fijo por interpolación lineal.

La OBU emulada publica un MP por fila (gateway/obu_emulada.py) y el servidor
renueva M1 con cada MP, así que el paso de la trayectoria ES la frecuencia de
actualización de la corrida (RNF-02, >= 1 Hz).

Posición: interpolación lineal entre filas (basta para los pocos metros de un
paso). Rumbo y velocidad: los de la fila anterior, no se interpolan (un
promedio de rumbos cerca de 0/360 daría un valor sin sentido).

Uso:
    python scripts/trayectorias/remuestrear.py <archivo.csv> [...] --paso 1.0
Sobrescribe cada archivo.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CAMPOS = ["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh"]


def remuestrear(filas: list[dict], paso_s: float) -> list[dict]:
    """Filas con t_s = t0, t0+paso, ... hasta el último t_s de `filas`."""
    salida = []
    t_ini, t_fin = float(filas[0]["t_s"]), float(filas[-1]["t_s"])
    n = int(round((t_fin - t_ini) / paso_s))
    i = 0
    for k in range(n + 1):
        t = t_ini + k * paso_s
        while i < len(filas) - 2 and float(filas[i + 1]["t_s"]) <= t:
            i += 1
        a, b = filas[i], filas[min(i + 1, len(filas) - 1)]
        ta, tb = float(a["t_s"]), float(b["t_s"])
        f = (t - ta) / (tb - ta) if tb > ta else 0.0
        origen = b if f >= 1.0 else a
        salida.append({
            "t_s": f"{t:.1f}",
            "lat": f"{float(a['lat']) + f * (float(b['lat']) - float(a['lat'])):.7f}",
            "lon": f"{float(a['lon']) + f * (float(b['lon']) - float(a['lon'])):.7f}",
            "rumbo_deg": origen["rumbo_deg"],
            "velocidad_kmh": origen["velocidad_kmh"],
        })
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archivos", nargs="+", type=Path)
    ap.add_argument("--paso", type=float, default=1.0, help="segundos entre muestras")
    args = ap.parse_args()
    for ruta in args.archivos:
        with ruta.open(newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        nuevas = remuestrear(filas, args.paso)
        with ruta.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CAMPOS, lineterminator="\n")
            w.writeheader()
            w.writerows(nuevas)
        print(f"{ruta}: {len(filas)} -> {len(nuevas)} filas (paso {args.paso} s)")


if __name__ == "__main__":
    main()
