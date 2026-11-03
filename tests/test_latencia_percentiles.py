"""Pruebas de scripts/analisis/latencia_percentiles.py (M5,
prompt_figuras_cap4.md) con eventos sinteticos minimos. En particular,
test_recuperacion_no_mezcla_repeticiones es una prueba de regresion: la
primera version de buscar_recuperacion_plan agrupaba por nodo sin separar
por repeticion, y contaba el arranque del controlador de la SIGUIENTE
repeticion como si fuera la recuperacion de la anterior (dio una mediana
de 96 s con datos reales, groseramente mayor al ciclo de 21 s -- seria
facil reintroducir el mismo error sin esta prueba)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.latencia_percentiles import buscar_recuperacion_plan, extraer_t_obu_srv

CAMPOS = ["ts_ns", "nodo", "tipo_evento", "id_solicitud", "extra_json"]


def _escribir(directorio: Path, nodo: str, filas: list[tuple]) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    with (directorio / f"eventos_{nodo}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CAMPOS)
        for ts_ns, tipo_evento, id_sol, extra in filas:
            w.writerow([ts_ns, nodo, tipo_evento, id_sol, json.dumps(extra)])


def test_extraer_t_obu_srv_empareja_por_obu_id_y_seq():
    eventos = [
        {"tipo_evento": "mision_armada", "id_solicitud": "mis-1", "extra": {"obu_id": "obu-a"}, "ts_ns": 0},
        {"tipo_evento": "MP_tx", "nodo": "obu-a", "id_solicitud": "-", "extra": {"seq": 1}, "ts_ns": 100_000_000},
        {"tipo_evento": "MP_rx", "id_solicitud": "mis-1", "extra": {"seq": 1}, "ts_ns": 105_000_000},
    ]
    vals = extraer_t_obu_srv(eventos)
    assert vals == [5.0]  # (105-100) ms


def test_recuperacion_no_mezcla_repeticiones(tmp_path):
    """rep_01 libera y NUNCA vuelve a ciclo_normal dentro de esa misma
    repeticion; rep_02 arranca despues (mismo nodo ctrl_1, config=local).
    No debe contarse el arranque de rep_02 como recuperacion de rep_01."""
    campana = tmp_path / "campana"
    _escribir(campana / "rep_01", "ctrl_1", [
        (0, "ctrl_fase_cambio", "-", {"fase": "verde", "motivo": "ciclo_normal"}),
        (1_000_000_000, "ctrl_fase_cambio", "req-1", {"fase": "verde", "motivo": "solicitud_prioridad"}),
        (5_000_000_000, "ctrl_fase_cambio", "req-1", {"fase": "rojo_general", "motivo": "liberacion_manual"}),
        # sin mas eventos en rep_01: no hay recuperacion observada aqui.
    ])
    _escribir(campana / "rep_02", "ctrl_1", [
        # arranca ~20s despues (nueva pausa aleatoria), proceso NUEVO.
        (25_000_000_000, "ctrl_fase_cambio", "-", {"fase": "amarillo", "motivo": "ciclo_normal"}),
    ])

    filas = buscar_recuperacion_plan([campana])
    assert len(filas) == 1  # solo la liberacion de rep_01
    assert filas[0]["tiempo_recuperacion_s"] is None  # NO debe encontrar el ciclo_normal de rep_02


def test_recuperacion_detecta_ciclo_normal_dentro_de_la_misma_repeticion(tmp_path):
    campana = tmp_path / "campana"
    _escribir(campana / "rep_01", "ctrl_1", [
        (0, "ctrl_fase_cambio", "req-1", {"fase": "verde", "motivo": "solicitud_prioridad"}),
        (5_000_000_000, "ctrl_fase_cambio", "req-1", {"fase": "rojo_general", "motivo": "liberacion_manual"}),
        (7_000_000_000, "ctrl_fase_cambio", "-", {"fase": "rojo_general", "motivo": "ciclo_normal"}),
    ])
    filas = buscar_recuperacion_plan([campana])
    assert len(filas) == 1
    assert filas[0]["tiempo_recuperacion_s"] == 2.0
