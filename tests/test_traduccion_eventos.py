"""Pruebas de common/traduccion_eventos.py (usado por scripts/demo/
linea_tiempo.py y por consola/backend/eventos_remotos.py, ver
docs/CONSOLA.md): traduccion de un evento RF-10 a una frase en espanol."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.traduccion_eventos import describir  # noqa: E402


def _e(tipo: str, **extra) -> dict:
    return {"tipo": tipo, "x": extra}


def test_m1_nueva_solicitud_obu():
    frase = describir("OBU", _e("M1_tx", seq=1, rsu_id="1", interseccion_id="OSM-C24", acceso="O", distancia_m=142.0))
    assert "NUEVA SOLICITUD" in frase
    assert "rsu/1/solicitudes" in frase
    assert "OSM-C24" in frase and "O" in frase


def test_m1_actualizacion_obu():
    frase = describir("OBU", _e("M1_tx", seq=5))
    assert "actualizacion #5" in frase


def test_m2_concedida_con_rtt():
    frase = describir("OBU", _e("M2_rx", estado="concedida", fase="verde", rtt_ms=14.2))
    assert "CONCEDIDA" in frase
    assert "VERDE" in frase
    assert "14.2 ms" in frase


def test_m2_sin_rtt_aviso_inmediato():
    frase = describir("OBU", _e("M2_rx", estado="concedida", fase="verde", rtt_ms=None))
    assert "aviso inmediato" in frase


def test_rsu_m1_duplicado_se_descarta():
    frase = describir("RSU", _e("M1_rx", duplicado=True, seq=3))
    assert "duplicado" in frase


def test_rsu_m1_actualizacion_no_se_muestra():
    assert describir("RSU", _e("M1_rx", seq=2)) is None


def test_rsu_en_cola_despeje_rf06():
    frase = describir("RSU", _e("snmp_set_tx", accion="en_cola_despeje", fase="amarillo"))
    assert "ESPERA" in frase
    assert "AMBAR" in frase


def test_rsu_rechazo_rf05():
    frase = describir("RSU", _e("snmp_set_tx", accion="rechazada", motivo="clase_no_reconocida"))
    assert "RECHAZA" in frase
    assert "clase_no_reconocida" in frase


def test_rsu_caducidad():
    frase = describir("RSU", _e("caducidad"))
    assert "CADUCIDAD" in frase


def test_rsu_m2_tx_no_se_muestra():
    assert describir("RSU", _e("M2_tx", estado="concedida")) is None


def test_ctrl_cambio_de_fase():
    frase = describir("CTRL", _e("ctrl_fase_cambio", fase="verde", motivo="solicitud_prioridad"))
    assert "VERDE" in frase
    assert "por la prioridad" in frase


def test_evento_desconocido_no_se_muestra():
    assert describir("CTRL", _e("algo_que_no_existe")) is None
