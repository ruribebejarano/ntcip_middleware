"""Pruebas de servidor/rutas.py con el grafo SINTETICO (sin red, sin el
grafo real cacheado en data/) -- ver construir_grafo_sintetico()."""

from __future__ import annotations

import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pytest

from gateway.geometria import Acceso, Interseccion
from servidor.rutas import (
    SinRutaError,
    calcular_ruta,
    construir_grafo_sintetico,
    cruzar_con_registro,
    nodo_mas_cercano,
    planificar_ruta,
    proyectar_sobre_ruta,
)

# Coordenadas EXACTAS de los nodos C y F del grafo sintetico (ver
# construir_grafo_sintetico): dos intersecciones con un unico acceso "S"
# (llegada con rumbo ~0, hacia el norte), coherente con la geometria del
# grafo (todas las aristas van derecho hacia el norte).
REGISTRO_SINTETICO = [
    Interseccion("SINT-1", "SINT-C", -12.1074, -77.0320, (Acceso("S", 0.0, 1),)),
    Interseccion("SINT-2", "SINT-F", -12.1035, -77.0320, (Acceso("S", 0.0, 1),)),
]

ORIGEN = (-12.1100, -77.0320)   # nodo A
DESTINO = (-12.1022, -77.0320)  # nodo G


@pytest.fixture()
def grafo():
    return construir_grafo_sintetico()


def test_nodo_mas_cercano(grafo):
    assert nodo_mas_cercano(grafo, -12.1100, -77.0320) == "A"
    assert nodo_mas_cercano(grafo, -12.1022, -77.0320) == "G"


def test_calcular_ruta_recorre_todos_los_nodos(grafo):
    ruta = calcular_ruta(grafo, ORIGEN, DESTINO)
    ids = [n.nodo_id for n in ruta.geometria]
    assert ids == ["A", "B", "C", "D", "E", "F", "G"]
    assert ruta.geometria[0].distancia_acumulada_m == 0.0
    assert ruta.longitud_total_m == pytest.approx(ruta.geometria[-1].distancia_acumulada_m)
    # 6 tramos de ~144 m cada uno (0.0013 grados de latitud)
    assert ruta.longitud_total_m == pytest.approx(6 * 144.4, rel=0.05)


def test_sin_ruta_entre_componentes_desconectados(grafo):
    grafo.add_node("Z", x=-77.5, y=-12.5)  # nodo aislado, sin aristas
    with pytest.raises(SinRutaError):
        calcular_ruta(grafo, ORIGEN, (-12.5, -77.5))


def test_cruzar_con_registro_detecta_las_dos_rsu_en_orden(grafo):
    ruta = calcular_ruta(grafo, ORIGEN, DESTINO)
    paradas = cruzar_con_registro(ruta, REGISTRO_SINTETICO)
    assert [p.interseccion_id for p in paradas] == ["SINT-C", "SINT-F"]
    assert paradas[0].rsu_id == "SINT-1"
    assert paradas[0].acceso_id == "S"
    assert paradas[0].distancia_llegada_m < paradas[1].distancia_llegada_m


def test_planificar_ruta_combina_calculo_y_cruce(grafo):
    ruta = planificar_ruta(grafo, REGISTRO_SINTETICO, ORIGEN, DESTINO)
    assert len(ruta.paradas) == 2
    assert ruta.geometria[0].nodo_id == "A"


def test_planificar_ruta_sin_rsu_en_el_camino(grafo):
    """Si el registro no tiene ninguna interseccion cerca de la ruta, la
    lista de paradas queda vacia (no es un error)."""
    lejos = [Interseccion("X", "LEJOS", -1.0, -1.0, (Acceso("S", 0.0, 1),))]
    ruta = planificar_ruta(grafo, lejos, ORIGEN, DESTINO)
    assert ruta.paradas == ()


def test_proyectar_sobre_ruta_nodo_exacto(grafo):
    ruta = calcular_ruta(grafo, ORIGEN, DESTINO)
    nodo_d = next(n for n in ruta.geometria if n.nodo_id == "D")
    progreso = proyectar_sobre_ruta(ruta, nodo_d.lat, nodo_d.lon)
    assert progreso.nodo_id == "D"
    assert progreso.distancia_perpendicular_m == pytest.approx(0.0, abs=1e-6)
    assert progreso.distancia_acumulada_m == pytest.approx(nodo_d.distancia_acumulada_m)


def test_proyectar_sobre_ruta_fuera_de_la_ruta_tiene_distancia_grande(grafo):
    ruta = calcular_ruta(grafo, ORIGEN, DESTINO)
    progreso = proyectar_sobre_ruta(ruta, -12.1074, -77.0420)  # ~1 km al oeste de la ruta
    assert progreso.distancia_perpendicular_m > 500.0
