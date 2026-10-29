#!/usr/bin/env python3
"""Figuras de una campaña de la ARQUITECTURA CENTRALIZADA (PDF vectorial
para LaTeX + PNG), a partir de scripts/campanas/lazo_centralizado.py +
scripts/analisis/lazo_centralizado.py. Reemplaza, para este propósito, a
scripts/analisis/graficos_campana.py (que sigue sirviendo para el esquema
legado, ver su docstring).

Definiciones de cada métrica: docs/MEDICION_LATENCIA.md, sección 8.

Acepta varias corridas ETIQUETADAS (p. ej. local / pi-lan / pi-4g del
mismo escenario) para la figura comparativa:

    python scripts/analisis/graficos_campana_centralizada.py \\
        --dir resultados/campana/<corrida_local> --etiqueta local \\
        --dir resultados/campana/<corrida_pi_lan> --etiqueta pi-lan \\
        --salida F:\\tesis2\\Overleaf\\figuras\\resultados

--dir y --etiqueta se emparejan por posición (el primer --dir con el
primer --etiqueta, etc.). Si una misma etiqueta aparece en varios --dir,
sus eventos se combinan como una sola corrida (p. ej. varias repeticiones
guardadas en carpetas separadas).

Figuras:
  fig_rtt_cdf       CDF de RTT_srv, una curva por etiqueta
  fig_tramos        t_RSU, t_srv_RSU, L por etiqueta (caja + puntos; los
                     de dos relojes solo si esa etiqueta los tiene confiables)
  fig_comparacion   RTT_srv y t_RSU lado a lado, una caja por etiqueta
                     (la figura "comparativa por configuración" pedida)
  tabla_latencia.tex tabla LaTeX, una fila por métrica y etiqueta (n, mediana, p95, máx)
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import analizar, cargar, confiabilidad_dos_relojes, percentil  # noqa: E402

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
PALETA = [AZUL, NARANJA, AQUA, VIOLETA]
COL1, COL2 = 3.5, 7.16


def _grupos(dirs: list[str], etiquetas: list[str]) -> dict[str, list[Path]]:
    if len(dirs) != len(etiquetas):
        raise SystemExit(f"--dir ({len(dirs)}) y --etiqueta ({len(etiquetas)}) deben venir en pares, "
                         f"la misma cantidad de cada uno.")
    grupos: dict[str, list[Path]] = {}
    for d, et in zip(dirs, etiquetas):
        grupos.setdefault(et, []).append(Path(d))
    return grupos


def _ecdf(ax, valores, color, etiqueta):
    v = sorted(valores)
    if not v:
        return
    n = len(v)
    ys = [(i + 1) / n for i in range(n)]
    ax.step(v, ys, where="post", color=color, label=f"{etiqueta} (n={n})")


def fig_rtt_cdf(ax, resultados: dict[str, dict]):
    for (etq, g), color in zip(resultados.items(), PALETA):
        _ecdf(ax, _valores_de(g, "RTT_srv_ms"), color, etq)
    ax.set_xlabel("RTT_srv (ms)")
    ax.set_ylabel("Probabilidad acumulada")
    ax.set_ylim(0, 1.02)
    ax.set_title("(a) CDF de RTT_srv", loc="left")
    ax.legend(loc="lower right", frameon=False)
    ax.grid(True)


def _valores_de(g: dict, clave: str) -> list[float]:
    return g.get(f"_{clave}_valores", [])


def fig_tramos(ax, resultados: dict[str, dict]):
    etiquetas = list(resultados)
    metricas = [("t_RSU_ms", "$t_{RSU}$"), ("L_ms", "$L$")]
    pos = 1
    xticks, xlabels = [], []
    for metrica, nombre in metricas:
        for etq, color in zip(etiquetas, PALETA):
            vals = _valores_de(resultados[etq], metrica)
            if vals:
                jit = [pos + 0.12 * math.sin(i * 2.399) for i in range(len(vals))]
                ax.scatter(jit, vals, s=9, color=color, alpha=0.85, lw=0, zorder=3)
                ax.boxplot([vals], positions=[pos], widths=0.5, showfliers=False,
                          patch_artist=True, boxprops=dict(facecolor=color + "33", edgecolor=color, lw=0.7),
                          medianprops=dict(color="#0b0b0b", lw=1.1), whiskerprops=dict(color=INK2, lw=0.7),
                          capprops=dict(color=INK2, lw=0.7))
            xticks.append(pos)
            xlabels.append(f"{nombre}\n{etq}")
            pos += 1
        pos += 0.6
    ax.set_xticks(xticks, xlabels, fontsize=6.5)
    ax.set_ylabel("Latencia (ms)")
    ax.set_title("(b) $t_{RSU}$ y $L$ por configuración", loc="left")
    ax.grid(True, axis="y")
    ax.set_ylim(bottom=0)


def fig_comparacion(ax, resultados: dict[str, dict]):
    """La figura comparativa pedida: RTT_srv y t_RSU (un solo reloj,
    validas en cualquier config) lado a lado, una caja por etiqueta."""
    etiquetas = list(resultados)
    metricas = [("RTT_srv_ms", "RTT_srv"), ("t_RSU_ms", "t_RSU")]
    pos = 1
    xticks, xlabels = [], []
    for metrica, nombre in metricas:
        for etq, color in zip(etiquetas, PALETA):
            vals = _valores_de(resultados[etq], metrica)
            if vals:
                jit = [pos + 0.12 * math.sin(i * 2.399) for i in range(len(vals))]
                ax.scatter(jit, vals, s=9, color=color, alpha=0.85, lw=0, zorder=3)
                ax.boxplot([vals], positions=[pos], widths=0.5, showfliers=False,
                          patch_artist=True, boxprops=dict(facecolor=color + "33", edgecolor=color, lw=0.7),
                          medianprops=dict(color="#0b0b0b", lw=1.1), whiskerprops=dict(color=INK2, lw=0.7),
                          capprops=dict(color=INK2, lw=0.7))
            xticks.append(pos)
            xlabels.append(f"{nombre}\n{etq}")
            pos += 1
        pos += 0.6
    ax.set_xticks(xticks, xlabels, fontsize=6.5)
    ax.set_ylabel("Latencia (ms)")
    ax.set_title("Comparación por configuración (métricas de un solo reloj)", loc="left")
    ax.grid(True, axis="y")
    ax.set_ylim(bottom=0)


def guardar(fig, salida: Path, nombre: str):
    fig.savefig(salida / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(salida / f"{nombre}.png", bbox_inches="tight")
    plt.close(fig)


def tabla_latex(resultados: dict[str, dict], salida: Path, nota: str):
    metricas = [("RTT\\_srv", "RTT_srv_ms", "ms"), ("$t_{RSU}$", "t_RSU_ms", "ms"),
                ("$t_{OBU\\to srv}$", "t_OBU_srv_ms", "ms"), ("$L$ (RNF-01)", "L_ms", "ms"),
                ("Anticipación real", "anticipacion_real_s", "s")]
    lineas = ["\\begin{table}[H]", "\\centering",
              "\\caption{Latencia del lazo, arquitectura centralizada. " + nota + "}",
              "\\label{tab:latencia_campana_centralizada}", "\\small",
              "\\begin{tabular}{llrrrrl}", "\\toprule",
              "\\textbf{Métrica} & \\textbf{Config.} & \\textbf{n} & \\textbf{Mediana} & "
              "\\textbf{p95} & \\textbf{Máx.} & \\textbf{Unidad} \\\\", "\\midrule"]
    for nombre, clave, unidad in metricas:
        for etq, g in resultados.items():
            m = g.get(clave, {})
            if m.get("n"):
                lineas.append(f"{nombre} & {etq} & {m['n']} & {m['mediana']:.2f} & {m['p95']:.2f} & "
                              f"{m['max']:.2f} & {unidad} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_latencia.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _recolectar_valores(filas: list[dict], clave: str) -> list[float]:
    return [f[clave] for f in filas if f.get(clave) is not None]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--etiqueta", action="append", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--nota", default="")
    args = ap.parse_args()

    grupos = _grupos(args.dir, args.etiqueta)
    resultados: dict[str, dict] = {}
    for etq, dirs in grupos.items():
        confiable = confiabilidad_dos_relojes(dirs)
        _, filas_parada, g = analizar(cargar(dirs), confiable)
        # t_OBU_srv vive en filas_mision, no filas_parada; se omite de los
        # box plots comparativos por simplicidad (queda igual en lazo_resumen.json).
        for clave in ("RTT_srv_ms", "t_RSU_ms", "L_ms", "anticipacion_real_s"):
            g[f"_{clave}_valores"] = _recolectar_valores(filas_parada, clave)
        resultados[etq] = g

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(COL1, 2.4))
    fig_rtt_cdf(ax, resultados)
    guardar(fig, salida, "fig_rtt_cdf")

    fig, ax = plt.subplots(figsize=(COL2, 2.6))
    fig_tramos(ax, resultados)
    guardar(fig, salida, "fig_tramos")

    fig, ax = plt.subplots(figsize=(COL2, 2.6))
    fig_comparacion(ax, resultados)
    if args.nota:
        fig.text(0.01, -0.02, args.nota, fontsize=7, color=INK2, ha="left", va="top")
    guardar(fig, salida, "fig_comparacion")

    tabla_latex(resultados, salida, args.nota)
    print(f"Figuras en {salida}: fig_rtt_cdf, fig_tramos, fig_comparacion (.pdf y .png)")
    print(f"Tabla LaTeX: {salida / 'tabla_latencia.tex'}")
    for etq, g in resultados.items():
        rtt = g["RTT_srv_ms"]
        if rtt.get("n"):
            texto = f"mediana {rtt['mediana']:.2f} ms, p95 {rtt['p95']:.2f} ms"
        else:
            texto = "sin datos"
        print(f"  [{etq}] RTT_srv: {texto}")


if __name__ == "__main__":
    main()
