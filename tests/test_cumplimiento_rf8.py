"""Pruebas de scripts/analisis/cumplimiento_rf8.py (M3, prompt_figuras_cap4.md)
con un fixture minimo (config.json + lazo_por_parada.csv escritos a mano en
un directorio temporal), sin tocar las corridas reales de
resultados/campana/."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analisis.cumplimiento_rf8 import ANTICIPACION_MINIMA_S, cargar_corrida, clasificar, incumplimientos

CAMPOS = ["id_solicitud", "mision_id", "rsu_id", "resultado", "etapa_alcanzada", "cola_despeje",
          "t_srv_ms", "t_srv_RSU_ms", "t_RSU_ms", "RTT_srv_ms", "L_ms", "t_verde_ms", "T_desp_ms",
          "anticipacion_real_s", "obtuvo_verde", "ultimo_m3_motivo", "fase_decision", "condicion_llegada"]


def _fila(id_solicitud: str, anticipacion_real_s, ultimo_m3_motivo: str, rsu_id: str = "1") -> dict:
    base = {c: "" for c in CAMPOS}
    base.update(id_solicitud=id_solicitud, rsu_id=rsu_id, resultado="concedida",
                anticipacion_real_s=anticipacion_real_s, ultimo_m3_motivo=ultimo_m3_motivo,
                obtuvo_verde="True", condicion_llegada="verde", fase_decision="verde")
    return base


def _escribir_corrida(tmp_path: Path, nombre: str, escenario: str, config: str, filas: list[dict]) -> Path:
    d = tmp_path / nombre
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"escenario": escenario, "config": config}), encoding="utf-8")
    with (d / "lazo_por_parada.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    return d


def test_clasifica_cruce_desvio_y_cumplimiento(tmp_path):
    filas = [
        _fila("mis-1-C", "15.0", "cruce"),       # cumple RF8
        _fila("mis-2-C", "5.0", "cruce"),        # NO cumple RF8 (< 8 s)
        _fila("mis-3-C", "", "desvio"),          # sin dato, desvio -> no es incumplimiento
    ]
    d = _escribir_corrida(tmp_path, "corrida", "lazo", "local", filas)

    etiqueta, filas_leidas = cargar_corrida(d)
    assert etiqueta == "local/lazo"
    g = clasificar(filas_leidas)
    assert len(g["con_cruce"]) == 2
    assert len(g["sin_dato_desvio"]) == 1
    assert len(g["sin_dato_otro"]) == 0

    hallazgos = incumplimientos({etiqueta: g}, tmp_path)
    assert len(hallazgos) == 1
    assert hallazgos[0]["id_solicitud"] == "mis-2-C"
    assert hallazgos[0]["anticipacion_real_s"] < ANTICIPACION_MINIMA_S
    texto = (tmp_path / "incumplimientos.txt").read_text(encoding="utf-8")
    assert "mis-2-C" in texto


def test_sin_incumplimientos_no_inventa_ninguno(tmp_path):
    filas = [_fila("mis-1-C", "15.0", "cruce"), _fila("mis-2-C", "12.0", "cruce")]
    d = _escribir_corrida(tmp_path, "corrida", "lazo", "local", filas)
    _, filas_leidas = cargar_corrida(d)
    g = clasificar(filas_leidas)
    hallazgos = incumplimientos({"local/lazo": g}, tmp_path)
    assert hallazgos == []
    texto = (tmp_path / "incumplimientos.txt").read_text(encoding="utf-8")
    assert "Ninguna parada" in texto
