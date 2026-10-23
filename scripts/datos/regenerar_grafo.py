#!/usr/bin/env python3
"""Regenera data/grafo_san_miguel_real.graphml (el grafo vial REAL que usa
servidor/rutas.py cuando NO se arranca con GRAFO_SINTETICO=1).

Requiere osmnx instalado (`pip install osmnx`, no está en requirements.txt
porque solo hace falta para ESTE script, no para correr el servidor con el
grafo ya cacheado) y acceso a internet (API de Overpass, por defecto a
través de overpass-api.de).

Caja por defecto: el rectángulo que envuelve las dos intersecciones de
config/registro_rsu.json (OSM-C24 y OSM-C902, San Miguel, Lima) más un
margen de ~650 m (0.006 grados de latitud/longitud). Corrida original:
2026-10-22, 415 nodos, 725 aristas, ~75 s (ver
docs/bitacora/2026-10-22_arquitectura-centralizada.md).

Escenario de referencia (Cía. de Bomberos San Miguel N.º 83 -> Hospital
Centro Médico Naval): geocodificado con Nominatim el 2026-10-23 (no estaba
disponible el 2026-10-22). Con --incluir-escenario-referencia la caja se
amplía para cubrir también esos dos puntos (hasta ~7.5 km de lado), no solo
las dos intersecciones. Para una caja totalmente manual, usar
--norte/--sur/--este/--oeste.

Uso:
    python scripts/datos/regenerar_grafo.py
    python scripts/datos/regenerar_grafo.py --incluir-escenario-referencia
    python scripts/datos/regenerar_grafo.py --margen-deg 0.01 \\
        --salida data/grafo_mas_grande.graphml
    python scripts/datos/regenerar_grafo.py --norte -12.05 --sur -12.11 \\
        --este -77.02 --oeste -77.10
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

# Escenario de referencia, geocodificado con Nominatim el 2026-10-23
# (OpenStreetMap, nombres "Compañía de Bomberos San Miguel Nº 83" y
# "Hospital Centro Médico Naval"); no se inventaron coordenadas.
LAT_BOMBEROS, LON_BOMBEROS = -12.0856611, -77.0758653
LAT_HOSPITAL, LON_HOSPITAL = -12.0587319, -77.0891002


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--margen-deg", type=float, default=0.006, help="margen alrededor de los puntos incluidos, en grados")
    ap.add_argument("--network-type", default="drive", help="tipo de red de osmnx (drive, drive_service, all...)")
    ap.add_argument("--salida", default=str(RAIZ / "data" / "grafo_san_miguel_real.graphml"))
    ap.add_argument("--incluir-escenario-referencia", action="store_true",
                     help="amplía la caja para cubrir también la Cía. de Bomberos San Miguel Nº 83 y el Hospital Centro Médico Naval")
    ap.add_argument("--norte", type=float, default=None, help="caja manual: ignora los puntos anteriores")
    ap.add_argument("--sur", type=float, default=None)
    ap.add_argument("--este", type=float, default=None)
    ap.add_argument("--oeste", type=float, default=None)
    args = ap.parse_args()

    try:
        import osmnx as ox
    except ImportError:
        raise SystemExit("Falta osmnx: pip install osmnx (no está en requirements.txt a propósito, ver docstring)")

    ox.settings.log_console = True

    if None not in (args.norte, args.sur, args.este, args.oeste):
        norte, sur, este, oeste = args.norte, args.sur, args.este, args.oeste
    else:
        lats = [LAT_C24, LAT_C902]
        lons = [LON_C24, LON_C902]
        if args.incluir_escenario_referencia:
            lats += [LAT_BOMBEROS, LAT_HOSPITAL]
            lons += [LON_BOMBEROS, LON_HOSPITAL]
        norte = max(lats) + args.margen_deg
        sur = min(lats) - args.margen_deg
        este = max(lons) + args.margen_deg
        oeste = min(lons) - args.margen_deg
    print(f"Caja: norte={norte} sur={sur} este={este} oeste={oeste}")

    t0 = time.time()
    G = ox.graph_from_bbox((oeste, sur, este, norte), network_type=args.network_type)
    print(f"Descargados {len(G.nodes)} nodos, {len(G.edges)} aristas en {time.time() - t0:.1f} s")

    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, args.salida)
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
