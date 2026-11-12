#!/usr/bin/env python3
"""OE4 (Fase 4, prueba 8): recuperación del plan del controlador tras
liberar una prioridad.

Lanza el controlador emulado (controller/controller_emulator.py, con la
salida de prioridad por ámbar y todo rojo) y lo consulta a 10 Hz con un
observador externo por su propio protocolo (JSON Lines/TCP), igual que lo
consulta la RSU. Cada repetición:
  1. espera una pausa aleatoria (0..21 s, un ciclo completo) para que la
     prioridad empiece en una fase distinta del plan;
  2. pide la prioridad (request_priority) y la sostiene un tiempo aleatorio
     uniforme en [2, 16] s (incluye liberaciones antes del verde mínimo y
     duraciones como las de la campaña, mediana 14 s);
  3. la libera (clear_priority) y sigue consultando hasta que el controlador
     vuelve a su plan (fase visible == fase del plan y sin salida en curso)
     y se mantiene así 2 s.
Métricas: T_rec,plan = liberación -> primera consulta ya en el plan;
secuencia de fases tras la liberación (debe ser verde* -> amarillo ->
todo_rojo -> plan); verde mínimo respetado; transiciones prohibidas
(verde -> rojo sin ámbar).

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_recuperacion_plan/
  muestras.csv, resultados.json, tabla_recuperacion_plan.tex,
  fig_recuperacion_plan.pdf/.png

Uso: .venv/Scripts/python.exe scripts/evaluacion/recuperacion_plan.py [--repeticiones 20]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
PY = sys.executable
PUERTO = 9190
PERIODO_S = 0.1
VERDE_MIN_S = 8.0  # valores por defecto del emulador (verde 8, ámbar 3, todo rojo 2, rojo general 8)
CICLO_S = 21.0


class Cliente:
    def __init__(self, puerto: int) -> None:
        self.s = socket.create_connection(("127.0.0.1", puerto), timeout=2)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.s.makefile("r", encoding="utf-8")

    def pedir(self, cmd: dict) -> dict:
        self.s.sendall((json.dumps(cmd) + "\n").encode())
        return json.loads(self.f.readline())


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeticiones", type=int, default=20)
    ap.add_argument("--semilla", type=int, default=20261112)
    args = ap.parse_args()
    rnd = random.Random(args.semilla)
    salida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_recuperacion_plan"
    salida.mkdir(parents=True)
    env = dict(os.environ, RSU_ID="190", RSU_EVENTOS_DIR=str(salida))
    proc = subprocess.Popen([PY, "-u", str(RAIZ / "controller" / "controller_emulator.py"), "--port", str(PUERTO)],
                            stdout=open(salida / "controlador.log", "w"), stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(50):
            try:
                cli = Cliente(PUERTO)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("el controlador no abrió el puerto")
        reps, muestras = [], []
        for i in range(1, args.repeticiones + 1):
            time.sleep(rnd.uniform(0, CICLO_S))
            sostener = rnd.uniform(2.0, 16.0)
            e0 = cli.pedir({"cmd": "get_status"})
            t_req = time.monotonic()
            cli.pedir({"cmd": "request_priority", "vehiculo_id": "obs", "eta_seg": 10, "id_solicitud": f"r{i}"})
            while time.monotonic() - t_req < sostener:
                time.sleep(PERIODO_S)
                cli.pedir({"cmd": "get_status"})
            e_lib = cli.pedir({"cmd": "clear_priority", "id_solicitud": f"r{i}"})
            t_lib = time.monotonic()
            seq, t_rec, estable_desde, verde_hasta = [e_lib["fase"]], None, None, None
            while True:
                time.sleep(PERIODO_S)
                e = cli.pedir({"cmd": "get_status"})
                t = time.monotonic() - t_lib
                muestras.append((i, round(t, 3), e["fase"], e["fase_plan"], e["en_salida"]))
                if e["fase"] != seq[-1]:
                    if seq[-1] == "verde":
                        verde_hasta = t
                    seq.append(e["fase"])
                en_plan = e["fase"] == e["fase_plan"] and not e["en_salida"]
                if en_plan and t_rec is None:
                    t_rec = t
                if en_plan:
                    estable_desde = estable_desde if estable_desde is not None else t
                    if t - estable_desde >= 2.0:
                        break
                else:
                    estable_desde = None
                    t_rec = None  # salió del plan: la recuperación aún no terminó
                if t > 40:
                    break
            prohibidas = sum(1 for a, b in zip(seq, seq[1:]) if a == "verde" and b in ("todo_rojo", "rojo_general"))
            # verde mínimo: el verde visible duró al menos VERDE_MIN_S desde que empezó
            # (si ya estaba en verde al pedir, el verde empezó antes: no se puede violar)
            verde_total = sostener + (verde_hasta or 0.0)
            min_ok = e0["fase"] == "verde" or verde_total >= VERDE_MIN_S - 0.15
            reps.append({"rep": i, "fase_al_pedir": e0["fase"], "sostenida_s": round(sostener, 2),
                         "fase_plan_al_liberar": e_lib.get("fase_plan"), "secuencia": seq,
                         "verde_tras_liberar_s": round(verde_hasta or 0.0, 2), "T_rec_s": t_rec,
                         "transiciones_prohibidas": prohibidas, "verde_minimo_respetado": min_ok})
            print(f"rep {i:2d}: pedida en {e0['fase']:<12} sostenida {sostener:5.1f} s, plan al liberar "
                  f"{e_lib.get('fase_plan'):<12} -> {'/'.join(seq)}  T_rec={t_rec}")
        cli.pedir({"cmd": "get_status"})
    finally:
        proc.terminate()

    with (salida / "muestras.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rep", "t_desde_liberacion_s", "fase", "fase_plan", "en_salida"])
        w.writerows(muestras)
    tr = [r["T_rec_s"] for r in reps if r["T_rec_s"] is not None]
    res = {"repeticiones": len(reps), "periodo_consulta_s": PERIODO_S, "reps": reps,
           "T_rec_s": {"n": len(tr), "min": min(tr), "mediana": pct(tr, 50), "p95": pct(tr, 95), "max": max(tr)},
           "sin_recuperar": sum(1 for r in reps if r["T_rec_s"] is None),
           "transiciones_prohibidas": sum(r["transiciones_prohibidas"] for r in reps),
           "verde_minimo_violado": sum(1 for r in reps if not r["verde_minimo_respetado"])}
    (salida / "resultados.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    coma = lambda x, d=2: f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    s = res["T_rec_s"]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Recuperación del plan tras liberar la prioridad]{Recuperación "
           "del plan del controlador emulado tras liberar una prioridad, medida con un observador que lo consulta "
           f"a {int(1 / PERIODO_S)}~Hz; {len(reps)} liberaciones con una duración de la prioridad aleatoria entre "
           "2~s y 16~s. $T_{rec,plan}$: desde la liberación hasta que la fase visible coincide con la del plan.}\n"
           "\\label{tab:recuperacion_plan}\n\\small\n\\begin{tabular}{lr}\n\\toprule\n"
           "\\textbf{Métrica} & \\textbf{Valor} \\\\\n\\midrule\n"
           f"Liberaciones & {len(reps)} \\\\\n"
           f"$T_{{rec,plan}}$ mínimo / mediana / p95 / máximo (s) & {coma(s['min'])} / {coma(s['mediana'])} / "
           f"{coma(s['p95'])} / {coma(s['max'])} \\\\\n"
           f"Liberaciones sin recuperar el plan & {res['sin_recuperar']} \\\\\n"
           f"Transiciones de verde a rojo sin ámbar & {res['transiciones_prohibidas']} \\\\\n"
           f"Verde mínimo no respetado & {res['verde_minimo_violado']} \\\\\n"
           "\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_recuperacion_plan.tex").write_text(tex, encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    xs = sorted(r["sostenida_s"] for r in reps)
    por = sorted((r["sostenida_s"], r["T_rec_s"]) for r in reps if r["T_rec_s"] is not None)
    ax.scatter([a for a, _ in por], [b for _, b in por], color="#4C72B0", s=18)
    ax.axhline(5.0, color="0.4", ls="--", lw=1)
    ax.text(xs[-1], 5.0, " ámbar + todo rojo", fontsize=7, va="bottom", ha="right")
    ax.set_xlabel("Duración de la prioridad (s)")
    ax.set_ylabel("$T_{rec,plan}$ (s)")
    ax.set_ylim(0, max(b for _, b in por) + 2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(salida / f"fig_recuperacion_plan.{ext}", dpi=200)
    print(f"T_rec: {s}; sin recuperar {res['sin_recuperar']}, prohibidas {res['transiciones_prohibidas']}, "
          f"verde mínimo violado {res['verde_minimo_violado']}")
    print(f"Salida en {salida}")


if __name__ == "__main__":
    main()
