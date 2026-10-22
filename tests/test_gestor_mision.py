"""Pruebas de servidor/gestor_mision.py: ciclo de vida de una mision
(armado -> MP a 1 Hz -> M1 anticipado/geocerca -> M3 al cruzar) y arbitraje
de conflictos entre dos misiones en la misma RSU. Sin MQTT: los callbacks
enviar_m1/m3/mr/me solo acumulan lo que se habria publicado."""

from __future__ import annotations

import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import networkx as nx
import pytest

from gateway.geometria import Acceso, Interseccion, desplazar, proyeccion_local
from servidor.gestor_mision import (
    ESTADO_CANCELADA,
    ESTADO_EN_ESPERA,
    ESTADO_PENDIENTE,
    ESTADO_SOLICITADA,
    GestorMision,
)
from servidor.rutas import construir_grafo_cruce_sintetico, construir_grafo_sintetico

REGISTRO_SINTETICO = [
    Interseccion("SINT-1", "SINT-C", -12.1074, -77.0320, (Acceso("S", 0.0, 1),)),
    Interseccion("SINT-2", "SINT-F", -12.1035, -77.0320, (Acceso("S", 0.0, 1),)),
]

NODOS_RUTA = {
    "A": (-12.1100, -77.0320), "B": (-12.1087, -77.0320), "C": (-12.1074, -77.0320),
    "D": (-12.1061, -77.0320), "E": (-12.1048, -77.0320), "F": (-12.1035, -77.0320),
    "G": (-12.1022, -77.0320),
}
VELOCIDAD_KMH = 36.0  # 10 m/s, para que cada paso del grafo sintetico (~144 m) sea ~14.5 s


class _Registrador:
    """Acumula lo que el GestorMision hubiera publicado por MQTT."""

    def __init__(self) -> None:
        self.m1: list[tuple[str, dict]] = []
        self.m3: list[tuple[str, dict]] = []
        self.mr: list[tuple[str, dict]] = []
        self.me: list[tuple[str, dict]] = []

    def enviar_m1(self, rsu_id: str, cuerpo: dict) -> None:
        self.m1.append((rsu_id, cuerpo))

    def enviar_m3(self, rsu_id: str, cuerpo: dict) -> None:
        self.m3.append((rsu_id, cuerpo))

    def enviar_mr(self, obu_id: str, cuerpo: dict) -> None:
        self.mr.append((obu_id, cuerpo))

    def enviar_me(self, obu_id: str, cuerpo: dict) -> None:
        self.me.append((obu_id, cuerpo))


def _gestor(registro=REGISTRO_SINTETICO, **kwargs):
    grafo = construir_grafo_sintetico()
    reg = _Registrador()
    gestor = GestorMision(
        grafo, registro,
        enviar_m1=reg.enviar_m1, enviar_m3=reg.enviar_m3, enviar_mr=reg.enviar_mr, enviar_me=reg.enviar_me,
        **kwargs,
    )
    return gestor, reg


def test_armar_mision_calcula_ruta_y_publica_mr():
    gestor, reg = _gestor()
    mision = gestor.armar_mision("obu-1", clase=1, origen=NODOS_RUTA["A"], destino=NODOS_RUTA["G"])
    assert len(mision.ruta.paradas) == 2
    assert reg.mr[0][0] == "obu-1"
    assert len(reg.mr[0][1]["paradas"]) == 2


def test_ciclo_completo_recorrido_recto_dos_rsu():
    gestor, reg = _gestor()
    gestor.armar_mision("obu-1", clase=1, origen=NODOS_RUTA["A"], destino=NODOS_RUTA["G"])

    # Muestras cada 20 m (no exactamente sobre los nodos del grafo, para que
    # el vehiculo pase un par de muestras DENTRO de R_g antes de cruzar cada
    # interseccion, en vez de saltar de "fuera" a "cruzada" en un solo paso).
    lat_a, lon_a = NODOS_RUTA["A"]
    for paso_m in range(0, 900, 20):
        lat, lon = desplazar(lat_a, lon_a, 0.0, float(paso_m))
        gestor.procesar_mp("obu-1", lat, lon, VELOCIDAD_KMH, rumbo_deg=0.0)

    mision = gestor.misiones["obu-1"]
    # Las dos paradas se solicitaron (M1 seq=1) y se cruzaron (M3): el
    # vehiculo llega hasta G, mas alla de ambas RSU.
    nuevas = [c for _, c in reg.m1 if c["seq"] == 1]
    assert {c["acceso"] for c in nuevas} == {"S"}
    assert len(nuevas) == 2
    assert len(reg.m3) == 2
    assert {c["motivo"] for _, c in reg.m3} == {"cruce"}
    assert mision.paradas["SINT-C"].estado == ESTADO_CANCELADA
    assert mision.paradas["SINT-F"].estado == ESTADO_CANCELADA
    # Hubo al menos una renovacion (ACTUALIZAR_M1) entre el primer M1 y el M3
    # de cada parada (ver gestor_mision.procesar_mp).
    assert len(reg.m1) > len(nuevas)


def test_sin_mision_activa_no_hay_procesamiento():
    """ssec:minimizacion: sin MI armado, un MP no produce M1 ni efecto
    alguno (seguridad ante un publicador que no paso por el armado)."""
    gestor, reg = _gestor()
    gestor.procesar_mp("obu-fantasma", *NODOS_RUTA["C"], VELOCIDAD_KMH, 0.0)
    assert reg.m1 == [] and reg.me == []


def test_desarme_cancela_todo_lo_pendiente():
    gestor, reg = _gestor()
    gestor.armar_mision("obu-1", clase=1, origen=NODOS_RUTA["A"], destino=NODOS_RUTA["G"])
    gestor.procesar_mp("obu-1", *NODOS_RUTA["B"], VELOCIDAD_KMH, 0.0)  # entra a R_g de SINT-C: M1
    mision = gestor.misiones["obu-1"]
    assert mision.paradas["SINT-C"].estado == ESTADO_SOLICITADA
    assert len(reg.m1) == 1

    gestor.desarmar_mision("obu-1", motivo="boton")
    assert mision.activa is False
    assert mision.paradas["SINT-C"].estado == ESTADO_CANCELADA
    assert mision.paradas["SINT-F"].estado == ESTADO_CANCELADA
    assert any(c["motivo"] == "boton" for _, c in reg.m3)

    # Tras desarmar, un MP tardio no debe reactivar nada (ssec:minimizacion).
    antes = len(reg.m1)
    gestor.procesar_mp("obu-1", *NODOS_RUTA["F"], VELOCIDAD_KMH, 0.0)
    assert len(reg.m1) == antes


def test_m2_actualiza_estado_y_reenvia_me():
    gestor, reg = _gestor()
    gestor.armar_mision("obu-1", clase=1, origen=NODOS_RUTA["A"], destino=NODOS_RUTA["G"])
    gestor.procesar_mp("obu-1", *NODOS_RUTA["B"], VELOCIDAD_KMH, 0.0)
    id_solicitud = reg.m1[0][1]["id_solicitud"]

    gestor.procesar_m2({"id_solicitud": id_solicitud, "estado": "concedida", "fase": "verde"})
    mision = gestor.misiones["obu-1"]
    assert mision.paradas["SINT-C"].estado == "concedida"
    ultimo_me = reg.me[-1][1]
    assert ultimo_me["paradas"][0]["estado"] == "concedida"
    assert ultimo_me["paradas"][0]["fase"] == "verde"


# --- Conflicto: dos misiones, una misma RSU, accesos incompatibles --------


def _grafo_cruce():
    G = construir_grafo_cruce_sintetico()
    nodos = {nid: (data["y"], data["x"]) for nid, data in G.nodes(data=True)}
    return G, nodos


REGISTRO_CRUCE = [
    Interseccion("X-RSU", "X", -12.1074, -77.0320, (
        Acceso("S", 0.0, grupo_semaforico=1),    # llega del sur, rumbo norte
        Acceso("O", 90.0, grupo_semaforico=2),   # llega del oeste, rumbo este
    )),
]


def _gestor_cruce(**kwargs):
    grafo, nodos = _grafo_cruce()
    reg = _Registrador()
    gestor = GestorMision(
        grafo, REGISTRO_CRUCE,
        enviar_m1=reg.enviar_m1, enviar_m3=reg.enviar_m3, enviar_mr=reg.enviar_mr, enviar_me=reg.enviar_me,
        **kwargs,
    )
    return gestor, reg, nodos


def test_conflicto_gana_la_clase_de_mayor_prioridad():
    gestor, reg, nodos = _gestor_cruce()
    gestor.armar_mision("obu-a", clase=2, origen=nodos["S"], destino=nodos["N"])
    gestor.armar_mision("obu-b", clase=1, origen=nodos["O"], destino=nodos["E"])

    # Ambas entran a la geocerca (R_g=150 m) del cruce en el mismo paso.
    gestor.procesar_mp("obu-a", *nodos["S"], VELOCIDAD_KMH, rumbo_deg=0.0)
    gestor.procesar_mp("obu-b", *nodos["O"], VELOCIDAD_KMH, rumbo_deg=90.0)

    mision_a = gestor.misiones["obu-a"]
    mision_b = gestor.misiones["obu-b"]
    # B (clase 1, mayor prioridad) gana: queda solicitada; A queda en espera
    # y su solicitud (si llego a emitirse) se cancelo por conflicto.
    assert mision_b.paradas["X"].estado == ESTADO_SOLICITADA
    assert mision_a.paradas["X"].estado == ESTADO_EN_ESPERA
    assert any(c.get("motivo") == "conflicto" for _, c in reg.m3)
    assert any(acc == "O" for _, c in reg.m1 for acc in [c["acceso"]])


def test_conflicto_se_libera_al_desarmar_el_ganador():
    gestor, reg, nodos = _gestor_cruce()
    gestor.armar_mision("obu-a", clase=2, origen=nodos["S"], destino=nodos["N"])
    gestor.armar_mision("obu-b", clase=1, origen=nodos["O"], destino=nodos["E"])
    gestor.procesar_mp("obu-a", *nodos["S"], VELOCIDAD_KMH, rumbo_deg=0.0)
    gestor.procesar_mp("obu-b", *nodos["O"], VELOCIDAD_KMH, rumbo_deg=90.0)

    mision_a = gestor.misiones["obu-a"]
    assert mision_a.paradas["X"].estado == ESTADO_EN_ESPERA

    gestor.desarmar_mision("obu-b", motivo="boton")
    # Al liberarse el conflicto, A deja de estar "en_espera" (se promueve).
    assert mision_a.paradas["X"].estado != ESTADO_EN_ESPERA
