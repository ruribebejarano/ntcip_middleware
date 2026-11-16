#!/usr/bin/env python3
"""Campaña 4G con el broker y el servidor en la nube (Oracle Cloud,
Santiago; docs/CAMPANA_4G_NUBE.md) frente a la campaña 4G del 2026-11-03
(broker y servidor en la laptop, alcanzados por la red superpuesta).

Reusa scripts/analisis/recalculo_por_mensaje.py (mismas métricas por
mensaje, mismo bootstrap) con otras condiciones, y escribe además una tabla
compacta para la tesis.

Uso:
    python scripts/analisis/campana_nube.py --salida resultados/campana/_campana_nube
    python scripts/analisis/campana_nube.py --salida ... \\
        --sesion "S2=20261117-083000_lazo_pi-4g,20261117-090500_desvio_pi-4g"

Sin --sesion, compara la referencia del 2026-11-03 con la sesión 1
(2026-11-15). Cada --sesion agrega una condición "Nube, <etiqueta>".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analisis"))
from leyenda_tabla import formalizar  # noqa: E402  (título corto y nota al pie)

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import recalculo_por_mensaje as rpm  # noqa: E402

REFERENCIA = ("Laptop (3-nov)", ["20261103-232704_lazo_pi-4g", "20261103-235034_desvio_pi-4g"])
SESION_1 = ("Nube, S1 (15-nov)", ["20261115-222810_lazo_pi-4g", "20261115-233321_desvio_pi-4g"])


def _fmt(x: float | None, d: int = 1) -> str:
    return "--" if x is None else f"{x:.{d}f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True)
    ap.add_argument("--sesion", action="append", default=[],
                    help="'etiqueta=corrida_lazo,corrida_desvio' (carpetas en resultados/campana)")
    args = ap.parse_args()

    condiciones = dict([REFERENCIA, SESION_1])
    for s in args.sesion:
        etiqueta, dirs = s.split("=", 1)
        condiciones[f"Nube, {etiqueta}"] = [d.strip() for d in dirs.split(",") if d.strip()]
    rpm.CONDICIONES = condiciones
    sys.argv = ["recalculo_por_mensaje.py", "--salida", args.salida]
    rpm.main()

    salida = RAIZ / args.salida if not Path(args.salida).is_absolute() else Path(args.salida)
    res = json.loads((salida / "recalculo_por_mensaje.json").read_text(encoding="utf-8"))
    filas = []
    for cond, r in res.items():
        L, ida, vuelta, rtt, racha = r["L_corr_ms"], r["ida_corr_ms"], r["vuelta_corr_ms"], r["rtt_ms"], r["racha_s"]
        ent = r["entrega"]
        recibidos = sum(ent.get(f"{m}_rec", 0) for m in ("MP", "M1", "M2", "M3"))
        enviados = sum(ent.get(f"{m}_env", 0) for m in ("MP", "M1", "M2", "M3"))
        filas.append(
            f"{cond} & {r['repeticiones']} & {L['n']} & {_fmt(L['med'])} & {_fmt(L['p95'])} "
            f"[{_fmt(L['p95_ic'][0])}; {_fmt(L['p95_ic'][1])}] & {_fmt(ida['p95'])} & {_fmt(vuelta['p95'])} & "
            f"{_fmt(rtt['med'])} & {recibidos}/{enviados} & {_fmt(racha['max'], 2)} \\\\")
    tex = "\n".join([
        r"\begin{table}[H]", r"\centering",
        r"\caption[Campaña 4G con el \emph{broker} en la nube]{Lazo por 4G con el \emph{broker} y el servidor "
        r"en la laptop del banco (3-nov, red superpuesta) y en una máquina virtual en la nube (Santiago de "
        r"Chile), escenarios de lazo y desvío combinados. $L$, ida y vuelta corregidas por el desfase de "
        r"relojes; entre corchetes, intervalo de confianza al 95~\% del percentil 95 (\emph{bootstrap}). "
        r"Elaboración propia.}",
        r"\label{tab:campana_nube}", r"\small",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lrrrrrrrrr}", r"\toprule",
        r"\emph{Broker} & Rep. & Pares & $L$ med. & $L$ p95 [IC] & Ida p95 & Vuelta p95 & RTT med. & Entrega & Racha máx. \\",
        r" & & & (ms) & (ms) & (ms) & (ms) & (ms) & & (s) \\",
        r"\midrule", *filas, r"\bottomrule", r"\end{tabular}}", r"\end{table}", ""])
    (salida / "tabla_campana_nube.tex").write_text(formalizar(tex), encoding="utf-8")
    print(f"Tabla: {salida / 'tabla_campana_nube.tex'}")


if __name__ == "__main__":
    main()
