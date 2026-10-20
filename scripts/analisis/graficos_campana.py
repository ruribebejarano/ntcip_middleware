#!/usr/bin/env python3
"""Figuras de una campana del lazo, en estilo de publicacion (PDF vectorial
para LaTeX + PNG), a partir de los eventos registrados (RF-10).

Figuras:
  fig_rtt_cdf      CDF empirica del RTT M1/M2 (un solo reloj: la OBU), con p50 y p95
  fig_tramos       latencia por tramo (t_V2I, t_RSU, L) en ms, caja + puntos
  fig_despeje      espera del despeje T_desp (s) segun la fase al llegar la solicitud
  fig_rtt_serie    RTT de cada mensaje a lo largo de cada solicitud (estabilidad)
  fig_panel        las cuatro juntas (2x2) para una sola figura del Capitulo IV
  tabla_latencia.tex  tabla LaTeX con n, mediana, p95, max por metrica

Definiciones (ver docs/MEDICION_LATENCIA.md):
  L       = primer snmp_set_tx (request_priority o en_cola_despeje) - M1_tx(seq 1)   [RNF-01]
  T_desp  = activar_cola_rf06 - en_cola_despeje   (solo si llego en ambar/todo rojo)
  t_V2I   = M1_rx(seq 1) - M1_tx(seq 1)            (dos relojes)
  t_RSU   = primer snmp_set_tx - M1_rx(seq 1)      (reloj de la RSU)
  RTT     = M2_rx - M1_tx del mismo seq            (reloj de la OBU, Correlation Data)

Uso:
    python scripts/analisis/graficos_campana.py --dir resultados/lazo_emulado/<corrida> \\
        --dir resultados/rsu/eventos --salida resultados/lazo_emulado/<corrida>/figuras \\
        --nota "Banco: RSU en Raspberry Pi por Tailscale; OBU emulada"
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_emulado import cargar, percentil  # noqa: E402

# Estilo de publicacion: serif, tamanos pequenos, ejes y rejilla recesivos.
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 7.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.linewidth": 0.6,
    "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e",
    "ytick.color": "#52514e", "grid.color": "#e4e3df", "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 300,
    "figure.dpi": 150, "lines.linewidth": 1.4,
})
AZUL, NARANJA, AQUA, VIOLETA, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#52514e"
COL1, COL2 = 3.5, 7.16  # ancho de una y dos columnas (pulgadas, IEEE)


def metricas(eventos: list[dict]) -> dict:
    por_id = defaultdict(list)
    for e in eventos:
        por_id[e["id_solicitud"]].append(e)
    rtt_todos, series, L, tv2i, trsu, despeje = [], [], [], [], [], {"verde/rojo": [], "ambar/todo rojo": []}
    llegada_fase = []
    for id_sol, evs in por_id.items():
        m1 = sorted((e for e in evs if e["tipo_evento"] == "M1_tx" and "seq" in e["extra"]), key=lambda e: e["ts_ns"])
        if not m1:
            continue
        tx_por_seq = {e["extra"]["seq"]: e["ts_ns"] for e in m1}
        rx1 = next((e for e in evs if e["tipo_evento"] == "M1_rx" and e["extra"].get("seq") == 1), None)
        sets = sorted((e for e in evs if e["tipo_evento"] == "snmp_set_tx"), key=lambda e: e["ts_ns"])
        dec = next((e for e in sets if e["extra"].get("accion") in ("request_priority", "en_cola_despeje")), None)
        cola = next((e for e in sets if e["extra"].get("accion") == "activar_cola_rf06"), None)
        serie = []
        for e in sorted((x for x in evs if x["tipo_evento"] == "M2_rx"), key=lambda x: x["ts_ns"]):
            r = e["extra"].get("rtt_ms")
            if r is not None:
                rtt_todos.append(r)
                serie.append(r)
        if serie:
            series.append(serie)
        t0 = tx_por_seq.get(1, m1[0]["ts_ns"])
        if rx1:
            tv2i.append((rx1["ts_ns"] - t0) / 1e6)
        if dec:
            L.append((dec["ts_ns"] - t0) / 1e6)
            if rx1:
                trsu.append((dec["ts_ns"] - rx1["ts_ns"]) / 1e6)
            encolada = dec["extra"].get("accion") == "en_cola_despeje"
            llegada_fase.append(dec["extra"].get("fase", "verde") if encolada else "verde")
            if encolada and cola:
                despeje["ambar/todo rojo"].append((cola["ts_ns"] - dec["ts_ns"]) / 1e9)
            elif not encolada:
                despeje["verde/rojo"].append(0.0)
    return {"rtt": rtt_todos, "series": series, "L": L, "t_V2I": tv2i, "t_RSU": trsu, "despeje": despeje,
            "n_solicitudes": len(L)}


def _ecdf(ax, valores, color, etiqueta):
    v = sorted(valores)
    n = len(v)
    ys = [(i + 1) / n for i in range(n)]
    ax.step(v, ys, where="post", color=color, label=etiqueta)
    for q, ls in ((50, "--"), (95, ":")):
        x = percentil(v, q)
        ax.axvline(x, color=INK2, lw=0.7, ls=ls)
        ax.annotate(f"p{q} = {x:.1f} ms", xy=(x, q / 100), xytext=(6, -3), textcoords="offset points",
                    fontsize=7, color="#0b0b0b", va="top")
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("Probabilidad acumulada")
    ax.set_xlabel("RTT M1/M2 (ms)")
    ax.grid(True)


def fig_rtt_cdf(ax, m):
    _ecdf(ax, m["rtt"], AZUL, f"RTT (n = {len(m['rtt'])} mensajes)")
    ax.set_title("(a) CDF del RTT M1/M2", loc="left")
    ax.legend(loc="lower right", frameon=False)


def fig_tramos(ax, m):
    datos = [("$t_{V2I}$", m["t_V2I"], AZUL), ("$t_{RSU}$", m["t_RSU"], VIOLETA), ("$L$", m["L"], NARANJA)]
    datos = [d for d in datos if d[1]]
    if not datos:
        # ax.boxplot([], positions=[]) revienta con ValueError en matplotlib
        # ("List of boxplot statistics and `positions` values must have
        # same the length"): boxplot_stats(x=[]) devuelve una fila de NaN en
        # vez de una lista vacia. Pasa cuando la corrida no tiene NINGUN
        # t_V2I/t_RSU/L -- p. ej. al exportar antes de traer los eventos de
        # la RSU con scripts/pi.sh fetch.
        ax.text(0.5, 0.5, "sin datos de tramo\n(¿faltan eventos de la RSU? scripts/pi.sh fetch)",
                ha="center", va="center", fontsize=7.5, color=INK2, transform=ax.transAxes)
        ax.set_title(f"(b) Latencia por tramo (n = {m['n_solicitudes']} solicitudes)", loc="left")
        ax.set_xticks([])
        ax.set_yticks([])
        return
    pos = list(range(1, len(datos) + 1))
    bp = ax.boxplot([d[1] for d in datos], positions=pos, widths=0.45, showfliers=False, patch_artist=True,
                    medianprops=dict(color="#0b0b0b", lw=1.1), whiskerprops=dict(color=INK2, lw=0.7),
                    capprops=dict(color=INK2, lw=0.7), boxprops=dict(lw=0.7))
    for caja, (_, _, c) in zip(bp["boxes"], datos):
        caja.set_facecolor(c + "33")
        caja.set_edgecolor(c)
    for p, (_, vals, c) in zip(pos, datos):
        jit = [p + 0.12 * math.sin(i * 2.399) for i in range(len(vals))]
        ax.scatter(jit, vals, s=9, color=c, alpha=0.85, lw=0, zorder=3)
    ax.set_xticks(pos, [d[0] for d in datos])
    ax.set_ylabel("Latencia (ms)")
    ax.set_title(f"(b) Latencia por tramo (n = {m['n_solicitudes']} solicitudes)", loc="left")
    ax.grid(True, axis="y")
    ax.set_ylim(bottom=0)


def fig_despeje(ax, m):
    grupos = [("Llegó en verde\no rojo", m["despeje"]["verde/rojo"], AQUA),
              ("Llegó en ámbar\no todo rojo", m["despeje"]["ambar/todo rojo"], NARANJA)]
    for i, (et, vals, c) in enumerate(grupos, 1):
        if vals:
            jit = [i + 0.15 * math.sin(k * 2.399) for k in range(len(vals))]
            ax.scatter(jit, vals, s=14, color=c, lw=0, alpha=0.9, zorder=3)
            med = percentil(vals, 50)
            ax.hlines(med, i - 0.25, i + 0.25, color="#0b0b0b", lw=1.1)
            ax.annotate(f"mediana {med:.1f} s, n = {len(vals)}", xy=(i + 0.28, med), xytext=(0, 4),
                        textcoords="offset points", fontsize=7, va="bottom")
    ax.set_xticks([1, 2], [g[0] for g in grupos])
    ax.set_xlim(0.5, 2.9)
    ax.set_ylabel("Espera del despeje $T_{desp}$ (s)")
    ax.set_title("(c) Espera del despeje (RF-06), aparte de $L$", loc="left")
    ax.grid(True, axis="y")
    ax.set_ylim(bottom=-0.2)


def fig_rtt_serie(ax, m):
    for k, s in enumerate(m["series"]):
        ax.plot(range(1, len(s) + 1), s, color=AZUL, alpha=0.35, lw=0.8)
    if m["series"]:
        largo = max(len(s) for s in m["series"])
        med = [percentil([s[i] for s in m["series"] if len(s) > i], 50) for i in range(largo)]
        ax.plot(range(1, largo + 1), med, color="#0b0b0b", lw=1.3, label="mediana entre solicitudes")
    ax.set_xlabel("Mensaje dentro de la solicitud (1 Hz)")
    ax.set_ylabel("RTT M1/M2 (ms)")
    ax.set_title("(d) Estabilidad del RTT durante la aproximación", loc="left")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(True)
    ax.set_ylim(bottom=0)


def guardar(fig, salida: Path, nombre: str):
    fig.savefig(salida / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(salida / f"{nombre}.png", bbox_inches="tight")
    plt.close(fig)


def tabla_latex(m, salida: Path, nota: str):
    filas = [("RTT M1/M2", m["rtt"], "ms"), ("$t_{V2I}$", m["t_V2I"], "ms"), ("$t_{RSU}$", m["t_RSU"], "ms"),
             ("$L$ (RNF-01)", m["L"], "ms"), ("$T_{desp}$ (si llegó en ámbar/todo rojo)", m["despeje"]["ambar/todo rojo"], "s")]
    lineas = ["\\begin{table}[H]", "\\centering", "\\caption{Latencia del lazo de priorización. " + nota + "}",
              "\\label{tab:latencia_campana}", "\\small", "\\begin{tabular}{lrrrrl}", "\\toprule",
              "\\textbf{Métrica} & \\textbf{n} & \\textbf{Mediana} & \\textbf{p95} & \\textbf{Máx.} & \\textbf{Unidad} \\\\",
              "\\midrule"]
    for nombre, v, u in filas:
        if v:
            lineas.append(f"{nombre} & {len(v)} & {percentil(v, 50):.2f} & {percentil(v, 95):.2f} & {max(v):.2f} & {u} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_latencia.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--nota", default="", help="texto para el pie de la tabla y de la figura (banco, condiciones)")
    args = ap.parse_args()

    m = metricas(cargar([Path(d) for d in args.dir]))
    if not m["rtt"]:
        print("No hay mensajes M2 con RTT en esas carpetas.", file=sys.stderr)
        raise SystemExit(1)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    for nombre, fn, ancho, alto in (("fig_rtt_cdf", fig_rtt_cdf, COL1, 2.4), ("fig_tramos", fig_tramos, COL1, 2.4),
                                    ("fig_despeje", fig_despeje, COL1, 2.4), ("fig_rtt_serie", fig_rtt_serie, COL1, 2.4)):
        fig, ax = plt.subplots(figsize=(ancho, alto))
        fn(ax, m)
        guardar(fig, salida, nombre)

    fig, axs = plt.subplots(2, 2, figsize=(COL2, 5.0))
    fig_rtt_cdf(axs[0][0], m)
    fig_tramos(axs[0][1], m)
    fig_despeje(axs[1][0], m)
    fig_rtt_serie(axs[1][1], m)
    if args.nota:
        fig.text(0.01, -0.01, args.nota, fontsize=7, color=INK2, ha="left", va="top")
    fig.tight_layout()
    guardar(fig, salida, "fig_panel")
    tabla_latex(m, salida, args.nota)

    print(f"Figuras en {salida}: fig_panel, fig_rtt_cdf, fig_tramos, fig_despeje, fig_rtt_serie (.pdf y .png)")
    print(f"Tabla LaTeX: {salida / 'tabla_latencia.tex'}")
    if m["L"]:
        linea_l = f"L mediana {percentil(m['L'], 50):.2f} ms, p95 {percentil(m['L'], 95):.2f} ms (umbral RNF-01: 1000 ms); "
    else:
        linea_l = "L: sin datos (¿faltan eventos de la RSU? scripts/pi.sh fetch); "
    print(linea_l + f"RTT mediana {percentil(m['rtt'], 50):.2f} ms, p95 {percentil(m['rtt'], 95):.2f} ms")


if __name__ == "__main__":
    main()
