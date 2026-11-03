#!/usr/bin/env python3
"""M5 (prompt_figuras_cap4.md): percentiles de latencia (p50/p95/p99) y
recuperación del plan, sobre las 4 campañas válidas de la arquitectura
centralizada. Complementa (no reemplaza) scripts/analisis/graficos_campana_centralizada.py:
fig_tramos con el umbral de RNF-01 se regenera corriendo ESE script con
--marcar-umbral-rnf01 (ver informe de la sesión) -- este módulo solo cubre
fig_rtt_cdf (reemplazada aquí por la CDF de L con percentiles, mismo
nombre de archivo, pedido así explícitamente por el prompt),
tabla_latencia_percentiles.tex y la recuperación del plan.

*** Tamaño de muestra (L por condición): cada condición tiene ~18 paradas.
Con N < 100, el índice de p99 (ceil(0.99*N)-1) cae en el ÚLTIMO valor
ordenado -- p99 coincide, en la práctica, con el máximo observado. Se
reporta así explícitamente ("p99 ≈ máximo; N=18"), no como un percentil
estimado con precisión. Si al juntar condiciones o escenarios el N sube
(p. ej. local = lazo+desvío = 21), se indica el N real usado. ***

El tramo OBU→servidor (t_OBU_srv, de MP_tx/MP_rx) sí tiene suficientes
muestras por condición (~18 misiones x ~17-45 MP cada una) para un p99
real: se agrega como fila aparte cuando N >= 100.

*** Recuperación del plan: NO SE PUDO CALCULAR con los datos disponibles.
Se buscó, en las 75 paradas observadas (72 de las 4 campañas + 3 de la
corrida multi-RSU de M1), un evento ctrl_fase_cambio con motivo=ciclo_normal
registrado DESPUÉS de la liberación/caducidad de cada solicitud -- no
existe ninguno: el controlador solo se re-evalúa cuando algo lo consulta
(ver controller/controller_emulator.py, no hay un timer propio), y nada
vuelve a consultarlo tras liberar una prioridad si no llega una solicitud
nueva (agent/rsu_middleware.py no tiene un watchdog periódico
independiente, solo uno ligado a una cola de despeje activa). Para medir
esto haría falta agregar un poll periódico (p. ej. cada 1-2 s) que seguya
corriendo después de liberar cada prioridad, hasta ver ciclo_normal de
nuevo -- no está en el banco de pruebas actual. ***

Salidas en --salida:
  fig_rtt_cdf.pdf/.png (SOBRESCRITA: ahora es la CDF de L, no RTT_srv --
                        ver docstring de M5.2 en prompt_figuras_cap4.md)
  tabla_latencia_percentiles.tex
  recuperacion_plan.txt

Uso:
    python scripts/analisis/latencia_percentiles.py \\
        --dir resultados/campana/<corrida1> --etiqueta local \\
        --dir resultados/campana/<corrida2> --etiqueta local \\
        --dir resultados/campana/<corrida3> --etiqueta pi-lan \\
        --dir resultados/campana/<corrida4> --etiqueta pi-lan \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import analizar, cargar, percentil  # noqa: E402
from common.events import (  # noqa: E402
    EVT_CTRL_FASE_CAMBIO, EVT_MISION_ARMADA, EVT_MP_RX, EVT_MP_TX,
)

MS = 1_000_000.0
UMBRAL_RNF01_MS = 1000.0
MOTIVOS_LIBERACION = ("liberacion_manual", "caducidad_prioridad")

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
COL1 = 3.5


def extraer_t_obu_srv(eventos: list[dict]) -> list[float]:
    """Replica la logica interna de lazo_centralizado.analizar() para
    t_OBU_srv (MP_rx(servidor) - MP_tx(OBU), mismo seq) -- esa funcion solo
    expone el resumen agregado (resumen(), sin p99), no la lista cruda, que
    es lo que hace falta aca para un p99 real con N>=100."""
    armadas: dict[str, dict] = {}
    for e in eventos:
        if e["tipo_evento"] == EVT_MISION_ARMADA:
            armadas[e["id_solicitud"]] = {"obu_id": e["extra"].get("obu_id")}
    mp_tx_por_obu: dict[tuple[str, int], int] = {}
    for e in eventos:
        if e["tipo_evento"] == EVT_MP_TX and "seq" in e["extra"]:
            mp_tx_por_obu[(e["nodo"], int(e["extra"]["seq"]))] = e["ts_ns"]
    mp_rx_por_mision: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] == EVT_MP_RX:
            mp_rx_por_mision[e["id_solicitud"]].append(e)

    valores = []
    for mision_id, info in armadas.items():
        obu_id = info["obu_id"]
        for mp_rx in mp_rx_por_mision.get(mision_id, []):
            seq = mp_rx["extra"].get("seq")
            if seq is None:
                continue
            t_tx = mp_tx_por_obu.get((obu_id, int(seq)))
            if t_tx is not None:
                valores.append((mp_rx["ts_ns"] - t_tx) / MS)
    return valores


def _unidades_de_proceso(dirs: list[Path]) -> list[Path]:
    """Cada repeticion de una campana (rep_XX/) es un proceso de controlador
    FRESCO, con su propio reloj (ver controller_emulator.py::Controller.__init__,
    self._epoch = time.monotonic() al construirse) -- mezclar las
    repeticiones de una misma carpeta de campana en una sola linea de
    tiempo por nodo (todas usan el mismo RSU_ID="1" en config=local)
    contaminaria la busqueda de recuperacion con el arranque de la
    SIGUIENTE repeticion, no una recuperacion real. Por eso cada rep_XX se
    trata como su propia unidad; una corrida sin rep_XX (p. ej. la de M1,
    un solo proceso por RSU durante toda la corrida) se trata entera."""
    unidades = []
    for d in dirs:
        reps = sorted(p for p in d.glob("rep_*") if p.is_dir())
        unidades.extend(reps if reps else [d])
    return unidades


def buscar_recuperacion_plan(dirs: list[Path]) -> list[dict]:
    """Por cada parada con liberacion/caducidad, busca el PRIMER
    ctrl_fase_cambio posterior (mismo nodo, MISMA unidad de proceso -- ver
    _unidades_de_proceso) con motivo=ciclo_normal. Devuelve una fila por
    parada liberada, con tiempo_recuperacion_s=None si no se encontro."""
    filas = []
    for d in _unidades_de_proceso(dirs):
        eventos = sorted(cargar([d]), key=lambda e: e["ts_ns"])
        por_nodo: dict[str, list[dict]] = defaultdict(list)
        for e in eventos:
            if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO:
                por_nodo[e["nodo"]].append(e)
        for nodo, evs in por_nodo.items():
            for i, e in enumerate(evs):
                if e["extra"].get("motivo") in MOTIVOS_LIBERACION:
                    siguiente = next((e2 for e2 in evs[i + 1:] if e2["extra"].get("motivo") == "ciclo_normal"), None)
                    tiempo_s = (siguiente["ts_ns"] - e["ts_ns"]) / 1e9 if siguiente else None
                    filas.append({"dir": str(d), "nodo": nodo, "id_solicitud": e["id_solicitud"],
                                 "tiempo_recuperacion_s": tiempo_s})
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--etiqueta", action="append", required=True)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    if len(args.dir) != len(args.etiqueta):
        raise SystemExit("--dir y --etiqueta deben venir en pares")
    grupos: dict[str, list[Path]] = defaultdict(list)
    for d, et in zip(args.dir, args.etiqueta):
        grupos[et].append(Path(d))

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    resultados = {}
    for etq, dirs in grupos.items():
        eventos = cargar(dirs)
        _, filas_parada, _ = analizar(eventos)
        l_vals = [f["L_ms"] for f in filas_parada if f.get("L_ms") is not None]
        t_obu_srv = extraer_t_obu_srv(eventos)
        resultados[etq] = {"L_ms": l_vals, "t_obu_srv_ms": t_obu_srv}

    # --- fig_rtt_cdf.pdf/.png: CDF de L con p50/p95/p99 + linea RNF-01 ----
    max_l = max((max(r["L_ms"]) for r in resultados.values() if r["L_ms"]), default=0.0)
    usar_log = max_l > 0 and UMBRAL_RNF01_MS > 3 * max_l
    fig, ax = plt.subplots(figsize=(COL1, 2.6))
    for (etq, r), color in zip(resultados.items(), PALETA):
        vals = sorted(r["L_ms"])
        if not vals:
            continue
        n = len(vals)
        ys = [(i + 1) / n for i in range(n)]
        ax.step(vals, ys, where="post", color=color, label=f"{etq} (n={n})")
        for q, ls in ((50, ":"), (95, "--"), (99, "-.")):
            v = percentil(vals, q)
            ax.axvline(v, color=color, lw=0.8, ls=ls, alpha=0.7)
    ax.axvline(UMBRAL_RNF01_MS, color="#0b0b0b", lw=1.2, ls="-")
    ax.text(UMBRAL_RNF01_MS, 0.02, " RNF-01\n 1000 ms", fontsize=6, va="bottom", ha="right")
    ax.set_xlabel("L (ms)")
    ax.set_ylabel("Probabilidad acumulada")
    ax.set_ylim(0, 1.02)
    titulo = "CDF de L con p50 (:), p95 (--), p99 (-.)"
    if usar_log:
        # El umbral de RNF-01 es >> el L observado (ms vs. 1000 ms): en
        # escala lineal la CDF entera queda aplastada contra el eje
        # izquierdo. Escala log en X para que siga siendo legible (ver
        # prompt_figuras_cap4.md, M5.1).
        ax.set_xscale("log")
        ax.set_xlim(left=max(0.1, min(min(r["L_ms"], default=1.0) for r in resultados.values() if r["L_ms"]) * 0.5))
        titulo += " -- escala log: el margen a RNF-01 es grande"
    ax.set_title(titulo, loc="left")
    ax.legend(loc="center right", frameon=False, fontsize=6.5)
    ax.grid(True)
    fig.savefig(salida / "fig_rtt_cdf.pdf", bbox_inches="tight")
    fig.savefig(salida / "fig_rtt_cdf.png", bbox_inches="tight")
    plt.close(fig)

    # --- tabla_latencia_percentiles.tex -------------------------------------
    lineas = [
        "\\begin{table}[H]", "\\centering",
        "\\caption{Percentiles de latencia por condición. Para $L$ (N $\\approx$ 18 por condición), "
        "p99 coincide en la práctica con el máximo observado (N $<$ 100: no es un percentil estimado "
        "con precisión, ver texto). El tramo OBU$\\to$servidor ($t_{OBU\\to srv}$) tiene N $\\geq$ 100 "
        "(todas las posiciones MP de la campaña), así que su p99 sí es un percentil real.}",
        "\\label{tab:latencia_percentiles}", "\\small",
        "\\begin{tabular}{llrrrrl}", "\\toprule",
        "\\textbf{Métrica} & \\textbf{Condición} & \\textbf{N} & \\textbf{p50} & \\textbf{p95} & "
        "\\textbf{p99} & \\textbf{Máx.} \\\\", "\\midrule",
    ]
    for etq, r in resultados.items():
        vals = r["L_ms"]
        if vals:
            n = len(vals)
            nota = " (p99 $\\approx$ máx., N$<$100)" if n < 100 else ""
            lineas.append(f"$L${nota} & {etq} & {n} & {percentil(vals,50):.2f} & {percentil(vals,95):.2f} & "
                          f"{percentil(vals,99):.2f} & {max(vals):.2f} \\\\")
    for etq, r in resultados.items():
        vals = r["t_obu_srv_ms"]
        if vals:
            n = len(vals)
            lineas.append(f"$t_{{OBU\\to srv}}$ & {etq} & {n} & {percentil(vals,50):.2f} & "
                          f"{percentil(vals,95):.2f} & {percentil(vals,99):.2f} & {max(vals):.2f} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_latencia_percentiles.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # --- recuperacion_plan.txt ----------------------------------------------
    todas_dirs = [d for dirs in grupos.values() for d in dirs]
    filas_rec = buscar_recuperacion_plan(todas_dirs)
    medidos = [f["tiempo_recuperacion_s"] for f in filas_rec if f["tiempo_recuperacion_s"] is not None]
    if medidos:
        texto = (f"Recuperación del plan: {len(medidos)}/{len(filas_rec)} paradas liberadas con un "
                f"ciclo_normal posterior observado. Mediana={percentil(medidos,50):.2f} s, "
                f"p95={percentil(medidos,95):.2f} s.")
    else:
        texto = (
            f"Recuperación del plan: NO SE PUDO CALCULAR. Se revisaron {len(filas_rec)} paradas con "
            "liberación/caducidad de prioridad (72 de las 4 campañas + 3 de la corrida multi-RSU de "
            "M1) y en NINGUNA hay un evento ctrl_fase_cambio posterior con motivo=ciclo_normal: el "
            "controlador emulado solo se re-evalúa cuando algo lo consulta (sin timer propio, ver "
            "controller/controller_emulator.py), y nada vuelve a consultarlo tras liberar una "
            "prioridad si no llega una solicitud nueva (agent/rsu_middleware.py no tiene un watchdog "
            "periódico independiente de una cola de despeje activa). Para medir esto haría falta "
            "agregar un poll periódico que siga corriendo después de cada liberación hasta ver "
            "ciclo_normal de nuevo -- no está en el banco de pruebas actual. No se aproxima con un "
            "valor inventado."
        )
    (salida / "recuperacion_plan.txt").write_text(texto + "\n", encoding="utf-8")

    print(f"Salidas en {salida}: fig_rtt_cdf (.pdf/.png, CDF de L), tabla_latencia_percentiles.tex, "
         f"recuperacion_plan.txt")
    print(texto)


if __name__ == "__main__":
    main()
