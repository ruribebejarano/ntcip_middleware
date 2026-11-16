"""Pruebas de servidor/seguridad.py::MonitorSeguridad (sin red ni broker)."""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from gateway.geometria import desplazar  # noqa: E402
from servidor.seguridad import MonitorSeguridad  # noqa: E402

LAT0, LON0 = -12.11, -77.032


class _Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _monitor(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    alertas, suspendidas = [], []
    reloj = _Reloj()
    m = MonitorSeguridad(None, alertas.append, lambda obu, motivo: suspendidas.append((obu, motivo)), ahora=reloj)
    return m, alertas, suspendidas, reloj


def test_trayectoria_normal_no_alerta(monkeypatch):
    m, alertas, _s, reloj = _monitor(monkeypatch)
    for k in range(30):
        lat, lon = desplazar(LAT0, LON0, 0.0, 10.0 * k)  # 36 km/h a 1 Hz
        assert m.al_recibir_mp("obu-a", lat, lon, 1_000_000 + 1000 * k)
        reloj.t += 1.0
    assert alertas == []


def test_rafaga_tras_reconexion_no_es_salto(monkeypatch):
    """MP retenidos que llegan juntos: el intervalo se toma de ts_ms de la OBU."""
    m, alertas, _s, reloj = _monitor(monkeypatch)
    for k in range(10):
        lat, lon = desplazar(LAT0, LON0, 0.0, 10.0 * k)
        m.al_recibir_mp("obu-a", lat, lon, 1_000_000 + 1000 * k)
        reloj.t += 0.01
    assert [a for a in alertas if a["alerta"] == "salto_posicion"] == []


def test_clon_salto_alerta_y_suspende_con_politica_suspender(monkeypatch):
    m, alertas, suspendidas, reloj = _monitor(monkeypatch, SEG_POLITICA="suspender")
    m.al_recibir_mp("obu-c", LAT0, LON0, 1_000_000)
    reloj.t += 1.0
    lat, lon = desplazar(LAT0, LON0, 90.0, 3000.0)
    assert not m.al_recibir_mp("obu-c", lat, lon, 1_001_000)
    assert alertas[0]["alerta"] == "salto_posicion" and alertas[0]["severidad"] == "alta"
    assert suspendidas == [("obu-c", "suspendida_automatico")]
    assert not m.al_recibir_mp("obu-c", LAT0, LON0, 1_002_000)  # ya suspendida: se ignora


def test_politica_alertar_no_suspende_sola(monkeypatch):
    m, alertas, suspendidas, reloj = _monitor(monkeypatch)
    m.al_recibir_mp("obu-c", LAT0, LON0, 1_000_000)
    reloj.t += 1.0
    lat, lon = desplazar(LAT0, LON0, 90.0, 3000.0)
    assert m.al_recibir_mp("obu-c", lat, lon, 1_001_000)
    assert alertas and suspendidas == []


def test_inundacion(monkeypatch):
    m, alertas, _s, reloj = _monitor(monkeypatch, SEG_TASA_MAX_HZ=3, SEG_VENTANA_S=5)
    for k in range(20):  # 20 MP en 0,4 s
        m.al_recibir_mp("obu-f", LAT0, LON0, 1_000_000 + 20 * k)
        reloj.t += 0.02
    assert any(a["alerta"] == "inundacion" for a in alertas)
    assert sum(1 for a in alertas if a["alerta"] == "inundacion") == 1  # una alerta, no una por MP


def test_comando_operador_suspende_y_reanuda(monkeypatch):
    m, _a, suspendidas, _r = _monitor(monkeypatch)
    assert m.comando({"accion": "suspender_obu", "obu_id": "obu-x", "motivo": "despacho_sin_emergencia"}) is None
    assert suspendidas == [("obu-x", "suspendida_operador")]
    assert not m.al_recibir_mi("obu-x")
    assert m.comando({"accion": "reanudar_obu", "obu_id": "obu-x"}) is None
    assert m.al_recibir_mi("obu-x")
    assert m.comando({"accion": "borrar_todo", "obu_id": "obu-x"}) is not None


def test_confirmacion_obligatoria(monkeypatch):
    m, alertas, suspendidas, reloj = _monitor(monkeypatch, SEG_CONFIRMACION_S=20)
    m.al_armar_mision("obu-ok", "mis-1")
    m.al_armar_mision("obu-falsa", "mis-2")
    assert {a["alerta"] for a in alertas} == {"verificacion_despacho"}
    m.comando({"accion": "confirmar_mision", "obu_id": "obu-ok"})
    reloj.t += 19.0
    m.revisar_confirmaciones()
    assert suspendidas == []
    reloj.t += 1.5
    m.revisar_confirmaciones()
    assert suspendidas == [("obu-falsa", "sin_confirmacion_despacho")]


def test_mi_repetido_no_reinicia_la_verificacion(monkeypatch):
    m, alertas, _s, _r = _monitor(monkeypatch)
    m.al_armar_mision("obu-a", "mis-1")
    m.al_armar_mision("obu-a", "mis-1")
    assert sum(1 for a in alertas if a["alerta"] == "verificacion_despacho") == 1
