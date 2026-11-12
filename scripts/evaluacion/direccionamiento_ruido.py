#!/usr/bin/env python3
"""OE4 (Fase 4, prueba 7): exactitud del direccionamiento del servidor con
ruido GNSS creciente, sobre la ruta de 13 RSU hacia el Hospital del Niño.

Reproduce FUERA DE LÍNEA la lógica del servidor (servidor/gestor_mision.py,
servidor/rutas.py y gateway/geometria.py, sin cambios) con un reloj falso,
igual que scripts/campanas/preparar_ruta_completa.py::simular: la OBU
emulada no aporta nada aquí (solo publica la trayectoria), y el broker y la
RSU no influyen en qué RSU ni qué acceso elige el servidor.

Trayectoria base: scripts/campanas/fixtures/ruta_completa/trayectoria_A.csv
(36 km/h constante, la misma de la campaña de ruta completa). Ruido: el
mismo modelo de la campaña (lazo_centralizado.py::_trayectoria_con_ruido),
desplazamiento de módulo |N(0, σ)| en dirección uniforme, independiente en
cada muestra de 1 s. σ ∈ {0, 2, 5, 10, 20} m, 50 semillas por σ.

Verdad de referencia: la ruta sin ruido (13 RSU, con su acceso esperado).
Por cada repetición y cada RSU de referencia se cuenta:
  correcta     el servidor emitió M1 a esa RSU con el acceso esperado y la
               cerró con M3 de cruce;
  acceso_mal   emitió M1 a esa RSU con otro acceso;
  sin_cruce    emitió M1 pero la cerró con otro motivo (desvío, etc.);
  omitida      nunca emitió M1 a esa RSU.
Además: M1 a RSU fuera de la ruta de referencia (espurias) y recálculos de
ruta (ruta_recalculada), que con una trayectoria que no sale de la ruta
son siempre espurios.

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_direccionamiento_ruido/
  resultados.json, tabla_direccionamiento.tex, fig_direccionamiento.pdf/.png

Uso (raíz del repo):
    .venv/Scripts/python.exe scripts/evaluacion/direccionamiento_ruido.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

from gateway.geometria import cargar_registro  # noqa: E402
from scripts.campanas.lazo_centralizado import _trayectoria_con_ruido  # noqa: E402
from servidor import rutas  # noqa: E402
from servidor.gestor_mision import GestorMision  # noqa: E402

FIX = RAIZ / "scripts" / "campanas" / "fixtures"
REGISTRO = FIX / "registro_ruta_hospital_nino.json"
BASE = FIX / "ruta_completa" / "trayectoria_A.csv"
SIGMAS_M = (0.0, 2.0, 5.0, 10.0, 20.0)
N_SEMILLAS = 50
SEMILLA_BASE = 70000


def simular(G, registro, sigma: float, semilla: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ruidosa = Path(tmp) / "t.csv"
        _trayectoria_con_ruido(BASE, ruidosa, semilla, sigma)
        with ruidosa.open(newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
    reloj = [0.0]
    eventos: list[tuple[str, str, dict]] = []
    m1: list[tuple[str, dict]] = []

    class Registro:
        def log(self, tipo, id_ref, **extra):
            eventos.append((tipo, id_ref, extra))

    g = GestorMision(G, registro, enviar_m1=lambda rsu, cuerpo: m1.append((rsu, cuerpo)),
                     enviar_m3=lambda *a: None, enviar_mr=lambda *a: None, enviar_me=lambda *a: None,
                     eventos=Registro(), ahora=lambda: reloj[0])
    # Origen y destino de la misión: los de la trayectoria SIN ruido (el
    # operador arma la misión con un destino fijo; el origen es el punto de
    # partida conocido), para que el ruido solo afecte al seguimiento.
    with BASE.open(newline="", encoding="utf-8") as fh:
        base = list(csv.DictReader(fh))
    g.armar_mision("obu", 1, (float(base[0]["lat"]), float(base[0]["lon"])),
                   (float(base[-1]["lat"]), float(base[-1]["lon"])))
    for k, f in enumerate(filas, start=1):
        reloj[0] = float(f["t_s"])
        g.procesar_mp("obu", float(f["lat"]), float(f["lon"]), float(f["velocidad_kmh"]),
                      float(f["rumbo_deg"]), seq=k, fuente_velocidad="sintetica")
    # por id_solicitud: rsu, acceso del primer M1 y motivo del último M3
    sol: dict[str, dict] = {}
    for rsu, c in m1:
        if c.get("seq") == 1 or c["id_solicitud"] not in sol:
            sol.setdefault(c["id_solicitud"], {"rsu": rsu, "acceso": c.get("acceso"), "m3": None})
    for tipo, ref, ex in eventos:
        if tipo == "M3_tx" and ref in sol:
            sol[ref]["m3"] = ex.get("motivo")
    return {"sol": list(sol.values()),
            "recalculos": sum(1 for t, _, _ in eventos if t == "ruta_recalculada")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--semillas", type=int, default=N_SEMILLAS)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = Path(args.salida) if args.salida else (
        RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_direccionamiento_ruido")
    salida.mkdir(parents=True, exist_ok=True)

    G = rutas.cargar_grafo()
    registro = cargar_registro(REGISTRO)
    with BASE.open(newline="", encoding="utf-8") as fh:
        base = list(csv.DictReader(fh))
    ref = rutas.planificar_ruta(G, registro, (float(base[0]["lat"]), float(base[0]["lon"])),
                                (float(base[-1]["lat"]), float(base[-1]["lon"])))
    esperado = {p.rsu_id: p.acceso_id for p in ref.paradas}

    res = {"ruta_m": round(ref.longitud_total_m, 1), "esperado": esperado, "sigmas": {}}
    for sigma in SIGMAS_M:
        c, motivos = Counter(), Counter()
        recalc, espurias = [], 0
        for i in range(args.semillas):
            r = simular(G, registro, sigma, SEMILLA_BASE + 1000 * int(sigma) + i)
            recalc.append(r["recalculos"])
            vistas = {}
            for d in r["sol"]:
                if d["rsu"] not in esperado:
                    espurias += 1
                vistas.setdefault(d["rsu"], []).append(d)
            for rsu, acc in esperado.items():
                ds = vistas.get(rsu)
                if not ds:
                    c["omitida"] += 1
                elif any(d["acceso"] == acc and d["m3"] == "cruce" for d in ds):
                    c["correcta"] += 1
                elif all(d["acceso"] != acc for d in ds):
                    c["acceso_mal"] += 1
                else:
                    c["sin_cruce"] += 1
                    motivos[f"{rsu}:{'/'.join(str(d['m3']) for d in ds)}"] += 1
        total = len(esperado) * args.semillas
        res["sigmas"][str(sigma)] = {
            "repeticiones": args.semillas, "paradas": total, **{k: c[k] for k in
            ("correcta", "acceso_mal", "sin_cruce", "omitida")},
            "pct_correcta": 100.0 * c["correcta"] / total,
            "pct_acceso_correcto": 100.0 * (total - c["acceso_mal"] - c["omitida"]) / total,
            "m1_espurias": espurias, "recalculos_total": sum(recalc),
            "reps_con_recalculo": sum(1 for x in recalc if x),
            "sin_cruce_por_rsu_y_motivo": dict(motivos),
        }
        s = res["sigmas"][str(sigma)]
        print(f"sigma={sigma:4.0f} m: correctas {s['correcta']}/{total} ({s['pct_correcta']:.1f} %), "
              f"acceso mal {s['acceso_mal']}, sin cruce {s['sin_cruce']}, omitidas {s['omitida']}, "
              f"espurias {espurias}, recálculos {sum(recalc)} en {s['reps_con_recalculo']} rep.")
    (salida / "resultados.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    coma = lambda x, d=1: f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    def destino(s):  # cerradas porque la misión terminó al llegar al destino, antes del cruce
        return sum(v for kk, v in s["sin_cruce_por_rsu_y_motivo"].items() if kk.endswith(":destino"))

    fil = [f"{coma(float(k), 0)} & {s['paradas']} & {coma(s['pct_correcta'])} & {s['acceso_mal']} & "
           f"{destino(s)} & {s['sin_cruce'] - destino(s)} & {s['omitida']} & {s['m1_espurias']} & "
           f"{s['reps_con_recalculo']} \\\\" for k, s in res["sigmas"].items()]
    ultima = list(esperado)[-1]
    d_ult = res["ruta_m"] - [p.distancia_llegada_m for p in ref.paradas][-1]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Direccionamiento del servidor con ruido GNSS]{Exactitud "
           f"del direccionamiento del servidor con ruido GNSS creciente, sobre una ruta de {len(esperado)} RSU "
           f"y {coma(res['ruta_m'] / 1000, 1)}~km a 36~km/h, {args.semillas} repeticiones por nivel de ruido. "
           "Una parada es correcta si el servidor solicitó la prioridad a la RSU esperada, con el acceso "
           "esperado, y la cerró por el cruce del vehículo. $\\sigma$: desviación del módulo del error de "
           "posición, independiente en cada muestra de 1~s. ``Cierre en destino'': la misión terminó al "
           f"llegar al destino, que está a {coma(d_ult, 0)}~m de la última RSU ({ultima}), antes de registrar "
           "su cruce.}\n\\label{tab:direccionamiento}\n\\small\n"
           "\\begin{tabular}{rrrrrrrrr}\n\\toprule\n\\textbf{$\\sigma$ (m)} & \\textbf{Paradas} & "
           "\\textbf{Correctas (\\%)} & \\textbf{Acceso errado} & \\textbf{Cierre en destino} & "
           "\\textbf{Sin cruce (otro)} & \\textbf{Omitidas} & "
           "\\textbf{M1 espurios} & \\textbf{Rep. con recálculo} \\\\\n\\midrule\n" + "\n".join(fil) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_direccionamiento.tex").write_text(tex, encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    xs = [float(k) for k in res["sigmas"]]
    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    ax.plot(xs, [s["pct_correcta"] for s in res["sigmas"].values()], "o-", color="#4C72B0",
            label="Paradas correctas")
    ax.plot(xs, [100 * s["reps_con_recalculo"] / s["repeticiones"] for s in res["sigmas"].values()],
            "s--", color="#C44E52", label="Repeticiones con recálculo")
    ax.set_xlabel("$\\sigma$ del error de posición (m)")
    ax.set_ylabel("%")
    ax.set_ylim(-3, 103)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="center left")
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(salida / f"fig_direccionamiento.{ext}", dpi=200)
    print(f"Salida en {salida}")


if __name__ == "__main__":
    main()
