"""Pruebas de scripts/analisis/validacion_ntcip.py (M4, prompt_figuras_cap4.md)
con eventos sinteticos minimos, sin tocar las corridas reales ni volver a
correr pytest (eso se prueba por separado, ejecutando el script completo
manualmente -- ver informe de la sesion)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.validacion_ntcip import analizar_traduccion

CAMPOS = ["ts_ns", "nodo", "tipo_evento", "id_solicitud", "extra_json"]


def _escribir_eventos(directorio: Path, nodo: str, filas: list[tuple]) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    with (directorio / f"eventos_{nodo}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CAMPOS)
        for ts_ns, tipo_evento, id_sol, extra in filas:
            import json
            w.writerow([ts_ns, nodo, tipo_evento, id_sol, json.dumps(extra)])


def test_traduccion_completa_se_cuenta_correcta(tmp_path):
    d = tmp_path / "corrida"
    _escribir_eventos(d, "rsu_1", [
        (0, "M1_rx", "req-1", {"seq": 1}),
        (5_000_000, "snmp_set_tx", "req-1", {"accion": "request_priority", "fase": "verde"}),
        (10_000_000, "M3_rx", "req-1", {"motivo": "cruce"}),
        (15_000_000, "snmp_set_tx", "req-1", {"accion": "clear_priority_m3"}),
    ])
    r = analizar_traduccion([d])
    assert r["n_m1_iniciales"] == 1
    assert r["n_set_ok"] == 1
    assert r["n_ctrl_consistente"] == 1  # fase ya era verde: consistente sin ctrl_fase_cambio nuevo
    assert r["n_m3"] == 1
    assert r["n_m3_cancelado_ok"] == 1


def test_m1_sin_set_no_se_cuenta_como_traducido(tmp_path):
    """M1 inicial sin ningun snmp_set_tx de decision (p. ej. RF-05 rechazo
    inmediato): no debe contarse como traduccion correcta."""
    d = tmp_path / "corrida"
    _escribir_eventos(d, "rsu_1", [
        (0, "M1_rx", "req-1", {"seq": 1}),
    ])
    r = analizar_traduccion([d])
    assert r["n_m1_iniciales"] == 1
    assert r["n_set_ok"] == 0


def test_m3_sin_cancelacion_no_se_cuenta_como_correcta(tmp_path):
    d = tmp_path / "corrida"
    _escribir_eventos(d, "rsu_1", [
        (0, "M3_rx", "req-1", {"motivo": "cruce"}),
    ])
    r = analizar_traduccion([d])
    assert r["n_m3"] == 1
    assert r["n_m3_cancelado_ok"] == 0
