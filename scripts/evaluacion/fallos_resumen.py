#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 1): tabla de la inyección de fallos a partir de
las corridas de scripts/evaluacion/inyeccion_fallos.py (local) e
inyeccion_fallos_pi.py (RSU física). Una fila por caso.

Lectura por caso:
  broker / servidor   la RSU deja de recibir renovaciones y libera por
                      caducidad: t_lib = último M1 recibido -> liberación en
                      el controlador (RNF-07: <= T_cad + Δt = 4 s).
  rsu                 el proceso de la RSU muere y systemd lo reinicia; el
                      controlador sostiene la prioridad hasta
                      PRIORITY_HOLD_SECONDS (15 s) desde la última escritura.
                      Si el agente vuelve antes de que el vehículo cruce,
                      retoma la solicitud (misión reanudada) y la libera el
                      cruce; si el cruce ocurrió durante la caída, el M3 se
                      perdió y libera el límite del controlador (t_lib ~ 15 s
                      desde el último M1). Se cuentan ambos casos.
  T_rec               restauración -> primera respuesta de la RSU a una sonda
                      (local) o reconexión del agente al broker (RSU física).

Uso: .venv/Scripts/python.exe scripts/evaluacion/fallos_resumen.py --dir <corrida> [--dir ...] --salida <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

NOMBRE = {
    "broker": "Caída del \\emph{broker} (local)",
    "servidor": "Caída del servidor (local)",
    "rsu": "Caída del proceso de la RSU (local)",
    "pi_rsu": "Caída del proceso de la RSU (RSU física, 4G)",
    "pi_enlace4g": "Corte del enlace 4G (RSU física)",
}
LIMITE_CONTROLADOR_S = 14.0  # por encima, la liberación la hizo el límite de 15 s del controlador


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
    coma = lambda x, d=1: "--" if x is None else f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    filas, resumen = [], {}
    for d in args.dir:
        d = Path(d)
        r = json.loads((d / "resultados.json").read_text(encoding="utf-8"))
        clave = ("pi_" if "_fallos_pi_" in d.name else "") + r["caso"]
        reps = [x for x in r["reps"] if "error" not in x]
        # Si la prioridad ya se había liberado antes del corte (el vehículo
        # cruzó y llegó el M3), esa liberación no la causó el fallo: no
        # cuenta para t_lib, pero sí para T_rec.
        tl = [x["t_lib_m1_s"] for x in reps
              if x.get("t_lib_m1_s") is not None and x.get("prioridad_al_fallo") is not False]
        tr = [x["T_rec_s"] for x in reps if x.get("T_rec_s") is not None]
        ret = sum(1 for x in reps if x.get("retenida"))
        if clave.endswith("rsu"):
            limite = [t for t in tl if t > LIMITE_CONTROLADOR_S]
            reanudadas = len(reps) - len(limite)
            s = {"repeticiones": len(reps), "reanudadas": reanudadas, "liberadas_por_limite": len(limite),
                 "t_lib_limite_s": limite, "T_rec_s": tr, "retenidas": ret}
            col_lib = (f"{coma(pct(limite, 50))} / {coma(max(limite))} ({len(limite)})" if limite else "-- (0)")
            col_rean = f"{reanudadas}/{len(reps)}"
        else:
            s = {"repeticiones": len(reps), "t_lib_m1_s": tl, "T_rec_s": tr, "retenidas": ret,
                 "reanudadas": sum(1 for x in reps if x.get("reanudada"))}
            col_lib = f"{coma(pct(tl, 50))} / {coma(max(tl))} ({len(tl)})"
            col_rean = f"{s['reanudadas']}/{len(reps)}"
        resumen[clave] = s
        filas.append(f"{NOMBRE[clave]} & {len(reps)} & {col_rean} & {col_lib} & "
                     f"{coma(pct(tr, 50))} / {coma(max(tr))} & {ret} \\\\")
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "fallos_resumen.json").write_text(json.dumps(resumen, indent=1), encoding="utf-8")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Inyección de fallos con una prioridad activa]{Inyección de "
           "fallos con una prioridad activa (RNF-07, RNF-08). ``Misión reanudada'': la misión en curso volvió a "
           "renovar su solicitud tras la restauración. $t_{lib}$: desde el último M1 recibido por la RSU hasta que "
           "el controlador deja de sostener la prioridad, en las repeticiones en que la liberación la causó el "
           "fallo (entre paréntesis, cuántas); en las demás la liberó el cruce del vehículo. $T_{rec}$: desde la "
           "restauración hasta que la RSU responde de nuevo (local: a una sonda que publica cada 0,5~s; RSU física: "
           "reconexión del agente al \\emph{broker}, incluidos los 2~s de espera del reinicio). ``Retenidas'': "
           "repeticiones que terminaron con la prioridad activa.}\n"
           "\\label{tab:fallos}\n\\footnotesize\n\\begin{tabular}{>{\\raggedright\\arraybackslash}p{3.6cm}r"
           ">{\\centering\\arraybackslash}p{1.6cm}>{\\centering\\arraybackslash}p{2.4cm}"
           ">{\\centering\\arraybackslash}p{2.2cm}>{\\centering\\arraybackslash}p{1.5cm}}\n\\toprule\n"
           "\\textbf{Fallo} & \\textbf{n} & \\textbf{Misión reanudada} & \\textbf{$t_{lib}$ med./máx. (s)} & "
           "\\textbf{$T_{rec}$ med./máx. (s)} & \\textbf{Retenidas} \\\\\n\\midrule\n" + "\n".join(filas) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_fallos.tex").write_text(tex, encoding="utf-8")
    print(tex)


if __name__ == "__main__":
    main()
