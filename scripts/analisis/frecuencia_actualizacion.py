#!/usr/bin/env python3
"""Frecuencia real de actualización (RNF-02) desde los eventos de campaña.

Intervalo entre MP_tx consecutivos de la OBU (por repetición) y entre M1_tx
consecutivos de una misma solicitud en el servidor (renovaciones por
parada), más el conteo de misiones con MI y con MF. No se mira si una
renovación tuvo respuesta: eso es la caducidad, tabla_renovacion.

Uso:
    python scripts/analisis/frecuencia_actualizacion.py --dir resultados/campana/<corrida1> [--dir ...]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from common.events import iter_eventos  # noqa: E402
from lazo_centralizado import percentil  # noqa: E402

NS_POR_S = 1e9


def intervalos_s(marcas_ns: list[int]) -> list[float]:
    orden = sorted(marcas_ns)
    return [(b - a) / NS_POR_S for a, b in zip(orden, orden[1:])]


def intervalos_de_repeticion(eventos: list[dict]) -> tuple[list[float], list[float], int, int]:
    """(intervalos MP, intervalos M1 por solicitud, n MI, n MF)."""
    mp = [e["ts_ns"] for e in eventos if e["tipo_evento"] == "MP_tx"]
    m1_por_solicitud: dict[str, list[int]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] == "M1_tx":
            m1_por_solicitud[e["id_solicitud"]].append(e["ts_ns"])
    m1 = [i for marcas in m1_por_solicitud.values() for i in intervalos_s(marcas)]
    n_mi = sum(1 for e in eventos if e["tipo_evento"] == "MI_tx")
    n_mf = sum(1 for e in eventos if e["tipo_evento"] == "MF_tx")
    return intervalos_s(mp), m1, n_mi, n_mf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    args = ap.parse_args()

    mp, m1, n_mi, n_mf = [], [], 0, 0
    for d in map(Path, args.dir):
        for rep in sorted(p for p in d.iterdir() if p.is_dir() and p.name.startswith("rep_")):
            r_mp, r_m1, r_mi, r_mf = intervalos_de_repeticion(list(iter_eventos(rep)))
            mp += r_mp
            m1 += r_m1
            n_mi += r_mi
            n_mf += r_mf

    for nombre, valores in (("MP (OBU)", mp), ("M1 renovación (servidor)", m1)):
        print(f"{nombre}: n={len(valores)} mediana={percentil(valores, 50):.3f} s "
              f"p95={percentil(valores, 95):.3f} s máx={max(valores):.3f} s")
    print(f"Misiones con MI: {n_mi}; con MF: {n_mf}")


if __name__ == "__main__":
    main()
