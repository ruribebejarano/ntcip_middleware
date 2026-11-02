"""Geometria del mapa del corredor para la pantalla de monitoreo: proyecta
intersecciones y accesos de config/registro_rsu.json a un plano local en
metros, reutilizando gateway/geometria.py (proyeccion_local, desplazar) --
no reimplementa la proyeccion. El SVG en si lo dibuja el navegador
(consola/static/js/mapa.js); aqui solo se calculan las coordenadas.

El registro es el de la demo multi-RSU si se dio uno (consola/backend/demo_rsu.py)
o config/registro_rsu.json si no. Las calles de fondo salen del grafo vial
de OpenStreetMap ya cacheado en data/ (el mismo que usa servidor/rutas.py),
leido aqui con ElementTree: sin teselas ni ningun servicio externo, la
consola sigue funcionando sin internet."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from gateway.geometria import ParametrosGeometria, cargar_registro, desplazar, proyeccion_local

from consola.backend import config, demo_rsu

_P = ParametrosGeometria()


def geometria_corredor() -> dict:
    registro = cargar_registro(demo_rsu.ruta_registro())
    if not registro:
        return {"lat0": 0.0, "lon0": 0.0, "intersecciones": []}
    lat0 = sum(i.lat for i in registro) / len(registro)
    lon0 = sum(i.lon for i in registro) / len(registro)

    intersecciones = []
    for inter in registro:
        x, y = proyeccion_local(inter.lat, inter.lon, lat0, lon0)
        accesos = []
        for a in inter.accesos:
            lat_ini, lon_ini = desplazar(inter.lat, inter.lon, (a.rumbo_llegada_deg + 180) % 360, 220)
            x_ini, y_ini = proyeccion_local(lat_ini, lon_ini, lat0, lon0)
            accesos.append({
                "acceso_id": a.acceso_id, "rumbo_llegada_deg": a.rumbo_llegada_deg,
                "grupo_semaforico": a.grupo_semaforico,
                "x_ini": x_ini, "y_ini": y_ini, "x_fin": x, "y_fin": y,
            })
        intersecciones.append({
            "rsu_id": inter.rsu_id, "interseccion_id": inter.interseccion_id,
            "x": x, "y": y, "r_i_m": _P.r_i_m, "r_g_m": _P.r_g_m, "accesos": accesos,
        })
    return {"lat0": lat0, "lon0": lon0, "intersecciones": intersecciones}


def proyectar_punto(lat: float, lon: float) -> dict:
    g = geometria_corredor()
    x, y = proyeccion_local(lat, lon, g["lat0"], g["lon0"])
    return {"x": x, "y": y}


_GML = "{http://graphml.graphdrawing.org/xmlns}"
_PUNTO_WKT = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
# Grosor relativo por tipo de via (atributo highway de OSM); el resto = 1.
_JERARQUIA = {"motorway": 4, "trunk": 4, "primary": 3, "secondary": 2.5, "tertiary": 2}


@lru_cache(maxsize=1)
def _aristas_osm() -> tuple[tuple[str, str, tuple[tuple[float, float], ...]], ...]:
    """(highway, nombre, ((lat, lon), ...)) de cada calle del grafo, una sola
    vez por par de nodos (el grafo de OSMnx trae ambos sentidos)."""
    if not config.GRAFO_OSM.exists():
        return ()
    raiz = ET.parse(config.GRAFO_OSM).getroot()
    claves = {k.get("id"): k.get("attr.name") for k in raiz.iter(f"{_GML}key")}
    grafo = raiz.find(f"{_GML}graph")
    nodos = {}
    for n in grafo.iter(f"{_GML}node"):
        datos = {claves.get(d.get("key")): d.text for d in n.findall(f"{_GML}data")}
        if "x" in datos and "y" in datos:
            nodos[n.get("id")] = (float(datos["y"]), float(datos["x"]))
    vistas, salida = set(), []
    for e in grafo.iter(f"{_GML}edge"):
        u, v = e.get("source"), e.get("target")
        par = (u, v) if u < v else (v, u)
        if par in vistas or u not in nodos or v not in nodos:
            continue
        vistas.add(par)
        datos = {claves.get(d.get("key")): d.text for d in e.findall(f"{_GML}data")}
        if datos.get("geometry"):
            puntos = tuple((float(lat), float(lon)) for lon, lat in _PUNTO_WKT.findall(datos["geometry"]))
        else:
            puntos = (nodos[u], nodos[v])
        tipo = (datos.get("highway") or "").strip("[]' ").split("'")[0]
        salida.append((tipo, datos.get("name") or "", puntos))
    return tuple(salida)


def calles(sur: float, oeste: float, norte: float, este: float) -> dict:
    """Calles del grafo OSM que tocan el recuadro dado, proyectadas al mismo
    plano local que geometria_corredor()."""
    g = geometria_corredor()
    lineas = []
    for tipo, nombre, puntos in _aristas_osm():
        if not any(sur <= lat <= norte and oeste <= lon <= este for lat, lon in puntos):
            continue
        xy = [proyeccion_local(lat, lon, g["lat0"], g["lon0"]) for lat, lon in puntos]
        lineas.append({"tipo": tipo, "peso": _JERARQUIA.get(tipo, 1), "nombre": nombre,
                       "p": [[round(x, 1), round(y, 1)] for x, y in xy]})
    return {"fuente": config.GRAFO_OSM.name if config.GRAFO_OSM.exists() else None, "lineas": lineas}
