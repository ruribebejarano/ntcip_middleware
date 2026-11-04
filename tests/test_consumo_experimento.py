"""scripts/consumo/analizar.py: reposo, ventana de misiones y descuento del reposo."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("consumo_analizar", RAIZ / "scripts" / "consumo" / "analizar.py")
an = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = an
_spec.loader.exec_module(an)


def _serie(tramos):
    """tramos: (fase, duración en s, bytes/s). Una muestra cada 10 s."""
    muestras, t, total = [], 1000.0, 0.0
    for fase, dur, tasa in tramos:
        for _ in range(int(dur / 10)):
            muestras.append({"ts": t, "fase": fase, "bytes": int(total), "rx": int(total), "tx": 0})
            t += 10
            total += tasa * 10
    muestras.append({"ts": t, "fase": tramos[-1][0], "bytes": int(total), "rx": int(total), "tx": 0})
    return muestras


def test_descuenta_el_reposo_y_divide_entre_misiones():
    m = _serie([("reposo", 600, 100), ("misiones", 400, 600), ("reposo2", 600, 100)])
    v = {an.OBU_RSU: {"inicio": 1600.0, "fin": 2000.0, "n": 2}}
    r = an.calcular(m, v, margen_s=60)
    assert r["reposo_bytes_s"] == pytest.approx(100, rel=0.02)
    # 500 bytes/s por encima del reposo, 400 s, entre 2 misiones.
    assert r["rsu"]["bytes_por_mision"] == pytest.approx(100_000, rel=0.03)


def test_margen_quita_la_conexion_inicial_del_reposo():
    m = _serie([("reposo", 60, 5000), ("reposo", 600, 100)])
    assert an.tasa_fase(m, "reposo", 60)["bytes_s"] == pytest.approx(100, rel=0.02)


def test_el_obu_se_descuenta_del_fondo_no_del_reposo():
    m = _serie([("fondo", 600, 50), ("reposo", 600, 100), ("obu", 300, 150)])
    v = {an.OBU_PI: {"inicio": 2200.0, "fin": 2500.0, "n": 1}}
    r = an.calcular(m, v, margen_s=60)
    assert r["obu"]["bytes_por_mision"] == pytest.approx(100 * 300, rel=0.03)


def test_detecta_un_pico_en_reposo():
    m = _serie([("reposo", 600, 100)])
    for x in m[30:]:
        x["bytes"] += 500_000
    assert an.tasa_fase(m, "reposo", 0)["picos"] == 1


def test_ventanas_cuentan_solo_misiones_completas(tmp_path):
    ruta = tmp_path / "eventos_servidor.csv"
    with ruta.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_ns", "nodo", "tipo_evento", "id_solicitud", "extra_json"])
        w.writerow([1_000_000_000, "s", "mision_armada", "m1", json.dumps({"obu_id": an.OBU_RSU})])
        w.writerow([5_000_000_000, "s", "mision_desarmada", "m1", "{}"])
        w.writerow([6_000_000_000, "s", "mision_armada", "m2", json.dumps({"obu_id": an.OBU_RSU})])
    v = an.ventanas_mision(ruta)[an.OBU_RSU]
    assert (v["inicio"], v["fin"], v["n"]) == (1.0, 5.0, 1)
