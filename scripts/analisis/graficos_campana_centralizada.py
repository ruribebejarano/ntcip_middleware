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
  fig_tramos        Desglose por tramo de la arquitectura centralizada
                     (t_srv, t_srv->RSU, t_RSU, retorno -- este ultimo
                     derivado = RTT_srv - L) por etiqueta (caja + puntos);
                     los tramos de dos relojes (t_srv->RSU, retorno) se
                     dibujan solo si comparten reloj (config=local): con la
                     RSU real salen negativos por el desfase laptop/Pi, ver
                     _cruza_reloj. L en si
                     (= t_srv_RSU + t_RSU) no se grafica aca: ya esta en
                     tabla_latencia.tex con su cota de reloj.
  fig_comparacion   RTT_srv y t_RSU lado a lado, una caja por etiqueta
                     (la figura "comparativa por configuración" pedida)
  tabla_latencia.tex tabla LaTeX, una fila por métrica y etiqueta (n, mediana, p95, máx)
  notas_figuras.txt  texto largo (nota de la campaña, cota de reloj) para
                     copiar al \\caption de LaTeX de cada figura -- NO se
                     incrusta en los PNG (se superponía con las etiquetas
                     del eje x, ver docs/bitacora/2026-10-28_*.md).
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
from lazo_centralizado import (  # noqa: E402
    analizar, cargar, cota_reloj_pi_ms_de_dirs, percentil, reloj_pi_sincronizado_de_dirs,
)

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


def _cruza_reloj(g: dict) -> bool:
    """True si la RSU no comparte el reloj del servidor (cota != 0, o sin
    caracterizar). Las corridas del 2026-11-04 dan L negativa en el 100 % de
    las paradas de pi-lan (mediana -55 ms con RTT_srv de 11 ms): el desfase
    laptop/Pi (~60 ms, w32time sin caracterizar) supera al tramo medido, así
    que L, t_srv->RSU, retorno y t_verde no se reportan en esas etiquetas.
    Queda RTT_srv (un reloj), que acota L: la decisión precede a M2."""
    return g.get("cota_reloj_pi_ms") != 0


def _valores_de(g: dict, clave: str) -> list[float]:
    return g.get(f"_{clave}_valores", [])


#: desglose por tramo de la arquitectura centralizada (ver docstring de
#: lazo_centralizado.py y servidor/gestor_mision.py): t_srv (cola en el
#: servidor antes de M1, un reloj), t_srv_RSU (red servidor->RSU, dos
#: relojes), t_RSU (procesamiento en la RSU, un reloj), retorno (RSU->
#: servidor hasta M2_rx, derivado = RTT_srv - L, dos relojes porque L ya
#: incluye el tramo de dos relojes t_srv_RSU). L (= t_srv_RSU + t_RSU) no
#: se repite aca: ya se reporta en tabla_latencia.tex con su cota.
TRAMOS = [("t_srv_ms", "$t_{srv}$", False), ("t_srv_RSU_ms", "$t_{srv\\to RSU}$", True),
          ("t_RSU_ms", "$t_{RSU}$", False), ("retorno_ms", "$t_{retorno}$", True)]


#: RNF-01: umbral de L (prompt_figuras_cap4.md, M5.1). No se grafica L en
#: si en fig_tramos (ver TRAMOS arriba), pero la linea de umbral se deja
#: igual como referencia visual de cuanto margen hay en cada tramo
#: individual frente al presupuesto total.
UMBRAL_RNF01_MS = 1000.0


def fig_tramos(ax, resultados: dict[str, dict], marcar_umbral_rnf01: bool = False):
    etiquetas = list(resultados)
    pos = 1
    xticks, xlabels = [], []
    max_valor = 0.0
    for metrica, _, es_dos_relojes in TRAMOS:
        for etq in etiquetas:
            vals = _valores_de(resultados[etq], metrica)
            if vals and not (es_dos_relojes and _cruza_reloj(resultados[etq])):
                max_valor = max(max_valor, max(vals))
    for metrica, nombre, es_dos_relojes in TRAMOS:
        for etq, color in zip(etiquetas, PALETA):
            g = resultados[etq]
            vals = _valores_de(g, metrica)
            # Tramo de dos relojes con la RSU real: no se dibuja (_cruza_reloj).
            if es_dos_relojes and _cruza_reloj(g):
                continue
            if vals:
                jit = [pos + 0.12 * math.sin(i * 2.399) for i in range(len(vals))]
                ax.scatter(jit, vals, s=9, color=color, alpha=0.85, lw=0, zorder=3)
                ax.boxplot([vals], positions=[pos], widths=0.5, showfliers=False,
                          patch_artist=True,
                          boxprops=dict(facecolor=color + "33", edgecolor=color, lw=0.7),
                          medianprops=dict(color="#0b0b0b", lw=1.1), whiskerprops=dict(color=INK2, lw=0.7),
                          capprops=dict(color=INK2, lw=0.7))
            xticks.append(pos)
            xlabels.append(f"{nombre}\n{etq}")
            pos += 1
        pos += 0.6
    ax.set_xticks(xticks, xlabels, fontsize=6.5)
    ax.set_ylabel("Latencia (ms)")
    titulo = "(b) Desglose por tramo (arquitectura centralizada)"
    if marcar_umbral_rnf01:
        # El umbral de RNF-01 (1000 ms) es L completo (= t_srv_RSU + t_RSU),
        # no un tramo individual -- se marca igual como referencia de
        # cuanto margen le queda a CADA tramo por separado frente al
        # presupuesto total. Si los tramos reales son >> 3x mas chicos que
        # el umbral, una escala lineal hasta 1000 ms los aplastaria a una
        # linea en la base (ilegible): se usa escala log en ese caso, y se
        # dice en el titulo/pie de figura.
        if max_valor > 0 and UMBRAL_RNF01_MS > 3 * max_valor:
            ax.set_yscale("log")
            ax.set_ylim(bottom=max(0.01, max_valor * 0.01))
            titulo += " -- escala log: el margen a RNF-01 es grande"
        else:
            ax.set_ylim(bottom=0, top=UMBRAL_RNF01_MS * 1.08)
        ax.axhline(UMBRAL_RNF01_MS, color="#0b0b0b", lw=1.0, ls="--", zorder=1)
        ax.text(ax.get_xlim()[1], UMBRAL_RNF01_MS, " RNF-01 (1000 ms)", fontsize=6.5, va="bottom", ha="right")
        margen = UMBRAL_RNF01_MS - max_valor
        ax.annotate(f"margen al umbral (peor tramo medido): {margen:.1f} ms",
                   (0.01, 0.02), xycoords="axes fraction", fontsize=6, color="#52514e")
    else:
        ax.set_ylim(bottom=0)
    ax.set_title(titulo, loc="left")
    ax.grid(True, axis="y")


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


#: métricas que cruzan el reloj de la laptop y el de la Pi (ver
#: docs/MEDICION_LATENCIA.md 8.4): llevan la cota de error de reloj de su
#: etiqueta en la tabla, no un valor puntual sin incertidumbre.
#: t_OBU_srv no entra: la OBU emulada corre en la misma laptop que el servidor.
METRICAS_DOS_RELOJES = {"L_ms", "anticipacion_real_s"}
#: no se reportan si la RSU no comparte el reloj del servidor (_cruza_reloj).
METRICAS_SOLO_MISMO_RELOJ = {"L_ms", "t_verde_ms"}


def _cota_para_tabla(g: dict, clave: str) -> str:
    if clave not in METRICAS_DOS_RELOJES:
        return "--"
    if not g.get("reloj_pi_sincronizado", True):
        return "no sincronizado"
    cota = g.get("cota_reloj_pi_ms")
    if cota is None:
        return "sin caracterizar"
    if cota == 0:
        return "0 (mismo reloj)"
    return f"{cota / 1000.0:.3f} s" if clave == "anticipacion_real_s" else f"{cota:.1f} ms"


def tabla_latex(resultados: dict[str, dict], salida: Path, nota: str):
    metricas = [("RTT\\_srv", "RTT_srv_ms", "ms"), ("$t_{RSU}$", "t_RSU_ms", "ms"),
                ("$t_{OBU\\to srv}$", "t_OBU_srv_ms", "ms"), ("$L$ (RNF-01)", "L_ms", "ms"),
                ("Anticipación real", "anticipacion_real_s", "s")]
    lineas = ["\\begin{table}[H]", "\\centering",
              "\\caption{Latencia del lazo, escenarios de lazo y desvío combinados por condición de "
              "enlace. " + nota + " Con la RSU real no se reporta $L$, porque cruza el reloj de dos "
              "equipos y el desfase entre ellos supera al tramo medido: su cota superior es "
              "RTT\\_srv, medido con un solo reloj. La anticipación real lleva la cota de error de "
              "reloj del lado de la Raspberry Pi.}",
              "\\label{tab:latencia_campana_centralizada}", "\\small",
              "\\begin{tabular}{llrrrrll}", "\\toprule",
              "\\textbf{Métrica} & \\textbf{Config.} & \\textbf{n} & \\textbf{Mediana} & "
              "\\textbf{p95} & \\textbf{Máx.} & \\textbf{Unidad} & \\textbf{Cota reloj (Pi)} \\\\",
              "\\midrule"]
    for nombre, clave, unidad in metricas:
        for etq, g in resultados.items():
            if clave in METRICAS_SOLO_MISMO_RELOJ and _cruza_reloj(g):
                continue
            m = g.get(clave, {})
            if m.get("n"):
                lineas.append(f"{nombre} & {etq} & {m['n']} & {m['mediana']:.2f} & {m['p95']:.2f} & "
                              f"{m['max']:.2f} & {unidad} & {_cota_para_tabla(g, clave)} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_latencia.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


#: etiqueta de presentación para cada condición de llegada (ver
#: scripts/campanas/lazo_centralizado.py y
#: scripts/analisis/lazo_centralizado.py::CONDICIONES_LLEGADA).
NOMBRE_CONDICION = {"verde": "verde", "ambar_todo_rojo": "ámbar/todo rojo", "rojo_general": "rojo"}


def tabla_condicion_latex(resultados: dict[str, dict], salida: Path, nota: str):
    """Tabla LaTeX con las métricas de latencia desglosadas por CONDICIÓN
    de llegada (verde/ámbar-todo_rojo/rojo), una por etiqueta -- pedida
    tras la campaña con cuotas adaptativas del 2026-10-29 (antes del
    arreglo del controlador emulado, el 100 % de las decisiones caía en
    "ámbar/todo rojo", así que este desglose no tenía sentido -- ver
    docs/bitacora/2026-10-29_fase-controlador-emulado.md)."""
    metricas = [("RTT\\_srv", "RTT_srv_ms", "ms"), ("$t_{RSU}$", "t_RSU_ms", "ms"),
                ("$L$ (RNF-01)", "L_ms", "ms"), ("$t_{verde}$", "t_verde_ms", "ms"),
                ("$T_{desp}$ (RF-04)", "T_desp_ms", "ms"), ("Anticipación real (RF-11)", "anticipacion_real_s", "s")]
    lineas = ["\\begin{table}[H]", "\\centering",
              "\\caption{Latencia del lazo por condición de llegada: la fase del controlador en el "
              "momento de la decisión (verde, ámbar/todo rojo --tratadas juntas por ser ambas no "
              "interrumpibles-- o rojo general). Escenarios de lazo y desvío combinados por condición "
              "de enlace. $L$ y $t_{verde}$ se reportan solo en la condición local, "
              "donde no cruzan el reloj de dos equipos.}",
              "\\label{tab:latencia_por_condicion}", "\\small",
              "\\begin{tabular}{lllrrrl}", "\\toprule",
              "\\textbf{Métrica} & \\textbf{Config.} & \\textbf{Condición} & \\textbf{n} & "
              "\\textbf{Mediana} & \\textbf{p95} & \\textbf{Unidad} \\\\",
              "\\midrule"]
    for nombre, clave, unidad in metricas:
        for etq, g in resultados.items():
            if clave in METRICAS_SOLO_MISMO_RELOJ and _cruza_reloj(g):
                continue
            for cond in ("verde", "ambar_todo_rojo", "rojo_general"):
                m = g.get("por_condicion_llegada", {}).get(cond, {}).get(clave, {})
                if m.get("n"):
                    lineas.append(f"{nombre} & {etq} & {NOMBRE_CONDICION[cond]} & {m['n']} & "
                                  f"{m['mediana']:.2f} & {m['p95']:.2f} & {unidad} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_condicion.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _recolectar_valores(filas: list[dict], clave: str) -> list[float]:
    return [f[clave] for f in filas if f.get(clave) is not None]


def _recolectar_retorno(filas: list[dict]) -> list[float]:
    """Tramo RSU->servidor (hasta M2_rx), derivado por parada:
    retorno = RTT_srv - L (ambos ya calculados en la misma fila por
    lazo_centralizado.py::analizar()). Dos relojes, igual que L (RTT_srv
    es de un solo reloj, pero L arrastra el tramo t_srv_RSU)."""
    vals = []
    for f in filas:
        rtt, l = f.get("RTT_srv_ms"), f.get("L_ms")
        if rtt is not None and l is not None:
            vals.append(rtt - l)
    return vals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--etiqueta", action="append", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--nota", default="")
    ap.add_argument("--marcar-umbral-rnf01", action="store_true",
                    help="agrega la linea de 1000 ms (RNF-01) a fig_tramos -- M5, prompt_figuras_cap4.md")
    args = ap.parse_args()

    grupos = _grupos(args.dir, args.etiqueta)
    resultados: dict[str, dict] = {}
    for etq, dirs in grupos.items():
        cota_reloj_ms = cota_reloj_pi_ms_de_dirs(dirs)
        reloj_sincronizado = reloj_pi_sincronizado_de_dirs(dirs)
        _, filas_parada, g = analizar(cargar(dirs), cota_reloj_ms, reloj_sincronizado)
        # t_OBU_srv vive en filas_mision, no filas_parada; se omite de los
        # box plots comparativos por simplicidad (queda igual en lazo_resumen.json).
        for clave in ("RTT_srv_ms", "t_srv_ms", "t_srv_RSU_ms", "t_RSU_ms", "L_ms", "anticipacion_real_s"):
            g[f"_{clave}_valores"] = _recolectar_valores(filas_parada, clave)
        g["_retorno_ms_valores"] = _recolectar_retorno(filas_parada)
        resultados[etq] = g

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(COL1, 2.4))
    fig_rtt_cdf(ax, resultados)
    guardar(fig, salida, "fig_rtt_cdf")

    fig, ax = plt.subplots(figsize=(COL2, 2.9))
    fig_tramos(ax, resultados, marcar_umbral_rnf01=args.marcar_umbral_rnf01)
    guardar(fig, salida, "fig_tramos")

    fig, ax = plt.subplots(figsize=(COL2, 2.6))
    fig_comparacion(ax, resultados)
    guardar(fig, salida, "fig_comparacion")

    # El texto largo (nota de la campaña, cota de reloj) NO se incrusta en
    # el PNG: con fig_comparacion se superponía con las etiquetas del eje x
    # (ver docs/bitacora). Va en el \caption de LaTeX; se deja aca como
    # texto listo para copiar.
    notas = []
    if args.nota:
        notas.append(f"fig_comparacion / tabla_latencia: {args.nota}")
    if notas:
        (salida / "notas_figuras.txt").write_text(
            "Texto para el \\caption de LaTeX de cada figura (no está incrustado en el PNG):\n\n"
            + "\n\n".join(notas) + "\n", encoding="utf-8")

    tabla_latex(resultados, salida, args.nota)
    tabla_condicion_latex(resultados, salida, args.nota)
    print(f"Figuras en {salida}: fig_rtt_cdf, fig_tramos, fig_comparacion (.pdf y .png)")
    print(f"Tabla LaTeX: {salida / 'tabla_latencia.tex'}, {salida / 'tabla_condicion.tex'}")
    for etq, g in resultados.items():
        rtt = g["RTT_srv_ms"]
        if rtt.get("n"):
            texto = f"mediana {rtt['mediana']:.2f} ms, p95 {rtt['p95']:.2f} ms"
        else:
            texto = "sin datos"
        print(f"  [{etq}] RTT_srv: {texto}")
        a = g["anticipacion_real_s"]
        if a.get("n"):
            print(f"  [{etq}] Anticipación real (RF8): n={a['n']}, mediana={a['mediana']:.2f} s, "
                  f"p95={a['p95']:.2f} s (cota reloj Pi: {_cota_para_tabla(g, 'anticipacion_real_s')})")
        else:
            print(f"  [{etq}] Anticipación real (RF8): sin datos (ningún M3_tx motivo=cruce con un "
                  f"verde previo detectado en las repeticiones de esta etiqueta)")


if __name__ == "__main__":
    main()
