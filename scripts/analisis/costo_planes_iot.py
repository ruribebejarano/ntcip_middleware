#!/usr/bin/env python3
"""Costo mensual de datos de una RSU con planes IoT de tarifa publicada que
cubren Perú (sección 4.6.3 de la tesis, dimensionamiento del despliegue).

Entrada: la proyección mensual de datos de una RSU con TLS 1.3 que calcula
scripts/evaluacion/resumen_fase4.py (resumen_fase4.json, clave
bytes.proyeccion_MB_mes), es decir, los mismos valores de la Tabla
tab:proyeccion_datos.

Tarifas: las publicadas por cada proveedor, consultadas el 2026-11-14, sin
impuestos (IGV) y sin cargos únicos (tarjeta SIM, activación). Solo se
incluyen planes cuya página o lista de precios nombra a Perú:

- 1NCE High Data IoT: Perú está en la zona 3 del Apéndice 1 de la lista de
  precios de 1NCE Inc. (octubre de 2026): US$0,60 al mes por SIM y
  US$12,00 por GB. Se toma 1 GB = 1000 MB, lo que redondea el costo hacia
  arriba.
- Telnyx: página de SIM IoT para Perú, desde US$0,0625 por MB, sin cargo
  mensual (solo US$1 por SIM, una vez).

El volumen proyectado es carga TCP, sin encabezados IP ni TCP, de modo que
el costo facturado será algo mayor.

Uso: .venv/Scripts/python.exe scripts/analisis/costo_planes_iot.py \
       --resumen <dir con resumen_fase4.json> --salida <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# (nombre en la tabla, cargo mensual por SIM en US$, US$ por MB)
PLANES = (
    ("1NCE (US\\$/mes)", 0.60, 12.00 / 1000),
    ("Telnyx (US\\$/mes)", 0.0, 0.0625),
)


def coma(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def costo_mensual(mb_mes: float, fijo: float, por_mb: float) -> float:
    return fijo + mb_mes * por_mb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resumen", required=True, type=Path,
                    help="carpeta con resumen_fase4.json")
    ap.add_argument("--salida", required=True, type=Path)
    a = ap.parse_args()

    r = json.loads((a.resumen / "resumen_fase4.json").read_text(encoding="utf-8"))
    proy = {int(k): v for k, v in r["bytes"]["proyeccion_MB_mes"].items()}

    filas = []
    for mis in sorted(proy):
        mb = proy[mis]
        costos = [costo_mensual(mb, f, p) for _, f, p in PLANES]
        filas.append(f"{mis} & {coma(mb)} & " + " & ".join(coma(c) for c in costos) + " \\\\")
        print(f"{mis:>4} misiones/día  {mb:6.2f} MB/mes  " +
              "  ".join(f"{n}: US${c:.2f}" for (n, _, _), c in zip(PLANES, costos)))

    cab = " & ".join(f"\\textbf{{{n}}}" for n, _, _ in PLANES)
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Costo mensual de datos de una RSU con planes IoT]{Costo "
           "mensual de datos de una RSU con TLS~1.3 en dos planes IoT de tarifa publicada que cubren Perú, a "
           "partir de la proyección de la Tabla~\\ref{tab:proyeccion_datos}. 1NCE: US\\$0,60 al mes y "
           "US\\$12 por GB (zona~3)~\\cite{1nce_precios_2026}; Telnyx: US\\$0,0625 por MB, sin cargo "
           "mensual~\\cite{telnyx_peru}. Tarifas consultadas el 14 de noviembre de 2026, en dólares, sin IGV ni "
           "cargos únicos de tarjeta SIM o activación; el volumen facturado será algo mayor que el proyectado, "
           "que no incluye encabezados IP ni TCP.}\n\\label{tab:costo_planes}\n\\small\n"
           "\\begin{tabular}{rrrr}\n\\toprule\n\\textbf{Misiones por día} & \\textbf{MB por mes} & "
           + cab + " \\\\\n\\midrule\n" + "\n".join(filas) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "tabla_costo_planes.tex").write_text(tex, encoding="utf-8")


if __name__ == "__main__":
    main()
