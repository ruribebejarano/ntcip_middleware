"""Pruebas de servidor/conflictos.py (politica de arbitraje, sin MQTT ni
gestor de mision)."""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from servidor.conflictos import ArbitroConflictos, Solicitante, arbitrar


def _sol(mision_id, grupo, clase, eta_s, acceso_id="X"):
    return Solicitante(mision_id=mision_id, acceso_id=acceso_id, grupo_semaforico=grupo, clase=clase, eta_s=eta_s)


def test_mismo_grupo_semaforico_no_hay_conflicto():
    a = _sol("mis-a", grupo=1, clase=1, eta_s=10.0)
    b = _sol("mis-b", grupo=1, clase=2, eta_s=5.0)
    resultado = arbitrar("rsu-1", [a, b])
    assert not resultado.hubo_conflicto
    assert set(resultado.atendidos) == {a, b}
    assert resultado.en_espera == ()


def test_clase_mayor_prioridad_gana_sobre_clase_menor():
    # clase_tipo: numero MENOR = prioridad MAYOR (misma convencion de RF-05)
    prioritaria = _sol("mis-a", grupo=1, clase=1, eta_s=20.0)
    secundaria = _sol("mis-b", grupo=2, clase=3, eta_s=1.0)
    resultado = arbitrar("rsu-1", [secundaria, prioritaria])
    assert resultado.hubo_conflicto
    assert resultado.atendidos == (prioritaria,)
    assert resultado.en_espera == (secundaria,)


def test_misma_clase_gana_menor_eta():
    lejos = _sol("mis-lejos", grupo=1, clase=1, eta_s=30.0)
    cerca = _sol("mis-cerca", grupo=2, clase=1, eta_s=5.0)
    resultado = arbitrar("rsu-1", [lejos, cerca])
    assert resultado.atendidos == (cerca,)
    assert resultado.en_espera == (lejos,)


def test_empate_total_desempata_por_mision_id():
    a = _sol("mis-aaa", grupo=1, clase=1, eta_s=10.0)
    b = _sol("mis-bbb", grupo=2, clase=1, eta_s=10.0)
    resultado = arbitrar("rsu-1", [b, a])
    assert resultado.atendidos == (a,)
    assert resultado.en_espera == (b,)


def test_tres_solicitantes_dos_grupos_incompatibles():
    g1 = _sol("mis-g1", grupo=1, clase=2, eta_s=10.0)
    g1b = _sol("mis-g1b", grupo=1, clase=2, eta_s=12.0)   # compatible con g1 (mismo grupo)
    g2 = _sol("mis-g2", grupo=2, clase=1, eta_s=15.0)      # incompatible, pero clase 1 gana
    resultado = arbitrar("rsu-1", [g1, g1b, g2])
    assert resultado.hubo_conflicto
    assert set(resultado.atendidos) == {g2}
    assert set(resultado.en_espera) == {g1, g1b}


def test_arbitro_conflictos_recuerda_el_ultimo_resultado():
    arbitro = ArbitroConflictos()
    assert arbitro.ultimo_resultado("rsu-1") is None
    a = _sol("mis-a", grupo=1, clase=1, eta_s=5.0)
    resultado = arbitro.evaluar("rsu-1", [a])
    assert arbitro.ultimo_resultado("rsu-1") is resultado
