"""Pruebas de consola/backend/analisis.py: que la pantalla "Ensayos y
metricas" calcule lo mismo que scripts/analisis/lazo_emulado.py (reusado
tal cual, ver test_lazo_emulado_analisis.py para las formulas) y que el
intervalo de Wilson del PDR comparado sea razonable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import EventLogger  # noqa: E402
from consola.backend import analisis, config  # noqa: E402

NS = 1_000_000


def _escribir_corrida(base: Path, nombre: str) -> Path:
    corrida = base / nombre
    (corrida).mkdir(parents=True)
    (corrida / "config.json").write_text(json.dumps({"commit": "abc123", "escenarios": ["transversal_a"]}),
                                         encoding="utf-8")
    obu = EventLogger("obu", directorio=corrida)
    rsu = EventLogger("rsu_1", directorio=corrida)
    obu.log("M1_tx", "req-1", seq=1, rsu_id="1", interseccion_id="A", acceso="O",
            verdad_interseccion="A", verdad_acceso="O")
    rsu.log("M1_rx", "req-1", seq=1)
    rsu.log("snmp_set_tx", "req-1", origen="v2i", accion="request_priority")
    obu.log("M2_rx", "req-1", estado="concedida", fase="verde", rtt_ms=20.0)
    return corrida


@pytest.fixture
def banco_corridas(tmp_path, monkeypatch):
    base = tmp_path / "lazo_emulado"
    monkeypatch.setattr(config, "DIR_LAZO_EMULADO", base)
    monkeypatch.setattr(analisis, "DIR_RSU_FETCHED", tmp_path / "no_existe")
    _escribir_corrida(base, "20260101-000000")
    _escribir_corrida(base, "20260101-000100")
    return base


def test_listar_corridas_lee_config_json(banco_corridas):
    corridas = analisis.listar_corridas()
    nombres = {c["nombre"] for c in corridas}
    assert nombres == {"20260101-000000", "20260101-000100"}
    assert all(c["config"]["commit"] == "abc123" for c in corridas)


def test_resumen_corrida_usa_lazo_emulado_analizar(banco_corridas):
    r = analisis.resumen_corrida("20260101-000000")
    assert r is not None
    assert r["global"]["solicitudes"] == 1
    # EventLogger.log() usa time.time_ns() real (no un reloj sintetico, a
    # diferencia de test_lazo_emulado_analisis.py): solo se verifica que la
    # formula se aplico (L >= 0), no un valor exacto.
    assert r["global"]["L_ms"]["mediana"] >= 0
    assert r["global"]["resultados"]["concedida"] == 1
    assert r["por_solicitud"][0]["id_solicitud"] == "req-1"
    assert "rtt" in r["graficos"]  # scripts/analisis/graficos_campana.metricas()


def test_resumen_corrida_inexistente_da_none(banco_corridas):
    assert analisis.resumen_corrida("no-existe") is None


def test_comparar_corridas_incluye_wilson(banco_corridas):
    r = analisis.comparar_corridas([("20260101-000000", "A"), ("20260101-000100", "B")])
    assert [c["etiqueta"] for c in r["condiciones"]] == ["A", "B"]
    for c in r["condiciones"]:
        w = c["pdr_wilson"]
        assert w["n"] > 0
        assert 0 <= w["inferior"] <= w["p"] <= w["superior"] <= 1


def test_wilson_sin_mensajes_da_none():
    w = analisis._wilson(0, 0)
    assert w["p"] is None and w["n"] == 0


def test_wilson_intervalo_se_angosta_con_mas_datos():
    chico = analisis._wilson(9, 10)
    grande = analisis._wilson(900, 1000)
    assert (grande["superior"] - grande["inferior"]) < (chico["superior"] - chico["inferior"])
