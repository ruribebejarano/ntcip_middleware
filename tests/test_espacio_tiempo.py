"""Pruebas de scripts/analisis/espacio_tiempo.py (M1, prompt_figuras_cap4.md)
con datos sinteticos minimos, sin tocar la corrida real de
resultados/espacio_tiempo/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.espacio_tiempo import distancia_acumulada, fase_en_decision_y_liberacion

NS = 1_000_000_000


def ev(ts_s: float, tipo_evento: str, id_sol: str, **extra) -> dict:
    return {"ts_ns": round(ts_s * NS), "tipo_evento": tipo_evento, "id_solicitud": id_sol, "extra": extra}


def test_distancia_acumulada_tramo_recto_norte():
    """~111.32 km por grado de latitud -> 0.001 deg norte ~ 111.32 m."""
    tray = [{"lat": -12.0, "lon": -77.0}, {"lat": -11.999, "lon": -77.0}]
    dist = distancia_acumulada(tray)
    assert dist[0] == 0.0
    assert 110.0 < dist[1] < 112.5


def test_fase_decision_verde_sin_cambio_logueado_usa_snmp_set_tx():
    """Decision ya en verde: no hay fila 'solicitud_prioridad' en
    ctrl_fase_cambio (ver controller_emulator.py), se debe caer al propio
    snmp_set_tx como referencia de ts/fase."""
    eventos = [
        ev(0.0, "snmp_set_tx", "req-1", origen="v2i", accion="request_priority", fase="verde"),
        ev(10.0, "ctrl_fase_cambio", "req-1", fase="todo_rojo", motivo="liberacion_manual"),
    ]
    info = fase_en_decision_y_liberacion(eventos, "req-1")
    assert info["fase_decision"] == "verde"
    assert info["ts_verde"] == 0
    assert info["fase_liberacion"] == "todo_rojo"
    assert info["ts_liberacion"] == 10 * NS


def test_fase_liberacion_sin_evento_infiere_verde_sostenido():
    eventos = [
        ev(0.0, "snmp_set_tx", "req-1", origen="v2i", accion="request_priority", fase="rojo_general"),
        ev(0.1, "ctrl_fase_cambio", "req-1", fase="verde", motivo="solicitud_prioridad"),
    ]
    info = fase_en_decision_y_liberacion(eventos, "req-1")
    assert info["fase_liberacion"] == "verde"
    assert info["ts_liberacion"] is None  # sin evento nuevo: no se inventa un instante
