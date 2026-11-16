#!/usr/bin/env python3
"""OE1: separación entre intersecciones consecutivas de una ruta real y el
tiempo que el vehículo tarda en recorrerla (t = d / v), para compararlo con
la latencia del lazo.

Fuente: la ruta de 13 RSU hacia el Instituto Nacional de Salud del Niño
(Breña), calculada por el servidor sobre el grafo de OpenStreetMap
(scripts/campanas/preparar_ruta_completa.py -> fixtures/ruta_completa/
validacion_sin_red.json, campo "paradas": distancia acumulada de cada RSU
desde el origen, en metros).

Salida: tabla LaTeX con la separación mínima, mediana y máxima y el tiempo
correspondiente a 36 km/h y a 60 km/h.

Uso: .venv/Scripts/python.exe scripts/analisis/separacion_rsu.py --salida <dir>
"""
from __future__ import annotations

import sys

import argparse
import json
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analisis"))
from leyenda_tabla import formalizar  # noqa: E402  (título corto y nota al pie)

RAIZ = Path(__file__).resolve().parent.parent.parent
FUENTE = RAIZ / "scripts" / "campanas" / "fixtures" / "ruta_completa" / "validacion_sin_red.json"
VELOCIDADES_KMH = (36.0, 60.0)


def coma(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    v = json.loads(FUENTE.read_text(encoding="utf-8"))
    acum = sorted(v["paradas"].values())
    sep = [b - a for a, b in zip(acum, acum[1:])]
    filas = []
    for nombre, d in (("Mínima", min(sep)), ("Mediana", statistics.median(sep)), ("Máxima", max(sep))):
        tiempos = " & ".join(coma(d / (kmh / 3.6)) for kmh in VELOCIDADES_KMH)
        filas.append(f"{nombre} & {coma(d, 0)} & {tiempos} \\\\")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption{Separación entre intersecciones semaforizadas "
           f"consecutivas en una ruta real de {len(acum)} intersecciones y {coma(v['ruta_m'] / 1000, 1)}~km "
           "hacia el Instituto Nacional de Salud del Niño, calculada sobre OpenStreetMap, y tiempo de recorrido "
           "$t = d/v$.}\n\\label{tab:separacion_rsu}\n\\small\n\\begin{tabular}{lrrr}\n\\toprule\n"
           "\\textbf{Separación} & \\textbf{$d$ (m)} & \\textbf{$t$ a 36~km/h (s)} & \\textbf{$t$ a 60~km/h (s)} "
           "\\\\\n\\midrule\n" + "\n".join(filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "tabla_separacion_rsu.tex").write_text(formalizar(tex), encoding="utf-8")
    print(f"{len(sep)} separaciones: min {min(sep):.1f} m, mediana {statistics.median(sep):.1f} m, "
          f"max {max(sep):.1f} m; t min a 60 km/h = {min(sep) / (60 / 3.6):.1f} s")


if __name__ == "__main__":
    main()
