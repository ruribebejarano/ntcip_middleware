"""Prueba de regresion de scripts/analisis/graficos_campana.py::fig_tramos():
no debe reventar cuando una corrida no tiene NINGUN dato de t_V2I/t_RSU/L
(p. ej. si todavia no se trajeron los eventos de la RSU con
scripts/pi.sh fetch -- solo quedan eventos M1_tx/M2_rx del lado OBU).
Bug real, reproducido tambien desde la linea de comandos antes de este
arreglo (ver docs/bitacora/2026-10-20_consola-web.md)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.graficos_campana import fig_tramos, metricas  # noqa: E402

NS = 1_000_000


def _ev(ts_ms: float, nodo: str, tipo_evento: str, id_sol: str, **extra) -> dict:
    return {"ts_ns": round(ts_ms * NS), "nodo": nodo, "tipo_evento": tipo_evento,
            "id_solicitud": id_sol, "extra": extra, "archivo": f"eventos_{nodo}.csv"}


def _eventos_solo_obu() -> list[dict]:
    """Solo M1_tx/M2_rx del lado OBU: sin M1_rx ni snmp_set_tx de la RSU,
    asi m["t_V2I"], m["t_RSU"] y m["L"] quedan vacios mientras que
    m["rtt"] si tiene datos (es lo que exportar_figuras() recibe si se le
    exportan figuras a una corrida sin los eventos de la RSU todavia)."""
    return [
        _ev(0.0, "obu", "M1_tx", "req-1", seq=1),
        _ev(20.0, "obu", "M2_rx", "req-1", estado="concedida", fase="verde", rtt_ms=20.0),
    ]


def test_fig_tramos_sin_datos_de_tramo_no_revienta():
    m = metricas(_eventos_solo_obu())
    assert m["rtt"] == [20.0]
    assert m["t_V2I"] == [] and m["t_RSU"] == [] and m["L"] == []

    fig, ax = plt.subplots()
    try:
        fig_tramos(ax, m)  # no debe levantar ValueError
    finally:
        plt.close(fig)


def test_fig_tramos_con_datos_sigue_dibujando_cajas():
    eventos = [
        _ev(0.0, "obu", "M1_tx", "req-1", seq=1),
        _ev(12.0, "rsu_1", "M1_rx", "req-1", seq=1),
        _ev(15.0, "rsu_1", "snmp_set_tx", "req-1", accion="request_priority"),
        _ev(55.0, "obu", "M2_rx", "req-1", estado="concedida", fase="verde", rtt_ms=55.0),
    ]
    m = metricas(eventos)
    assert m["t_V2I"] == [12.0] and m["L"] == [15.0]

    fig, ax = plt.subplots()
    try:
        fig_tramos(ax, m)
        assert len(ax.get_xticks()) == 3  # t_V2I, t_RSU, L
    finally:
        plt.close(fig)


def test_cli_completo_sin_eventos_de_rsu_termina_en_codigo_0(tmp_path):
    """Reproduce el fallo original de punta a punta por la CLI (sin pasar
    por fig_tramos directamente): generaba una corrida con solo eventos
    OBU (sin RSU) y exportaba figuras. Antes del arreglo, esto terminaba
    con dos tracebacks distintos: uno en fig_tramos() (ValueError de
    matplotlib) y, arreglado ese, otro en el print final del resumen
    (TypeError: unsupported format string passed to NoneType)."""
    raiz = Path(__file__).resolve().parent.parent
    from common.events import EventLogger

    EventLogger("obu", directorio=tmp_path).log("M1_tx", "req-1", seq=1)
    EventLogger("obu", directorio=tmp_path).log("M2_rx", "req-1", estado="concedida", fase="verde", rtt_ms=20.0)

    r = subprocess.run(
        [sys.executable, str(raiz / "scripts" / "analisis" / "graficos_campana.py"),
         "--dir", str(tmp_path), "--salida", str(tmp_path / "figuras"), "--nota", "prueba"],
        cwd=raiz, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert (tmp_path / "figuras" / "fig_tramos.png").exists()
    assert (tmp_path / "figuras" / "tabla_latencia.tex").exists()
