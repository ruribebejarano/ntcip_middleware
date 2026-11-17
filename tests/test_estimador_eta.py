"""Pruebas de servidor/estimador_eta.py: estimador de ETA reemplazable."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from servidor.estimador_eta import ContextoETA, EstimadorServicioExterno, EstimadorVelocidadConstante  # noqa: E402

CTX = ContextoETA(distancia_restante_m=100.0, velocidad_kmh=36.0, posicion=(-12.1, -77.0),
                  interseccion=(-12.099, -77.0))


def test_velocidad_constante():
    assert EstimadorVelocidadConstante().estimar(CTX) == 10.0
    assert EstimadorVelocidadConstante().estimar(ContextoETA(-1.0, 36.0)) == 0.0


def test_servicio_externo_usa_la_consulta():
    llamadas = []

    def consultar(origen, destino):
        llamadas.append((origen, destino))
        return 42.0

    assert EstimadorServicioExterno(consultar).estimar(CTX) == 42.0
    assert llamadas == [(CTX.posicion, CTX.interseccion)]


def test_servicio_externo_cae_al_respaldo():
    def falla(origen, destino):
        raise TimeoutError

    assert EstimadorServicioExterno(falla).estimar(CTX) == 10.0
    assert EstimadorServicioExterno(lambda o, d: None).estimar(CTX) == 10.0
    sin_posicion = ContextoETA(100.0, 36.0)
    assert EstimadorServicioExterno(lambda o, d: 1.0).estimar(sin_posicion) == 10.0
