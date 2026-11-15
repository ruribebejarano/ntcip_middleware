#!/usr/bin/env python3
"""Consumo y costo mensual de datos de una RSU y de una OBU con planes IoT de
tarifa publicada que cubren Perú (sección 4.6.3 de la tesis,
dimensionamiento del despliegue).

Entradas:
- RSU: la proyección mensual de datos con TLS 1.3 que calcula
  scripts/evaluacion/resumen_fase4.py (resumen_fase4.json, clave
  bytes.proyeccion_MB_mes), es decir, los mismos valores de la Tabla
  tab:proyeccion_datos.
- OBU: los bytes por misión con TLS 1.3 de la misma prueba
  (bytes.tls.obu_mision) y la duración real de esas misiones, leída de los
  eventos de la OBU emulada en cada repetición de la corrida de bytes
  (desde MI_tx hasta MF_tx). De ahí sale una tasa en bytes por segundo de
  misión, que se proyecta a horas de misión por día. Las horas son
  escenarios, no una medición de cuánto opera una ambulancia.

Tarifas: las publicadas por cada proveedor, consultadas el 2026-11-14, sin
impuestos (IGV) y sin cargos únicos (tarjeta SIM, activación). Solo se
incluyen planes cuya página o lista de precios nombra a Perú:

- 1NCE High Data IoT: Perú está en la zona 3 del Apéndice 1 de la lista de
  precios de 1NCE Inc. (octubre de 2026): US$0,60 al mes por SIM y
  US$12,00 por GB. Se toma 1 GB = 1000 MB, lo que redondea el costo hacia
  arriba.
- Telnyx: página de SIM IoT para Perú, desde US$0,0625 por MB, sin cargo
  mensual (solo US$1 por SIM, una vez).

Los volúmenes son carga TCP, sin encabezados IP ni TCP, de modo que el
costo facturado será algo mayor. Un mes = 30 días.

Uso: .venv/Scripts/python.exe scripts/analisis/costo_planes_iot.py \
       --resumen <dir con resumen_fase4.json> \
       --bytes-tls <corrida de bytes con TLS> --salida <dir> \
       [--reposo-tls <corrida de bytes con TLS cuyo reposo de la RSU se usa>]

--reposo-tls sirve para evaluar un cambio de keepalive de la RSU sin rehacer
toda la Fase 4: reemplaza el tráfico en reposo de la proyección (clave
rsu_reposo.bytes_por_hora de esa corrida) y deja igual misiones y conexión.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

# (nombre en la tabla, cargo mensual por SIM en US$, US$ por MB)
PLANES = (
    ("1NCE (US\\$/mes)", 0.60, 12.00 / 1000),
    ("Telnyx (US\\$/mes)", 0.0, 0.0625),
)
HORAS_MISION_DIA = (1, 2, 4, 8)
DIAS_MES = 30


def coma(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def costo_mensual(mb_mes: float, fijo: float, por_mb: float) -> float:
    return fijo + mb_mes * por_mb


def duracion_misiones_s(corrida: Path) -> list[float]:
    """Duración MI_tx -> MF_tx de cada repetición de la corrida de bytes."""
    duraciones = []
    for f in sorted(corrida.glob("rep_*/eventos_obu-*.csv")):
        with f.open(encoding="utf-8") as fh:
            ts = {r["tipo_evento"]: int(r["ts_ns"]) for r in csv.DictReader(fh)
                  if r["tipo_evento"] in ("MI_tx", "MF_tx")}
        duraciones.append((ts["MF_tx"] - ts["MI_tx"]) / 1e9)
    if not duraciones:
        raise SystemExit(f"sin eventos de la OBU en {corrida}")
    return duraciones


def tabla(caption: str, etiqueta: str, col1: str, filas: list[str]) -> str:
    cab = " & ".join(f"\\textbf{{{n}}}" for n, _, _ in PLANES)
    return ("\\begin{table}[H]\n\\centering\n" + caption + f"\n\\label{{{etiqueta}}}\n\\small\n"
            "\\begin{tabular}{rrrr}\n\\toprule\n" + f"\\textbf{{{col1}}} & \\textbf{{MB por mes}} & "
            + cab + " \\\\\n\\midrule\n" + "\n".join(filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")


def fila(etiqueta: str, mb: float) -> str:
    costos = [costo_mensual(mb, f, p) for _, f, p in PLANES]
    print(f"  {etiqueta:>4}  {mb:8.2f} MB/mes  " + "  ".join(f"US${c:.2f}" for c in costos))
    return f"{etiqueta} & {coma(mb)} & " + " & ".join(coma(c) for c in costos) + " \\\\"


TARIFAS = ("1NCE: US\\$0,60 al mes y US\\$12 por GB (zona~3)~\\cite{1nce_precios_2026}; Telnyx: US\\$0,0625 "
           "por MB, sin cargo mensual~\\cite{telnyx_peru}. Tarifas consultadas el 14 de noviembre de 2026, en "
           "dólares, sin IGV ni cargos únicos de tarjeta SIM o activación; el volumen facturado será algo mayor, "
           "porque no incluye encabezados IP ni TCP.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resumen", required=True, type=Path, help="carpeta con resumen_fase4.json")
    ap.add_argument("--bytes-tls", required=True, type=Path, help="corrida de bytes con TLS")
    ap.add_argument("--salida", required=True, type=Path)
    ap.add_argument("--reposo-tls", type=Path, help="corrida de bytes con TLS cuyo reposo de la RSU se usa")
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)

    r = json.loads((a.resumen / "resumen_fase4.json").read_text(encoding="utf-8"))

    # RSU: proyección por misiones atendidas por día
    print("RSU (misiones por día):")
    proy = {int(k): v for k, v in r["bytes"]["proyeccion_MB_mes"].items()}
    nota_reposo = ""
    if a.reposo_tls:
        nuevo = json.loads((a.reposo_tls / "resumen.json").read_text(encoding="utf-8"))["rsu_reposo"]["bytes_por_hora"]
        viejo = r["bytes"]["reposo_tls_B_h"]
        extra_mb = 24 * DIAS_MES * (nuevo - viejo) / 1e6
        proy = {m: v + extra_mb for m, v in proy.items()}
        print(f"  reposo reemplazado: {viejo:.0f} -> {nuevo:.0f} B/h ({extra_mb:+.2f} MB/mes)")
        nota_reposo = (f"Reposo de la RSU con el \\emph{{keepalive}} ajustado: {coma(nuevo / 1000)}~kB por hora "
                       f"(antes {coma(viejo / 1000)}~kB). ")
    filas = [fila(str(m), proy[m]) for m in sorted(proy)]
    cap = ("\\caption[Costo mensual de datos de una RSU con planes IoT]{Costo mensual de datos de una RSU con "
           "TLS~1.3 en dos planes IoT de tarifa publicada que cubren Perú, a partir de la proyección de la "
           "Tabla~\\ref{tab:proyeccion_datos}. " + nota_reposo + TARIFAS + "}")
    (a.salida / "tabla_costo_planes.tex").write_text(
        tabla(cap, "tab:costo_planes", "Misiones por día", filas), encoding="utf-8")

    # OBU: tasa medida por segundo de misión, proyectada a horas de misión por día
    durs = duracion_misiones_s(a.bytes_tls)
    dur = statistics.mean(durs)
    tasa_B_s = r["bytes"]["tls"]["obu_mision"] / dur
    print(f"OBU: {r['bytes']['tls']['obu_mision']:.0f} B por misión de {dur:.1f} s "
          f"({len(durs)} misiones) = {tasa_B_s:.1f} B/s = {tasa_B_s * 3600 / 1e6:.2f} MB por hora de misión")
    print("OBU (horas de misión por día):")
    filas = [fila(str(h), tasa_B_s * 3600 * h * DIAS_MES / 1e6) for h in HORAS_MISION_DIA]
    cap = ("\\caption[Consumo y costo mensual de datos de una OBU]{Consumo y costo mensual de datos de una OBU "
           f"con TLS~1.3 según las horas de misión por día, a partir de la tasa medida de "
           f"{coma(tasa_B_s * 3600 / 1e6)}~MB por hora de misión ({coma(r['bytes']['tls']['obu_mision'] / 1000, 1)}~kB "
           f"en misiones de {coma(dur, 1)}~s, Tabla~\\ref{{tab:bytes}}). Las horas por día son escenarios, no una "
           "medición de la operación de un vehículo. " + TARIFAS + "}")
    (a.salida / "tabla_costo_obu.tex").write_text(
        tabla(cap, "tab:costo_obu", "Horas de misión por día", filas), encoding="utf-8")


if __name__ == "__main__":
    main()
