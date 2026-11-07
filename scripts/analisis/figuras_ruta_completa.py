#!/usr/bin/env python3
"""Figuras de la campaña de ruta completa, con el estilo de
scripts/analisis/espacio_tiempo.py (figuras/resultados/ de la tesis), en
PDF vectorial (y PNG para la presentación):

  fig_ruta_mapa                 trazado sobre el grafo, cada RSU coloreada
                                según la fase en que llegó la solicitud en
                                una repetición representativa.
  fig_ruta_espacio_tiempo_<E>   diagrama espacio-tiempo de toda la ruta, para
                                una repetición de A y otra de B. El fondo de
                                cada RSU es el plan del controlador
                                reconstruido con el instante de inicio de su
                                ciclo (evento ctrl_inicio): exacto para el
                                controlador emulado de tiempos fijos.
  fig_ruta_anticipacion         anticipación real por RSU, un punto por
                                repetición, con la línea de 8 s.
  fig_ruta_con_sin_prioridad    % de cruces en verde con y sin prioridad
                                (método de la Tabla 4.10) y demora evitada
                                acumulada a lo largo de la ruta.

Uso:
    python scripts/analisis/figuras_ruta_completa.py --analisis resultados/ruta_completa/analisis \\
        --rep-a <corrida A>/rep_01 --rep-b <corrida B>/rep_01 --salida resultados/ruta_completa/figuras
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from espacio_tiempo import AZUL, COL2, INK2, NOMBRE_FASE  # noqa: E402,F401  (también fija rcParams)
from common.events import iter_eventos  # noqa: E402
from ruta_completa import CICLO, ORDEN  # noqa: E402
from servidor import rutas  # noqa: E402

NS = 1e9
COLOR_FASE = {"verde": "#1baf7a", "amarillo": "#eab308", "todo_rojo": "#eb6834", "rojo_general": "#b91c1c"}
COLOR_FASE_SUAVE = {"verde": "#c9ecdc", "amarillo": "#f8eab8", "todo_rojo": "#f8d3c2", "rojo_general": "#ecc6c6"}
REGISTRO = RAIZ / "scripts" / "campanas" / "fixtures" / "registro_ruta_hospital_nino.json"
VALID = RAIZ / "scripts" / "campanas" / "fixtures" / "ruta_completa" / "validacion_sin_red.json"
ORIGEN = (-12.074664, -77.082933)
DESTINO = (-12.0649978, -77.0464372)


def leer_filas(analisis: Path) -> list[dict]:
    with (analisis / "por_parada.csv").open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for f in filas:
        for k, v in f.items():
            if v in ("", "None"):
                f[k] = None
            else:
                try:
                    f[k] = float(v) if k not in ("rsu_id", "id_solicitud", "mision_id") else v
                except ValueError:
                    pass
    return filas


def guardar(fig, salida: Path, nombre: str) -> None:
    fig.savefig(salida / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(salida / f"{nombre}.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


def fig_mapa(filas: list[dict], rep: str, corrida: str, salida: Path) -> None:
    G = rutas.cargar_grafo()
    reg = json.loads(REGISTRO.read_text(encoding="utf-8"))["rsu"]
    ruta = rutas.calcular_ruta(G, ORIGEN, DESTINO)
    lats = [n.lat for n in ruta.geometria]
    lons = [n.lon for n in ruta.geometria]
    m = 0.003
    caja = (min(lats) - m, max(lats) + m, min(lons) - m, max(lons) + m)
    fig, ax = plt.subplots(figsize=(COL2, 4.3))
    for u, v in G.edges():
        a, b = G.nodes[u], G.nodes[v]
        ya, xa, yb, xb = float(a["y"]), float(a["x"]), float(b["y"]), float(b["x"])
        if caja[0] <= ya <= caja[1] and caja[2] <= xa <= caja[3]:
            ax.plot([xa, xb], [ya, yb], color="#e4e3df", lw=0.4, zorder=1)
    ax.plot(lons, lats, color=AZUL, lw=2.0, zorder=2, label="Ruta calculada por el servidor")
    fase = {f["rsu_id"]: f.get("fase_decision") for f in filas if f["repeticion"] == rep and f["corrida"] == corrida}
    for r in reg:
        fz = fase.get(r["rsu_id"])
        ax.plot(r["centro"]["lon"], r["centro"]["lat"], "o", ms=7, color=COLOR_FASE.get(fz, "#999999"),
                mec="#0b0b0b", mew=0.6, zorder=4)
        ax.annotate(r["rsu_id"], (r["centro"]["lon"], r["centro"]["lat"]), xytext=(5, 4),
                    textcoords="offset points", fontsize=6.5, zorder=5)
    ax.plot(*ORIGEN[::-1], marker="s", ms=6, color="#0b0b0b", zorder=5)
    ax.annotate("Origen", ORIGEN[::-1], xytext=(-6, -10), textcoords="offset points", fontsize=7, ha="right")
    ax.plot(*DESTINO[::-1], marker="P", ms=8, color="#0b0b0b", zorder=5)
    ax.annotate("Hospital", DESTINO[::-1], xytext=(6, 4), textcoords="offset points", fontsize=7)
    ax.set_xlim(caja[2], caja[3])
    ax.set_ylim(caja[0], caja[1])
    ax.set_aspect(1 / 0.978)  # cos(12.07°): misma escala en x e y
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    leyenda = [plt.Line2D([0], [0], color=AZUL, lw=2, label="Ruta")] + [
        plt.Line2D([0], [0], marker="o", lw=0, color=COLOR_FASE[k], mec="#0b0b0b",
                   label=f"Solicitud llegó en {NOMBRE_FASE[k]}") for k in ("verde", "amarillo", "todo_rojo", "rojo_general")]
    ax.legend(handles=leyenda, loc="lower right", frameon=True, fontsize=6.5)
    guardar(fig, salida, "fig_ruta_mapa")


def fig_espacio_tiempo(rep_dir: Path, salida: Path, nombre: str) -> None:
    eventos = sorted(iter_eventos(rep_dir), key=lambda e: e["ts_ns"])
    t0 = next(e["ts_ns"] for e in eventos if e["tipo_evento"] == "mision_armada")
    mision = next(e["id_solicitud"] for e in eventos if e["tipo_evento"] == "mision_armada")
    paradas = {k: float(v) for k, v in json.loads(VALID.read_text(encoding="utf-8"))["paradas"].items()}
    reg = {r["rsu_id"]: r["interseccion_id"] for r in json.loads(REGISTRO.read_text(encoding="utf-8"))["rsu"]}
    with (rep_dir / "trayectoria_base.csv").open(newline="", encoding="utf-8") as fh:
        base = {round(float(r["t_s"]), 1): float(r["s_m"]) for r in csv.DictReader(fh)}
    tv, sv = [], []
    for e in eventos:
        if e["tipo_evento"] == "MP_tx":
            s = base.get(round(e["extra"]["t_tray_s"], 1))
            if s is not None:
                tv.append((e["ts_ns"] - t0) / NS)
                sv.append(s)
    inicio = {e["nodo"].split("_")[1]: e["extra"]["epoch_wall_ns"] for e in eventos if e["tipo_evento"] == "ctrl_inicio"}
    t_max = tv[-1] + 5
    banda = 46.0
    fig, ax = plt.subplots(figsize=(COL2, 5.0))
    for rid, d in paradas.items():
        sid = f"{mision}-{reg[rid]}"
        # Plan sin prioridad, reconstruido con el inicio del ciclo.
        if rid in inicio:
            t = (inicio[rid] - t0) / NS
            while t > 0:
                t -= CICLO
            while t < t_max:
                for fase, dur in ORDEN:
                    a, b = max(t, 0), min(t + dur, t_max)
                    if b > a:
                        ax.add_patch(Rectangle((a, d - banda / 2), b - a, banda, facecolor=COLOR_FASE_SUAVE[fase],
                                               edgecolor="none", zorder=1))
                    t += dur
        conc = [e["ts_ns"] for e in eventos if e["id_solicitud"] == sid and e["tipo_evento"] == "M2_rx"
                and e["extra"].get("estado") == "concedida"]
        verde_ctrl = [e["ts_ns"] for e in eventos if e["id_solicitud"] == sid and e["tipo_evento"] == "ctrl_fase_cambio"
                      and e["extra"].get("motivo") == "solicitud_prioridad"]
        m3 = [e["ts_ns"] for e in eventos if e["id_solicitud"] == sid and e["tipo_evento"] == "M3_tx"]
        m1 = [e["ts_ns"] for e in eventos if e["id_solicitud"] == sid and e["tipo_evento"] == "M1_tx"]
        decision = next((e for e in eventos if e["id_solicitud"] == sid and e["tipo_evento"] == "snmp_set_tx"
                         and e["extra"].get("accion") in ("request_priority", "en_cola_despeje")), None)
        t_verde = min(verde_ctrl or conc or [None]) if (verde_ctrl or conc) else None
        if t_verde and m3:
            a, b = (t_verde - t0) / NS, (max(m3) - t0) / NS
            ax.add_patch(Rectangle((a, d - banda / 2), b - a, banda, facecolor="#1baf7a", edgecolor="#0b0b0b",
                                   lw=0.4, zorder=2))
        if decision and t_verde and decision["ts_ns"] < t_verde - 0.2 * NS:  # en cola de despeje
            a = (decision["ts_ns"] - t0) / NS
            ax.add_patch(Rectangle((a, d - banda / 2), (t_verde - decision["ts_ns"]) / NS, banda,
                                   facecolor="none", edgecolor="#0b0b0b", hatch="////", lw=0.4, zorder=2))
        if m1:
            ax.plot((min(m1) - t0) / NS, d - banda / 2 - 14, marker="^", ms=3.5, color=INK2, zorder=4)
        ax.annotate(rid, (t_max, d), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6,
                    annotation_clip=False)
    ax.plot(tv, sv, color=AZUL, lw=1.5, zorder=6)
    ax.set_xlim(0, t_max)
    ax.set_ylim(0, max(sv) + 60)
    ax.set_xlabel("Tiempo desde el armado de la misión (s)")
    ax.set_ylabel("Distancia a lo largo de la ruta (m)")
    ax.grid(True, axis="x", alpha=0.5)
    leyenda = [
        plt.Line2D([0], [0], color=AZUL, lw=1.5, label="Vehículo (trayectoria reproducida)"),
        Rectangle((0, 0), 1, 1, facecolor="#1baf7a", edgecolor="#0b0b0b", lw=0.4, label="Verde por prioridad"),
        Rectangle((0, 0), 1, 1, facecolor="none", edgecolor="#0b0b0b", hatch="////", label="En cola de despeje"),
        plt.Line2D([0], [0], marker="^", color=INK2, lw=0, label="Primera solicitud (M1)"),
    ] + [Rectangle((0, 0), 1, 1, facecolor=COLOR_FASE_SUAVE[k], label=f"Plan: {NOMBRE_FASE[k]}") for k, _ in ORDEN]
    ax.legend(handles=leyenda, loc="upper center", bbox_to_anchor=(0.5, -0.11), ncol=4, frameon=False, fontsize=6)
    guardar(fig, salida, nombre)


def fig_anticipacion(filas: list[dict], salida: Path) -> None:
    ids = sorted({f["rsu_id"] for f in filas}, key=int)
    pos = {r: i for i, r in enumerate(ids)}
    fig, ax = plt.subplots(figsize=(COL2, 2.8))
    estilos = {"ruta_A": ("o", AZUL, -0.15, "A: 36 km/h constante"),
               "ruta_B": ("^", "#eb6834", 0.15, "B: perfil sintético variable")}
    for esc, (mk, col, dx, lab) in estilos.items():
        xs = [pos[f["rsu_id"]] + dx for f in filas if f["escenario"] == esc and f["anticipacion_real_s"] is not None]
        ys = [f["anticipacion_real_s"] for f in filas if f["escenario"] == esc and f["anticipacion_real_s"] is not None]
        if xs:
            ax.plot(xs, ys, mk, ms=3.5, color=col, alpha=0.8, lw=0, label=lab)
    ax.axhline(8.0, color="#b91c1c", lw=0.9, ls="--", label="Anticipación mínima (8 s)")
    ax.set_xticks(range(len(ids)), ids)
    ax.set_xlabel("RSU (en el orden de la ruta)")
    ax.set_ylabel("Anticipación real (s)")
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", alpha=0.5)
    ax.legend(loc="lower right", frameon=False, fontsize=6.5, ncol=3)
    guardar(fig, salida, "fig_ruta_anticipacion")


def fig_con_sin(filas: list[dict], salida: Path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(COL2, 2.6), gridspec_kw={"width_ratios": [1, 1.6]})
    escs = [e for e in ("ruta_A", "ruta_B") if any(f["escenario"] == e for f in filas)]
    con, sin = [], []
    for e in escs:
        fs = [f for f in filas if f["escenario"] == e and f["ultimo_m3_motivo"] == "cruce"]
        con.append(100 * sum(1 for f in fs if f["obtuvo_verde"] in (True, "True", 1.0)) / len(fs))
        fs2 = [f for f in fs if f["metodo_contrafactual"] != "sin_dato"]
        sin.append(100 * sum(1 for f in fs2 if f["fase_sin_prioridad_tesis"] == "verde") / len(fs2))
    x = range(len(escs))
    a1.bar([i - 0.18 for i in x], con, 0.36, color="#1baf7a", label="Con prioridad")
    a1.bar([i + 0.18 for i in x], sin, 0.36, color="#999999", label="Sin prioridad (est.)")
    a1.set_xticks(list(x), [e.replace("ruta_", "Escenario ") for e in escs])
    a1.set_ylabel("Cruces en verde (%)")
    a1.set_ylim(0, 105)
    a1.legend(frameon=False, fontsize=6, loc="lower left")
    for e, col in (("ruta_A", AZUL), ("ruta_B", "#eb6834")):
        por_rep = defaultdict(list)
        for f in filas:
            if f["escenario"] == e and f["ultimo_m3_motivo"] == "cruce" and f["acum_m"] is not None:
                por_rep[(f["corrida"], f["repeticion"])].append((f["acum_m"], f["demora_evitada_tesis_s"] or 0.0))
        for k, (clave, pts) in enumerate(sorted(por_rep.items())):
            pts.sort()
            xs, ys, acc = [0.0], [0.0], 0.0
            for d, dem in pts:
                xs.append(d)
                ys.append(acc)
                acc += dem
                xs.append(d)
                ys.append(acc)
            a2.plot(xs, ys, color=col, lw=1.0, alpha=0.7, label=e.replace("ruta_", "Escenario ") if k == 0 else None)
    a2.set_xlabel("Distancia a lo largo de la ruta (m)")
    a2.set_ylabel("Demora evitada acumulada (s, est.)")
    a2.grid(True, alpha=0.5)
    a2.legend(frameon=False, fontsize=6, loc="upper left")
    fig.tight_layout()
    guardar(fig, salida, "fig_ruta_con_sin_prioridad")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analisis", required=True)
    ap.add_argument("--rep-a", required=True)
    ap.add_argument("--rep-b", default=None)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    filas = leer_filas(Path(args.analisis))
    rep_a = Path(args.rep_a)
    fig_mapa(filas, rep_a.name, rep_a.parent.name, salida)
    fig_espacio_tiempo(rep_a, salida, "fig_ruta_espacio_tiempo_A")
    if args.rep_b:
        fig_espacio_tiempo(Path(args.rep_b), salida, "fig_ruta_espacio_tiempo_B")
    fig_anticipacion(filas, salida)
    fig_con_sin(filas, salida)
    print(f"Figuras en {salida}")


if __name__ == "__main__":
    main()
