#!/usr/bin/env python3
"""Genera el registro de RSU de una ruta real: una RSU por intersección
semaforizada de OpenStreetMap que la ruta atraviesa (campaña de ruta
completa, resultados/ruta_completa/).

Pasos:
  1. Ruta con servidor/rutas.py::calcular_ruta sobre el grafo cacheado.
  2. Nodos highway=traffic_signals de OSM (semaforos_nodos.geojson, salida
     de E:\\Tesis\\osm\\osm_lima_rsu.py), agrupados en intersecciones por
     enlace simple con radio --radio-grupo (40 m, el mismo de
     osm_lima_rsu.py::agrupar_intersecciones por defecto).
  3. Una intersección cuenta si su centro (centroide de sus nodos) está a
     menos de --dist-ruta (25 m) de la polilínea de la ruta.
  4. Accesos: rumbo de llegada REAL desde el grafo, entre el nodo de la ruta
     más cercano al centro y cada uno de sus vecinos (no supuesto
     perpendicular). El acceso "A" es el que usa la ruta. Grupo semafórico:
     1 si el acceso es colineal con el de la ruta (±45°, mismo sentido o el
     contrario), 2 si no -- VALOR DE RELLENO, el plan real lo entrega el CCGT.

Escribe el registro (formato de config/registro_rsu.json) y un CSV con las
intersecciones aceptadas y las descartadas (entre --dist-ruta y 60 m), con
el motivo.

Uso:
    python scripts/datos/registro_ruta.py \\
        --origen=-12.074664,-77.082933 --destino=-12.0649978,-77.0464372 \\
        --semaforos E:/Tesis/osm/salida_osm/semaforos_nodos.geojson \\
        --rsu-id-base 101 \\
        --salida scripts/campanas/fixtures/registro_ruta_hospital_nino.json \\
        --csv resultados/ruta_completa/intersecciones_ruta.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import delta_psi, proyeccion_local, rumbo_entre  # noqa: E402
from servidor import rutas  # noqa: E402


def _par(texto: str) -> tuple[float, float]:
    a, b = texto.split(",")
    return float(a), float(b)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    x, y = proyeccion_local(a[0], a[1], b[0], b[1])
    return math.hypot(x, y)


def agrupar(puntos: list[dict], radio_m: float) -> list[list[dict]]:
    """Enlace simple: dos nodos a menos de radio_m quedan en el mismo grupo."""
    padre = list(range(len(puntos)))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i in range(len(puntos)):
        for j in range(i + 1, len(puntos)):
            if _dist((puntos[i]["lat"], puntos[i]["lon"]), (puntos[j]["lat"], puntos[j]["lon"])) < radio_m:
                padre[raiz(i)] = raiz(j)
    grupos: dict[int, list[dict]] = {}
    for i, p in enumerate(puntos):
        grupos.setdefault(raiz(i), []).append(p)
    return list(grupos.values())


def proyectar(geo, lat: float, lon: float) -> tuple[float, float]:
    """(distancia perpendicular, distancia acumulada) del punto a la polilínea."""
    mejor = (math.inf, 0.0)
    for n0, n1 in zip(geo[:-1], geo[1:]):
        bx, by = proyeccion_local(n1.lat, n1.lon, n0.lat, n0.lon)
        px, py = proyeccion_local(lat, lon, n0.lat, n0.lon)
        l2 = bx * bx + by * by
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / l2))
        d = math.hypot(px - t * bx, py - t * by)
        if d < mejor[0]:
            mejor = (d, n0.distancia_acumulada_m + t * math.sqrt(l2))
    return mejor


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--origen", required=True, type=_par)
    ap.add_argument("--destino", required=True, type=_par)
    ap.add_argument("--semaforos", required=True)
    ap.add_argument("--grafo", default=str(rutas.GRAFO_REAL_DEFAULT))
    ap.add_argument("--radio-grupo", type=float, default=40.0)
    ap.add_argument("--dist-ruta", type=float, default=25.0)
    ap.add_argument("--rsu-id-base", type=int, default=101)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    G = rutas.cargar_grafo(args.grafo)
    ruta = rutas.calcular_ruta(G, args.origen, args.destino)
    geo = ruta.geometria
    lats = [n.lat for n in geo]
    lons = [n.lon for n in geo]
    margen = 0.002
    caja = (min(lats) - margen, max(lats) + margen, min(lons) - margen, max(lons) + margen)

    datos = json.loads(Path(args.semaforos).read_text(encoding="utf-8"))
    puntos = []
    for f in datos["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        if caja[0] <= lat <= caja[1] and caja[2] <= lon <= caja[3]:
            puntos.append({"lat": lat, "lon": lon, "props": f.get("properties", {})})

    filas_csv = []
    aceptadas = []
    for grupo in agrupar(puntos, args.radio_grupo):
        lat = sum(p["lat"] for p in grupo) / len(grupo)
        lon = sum(p["lon"] for p in grupo) / len(grupo)
        d_perp, acum = proyectar(geo, lat, lon)
        if d_perp > 60.0:
            continue
        etiquetas = sorted({f"{k}={v}" for p in grupo for k, v in p["props"].items() if k not in ("id", "highway")})
        ids_osm = sorted(str(p["props"].get("id")) for p in grupo)
        peatonal = any("pedestrian" in e or "crossing" in e for e in etiquetas) and not any(
            e in ("traffic_signals=signal", "traffic_signals=traffic_lights") for e in etiquetas)
        motivo = None
        if d_perp > args.dist_ruta:
            motivo = f"centro a {d_perp:.1f} m de la ruta (> {args.dist_ruta:.0f} m)"
        elif peatonal:
            motivo = "solo semaforo peatonal segun etiquetas OSM"
        fila = {"lat": round(lat, 7), "lon": round(lon, 7), "n_nodos": len(grupo),
                "dist_ruta_m": round(d_perp, 1), "acum_m": round(acum, 1),
                "etiquetas_osm": ";".join(etiquetas), "nodos_osm": ";".join(ids_osm),
                "aceptada": motivo is None, "motivo_descarte": motivo or ""}
        filas_csv.append(fila)
        if motivo is None:
            aceptadas.append(fila)

    aceptadas.sort(key=lambda f: f["acum_m"])
    filas_csv.sort(key=lambda f: f["acum_m"])

    registro_rsu = []
    for k, f in enumerate(aceptadas):
        rsu_id = str(args.rsu_id_base + k)
        f["rsu_id"] = rsu_id
        f["interseccion_id"] = f"RUTA-{k + 1:02d}"
        idx = min(range(1, len(geo)), key=lambda i: _dist((geo[i].lat, geo[i].lon), (f["lat"], f["lon"])))
        nodo, previo = geo[idx], geo[idx - 1]
        f["nodo_ruta"] = nodo.nodo_id
        rumbo_ruta = rumbo_entre(previo.lat, previo.lon, nodo.lat, nodo.lon)
        accesos = [{"acceso_id": "A", "rumbo_llegada_deg": round(rumbo_ruta, 1), "grupo_semaforico": 1,
                    "nota": f"acceso de la ruta (nodo {previo.nodo_id} -> {nodo.nodo_id})"}]
        vecinos = set(G.predecessors(nodo.nodo_id)) | set(G.successors(nodo.nodo_id))
        for v in sorted(vecinos):
            if v == previo.nodo_id:
                continue
            vd = G.nodes[v]
            rumbo = rumbo_entre(float(vd["y"]), float(vd["x"]), nodo.lat, nodo.lon)
            if any(delta_psi(rumbo, a["rumbo_llegada_deg"]) < 20.0 for a in accesos):
                continue
            colineal = min(delta_psi(rumbo, rumbo_ruta), delta_psi(rumbo, (rumbo_ruta + 180) % 360)) <= 45.0
            accesos.append({"acceso_id": chr(ord("A") + len(accesos)), "rumbo_llegada_deg": round(rumbo, 1),
                            "grupo_semaforico": 1 if colineal else 2,
                            "nota": f"llegada real desde el nodo {v} hacia {nodo.nodo_id}"})
        registro_rsu.append({"rsu_id": rsu_id, "interseccion_id": f["interseccion_id"], "codigo_mml": None,
                             "centro": {"lat": f["lat"], "lon": f["lon"]}, "accesos": accesos,
                             "acum_m": f["acum_m"], "n_nodos_osm": f["n_nodos"]})

    salida = {
        "version": "ruta-completa-hospital-nino-brena",
        "descripcion": (
            "Registro de RSU de la campaña de ruta completa (resultados/ruta_completa/): una RSU por "
            "interseccion semaforizada de OSM a menos de "
            f"{args.dist_ruta:.0f} m de la ruta {args.origen} -> {args.destino} (destino: Instituto "
            "Nacional de Salud del Nino, Brena, OSM way/194898813). Generado por scripts/datos/registro_ruta.py."),
        "origen": {
            "ruta": f"servidor/rutas.py::calcular_ruta sobre {Path(args.grafo).name}: "
                    f"{ruta.longitud_total_m:.1f} m, {len(geo)} nodos",
            "semaforos": f"{Path(args.semaforos).name}, agrupados por enlace simple a {args.radio_grupo:.0f} m",
            "accesos": "rumbo_llegada_deg REAL desde el grafo (vecinos del nodo de la ruta mas cercano al centro)",
            "grupo_semaforico": "Valor de relleno (1 = colineal con la ruta, 2 = transversal); el plan real lo entrega el CCGT.",
            "rsu_id": f"{args.rsu_id_base} en adelante: no chocan con el agente real de la Raspberry Pi (rsu_id 1) "
                      "ni con los registros de demostracion (2 a 6).",
            "codigo_mml": "Sin cruzar con el inventario de la MML.",
        },
        "rsu": registro_rsu,
    }
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.salida).write_text(json.dumps(salida, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    campos = ["rsu_id", "interseccion_id", "acum_m", "dist_ruta_m", "n_nodos", "lat", "lon", "nodo_ruta",
              "aceptada", "motivo_descarte", "etiquetas_osm", "nodos_osm"]
    with Path(args.csv).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas_csv)

    print(f"Ruta: {ruta.longitud_total_m:.1f} m, {len(geo)} nodos")
    print(f"Intersecciones a menos de 60 m: {len(filas_csv)}; aceptadas: {len(aceptadas)}")
    for f in filas_csv:
        estado = f"RSU {f.get('rsu_id')}" if f["aceptada"] else f"descartada ({f['motivo_descarte']})"
        print(f"  {f['acum_m']:7.1f} m  d={f['dist_ruta_m']:5.1f} m  n={f['n_nodos']}  {estado}")
    print(f"Registro: {args.salida}\nCSV: {args.csv}")


if __name__ == "__main__":
    main()
