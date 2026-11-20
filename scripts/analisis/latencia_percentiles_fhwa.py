#!/usr/bin/env python3
"""OE5: curva de la latencia L por percentil (60 % a 100 %), por sesión de la
campaña 4G, en el formato del informe final de la FHWA (FHWA-JPO-20-812,
figuras 17 y 18), para comparar las colas de la distribución.

Reusa el cálculo por mensaje de scripts/analisis/recalculo_por_mensaje.py
(L_corr = ida corregida por el desfase de relojes + retención en la RSU), sin
descartar valores atípicos: a diferencia de la FHWA, que eliminó entre 6,05 %
y 12,56 % de sus datos celulares antes de calcular sus percentiles, aquí la
parte alta de la curva incluye todos los mensajes.

Como referencia se dibujan la mediana (36,46 ms) y el máximo (68,00 ms) que la
FHWA reporta para la red celular en su tabla 6, ambos después de descartar
atípicos.

Uso:
    python scripts/analisis/latencia_percentiles_fhwa.py --salida resultados/campana/_campana_nube
    python scripts/analisis/latencia_percentiles_fhwa.py --salida ... \\
        --sesion "Nube, S3 (tarde)=20261120-1700xx_lazo_pi-4g,20261120-1730xx_desvio_pi-4g"

Escribe fig_latencia_percentiles_fhwa.{pdf,png} y latencia_percentiles_fhwa.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import recalculo_por_mensaje as rpm  # noqa: E402

SESIONES = {  # mismas corridas que scripts/analisis/campana_nube.py
    "Laptop (3-nov)": ["20261103-232704_lazo_pi-4g", "20261103-235034_desvio_pi-4g"],
    "Nube, S1 (15-nov)": ["20261115-222810_lazo_pi-4g", "20261115-233321_desvio_pi-4g"],
    "Nube, S2 (20-nov, mañana)": ["20261120-131856_lazo_pi-4g", "20261120-135406_desvio_pi-4g"],
}
PERCENTILES = np.arange(60.0, 100.0 + 1e-9, 0.5)
TABLA_P = (60, 70, 80, 90, 95, 99, 100)
FHWA_CELULAR_MS = {"mediana": 36.46, "maximo": 68.00}  # FHWA-JPO-20-812, tabla 6
ESTILOS = [("0.0", "-", "o"), ("0.35", "--", "s"), ("0.55", "-.", "^"), ("0.7", ":", "D")]


def coma(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def latencias(corridas: list[str], centro) -> list[float]:
    valores: list[float] = []
    for d in corridas:
        reps = sorted(glob.glob(str(rpm.C / d / "rep_*")))
        if not reps:
            sys.exit(f"No hay repeticiones en {rpm.C / d}")
        for rep in reps:
            valores += rpm.analizar_rep(Path(rep), centro)["L_corr"]
    return valores


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True)
    ap.add_argument("--sesion", action="append", default=[],
                    help="'etiqueta=corrida_lazo,corrida_desvio' (carpetas en resultados/campana)")
    args = ap.parse_args()

    sesiones = dict(SESIONES)
    for s in args.sesion:
        etiqueta, dirs = s.split("=", 1)
        sesiones[etiqueta] = [d.strip() for d in dirs.split(",") if d.strip()]

    salida = Path(args.salida) if Path(args.salida).is_absolute() else RAIZ / args.salida
    salida.mkdir(parents=True, exist_ok=True)
    reg = json.load(open(rpm.REGISTRO, encoding="utf-8"))["rsu"][0]["centro"]
    centro = (reg["lat"], reg["lon"])

    resultado = {"fuente_referencia": "FHWA-JPO-20-812, tabla 6 (celular, tras descartar atípicos)",
                 "fhwa_celular_ms": FHWA_CELULAR_MS, "sesiones": {}}
    curvas = {}
    for nombre, corridas in sesiones.items():
        v = np.asarray(latencias(corridas, centro), dtype=float)
        curvas[nombre] = np.percentile(v, PERCENTILES)
        resultado["sesiones"][nombre] = {
            "corridas": corridas, "n": int(v.size),
            "percentiles_ms": {str(p): round(float(np.percentile(v, p)), 1) for p in TABLA_P},
        }
        print(nombre, "n =", v.size, " ".join(
            f"p{p}={coma(float(np.percentile(v, p)))}" for p in TABLA_P))

    (salida / "latencia_percentiles_fhwa.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "font.size": 9})
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    for (nombre, y), (color, ls, mk) in zip(curvas.items(), ESTILOS):
        n = resultado["sesiones"][nombre]["n"]
        ax.plot(PERCENTILES, y, color=color, ls=ls, lw=1.3, marker=mk, markevery=10, ms=3.5,
                label=f"{nombre} (n = {n})")
    for clave, txt, ls in (("maximo", "FHWA, celular: máximo tras descartar atípicos", (0, (1, 1))),
                           ("mediana", "FHWA, celular: mediana", (0, (4, 2)))):
        y = FHWA_CELULAR_MS[clave]
        ax.axhline(y, color="0.45", ls=ls, lw=0.9)
        ax.text(60.4, y * 1.06, f"{txt} ({coma(y, 2)} ms)", fontsize=7.5, color="0.25", va="bottom")
    ax.set_yscale("log")
    ax.set_xlim(60, 100)
    ax.set_xticks(range(60, 101, 5))
    ax.set_xlabel("Percentil (%)")
    ax.set_ylabel("Latencia $L$ (ms, escala logarítmica)")
    ax.grid(alpha=0.3, which="both", lw=0.5)
    ax.legend(loc="upper left", fontsize=7.5, frameon=False)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(salida / f"fig_latencia_percentiles_fhwa.{ext}", dpi=200)
    plt.close(fig)
    print(f"Figura: {salida / 'fig_latencia_percentiles_fhwa.pdf'}")


if __name__ == "__main__":
    main()
