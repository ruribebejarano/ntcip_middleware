#!/usr/bin/env python3
"""Resumen de la prueba de RF-11 con los tiempos del controlador INDRA
(scripts/campanas/prueba_rf11_indra.sh, docs/PRUEBA_RF11_TIEMPOS_REALES.md).

Para cada corrida (carpeta resultados/campana/*_lazo_local_rf11_indra_*),
corre scripts/analisis/lazo_centralizado.py si todavía no tiene
lazo_por_parada.csv, y resume por parada:

  t_verde   espera desde el M1 inicial hasta el verde (incluye el despeje
            de la fase en conflicto)
  A_v       anticipación real: verde concedido -> cruce del vehículo
  cumplimiento de RF-11: T_m <= A_v <= A_v,max

Límites con los tiempos del manual: T_m = 2 s; A_v,max = T_desp,max + T_m
+ Δt = 13 + 2 + 1 = 16 s (ecuación eq:avmax de la tesis). T_desp,max = 13 s
es el peor caso con un controlador multifase: la solicitud llega al empezar
el ámbar del propio acceso (3 + 1 s) y, tras ese despeje, la fase siguiente
debe cumplir su verde mínimo, su ámbar y su rojo-rojo (5 + 3 + 1 s).

Uso:
    python scripts/analisis/rf11_indra_resumen.py                       # todas las corridas rf11_indra
    python scripts/analisis/rf11_indra_resumen.py --dir A --dir B --salida <carpeta>
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
T_M_S = 2.0
T_DESP_MAX_S = (3.0 + 1.0) + (5.0 + 3.0 + 1.0)
DELTA_T_S = 1.0
A_V_MAX_S = T_DESP_MAX_S + T_M_S + DELTA_T_S


def _paradas(corrida: Path) -> list[dict]:
    csv_path = corrida / "lazo_por_parada.csv"
    if not csv_path.exists():
        subprocess.run([sys.executable, str(RAIZ / "scripts" / "analisis" / "lazo_centralizado.py"),
                        "--dir", str(corrida)], check=True, cwd=RAIZ, capture_output=True)
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _resumen(corrida: Path) -> dict:
    config = json.loads((corrida / "config.json").read_text(encoding="utf-8"))
    filas = _paradas(corrida)
    a_v = [v for v in (_num(f["anticipacion_real_s"]) for f in filas) if v is not None]
    t_verde = [v / 1000 for v in (_num(f["t_verde_ms"]) for f in filas) if v is not None]
    sin_verde = sum(1 for f in filas if f.get("obtuvo_verde") != "True")
    condiciones: dict[str, int] = {}
    for f in filas:
        condiciones[f["condicion_llegada"] or "?"] = condiciones.get(f["condicion_llegada"] or "?", 0) + 1

    def est(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        return {"n": len(xs), "min": min(xs), "mediana": statistics.median(xs), "max": max(xs)}

    return {
        "corrida": corrida.name,
        "velocidad_kmh": config.get("velocidad_kmh"),
        "r_g_m": config.get("r_g_m"),
        "eta_emision_s": config.get("eta_emision_s"),
        "paradas": len(filas),
        "sin_verde": sin_verde,
        "condiciones": condiciones,
        "t_verde_s": est(t_verde),
        "A_v_s": est(a_v),
        "A_v_bajo_T_m": sum(1 for v in a_v if v < T_M_S),
        "A_v_sobre_max": sum(1 for v in a_v if v > A_V_MAX_S),
        "A_v_dentro": sum(1 for v in a_v if T_M_S <= v <= A_V_MAX_S),
    }


def _fmt(x: float | None) -> str:
    return "--" if x is None else f"{x:.2f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", default=None)
    ap.add_argument("--salida", default=None, help="carpeta para rf11_indra_resumen.json y la tabla .tex")
    args = ap.parse_args()
    dirs = [Path(d) for d in args.dir] if args.dir else sorted(
        (RAIZ / "resultados" / "campana").glob("*_lazo_local_rf11_indra_*"))
    if not dirs:
        raise SystemExit("No hay corridas *_lazo_local_rf11_indra_* (scripts/campanas/prueba_rf11_indra.sh)")

    resumenes = [_resumen(d) for d in dirs]
    print(f"Límites de RF-11 con los tiempos del manual INDRA: T_m = {T_M_S:.0f} s, "
          f"A_v,max = {A_V_MAX_S:.0f} s (T_desp,max = {T_DESP_MAX_S:.0f} s)\n")
    for r in resumenes:
        criterio = (f"geocerca {r['r_g_m']:.0f} m / ETA {r['eta_emision_s']} s" if r["r_g_m"]
                    else f"solo ETA {r['eta_emision_s']} s")
        a, t = r["A_v_s"], r["t_verde_s"]
        print(f"{r['corrida']}: {r['velocidad_kmh']} km/h, {criterio}; paradas={r['paradas']} "
              f"(sin verde {r['sin_verde']}), llegadas={r['condiciones']}")
        print(f"   t_verde (s): min {_fmt(t.get('min'))}  mediana {_fmt(t.get('mediana'))}  max {_fmt(t.get('max'))}")
        print(f"   A_v (s):     min {_fmt(a.get('min'))}  mediana {_fmt(a.get('mediana'))}  max {_fmt(a.get('max'))}"
              f"  -> dentro {r['A_v_dentro']}/{a.get('n', 0)}, < T_m {r['A_v_bajo_T_m']}, "
              f"> A_v,max {r['A_v_sobre_max']}")

    salida = Path(args.salida) if args.salida else dirs[-1].parent / "_rf11_indra"
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "rf11_indra_resumen.json").write_text(
        json.dumps({"T_m_s": T_M_S, "A_v_max_s": A_V_MAX_S, "corridas": resumenes}, indent=2,
                   ensure_ascii=False), encoding="utf-8")
    filas_tex = []
    for r in resumenes:
        criterio = f"Geocerca {r['r_g_m']:.0f}~m" if r["r_g_m"] else f"ETA {_fmt(r['eta_emision_s'])}~s"
        a, t = r["A_v_s"], r["t_verde_s"]
        filas_tex.append(
            f"{r['velocidad_kmh']:.0f} & {criterio} & {r['paradas']} & {r['sin_verde']} & "
            f"{_fmt(t.get('mediana'))} / {_fmt(t.get('max'))} & "
            f"{_fmt(a.get('min'))} / {_fmt(a.get('mediana'))} / {_fmt(a.get('max'))} & "
            f"{r['A_v_dentro']} / {r['A_v_bajo_T_m']} / {r['A_v_sobre_max']} \\\\")
    tex = "\n".join([
        r"\begin{table}[H]", r"\centering",
        r"\caption[RF-11 con los tiempos de un controlador real]{Anticipación $A_v$ con los tiempos del "
        r"controlador INDRA (verde mínimo 5~s, ámbar 3~s, rojo-rojo 1~s, ciclo de 110~s), por velocidad "
        r"y criterio de emisión. Límites de RF-11: $T_m = 2$~s y $A_{v,max} = "
        + f"{A_V_MAX_S:.0f}" + r"$~s. Elaboración propia.}",
        r"\label{tab:rf11_indra}", r"\small",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{rlrrccc}", r"\toprule",
        r"km/h & Emisión & Paradas & Sin verde & $t_{verde}$ med. / máx. (s) & $A_v$ mín. / med. / máx. (s) "
        r"& Dentro / $<T_m$ / $>A_{v,max}$ \\",
        r"\midrule", *filas_tex, r"\bottomrule", r"\end{tabular}}", r"\end{table}", ""])
    (salida / "tabla_rf11_indra.tex").write_text(tex, encoding="utf-8")
    print(f"\nResumen: {salida / 'rf11_indra_resumen.json'}\nTabla:   {salida / 'tabla_rf11_indra.tex'}")


if __name__ == "__main__":
    main()
