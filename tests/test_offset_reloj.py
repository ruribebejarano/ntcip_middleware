"""Pruebas de scripts/analisis/offset_reloj.py (M6, prompt_figuras_cap4.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.offset_reloj import distancia_por_error_s, offset_ms

TEXTO_SINCRONIZADO = """
Reference ID    : D8EF2300 (time1.google.com)
Stratum         : 2
System time     : 0.001634349 seconds slow of NTP time
Root delay      : 0.039570846 seconds
Root dispersion : 0.003108545 seconds
Leap status     : Normal
"""

TEXTO_ADELANTADO = """
System time     : 0.002 seconds fast of NTP time
Root delay      : 0.01 seconds
Root dispersion : 0.001 seconds
Leap status     : Normal
"""


def test_offset_ms_atrasado_es_negativo():
    assert offset_ms(TEXTO_SINCRONIZADO) == -1.634349


def test_offset_ms_adelantado_es_positivo():
    assert abs(offset_ms(TEXTO_ADELANTADO) - 2.0) < 1e-9


def test_offset_ms_sin_texto_es_none():
    assert offset_ms(None) is None
    assert offset_ms("texto sin el campo System time") is None


def test_distancia_por_error_s_1s_a_50kmh_es_13_9m():
    d = distancia_por_error_s(1.0, 50.0)
    assert abs(d - 13.888888888888889) < 1e-6
