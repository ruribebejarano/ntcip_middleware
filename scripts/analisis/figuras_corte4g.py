#!/usr/bin/env python3
"""OE5 (RNF-07, RNF-08): figuras del corte físico del enlace 4G de la RSU,
a partir del JSON de scripts/analisis/corte4g_resumen.py.

  fig_corte4g_tiempos  t_lib y T_rec de cada corte, una fila por corrida,
                       con los límites de RNF-07 (4 s) y RNF-08 (10 s)
  fig_corte4g_tramos   línea de tiempo de cada corte de la corrida con la
                       reconexión ajustada: módem desconectado, detección
                       de la pérdida por el cliente MQTT y los tramos de
                       T_rec (enlace USB, reconexión, primer M1)

Uso:
  .venv/Scripts/python.exe scripts/analisis/figuras_corte4g.py \
      --resumen <corte4g_resumen.json> --salida <dir> \
      --etiqueta <corrida>=<texto> [--etiqueta ...] --tramos <corrida>
Las corridas se dibujan en el orden de --etiqueta, de arriba abajo; la
primera va resaltada.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
from espacio_tiempo import AZUL, INK2  # noqa: E402  (también fija rcParams)

GRIS = "#b5b3ad"
REF = "#8a8984"
ANCHO = 6.3
LIM_RNF07, LIM_RNF08 = 4.0, 10.0


def coma(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}".replace(".", ",")


def guardar(fig, salida: Path, nombre: str) -> None:
    fig.savefig(salida / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(salida / f"{nombre}.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


def fig_tiempos(corridas: list[tuple[str, dict]], salida: Path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(ANCHO, 0.62 * len(corridas) + 1.0), sharey=True,
                                 gridspec_kw={"width_ratios": [1, 1.6], "wspace": 0.08})
    for k, (etq, c) in enumerate(corridas):
        y = len(corridas) - 1 - k
        color = AZUL if k == 0 else GRIS
        filas = c["por_repeticion"]
        for ax, campo in ((a1, "t_lib_s"), (a2, "T_rec_s")):
            v = [f[campo] for f in filas if f[campo] is not None]
            jit = [((f["rep"] % 5) - 2) * 0.07 for f in filas if f[campo] is not None]
            ax.scatter(v, [y + j for j in jit], s=14, color=color, alpha=0.85, lw=0, zorder=3)
            m = statistics.median(v)
            ax.plot([m, m], [y - 0.25, y + 0.25], color="#0b0b0b", lw=1.3, zorder=4)
            ax.text(m, y + 0.3, f"{coma(m, 2 if campo == 't_lib_s' else 1)} s", ha="center", va="bottom",
                    fontsize=6.5, color="#0b0b0b")
    for ax, lim, texto, xmax in ((a1, LIM_RNF07, "RNF-07: 4 s", 5.0), (a2, LIM_RNF08, "RNF-08: 10 s", 45.0)):
        ax.axvline(lim, color=REF, lw=0.8, ls=(0, (4, 3)), zorder=1)
        ax.text(lim + xmax * 0.012, len(corridas) - 0.45, texto, fontsize=6.5, color=INK2, va="top")
        ax.set_xlim(0, xmax)
        ax.grid(axis="x")
        ax.set_axisbelow(True)
    a1.set_xlabel("$t_{lib}$: último M1 → liberación (s)")
    a2.set_xlabel("$T_{rec}$: módem reconectado → primer M1 (s)")
    a1.set_yticks(range(len(corridas)))
    a1.set_yticklabels([etq for etq, _ in reversed(corridas)])
    a1.set_ylim(-0.6, len(corridas) - 0.2)
    a1.tick_params(axis="y", length=0)
    a2.tick_params(axis="y", length=0)
    guardar(fig, salida, "fig_corte4g_tiempos")


def fig_tramos(c: dict, salida: Path) -> None:
    filas = [f for f in c["por_repeticion"] if f.get("trec_mqtt_s") is not None]
    fig, ax = plt.subplots(figsize=(ANCHO, 0.24 * len(filas) + 1.0))
    tramos = (("trec_modem_s", "#9cc3ef", "enlace USB del módem"),
              ("trec_mqtt_s", AZUL, "reconexión: red celular, túnel y TLS"),
              ("trec_primer_m1_s", "#16467f", "primer M1"))
    for i, f in enumerate(filas):
        y = len(filas) - 1 - i
        ax.barh(y, f["corte_s"], left=0, height=0.55, color="#ecebe7", edgecolor=GRIS, lw=0.5)
        x = f["corte_s"]
        for campo, color, _ in tramos:
            ax.barh(y, f[campo], left=x, height=0.55, color=color, lw=0)
            x += f[campo]
        if f.get("deteccion_s") is not None:
            ax.plot(f["deteccion_s"], y, marker="v", ms=4.5, color="#0b0b0b", lw=0)
        ax.text(x + 0.4, y, f"{coma(f['T_rec_s'])} s", va="center", fontsize=6.5, color=INK2)
    hand = [plt.Rectangle((0, 0), 1, 1, fc="#ecebe7", ec=GRIS, lw=0.5)] + \
           [plt.Rectangle((0, 0), 1, 1, fc=col, lw=0) for _, col, _ in tramos] + \
           [plt.Line2D([0], [0], marker="v", ms=4.5, color="#0b0b0b", lw=0)]
    etqs = ["módem desconectado"] + [t for _, _, t in tramos] + ["el cliente MQTT da la conexión por perdida"]
    ax.legend(hand, etqs, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False)
    ax.set_yticks(range(len(filas)))
    ax.set_yticklabels([f"corte {f['rep']}" for f in reversed(filas)])
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("tiempo desde el corte (s)")
    ax.set_xlim(0, max(f["corte_s"] + f["T_rec_s"] for f in filas) + 3)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    guardar(fig, salida, "fig_corte4g_tramos")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--resumen", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    ap.add_argument("--etiqueta", action="append", required=True, help="<corrida>=<texto>")
    ap.add_argument("--tramos", required=True, help="corrida de la figura de tramos")
    a = ap.parse_args()
    datos = {c["corrida"]: c for c in json.loads(a.resumen.read_text(encoding="utf-8"))["corridas"]}
    corridas = []
    for e in a.etiqueta:
        nombre, texto = e.split("=", 1)
        corridas.append((texto, datos[nombre]))
    a.salida.mkdir(parents=True, exist_ok=True)
    fig_tiempos(corridas, a.salida)
    fig_tramos(datos[a.tramos], a.salida)
    print(f"Figuras en {a.salida}")


if __name__ == "__main__":
    main()
