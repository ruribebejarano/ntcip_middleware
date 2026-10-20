"""Pruebas de scripts/analisis/lazo_emulado.py con eventos SINTETICOS (sin
red, sin broker): construyen directamente la lista de eventos que normalmente
produce common.events.iter_eventos(), para verificar el calculo de L, T_desp,
t_OBU, t_up y t_down (ssec:metricas de main.tex, docs/MEDICION_LATENCIA.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.lazo_emulado import analizar  # noqa: E402

NS = 1_000_000  # 1 ms en ns


def ev(ts_ms: float, nodo: str, tipo_evento: str, id_sol: str, **extra) -> dict:
    """Construye un evento con la misma forma que common.events.iter_eventos()."""
    return {
        "ts_ns": round(ts_ms * NS),
        "nodo": nodo,
        "tipo_evento": tipo_evento,
        "id_solicitud": id_sol,
        "extra": extra,
        "archivo": f"eventos_{nodo}.csv",
    }


def test_solicitud_aceptada_en_verde_calcula_L_sin_T_desp():
    """Fase ya en verde: la RSU escribe directo (request_priority), sin cola.
    L = snmp_set_tx - M1_tx(seq 1); T_desp no existe (None)."""
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-1", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(12.0, "rsu_1", "M1_rx", "req-1", seq=1),
        ev(15.0, "rsu_1", "snmp_set_tx", "req-1", origen="v2i", accion="request_priority"),
        ev(40.0, "ctrl_1", "ctrl_fase_cambio", "req-1", fase="verde", motivo="solicitud_prioridad"),
        ev(55.0, "obu", "M2_rx", "req-1", estado="concedida", fase="verde", rtt_ms=55.0),
    ]
    filas, g = analizar(eventos)
    assert len(filas) == 1
    f = filas[0]
    assert f["L_ms"] == 15.0
    assert f["t_V2I_ms"] == 12.0
    assert f["t_RSU_ms"] == 3.0
    assert f["T_desp_ms"] is None
    assert f["t_hasta_verde_con_despeje_ms"] == 40.0
    assert f["resultado"] == "concedida"
    assert g["rnf01_cumple_p95"] is True


def test_solicitud_encolada_en_ambar_calcula_L_y_T_desp_por_separado():
    """Fase en ambar: la RSU encola (en_cola_despeje) y activa despues
    (activar_cola_rf06, watchdog). L termina en el encolado, NO en la
    activacion; T_desp es exactamente la espera entre ambas."""
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-2", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(10.0, "rsu_1", "M1_rx", "req-2", seq=1),
        ev(18.0, "rsu_1", "snmp_set_tx", "req-2", origen="v2i", accion="en_cola_despeje", fase="amarillo"),
        ev(2018.0, "rsu_1", "snmp_set_tx", "req-2", origen="watchdog", accion="activar_cola_rf06"),
        ev(2030.0, "ctrl_1", "ctrl_fase_cambio", "req-2", fase="verde", motivo="solicitud_prioridad"),
        ev(2045.0, "obu", "M2_rx", "req-2", estado="concedida", fase="verde", rtt_ms=45.0),
    ]
    filas, g = analizar(eventos)
    assert len(filas) == 1
    f = filas[0]
    assert f["L_ms"] == 18.0  # hasta el encolado, no hasta la activacion
    assert f["T_desp_ms"] == 2000.0  # 2018 - 18
    assert f["t_hasta_verde_con_despeje_ms"] == 2030.0  # L + T_desp + margen, no es L
    assert f["L_ms"] < f["t_hasta_verde_con_despeje_ms"]
    assert g["rnf01_cumple_p95"] is True  # L (18 ms) sigue cumpliendo RNF-01, aunque el verde tarde 2 s


def test_solicitud_rechazada_no_tiene_L():
    """RF-05 (clase no reconocida): snmp_set_tx con accion=rechazada no es
    una decision NTCIP -- no cuenta para L."""
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-3", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(10.0, "rsu_1", "M1_rx", "req-3", seq=1),
        ev(12.0, "rsu_1", "snmp_set_tx", "req-3", origen="v2i", accion="rechazada", motivo="clase_no_reconocida"),
        ev(20.0, "obu", "M2_rx", "req-3", estado="rechazada", rtt_ms=20.0),
    ]
    filas, _g = analizar(eventos)
    assert filas[0]["L_ms"] is None
    assert filas[0]["resultado"] == "rechazada"


def test_rnf01_no_cumple_si_p95_supera_1000ms():
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-lenta", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(1200.0, "rsu_1", "M1_rx", "req-lenta", seq=1),
        ev(1300.0, "rsu_1", "snmp_set_tx", "req-lenta", origen="v2i", accion="request_priority"),
    ]
    _filas, g = analizar(eventos)
    assert g["L_ms"]["p95"] == 1300.0
    assert g["rnf01_cumple_p95"] is False


def test_t_obu_usa_el_evento_muestra_de_la_misma_fila():
    """t_OBU = M1_tx - muestra, emparejados por (nodo, t_tray_s): la muestra
    se registra ANTES de la decision de geometria (gateway/obu_emulada.py),
    con id_solicitud="-"."""
    eventos = [
        ev(0.0, "obu", "muestra", "-", t_tray_s=5.0),
        ev(3.0, "obu", "M1_tx", "req-4", seq=1, rsu_id="1", t_tray_s=5.0,
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(15.0, "rsu_1", "M1_rx", "req-4", seq=1),
        ev(18.0, "rsu_1", "snmp_set_tx", "req-4", origen="v2i", accion="request_priority"),
    ]
    filas, _g = analizar(eventos)
    assert filas[0]["t_OBU_ms"] == 3.0


def test_t_obu_es_none_sin_evento_muestra():
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-5", seq=1, rsu_id="1", t_tray_s=5.0,
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(10.0, "rsu_1", "M1_rx", "req-5", seq=1),
        ev(12.0, "rsu_1", "snmp_set_tx", "req-5", origen="v2i", accion="request_priority"),
    ]
    filas, _g = analizar(eventos)
    assert filas[0]["t_OBU_ms"] is None


def test_t_up_y_t_down_con_testigo_del_broker():
    """t_up = broker_rx(M1) - M1_tx; t_down = M1_rx - broker_rx(M1): ambas
    cruzan el reloj del testigo (= reloj del broker) con el de un extremo."""
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-6", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(4.0, "testigo", "broker_rx", "req-6", tipo="M1", seq=1, topic="rsu/1/solicitudes"),
        ev(9.0, "rsu_1", "M1_rx", "req-6", seq=1),
        ev(12.0, "rsu_1", "snmp_set_tx", "req-6", origen="v2i", accion="request_priority"),
    ]
    filas, _g = analizar(eventos)
    f = filas[0]
    assert f["t_up_ms"] == 4.0
    assert f["t_down_ms"] == 5.0
    assert f["t_V2I_ms"] == 9.0
    assert f["t_up_ms"] + f["t_down_ms"] == f["t_V2I_ms"]


def test_t_up_y_t_down_son_none_sin_testigo():
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-7", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(9.0, "rsu_1", "M1_rx", "req-7", seq=1),
    ]
    filas, _g = analizar(eventos)
    assert filas[0]["t_up_ms"] is None
    assert filas[0]["t_down_ms"] is None


def test_rtt_mitad_es_la_mitad_de_la_mediana():
    eventos = [
        ev(0.0, "obu", "M1_tx", "req-8", seq=1, rsu_id="1",
           interseccion_id="A", acceso="O", verdad_interseccion="A", verdad_acceso="O"),
        ev(10.0, "rsu_1", "M1_rx", "req-8", seq=1),
        ev(12.0, "rsu_1", "snmp_set_tx", "req-8", origen="v2i", accion="request_priority"),
        ev(20.0, "obu", "M2_rx", "req-8", estado="recibida", rtt_ms=20.0),
        ev(30.0, "obu", "M2_rx", "req-8", estado="concedida", rtt_ms=30.0),
    ]
    filas, _g = analizar(eventos)
    assert filas[0]["rtt_mediana_ms"] == 20.0
    assert filas[0]["rtt_mitad_ms"] == 10.0
