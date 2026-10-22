"""Calculo de ruta en el servidor (ssec:ruta_servidor propuesta en el
inventario de redaccion). Reemplaza la copia local estatica del registro de
RSU que antes bajaba la OBU (esquema E2+E4): el registro
(config/registro_rsu.json) vive SOLO aqui, y la ruta se calcula UNA vez por
mision, al armarla, cruzando el camino mas corto del grafo vial con ese
registro para obtener la lista ORDENADA de RSU y accesos de llegada.

*** Herramienta de calculo: NetworkX puro, OSMnx solo para regenerar el
cache ***
Enrutar (dijkstra sobre 'length') NO requiere osmnx instalado -- solo
networkx, que ya es una dependencia de gateway/geometria.py transitivamente
(en realidad gateway/geometria.py no la usa; esta es la primera vez que el
repo depende de networkx para algo que no sea una prueba). osmnx se usa
UNICAMENTE para descargar y cachear el grafo real en disco (ver
scripts/datos/regenerar_grafo.py); el grafo cacheado se carga despues con
networkx.read_graphml, para que el servidor pueda correr sin osmnx instalado
(p. ej. en la Raspberry Pi) siempre que el .graphml ya este en data/.

*** Grafo real cacheado en este repo ***
data/grafo_san_miguel_real.graphml es un grafo VIAL REAL de OpenStreetMap
(via Overpass, osmnx 2.1.1), descargado el 2026-10-22 con acceso a internet
disponible en el entorno de desarrollo -- no hubo que recurrir al grafo
sintetico para el caso de uso real. El area es la caja que envuelve las dos
intersecciones de config/registro_rsu.json (OSM-C24 y OSM-C902, San Miguel,
Lima, cerca de la PUCP) mas un margen de ~650 m. 415 nodos, 725 aristas.
Ver scripts/datos/regenerar_grafo.py para repetir la descarga (p. ej. si
cambia el registro de RSU o el area de interes) y
docs/bitacora/2026-10-22_arquitectura-centralizada.md para el detalle de la
corrida.

[DATO: medir en campo] la caja no cubre necesariamente la ruta completa
Cia. de Bomberos San Miguel N.o 83 -> Hospital Centro Medico Naval citada en
el prompt de arquitectura centralizada: no se intento geocodificar esos dos
puntos (Nominatim no resolvio los nombres, ver bitacora) y NO se inventaron
sus coordenadas. Antes de usar este grafo para el escenario de referencia
completo de la tesis, el autor debe confirmar las coordenadas reales de esos
dos puntos y, si quedan fuera de la caja actual, volver a correr
scripts/datos/regenerar_grafo.py con una caja mas grande.

*** Grafo sintetico (solo pruebas) ***
construir_grafo_sintetico() genera un grafo pequeno a mano, con coordenadas
INVENTADAS (no es un lugar real), para que servidor/rutas.py y
servidor/gestor_mision.py tengan una prueba unitaria determinista que no
dependa de internet ni del grafo cacheado. No usar sus numeros como dato de
la tesis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx

from gateway.geometria import Interseccion, delta_psi, proyeccion_local, rumbo_entre

RAIZ = Path(__file__).resolve().parent.parent
GRAFO_REAL_DEFAULT = RAIZ / "data" / "grafo_san_miguel_real.graphml"

# Radio para decidir que una intersección del registro está "sobre" la ruta
# calculada (no sobre una calle cualquiera a la vuelta). PROVISIONAL
# [REVISAR con asesor]: depende de la resolución del grafo (cuántos nodos
# por cuadra) y de la precisión real del grafo de OSM frente al terreno.
RADIO_DETECCION_RSU_M = 40.0
# Tolerancia angular para decidir el acceso de llegada a partir del rumbo de
# viaje en el tramo de la ruta que pasa por la intersección. Más holgada que
# psi_tol_deg de ParametrosGeometria (30°) porque el rumbo de un segmento de
# calle de OSM no es exactamente el rumbo de aproximación real del vehículo.
# PROVISIONAL [REVISAR con asesor].
PSI_TOL_RUTA_DEG = 45.0


@dataclass(frozen=True)
class NodoRuta:
    nodo_id: str
    lat: float
    lon: float
    distancia_acumulada_m: float  # desde el origen de la ruta, por el camino


@dataclass(frozen=True)
class ParadaRsu:
    """Una RSU/acceso que la ruta atraviesa, en el orden en que el vehículo
    la encuentra (MR: 'lista ordenada de RSU y accesos de llegada')."""

    rsu_id: str
    interseccion_id: str
    acceso_id: str
    distancia_llegada_m: float
    nodo_id: str


@dataclass(frozen=True)
class Ruta:
    geometria: tuple[NodoRuta, ...]
    longitud_total_m: float
    paradas: tuple[ParadaRsu, ...]


@dataclass(frozen=True)
class Progreso:
    """Resultado de proyectar una posición MP sobre la ruta (ver
    gestor_mision.py): la distancia perpendicular AL SEGMENTO más cercano
    de la polilínea de la ruta (no solo al nodo más cercano -- con nodos de
    OSM espaciados decenas de metros, usar solo el nodo más cercano daba
    hasta ~la mitad del espaciado de falso "desvío" en una recta larga sin
    intersecciones intermedias) y la distancia acumulada hasta el punto de
    la proyección sobre ese segmento."""

    nodo_id: str
    distancia_acumulada_m: float
    distancia_perpendicular_m: float


class SinRutaError(Exception):
    """No existe camino en el grafo entre origen y destino (grafo
    desconectado, o alguno de los dos puntos fuera de la componente
    conectada que se cargó)."""


# ---------------------------------------------------------------------------
# Carga / cacheo del grafo
# ---------------------------------------------------------------------------


def cargar_grafo(ruta: Path | str = GRAFO_REAL_DEFAULT) -> nx.DiGraph:
    """Carga un grafo cacheado en disco (GraphML, generado por OSMnx o por
    construir_grafo_sintetico() + guardar_grafo()) con NetworkX puro -- no
    requiere osmnx instalado. GraphML guarda todos los atributos como texto;
    esta función normaliza 'x'/'y' (nodos) y 'length' (aristas) a float."""
    G = nx.read_graphml(str(ruta))
    for _, data in G.nodes(data=True):
        if "x" in data:
            data["x"] = float(data["x"])
        if "y" in data:
            data["y"] = float(data["y"])
    for _, _, data in G.edges(data=True):
        if "length" in data:
            data["length"] = float(data["length"])
    return G


def guardar_grafo(G: nx.DiGraph, ruta: Path | str) -> None:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, str(ruta))


def construir_grafo_sintetico() -> nx.DiGraph:
    """*** GRAFO SINTÉTICO, SOLO PARA PRUEBAS -- coordenadas inventadas ***

    Siete nodos A..G en línea recta hacia el norte (separación ~150 m cada
    uno), con dos "intersecciones" en C y F que un registro de RSU sintético
    (ver tests/test_rutas.py) ubica exactamente en esas coordenadas. Permite
    probar cargar_grafo/calcular_ruta/cruzar_con_registro sin red ni grafo
    cacheado. NO representa ningún lugar real; no usar sus números como
    dato de la tesis."""
    G = nx.DiGraph()
    nodos = [
        ("A", -12.1100, -77.0320),
        ("B", -12.1087, -77.0320),
        ("C", -12.1074, -77.0320),  # RSU-SINT-1
        ("D", -12.1061, -77.0320),
        ("E", -12.1048, -77.0320),
        ("F", -12.1035, -77.0320),  # RSU-SINT-2
        ("G", -12.1022, -77.0320),
    ]
    for nid, lat, lon in nodos:
        G.add_node(nid, x=lon, y=lat)
    for (n1, lat1, lon1), (n2, lat2, lon2) in zip(nodos[:-1], nodos[1:]):
        x, y = proyeccion_local(lat2, lon2, lat1, lon1)
        d = math.hypot(x, y)
        G.add_edge(n1, n2, length=d)
        G.add_edge(n2, n1, length=d)
    return G


def construir_grafo_cruce_sintetico() -> nx.DiGraph:
    """*** GRAFO SINTÉTICO, SOLO PARA PRUEBAS/DEMOS -- coordenadas inventadas ***

    Una cruz de 4 brazos (S-X-N vertical, O-X-E horizontal) que se cruzan
    en X, para ensayar el arbitraje de conflictos (servidor/conflictos.py)
    con dos misiones que llegan al MISMO punto por accesos con rumbos de
    llegada distintos (0° y 90°). Usado por tests/test_gestor_mision.py y
    por evidencia/2026-10-22_arquitectura-centralizada/ (escenario de
    conflicto de la fase 3.8)."""
    G = nx.DiGraph()
    nodos = {
        "S": (-12.1087, -77.0320), "X": (-12.1074, -77.0320), "N": (-12.1061, -77.0320),
        "O": (-12.1074, -77.033329), "E": (-12.1074, -77.030671),
    }
    for nid, (lat, lon) in nodos.items():
        G.add_node(nid, x=lon, y=lat)
    for a, b in (("S", "X"), ("X", "N"), ("O", "X"), ("X", "E")):
        lat1, lon1 = nodos[a]
        lat2, lon2 = nodos[b]
        x, y = proyeccion_local(lat2, lon2, lat1, lon1)
        d = math.hypot(x, y)
        G.add_edge(a, b, length=d)
        G.add_edge(b, a, length=d)
    return G


# ---------------------------------------------------------------------------
# Enrutamiento
# ---------------------------------------------------------------------------


def nodo_mas_cercano(G: nx.DiGraph, lat: float, lon: float) -> str:
    mejor: Optional[str] = None
    mejor_d = math.inf
    for nid, data in G.nodes(data=True):
        x, y = proyeccion_local(lat, lon, data["y"], data["x"])
        d = math.hypot(x, y)
        if d < mejor_d:
            mejor, mejor_d = nid, d
    if mejor is None:
        raise SinRutaError("grafo vacio")
    return mejor


def calcular_ruta(G: nx.DiGraph, origen: tuple[float, float], destino: tuple[float, float]) -> Ruta:
    """Camino más corto por distancia ('length', metros) entre el nodo más
    cercano a `origen` y el más cercano a `destino`. Sin tráfico en tiempo
    real (limitación conocida, ver ssec:ruta_servidor del inventario de
    redacción): el peso es solo distancia, no tiempo de viaje estimado."""
    n_origen = nodo_mas_cercano(G, *origen)
    n_destino = nodo_mas_cercano(G, *destino)
    try:
        camino = nx.shortest_path(G, n_origen, n_destino, weight="length")
    except nx.NetworkXNoPath as exc:
        raise SinRutaError(f"sin camino entre {n_origen} y {n_destino}") from exc

    geometria: list[NodoRuta] = []
    acumulada = 0.0
    for i, nid in enumerate(camino):
        data = G.nodes[nid]
        if i > 0:
            prev = camino[i - 1]
            acumulada += G[prev][nid]["length"]
        geometria.append(NodoRuta(nid, float(data["y"]), float(data["x"]), acumulada))

    return Ruta(geometria=tuple(geometria), longitud_total_m=acumulada, paradas=())


def _rumbo_llegada_en_nodo(geometria: tuple[NodoRuta, ...], indice: int) -> Optional[float]:
    if indice == 0:
        return None
    n0, n1 = geometria[indice - 1], geometria[indice]
    return rumbo_entre(n0.lat, n0.lon, n1.lat, n1.lon)


def cruzar_con_registro(
    ruta: Ruta,
    registro: list[Interseccion],
    radio_deteccion_m: float = RADIO_DETECCION_RSU_M,
    psi_tol_deg: float = PSI_TOL_RUTA_DEG,
) -> tuple[ParadaRsu, ...]:
    """Cruza la geometría de la ruta con el registro de RSU (que vive solo
    en el servidor, ssec:registro) y devuelve la lista ORDENADA de
    RSU/accesos que la ruta atraviesa (MR). Por cada intersección del
    registro, busca el nodo de la ruta más cercano a su centro; si está
    dentro de `radio_deteccion_m`, el rumbo de viaje en ese tramo decide el
    acceso de llegada (misma ecuación de ssec:zonas, delta_psi contra
    rumbo_llegada_deg de cada acceso)."""
    paradas: list[ParadaRsu] = []
    for inter in registro:
        mejor_indice: Optional[int] = None
        mejor_d = math.inf
        for i, nodo in enumerate(ruta.geometria):
            x, y = proyeccion_local(nodo.lat, nodo.lon, inter.lat, inter.lon)
            d = math.hypot(x, y)
            if d <= radio_deteccion_m and d < mejor_d:
                mejor_indice, mejor_d = i, d
        if mejor_indice is None:
            continue
        rumbo = _rumbo_llegada_en_nodo(ruta.geometria, mejor_indice)
        if rumbo is None:
            continue
        dpsi, acceso = min(
            ((delta_psi(rumbo, a.rumbo_llegada_deg), a) for a in inter.accesos),
            key=lambda c: c[0],
        )
        if dpsi > psi_tol_deg:
            continue
        nodo = ruta.geometria[mejor_indice]
        paradas.append(
            ParadaRsu(
                rsu_id=inter.rsu_id,
                interseccion_id=inter.interseccion_id,
                acceso_id=acceso.acceso_id,
                distancia_llegada_m=nodo.distancia_acumulada_m,
                nodo_id=nodo.nodo_id,
            )
        )
    paradas.sort(key=lambda p: p.distancia_llegada_m)
    return tuple(paradas)


def planificar_ruta(
    G: nx.DiGraph,
    registro: list[Interseccion],
    origen: tuple[float, float],
    destino: tuple[float, float],
    radio_deteccion_m: float = RADIO_DETECCION_RSU_M,
    psi_tol_deg: float = PSI_TOL_RUTA_DEG,
) -> Ruta:
    """Punto de entrada único: calcula la ruta y la cruza con el registro de
    RSU. Usado por servidor/gestor_mision.py al armar una misión y al
    recalcular por desvío."""
    ruta = calcular_ruta(G, origen, destino)
    paradas = cruzar_con_registro(ruta, registro, radio_deteccion_m, psi_tol_deg)
    return Ruta(geometria=ruta.geometria, longitud_total_m=ruta.longitud_total_m, paradas=paradas)


def proyectar_sobre_ruta(ruta: Ruta, lat: float, lon: float) -> Progreso:
    """Progreso de la OBU sobre la ruta calculada, a partir de una muestra
    MP: proyección (clamp a [0,1]) sobre cada segmento consecutivo de la
    polilínea, en el plano local tangente a cada segmento; se queda con el
    segmento de menor distancia perpendicular. distancia_perpendicular_m
    grande => posible desvío (ver UMBRAL_DESVIO_M en gestor_mision.py)."""
    geometria = ruta.geometria
    if len(geometria) == 1:
        nodo = geometria[0]
        x, y = proyeccion_local(lat, lon, nodo.lat, nodo.lon)
        return Progreso(nodo.nodo_id, nodo.distancia_acumulada_m, math.hypot(x, y))

    mejor: Optional[tuple[float, str, float]] = None  # (distancia, nodo_id, distancia_acumulada)
    for n0, n1 in zip(geometria[:-1], geometria[1:]):
        bx, by = proyeccion_local(n1.lat, n1.lon, n0.lat, n0.lon)
        px, py = proyeccion_local(lat, lon, n0.lat, n0.lon)
        largo2 = bx * bx + by * by
        t = 0.0 if largo2 == 0.0 else max(0.0, min(1.0, (px * bx + py * by) / largo2))
        d = math.hypot(px - t * bx, py - t * by)
        acumulada = n0.distancia_acumulada_m + t * math.hypot(bx, by)
        nodo_id = n0.nodo_id if t < 0.5 else n1.nodo_id
        if mejor is None or d < mejor[0]:
            mejor = (d, nodo_id, acumulada)

    d, nodo_id, acumulada = mejor
    return Progreso(nodo_id=nodo_id, distancia_acumulada_m=acumulada, distancia_perpendicular_m=d)
