#!/usr/bin/env python3
"""Regenera data/grafo_san_miguel_real.graphml (el grafo vial REAL que usa
servidor/rutas.py cuando NO se arranca con GRAFO_SINTETICO=1).

Requiere osmnx instalado (`pip install osmnx`, no está en requirements.txt
porque solo hace falta para ESTE script, no para correr el servidor con el
grafo ya cacheado) y acceso a internet (API de Overpass, por defecto a
través de overpass-api.de).

Caja: el rectángulo que envuelve las dos intersecciones de
config/registro_rsu.json (OSM-C24 y OSM-C902, San Miguel, Lima) más un
margen de ~650 m (0.006 grados de latitud/longitud). Corrida original:
2026-10-22, 415 nodos, 725 aristas, ~75 s (ver
docs/bitacora/2026-10-22_arquitectura-centralizada.md).

[DATO: medir en campo] esta caja NO necesariamente cubre la ruta completa
Cía. de Bomberos San Miguel N.º 83 -> Hospital Centro Médico Naval citada en
el prompt de arquitectura centralizada -- no se geocodificaron esos dos
puntos (Nominatim no resolvió los nombres) y no se inventaron sus
coordenadas. Si se confirman esas coordenadas y quedan fuera de la caja
actual, pasar --norte/--sur/--este/--oeste (o editar el margen) para volver
a correr este script con una caja más grande.

Uso:
    python scripts/datos/regenerar_grafo.py
    python scripts/datos/regenerar_grafo.py --margen-deg 0.01 \\
        --salida data/grafo_mas_grande.graphml
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

# Centros reales de config/registro_rsu.json (OSM-C24, OSM-C902).
LAT_C24, LON_C24 = -12.103551833333334, -77.03156646666667
LAT_C902, LON_C902 = -12.099695500000001, -77.03229606666666


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--margen-deg", type=float, default=0.006, help="margen alrededor de las dos intersecciones, en grados")
    ap.add_argument("--network-type", default="drive", help="tipo de red de osmnx (drive, drive_service, all...)")
    ap.add_argument("--salida", default=str(RAIZ / "data" / "grafo_san_miguel_real.graphml"))
    args = ap.parse_args()

    try:
        import osmnx as ox
    except ImportError:
        raise SystemExit("Falta osmnx: pip install osmnx (no está en requirements.txt a propósito, ver docstring)")

    ox.settings.log_console = True

    norte = max(LAT_C24, LAT_C902) + args.margen_deg
    sur = min(LAT_C24, LAT_C902) - args.margen_deg
    este = max(LON_C24, LON_C902) + args.margen_deg
    oeste = min(LON_C24, LON_C902) - args.margen_deg
    print(f"Caja: norte={norte} sur={sur} este={este} oeste={oeste}")

    t0 = time.time()
    G = ox.graph_from_bbox((oeste, sur, este, norte), network_type=args.network_type)
    print(f"Descargados {len(G.nodes)} nodos, {len(G.edges)} aristas en {time.time() - t0:.1f} s")

    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, args.salida)
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
