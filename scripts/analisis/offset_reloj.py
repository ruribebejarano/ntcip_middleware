#!/usr/bin/env python3
"""M6 (prompt_figuras_cap4.md): offset de reloj de la RSU respecto a su
referencia NTP (no respecto al servidor), por corrida (inicio y fin de cada una), a partir de la cota de
reloj que ya guarda scripts/campanas/lazo_centralizado.py en config.json
(reloj_pi_inicio/reloj_pi_fin: salida combinada de 'chronyc tracking' +
'chronyc sources -v' en la Pi, capturada por scripts/pi.sh clock).

*** "Por RSU": en las 4 campañas válidas (y en las dos de config=pi-lan en
particular, las únicas con un reloj distinto al del servidor) solo hay UNA
RSU (RSU_ID=1) -- "por RSU y condición" se reduce aquí a "por corrida",
no hay varias RSU físicas que comparar. La corrida multi-RSU de M1
(3 RSU) fue config=local (todo en la misma laptop, sin Raspberry Pi): no
aporta un offset de reloj real, por eso NO se incluye en esta figura
(incluirla sería mostrar un offset de 0 ms que no mide nada). ***

El OFFSET (con signo, de 'System time ... seconds slow/fast of NTP time')
es la MEJOR ESTIMACIÓN puntual de chrony, no la cota de error -- se
grafican ambos: el punto es el offset, la barra de error es la cota
(Root dispersion + Root delay/2, igual que cota_reloj_pi_ms() en
lazo_centralizado.py). Las corridas donde RNF-01 quedó "no evaluable"
(chrony perdió sincronización NTP en algún punto, ver
reloj_pi_sincronizado()) se marcan aparte: ese "offset" final es el último
valor bueno que chrony recuerda, CONGELADO, no una medición confiable del
momento -- graficarlo como si fuera un punto más sería engañoso.

Salidas en --salida:
  fig_offset_reloj.pdf/.png
  nota_offset_reloj.txt (conversión a distancia + umbral tolerable frente a RF8)

Uso:
    python scripts/analisis/offset_reloj.py \\
        --dir resultados/campana/<corrida_pi-lan_1> --dir resultados/campana/<corrida_pi-lan_2> \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
from lazo_centralizado import cota_reloj_pi_ms, reloj_pi_sincronizado  # noqa: E402

ANTICIPACION_MINIMA_S = 8.0  # RF8

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 7.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.linewidth": 0.6,
    "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e",
    "ytick.color": "#52514e", "grid.color": "#e4e3df", "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 300,
    "figure.dpi": 150, "lines.linewidth": 1.4,
})
AZUL, NARANJA, INK2 = "#2a78d6", "#eb6834", "#52514e"
COL1 = 3.5


def offset_ms(texto_reloj: str | None) -> float | None:
    """Offset con signo (ms), de 'System time : X seconds slow/fast of NTP
    time' en el texto de 'chronyc tracking' -- positivo = reloj de la RSU
    ADELANTADO respecto a NTP (fast), negativo = ATRASADO (slow)."""
    if not texto_reloj:
        return None
    m = re.search(r"System time\s*:\s*([\d.]+)\s*seconds\s*(slow|fast)\s*of NTP time", texto_reloj)
    if not m:
        return None
    signo = 1.0 if m.group(2) == "fast" else -1.0
    return signo * float(m.group(1)) * 1000.0


def distancia_por_error_s(error_s: float, velocidad_kmh: float) -> float:
    """Distancia (m) recorrida en `error_s` a `velocidad_kmh` -- eq. simple
    v*t, con v convertida a m/s."""
    return velocidad_kmh * (1000.0 / 3600.0) * error_s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True, help="corridas config=pi-lan (con reloj_pi_inicio/fin en config.json)")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    puntos = []  # (etiqueta, offset_ms, cota_ms, evaluable)
    for d in args.dir:
        cfg = json.loads((Path(d) / "config.json").read_text(encoding="utf-8"))
        nombre = f"{cfg['escenario']}"
        for momento in ("inicio", "fin"):
            texto = cfg.get(f"reloj_pi_{momento}")
            off = offset_ms(texto)
            cota = cota_reloj_pi_ms(texto)
            evaluable = reloj_pi_sincronizado(texto)
            if off is not None:
                puntos.append((f"{nombre}\n({momento})", off, cota, evaluable))

    fig, ax = plt.subplots(figsize=(COL1, 2.8))
    xs = range(len(puntos))
    for i, (etq, off, cota, evaluable) in enumerate(puntos):
        color = AZUL if evaluable else "#b91c1c"
        marker = "o" if evaluable else "x"
        # Sin barra en los no evaluables: su "cota" es el centinela de chrony
        # (1,5 s), no una medición, y aplastaría la escala de los demás puntos.
        if cota and evaluable:
            ax.errorbar(i, off, yerr=cota, fmt=marker, color=color, ecolor=INK2, elinewidth=0.8,
                       capsize=3, ms=6)
        else:
            ax.plot(i, off, marker=marker, color=color, ms=6, ls="none")
    ax.axhline(0, color=INK2, lw=0.6)
    ax.set_xticks(list(xs), [p[0] for p in puntos], fontsize=7)
    # El offset es frente a la referencia NTP de chrony, no frente al
    # servidor (la laptop no se mide aquí). Sin título: lo pone el \caption.
    ax.set_ylabel("Offset del reloj de la RSU\nfrente a NTP (ms)")
    ax.grid(True, axis="y")
    leyenda = [
        plt.Line2D([0], [0], marker="o", color=AZUL, lw=0, label="Evaluable (chrony sincronizado)"),
        plt.Line2D([0], [0], marker="x", color="#b91c1c", lw=0, label="RNF-01 no evaluable (chrony perdió sync.)"),
    ]
    ax.legend(handles=leyenda, loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False, fontsize=6)
    fig.savefig(salida / "fig_offset_reloj.pdf", bbox_inches="tight")
    fig.savefig(salida / "fig_offset_reloj.png", bbox_inches="tight")
    plt.close(fig)

    # --- nota_offset_reloj.txt ----------------------------------------------
    offs_evaluables = [abs(p[1]) for p in puntos if p[3] and p[1] is not None]
    cotas_evaluables = [p[2] for p in puntos if p[3] and p[2] is not None]
    d_50 = distancia_por_error_s(1.0, 50.0)
    d_36 = distancia_por_error_s(1.0, 36.0)  # velocidad real de las trayectorias de campaña (ver trayectoria_obu-*.csv)
    lineas = [
        f"1 s de error de reloj equivale a {d_50:.1f} m a 50 km/h (velocidad de referencia pedida), "
        f"o a {d_36:.1f} m a 36 km/h (la velocidad real usada en las trayectorias de estas campañas, "
        "ver resultados/campana/*/rep_*/trayectoria_obu-*.csv).",
        "",
    ]
    if offs_evaluables:
        peor = max(offs_evaluables)
        peor_cota = max(cotas_evaluables) if cotas_evaluables else None
        lineas.append(f"Offset observado (|System time|) en las corridas evaluables: máximo {peor:.3f} ms "
                     f"-> {distancia_por_error_s(peor/1000.0, 50.0)*1000:.3f} mm a 50 km/h (despreciable).")
        if peor_cota:
            lineas.append(f"Cota de error (Root dispersion + Root delay/2) en esas corridas: hasta "
                         f"{peor_cota:.1f} ms -> {distancia_por_error_s(peor_cota/1000.0, 50.0)*100:.2f} cm a 50 km/h.")
    n_no_evaluable = sum(1 for p in puntos if not p[3])
    lineas.append(f"\nCorridas con RNF-01 'no evaluable' (chrony perdió sincronización NTP en algún punto): "
                 f"{n_no_evaluable} de {len(puntos)} puntos (inicio/fin) revisados.")
    error_s_para_1m_50kmh = 1.0 / (50.0 * 1000.0 / 3600.0)
    lineas.append(
        "\nError de reloj tolerable frente a RF8 (anticipación mínima 8 s): a 50 km/h hacen falta "
        f"~{error_s_para_1m_50kmh*1000:.0f} ms de error de reloj para desplazar la posición equivalente "
        "en 1 m (irrelevante frente a los ~40 m de radio de detección de la RSU, RADIO_DETECCION_RSU_M en "
        "servidor/rutas.py); incluso la cota de error medida aquí (decenas de ms en el peor caso evaluable) "
        "es varios órdenes de magnitud menor que el margen de 8 s de RF8 -- el error de reloj de chrony NO "
        "es, en esta evidencia, un riesgo real para cumplir RF8. El riesgo real es perder la sincronización "
        "NTP por completo (como en desvio_pi-lan), que invalida la cota, no que la cota en sí sea grande."
    )
    (salida / "nota_offset_reloj.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"Salidas en {salida}: fig_offset_reloj (.pdf/.png), nota_offset_reloj.txt")
    print(f"{len(puntos)} puntos (inicio/fin de {len(args.dir)} corridas), {n_no_evaluable} no evaluables")


if __name__ == "__main__":
    main()
