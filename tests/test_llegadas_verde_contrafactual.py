"""Pruebas de scripts/analisis/llegadas_verde_contrafactual.py (M2,
prompt_figuras_cap4.md) con eventos SINTETICOS (mismo patron que
tests/test_lazo_emulado_analisis.py), sin tocar las corridas reales."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.llegadas_verde_contrafactual import (
    demora_hasta_verde_s,
    fase_natural_en_cruce,
)

NS = 1_000_000_000


def ev(ts_s: float, nodo: str, tipo_evento: str, id_sol: str, **extra) -> dict:
    return {"ts_ns": round(ts_s * NS), "nodo": nodo, "tipo_evento": tipo_evento,
            "id_solicitud": id_sol, "extra": extra}


def test_demora_hasta_verde_verde_es_cero():
    esperado, dmin, dmax = demora_hasta_verde_s("verde")
    assert (esperado, dmin, dmax) == (0.0, 0.0, 0.0)


def test_demora_hasta_verde_rojo_general_rango_0_8():
    esperado, dmin, dmax = demora_hasta_verde_s("rojo_general")
    assert dmin == 0.0 and dmax == 8.0
    assert esperado == 4.0  # duracion/2, llegada uniforme


def test_demora_hasta_verde_amarillo_suma_fases_restantes():
    # amarillo (3s) -> resto = todo_rojo(2) + rojo_general(8) = 10
    esperado, dmin, dmax = demora_hasta_verde_s("amarillo")
    assert dmin == 10.0 and dmax == 13.0
    assert esperado == 11.5


def test_fase_natural_medida_por_liberacion_manual():
    """Si hay un ctrl_fase_cambio con motivo=liberacion_manual, esa es la
    fase sin prioridad en el cruce -- no se infiere nada."""
    eventos = [
        ev(0.0, "ctrl_1", "ctrl_fase_cambio", "req-1", fase="rojo_general", motivo="ciclo_normal"),
        ev(0.1, "ctrl_1", "ctrl_fase_cambio", "req-1", fase="verde", motivo="solicitud_prioridad"),
        ev(16.0, "ctrl_1", "ctrl_fase_cambio", "req-1", fase="todo_rojo", motivo="liberacion_manual"),
    ]
    fase, metodo = fase_natural_en_cruce(eventos, "concedida")
    assert (fase, metodo) == ("todo_rojo", "medido_liberacion")


def test_fase_natural_sin_cambio_infiere_verde():
    """Decision en verde, ninguna fila nueva al liberar: la fase natural en
    el cruce tambien era verde (no se logueo cambio porque no lo hubo)."""
    eventos = [
        ev(0.0, "ctrl_1", "ctrl_fase_cambio", "req-1", fase="verde", motivo="solicitud_prioridad"),
    ]
    fase, metodo = fase_natural_en_cruce(eventos, "concedida")
    assert (fase, metodo) == ("verde", "medido_sin_cambio")


def test_fase_natural_sin_dato_si_nunca_hubo_prioridad():
    """Sin ningun evento de referencia (p. ej. 'rechazada'): no se inventa
    una fase, se marca explicitamente como sin dato."""
    fase, metodo = fase_natural_en_cruce([], "rechazada")
    assert (fase, metodo) == (None, "sin_dato")
