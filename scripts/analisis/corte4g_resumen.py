#!/usr/bin/env python3
"""OE5 (RNF-07, RNF-08): estadísticas del corte físico del enlace 4G de la RSU
a partir de una o más corridas de scripts/evaluacion/inyeccion_fallos_pi.py
--caso enlace4g. Complementa a scripts/evaluacion/fallos_resumen.py (que da
la fila de la tabla de fallos) con el detalle por repetición, la duración real
de cada corte y los datos que movió el túnel.

Definiciones (las mismas de inyeccion_fallos_pi.py):
  t_lib        último M1 recibido por la RSU -> el controlador deja de
               sostener la prioridad (RNF-07: <= T_cad + Δt = 4 s). Solo en
               repeticiones con la prioridad activa al cortar.
  t_lib_falla  instante del corte (usb0 desaparece) -> liberación.
  corte        usb0 desaparece -> usb0 reaparece (lo decide el autor al
               desconectar y reconectar el módem; nominal 20 s).
  T_rec        usb0 reaparece -> primer M1 recibido por la RSU (sonda),
               es decir, re-registro del módem en la red + túnel + MQTT
               (RNF-08: <= 10 s).

Uso:
  .venv/Scripts/python.exe scripts/analisis/corte4g_resumen.py --dir <corrida> [--dir ...] --salida <archivo.json>
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

LIMITE_RNF07_S = 4.0
LIMITE_RNF08_S = 10.0


def resumen(v: list[float]) -> dict:
    v = [x for x in v if x is not None]
    if not v:
        return {"n": 0}
    return {"n": len(v), "min": min(v), "mediana": st.median(v), "media": st.mean(v), "max": max(v),
            "desv_est": st.stdev(v) if len(v) > 1 else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    args = ap.parse_args()
    salida = {"corridas": []}
    for d in args.dir:
        r = json.loads((d / "resultados.json").read_text(encoding="utf-8"))
        validas = [x for x in r["reps"] if "error" not in x]
        filas = []
        for x in validas:
            filas.append({
                "rep": x["rep"],
                "prioridad_al_fallo": x.get("prioridad_al_fallo"),
                "corte_s": (x["t_up_ns"] - x["t_falla_ns"]) / 1e9 if x.get("t_up_ns") else None,
                "t_lib_s": x.get("t_lib_m1_s") if x.get("prioridad_al_fallo") is not False else None,
                "t_lib_falla_s": x.get("t_lib_falla_s") if x.get("prioridad_al_fallo") is not False else None,
                "T_rec_s": x.get("T_rec_s"),
                "retenida": x.get("retenida"),
                "intentos_sonda": x.get("sonda", {}).get("intentos"),
                "bytes_tunel": x.get("bytes_tailscale"),
            })
        col = lambda k: [f[k] for f in filas if f[k] is not None]  # noqa: E731
        bytes_ = col("bytes_tunel")
        salida["corridas"].append({
            "corrida": d.name,
            "repeticiones": len(r["reps"]),
            "validas": len(validas),
            "descartadas": [{"rep": x["rep"], "motivo": x["error"]} for x in r["reps"] if "error" in x],
            "con_prioridad_al_corte": sum(1 for f in filas if f["prioridad_al_fallo"]),
            "retenidas": sum(1 for f in filas if f["retenida"]),
            "t_lib_s": resumen(col("t_lib_s")),
            "t_lib_dentro_rnf07": sum(1 for t in col("t_lib_s") if t <= LIMITE_RNF07_S),
            "t_lib_falla_s": resumen(col("t_lib_falla_s")),
            "corte_s": resumen(col("corte_s")),
            "T_rec_s": resumen(col("T_rec_s")),
            "T_rec_dentro_rnf08": sum(1 for t in col("T_rec_s") if t <= LIMITE_RNF08_S),
            "bytes_tunel_total": sum(bytes_) if bytes_ else None,
            "bytes_tunel_por_rep": resumen(bytes_) if bytes_ else None,
            "por_repeticion": filas,
        })
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")
    for c in salida["corridas"]:
        print(f"{c['corrida']}: válidas {c['validas']}/{c['repeticiones']}, "
              f"t_lib med {c['t_lib_s'].get('mediana', 0):.2f} s máx {c['t_lib_s'].get('max', 0):.2f} s "
              f"({c['t_lib_dentro_rnf07']}/{c['t_lib_s']['n']} <= 4 s), "
              f"T_rec med {c['T_rec_s']['mediana']:.1f} s máx {c['T_rec_s']['max']:.1f} s "
              f"({c['T_rec_dentro_rnf08']}/{c['T_rec_s']['n']} <= 10 s)")
    print(f"Salida en {args.salida}")


if __name__ == "__main__":
    main()
