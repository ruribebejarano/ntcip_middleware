"""Casos de validacion de agent/rsu_middleware.py que el prompt_figuras_cap4.md
(M4) pidio agregar porque no tenian prueba todavia: M1 repetido (duplicado,
a nivel de la logica de rechazo -- no solo el texto de consola que ya cubre
tests/test_traduccion_eventos.py::test_rsu_m1_duplicado_se_descarta) y M1
invalido (campos faltantes/mal tipados). No duplica tests/test_ntcip1211.py
ni tests/test_traduccion_eventos.py."""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.rsu_middleware import _es_duplicado, _procesar_m1


def test_m1_repetido_mismo_seq_se_rechaza():
    """seq igual a la ultima vista: duplicado."""
    id_sol = "test-dup-mismo-seq"
    assert _es_duplicado(id_sol, 1) is False  # primera vez
    assert _es_duplicado(id_sol, 1) is True   # mismo seq otra vez


def test_m1_repetido_seq_menor_se_rechaza():
    """seq menor a la ultima vista (reenvio desordenado): duplicado."""
    id_sol = "test-dup-seq-menor"
    assert _es_duplicado(id_sol, 5) is False
    assert _es_duplicado(id_sol, 3) is True


def test_m1_seq_mayor_no_es_duplicado():
    """seq mayor (renovacion real, RF8): no es duplicado."""
    id_sol = "test-dup-seq-mayor"
    assert _es_duplicado(id_sol, 1) is False
    assert _es_duplicado(id_sol, 2) is False


def test_m1_invalido_sin_id_solicitud_no_lanza_excepcion(capsys):
    """M1 sin 'id_solicitud': _procesar_m1 debe descartarlo (KeyError
    capturado) sin propagar la excepcion ni tocar MQTT/EVENTOS."""
    msg = types.SimpleNamespace(topic="rsu/4/solicitudes")
    _procesar_m1(msg, {"seq": 1, "clase": 1})  # falta id_solicitud
    salida = capsys.readouterr().out
    assert "M1 invalido" in salida


def test_m1_invalido_seq_no_numerico_no_lanza_excepcion(capsys):
    """M1 con 'seq' no convertible a int: tambien se descarta sin lanzar."""
    msg = types.SimpleNamespace(topic="rsu/4/solicitudes")
    _procesar_m1(msg, {"id_solicitud": "mis-x-A", "seq": "no-es-un-numero"})
    salida = capsys.readouterr().out
    assert "M1 invalido" in salida
