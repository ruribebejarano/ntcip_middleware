"""Pruebas de scripts/campanas/lazo_centralizado.py: el chequeo de una
sola conexión al broker por repetición. Causa real de una campaña
contaminada el 2026-10-28 (ver docs/bitacora/
2026-10-28_campana-centralizada-lazo-desvio.md): el rsu-agent.service de
la Pi, con su broker.conf apuntando al broker de la laptop y el mismo
RSU_ID, usaba el mismo client_id que el agente local y Mosquitto
expulsaba a uno de los dos en bucle de reconexión -- NO fue falta de
memoria. Este archivo prueba el chequeo en aislado, con logs sintéticos
(no se puede reproducir el choque real sin dos procesos de verdad)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RUTA_MODULO = RAIZ / "scripts" / "campanas" / "lazo_centralizado.py"
# Import por ruta (no por sys.path + nombre) a propósito: scripts/analisis/
# también tiene un módulo llamado "lazo_centralizado" (ver
# tests/test_lazo_centralizado.py) -- importar ambos por nombre en la
# misma sesión de pytest pisaría uno con el otro en sys.modules.
_spec = importlib.util.spec_from_file_location("campana_lazo_centralizado", _RUTA_MODULO)
campana = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(campana)


def test_contar_conexiones_broker_una_sola_vez(tmp_path: Path) -> None:
    log = tmp_path / "agent.log"
    log.write_text(
        "=== Middleware RSU: SNMP + V2I (MQTT) + adaptador de controlador ===\n"
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n"
        "[middleware] Escuchando solicitudes V2I en mqtt://127.0.0.1:1883\n",
        encoding="utf-8",
    )
    assert campana._contar_conexiones_broker(log) == 1


def test_contar_conexiones_broker_detecta_reconexiones(tmp_path: Path) -> None:
    """El síntoma real: ~5 reconexiones por repetición en la campaña
    contaminada (choque de client_id con el agente de la Pi)."""
    log = tmp_path / "agent.log"
    log.write_text(
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n"
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n"
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n",
        encoding="utf-8",
    )
    assert campana._contar_conexiones_broker(log) == 3


def test_contar_conexiones_broker_log_inexistente(tmp_path: Path) -> None:
    assert campana._contar_conexiones_broker(tmp_path / "no_existe.log") == 0


def test_verificar_una_sola_conexion_aborta_si_hay_reconexiones(tmp_path: Path) -> None:
    rep_dir = tmp_path / "rep_02"
    rep_dir.mkdir()
    (rep_dir / "agent.log").write_text(
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n"
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n",
        encoding="utf-8",
    )
    try:
        campana._verificar_una_sola_conexion(rep_dir)
    except SystemExit as exc:
        assert "choque de client_id" in str(exc)
    else:
        raise AssertionError("se esperaba SystemExit: agent.log tiene 2 conexiones, no 1")


def test_verificar_una_sola_conexion_ok_con_una_sola(tmp_path: Path) -> None:
    rep_dir = tmp_path / "rep_01"
    rep_dir.mkdir()
    (rep_dir / "agent.log").write_text(
        "[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=Success\n",
        encoding="utf-8",
    )
    (rep_dir / "servidor.log").write_text(
        "[servidor] Conectado al broker (127.0.0.1:1883), reason_code=Success\n",
        encoding="utf-8",
    )
    campana._verificar_una_sola_conexion(rep_dir)  # no debe lanzar
