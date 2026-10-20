"""Geometria del mapa del corredor para la pantalla de monitoreo: proyecta
intersecciones y accesos de config/registro_rsu.json a un plano local en
metros, reutilizando gateway/geometria.py (proyeccion_local, desplazar) --
no reimplementa la proyeccion. El SVG en si lo dibuja el navegador
(consola/static/js/mapa.js); aqui solo se calculan las coordenadas."""

from __future__ import annotations

from gateway.geometria import ParametrosGeometria, cargar_registro, desplazar, proyeccion_local

from consola.backend import config

_P = ParametrosGeometria()


def geometria_corredor() -> dict:
    registro = cargar_registro(config.REGISTRO_RSU)
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
