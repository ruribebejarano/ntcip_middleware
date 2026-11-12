#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 1): tabla de la inyección de fallos a partir de
las corridas de scripts/evaluacion/inyeccion_fallos.py (local) e
inyeccion_fallos_pi.py (RSU física). Una fila por caso.

Uso: .venv/Scripts/python.exe scripts/evaluacion/fallos_resumen.py --dir <corrida> [--dir <corrida> ...] --salida <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NOMBRE = {
    "broker": ("Caída del \\emph{broker} (local)", "$\\leq 4$"),
    "servidor": ("Caída del servidor (local)", "$\\leq 4$"),
    "rsu": ("Caída del proceso de la RSU (local)", "límite del controlador"),
    "pi_rsu": ("Caída del proceso de la RSU (RSU física)", "límite del controlador"),
    "pi_enlace4g": ("Corte del enlace 4G (RSU física)", "$\\leq 4$"),
}


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    coma = lambda x, d=2: "--" if x is None else f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    filas, resumen = [], {}
    for d in args.dir:
        d = Path(d)
        r = json.loads((d / "resultados.json").read_text(encoding="utf-8"))
        clave = ("pi_" if "_fallos_pi_" in d.name else "") + r["caso"]
        reps = [x for x in r["reps"] if "error" not in x]
        tl = [x["t_lib_m1_s"] for x in reps if x.get("t_lib_m1_s") is not None]
        sin_lib = sum(1 for x in reps if x.get("t_lib_m1_s") is None)
        tr = [x["T_rec_s"] for x in reps if x.get("T_rec_s") is not None]
        ret = sum(1 for x in reps if x.get("retenida"))
        rean = sum(1 for x in reps if x.get("reanudada"))
        resumen[clave] = {"repeticiones": len(r["reps"]), "validas": len(reps), "t_lib_m1_s": tl,
                          "sin_liberacion": sin_lib, "T_rec_s": tr, "retenidas": ret, "reanudadas": rean}
        nombre, esperado = NOMBRE[clave]
        filas.append(f"{nombre} & {len(reps)} & {esperado} & "
                     f"{coma(pct(tl, 50) if tl else None)} / {coma(max(tl) if tl else None)} & {sin_lib} & "
                     f"{coma(pct(tr, 50) if tr else None)} / {coma(max(tr) if tr else None)} & {ret} \\\\")
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "fallos_resumen.json").write_text(json.dumps(resumen, indent=1), encoding="utf-8")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Inyección de fallos con una prioridad activa]{Inyección de "
           "fallos con una prioridad activa (RNF-07, RNF-08). $t_{lib}$: desde el último M1 que recibió la RSU "
           "hasta que el controlador deja de sostener la prioridad. $T_{rec}$: desde que se restablece el elemento "
           "caído hasta que la RSU vuelve a responder una solicitud. ``Sin liberar'': repeticiones en que la "
           "prioridad siguió activa porque la misión retomó sus renovaciones antes de vencer el plazo.}\n"
           "\\label{tab:fallos}\n\\small\n\\begin{tabular}{lrrrrrr}\n\\toprule\n"
           "\\textbf{Fallo} & \\textbf{n} & \\textbf{$t_{lib}$ esperado (s)} & "
           "\\textbf{$t_{lib}$ med./máx. (s)} & \\textbf{Sin liberar} & \\textbf{$T_{rec}$ med./máx. (s)} & "
           "\\textbf{Retenidas} \\\\\n\\midrule\n" + "\n".join(filas) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_fallos.tex").write_text(tex, encoding="utf-8")
    print(tex)


if __name__ == "__main__":
    main()
