#!/usr/bin/env python3
"""M3 (prompt_figuras_cap4.md): cumplimiento de RF8 (anticipación real >= 8 s)
por intersección, sobre las 4 campañas válidas de la arquitectura
centralizada (resultados/campana/2026102*, excluida _descartadas/).

Fuente única: columna `anticipacion_real_s` de `lazo_por_parada.csv` (ya
calculada por scripts/analisis/lazo_centralizado.py::analizar() a partir de
los eventos crudos -- este script NO reprocesa eventos, solo agrega lo que
ya está en esa columna). El escenario y la condición de cada corrida se
leen de su `config.json` (`escenario`, `config`), no se piden a mano.

Las paradas con `anticipacion_real_s` vacía (escenario `desvio`: la ruta se
recalculó antes del cruce por esa RSU, nunca hubo M3 motivo=cruce para
anclar la anticipación) NO son incumplimiento: se cuentan aparte.

Salidas en --salida:
  fig_rf8_cdf.pdf/.png   CDF de anticipacion_real_s, una curva por etiqueta
                         (condición+escenario), con línea vertical en 8 s.
  tabla_rf8.tex          % de paradas con anticipación >= 8 s por condición
                         y escenario, con n de paradas sin dato (desvío)
                         aparte.
  incumplimientos.txt    lista de paradas con anticipación < 8 s y su causa
                         probable (vacío si no hay ninguna: no aproximar un
                         hallazgo que no está en los datos).

Uso:
    python scripts/analisis/cumplimiento_rf8.py \\
        --dir resultados/campana/<corrida1> --dir resultados/campana/<corrida2> ... \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import percentil  # noqa: E402

ANTICIPACION_MINIMA_S = 8.0  # RF8 (servidor/gestor_mision.py)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 7.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.linewidth": 0.6,
    "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e",
    "ytick.color": "#52514e", "grid.color": "#e4e3df", "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 300,
    "figure.dpi": 150, "lines.linewidth": 1.4,
})
AZUL, NARANJA, AQUA, VIOLETA = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
PALETA = [AZUL, NARANJA, AQUA, VIOLETA, "#b8860b", "#52514e"]
COL1 = 3.5


def cargar_corrida(d: Path) -> tuple[str, list[dict]]:
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    etiqueta = f"{cfg['config']}/{cfg['escenario']}"
    filas = []
    with (d / "lazo_por_parada.csv").open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    return etiqueta, filas


def clasificar(filas: list[dict]) -> dict:
    """Separa las paradas de una corrida en: con_cruce (anticipacion_real_s
    con valor), sin_dato_desvio (ultimo_m3_motivo == 'desvio', sin valor),
    sin_dato_otro (cualquier otro motivo sin valor, para no asumir que todo
    vacío es un desvío)."""
    con_cruce, sin_dato_desvio, sin_dato_otro = [], [], []
    for f in filas:
        val = f.get("anticipacion_real_s")
        if val:
            con_cruce.append(f)
        elif f.get("ultimo_m3_motivo") == "desvio":
            sin_dato_desvio.append(f)
        else:
            sin_dato_otro.append(f)
    return {"con_cruce": con_cruce, "sin_dato_desvio": sin_dato_desvio, "sin_dato_otro": sin_dato_otro}


def fig_cdf(ax, grupos: dict[str, dict]):
    for (etq, g), color in zip(grupos.items(), PALETA):
        vals = sorted(float(f["anticipacion_real_s"]) for f in g["con_cruce"])
        if not vals:
            continue
        n = len(vals)
        ys = [(i + 1) / n for i in range(n)]
        ax.step(vals, ys, where="post", color=color, label=f"{etq} (n={n})")
    ax.axvline(ANTICIPACION_MINIMA_S, color="#0b0b0b", lw=1.0, ls="--")
    # Sin título: lo pone el \caption de la tesis, donde este margen es RF-14.
    ax.text(ANTICIPACION_MINIMA_S, 0.02, " 8 s (RF-13)", fontsize=7, va="bottom", ha="left")
    ax.set_xlabel("Anticipación real (s)")
    ax.set_ylabel("Probabilidad acumulada")
    ax.set_ylim(0, 1.02)
    ax.legend(loc="upper left", bbox_to_anchor=(0.12, 1.0), frameon=False, fontsize=6.5)
    ax.grid(True)


def tabla_latex(grupos: dict[str, dict], salida: Path) -> None:
    n_total = sum(len(g["con_cruce"]) + len(g["sin_dato_desvio"]) + len(g["sin_dato_otro"]) for g in grupos.values())
    lineas = [
        "\\begin{table}[H]", "\\centering",
        f"\\caption{{Paradas con anticipación real $\\geq$ 8~s (RF-13) por condición de enlace y escenario "
        f"({n_total} paradas). Una parada sin cruce (ruta recalculada antes de llegar a esa RSU) se "
        "contaría aparte: no sería incumplimiento, no habría cruce que medir.}",
        "\\label{tab:anticipacion_parada}", "\\small",
        "\\begin{tabular}{lrrrr}", "\\toprule",
        "\\textbf{Condición/escenario} & \\textbf{n con cruce} & \\textbf{\\% $\\geq$ 8 s} & "
        "\\textbf{n sin dato (desvío)} & \\textbf{n sin dato (otro)} \\\\",
        "\\midrule",
    ]
    for etq, g in grupos.items():
        vals = [float(f["anticipacion_real_s"]) for f in g["con_cruce"]]
        n = len(vals)
        pct = 100.0 * sum(1 for v in vals if v >= ANTICIPACION_MINIMA_S) / n if n else float("nan")
        pct_txt = f"{pct:.1f}" if n else "--"
        lineas.append(f"{etq} & {n} & {pct_txt} & {len(g['sin_dato_desvio'])} & {len(g['sin_dato_otro'])} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_rf8.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


CAUSA_POR_MOTIVO = {
    "desvio": "ruta recalculada por desvío (>60 m de la ruta, RF... ver gateway/geometria.py) antes del cruce",
    "conflicto": "solicitud cancelada por arbitraje de conflicto (servidor/conflictos.py) antes del cruce",
}


def incumplimientos(grupos: dict[str, dict], salida: Path) -> list[dict]:
    hallazgos = []
    for etq, g in grupos.items():
        for f in g["con_cruce"]:
            v = float(f["anticipacion_real_s"])
            if v < ANTICIPACION_MINIMA_S:
                hallazgos.append({"etiqueta": etq, "id_solicitud": f["id_solicitud"],
                                  "anticipacion_real_s": v, "rsu_id": f.get("rsu_id")})
    lineas = []
    if hallazgos:
        for h in hallazgos:
            lineas.append(f"{h['id_solicitud']} ({h['etiqueta']}, RSU {h['rsu_id']}): "
                          f"anticipación real = {h['anticipacion_real_s']:.3f} s < 8 s")
    else:
        lineas.append("Ninguna parada con cruce real (ultimo_m3_motivo=cruce) incumplió RF8 "
                      "(anticipación real < 8 s). "
                      "No hay incumplimiento que reportar en estos datos: no se aproxima ni se "
                      "inventa uno para tener contenido que mostrar.")
    (salida / "incumplimientos.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return hallazgos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True, help="carpeta de una corrida de campaña (con config.json y lazo_por_parada.csv)")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    grupos: dict[str, dict] = {}
    for d in args.dir:
        etq, filas = cargar_corrida(Path(d))
        grupos[etq] = clasificar(filas)

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(COL1, 2.4))
    fig_cdf(ax, grupos)
    fig.savefig(salida / "fig_rf8_cdf.pdf", bbox_inches="tight")
    fig.savefig(salida / "fig_rf8_cdf.png", bbox_inches="tight")
    plt.close(fig)

    tabla_latex(grupos, salida)
    hallazgos = incumplimientos(grupos, salida)

    print(f"Figuras/tablas en {salida}: fig_rf8_cdf (.pdf/.png), tabla_rf8.tex, incumplimientos.txt")
    for etq, g in grupos.items():
        vals = [float(f["anticipacion_real_s"]) for f in g["con_cruce"]]
        n = len(vals)
        if n:
            pct = 100.0 * sum(1 for v in vals if v >= ANTICIPACION_MINIMA_S) / n
            print(f"  [{etq}] n={n} con cruce, {pct:.1f}% >= 8s, mediana={percentil(vals, 50):.2f} s "
                 f"(sin dato por desvío: {len(g['sin_dato_desvio'])})")
        else:
            print(f"  [{etq}] sin paradas con cruce (todas desvío/otro)")
    print(f"Incumplimientos RF8 (anticipación < 8 s con cruce real): {len(hallazgos)}")


if __name__ == "__main__":
    main()
