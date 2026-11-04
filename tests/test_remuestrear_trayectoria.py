"""scripts/trayectorias/remuestrear.py: el paso de la trayectoria fija la
frecuencia de MP y de renovación de M1 (RNF-02)."""

import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "trayectorias"))
from remuestrear import remuestrear  # noqa: E402


def _fila(t, lat, lon=-77.0, rumbo="0.0", v="36.0"):
    return {"t_s": str(t), "lat": str(lat), "lon": str(lon), "rumbo_deg": rumbo, "velocidad_kmh": v}


def test_interpola_punto_medio_y_conserva_extremos():
    r = remuestrear([_fila(0.0, -12.0), _fila(2.0, -12.002)], 1.0)
    assert [x["t_s"] for x in r] == ["0.0", "1.0", "2.0"]
    assert [x["lat"] for x in r] == ["-12.0000000", "-12.0010000", "-12.0020000"]


def test_rumbo_y_velocidad_no_se_promedian():
    r = remuestrear([_fila(0.0, -12.0, rumbo="350.0", v="36.0"), _fila(2.0, -12.0, rumbo="10.0", v="0.0")], 1.0)
    assert [x["rumbo_deg"] for x in r] == ["350.0", "350.0", "10.0"]
    assert [x["velocidad_kmh"] for x in r] == ["36.0", "36.0", "0.0"]


def test_fixtures_de_campana_a_1_hz():
    for f in (RAIZ / "scripts" / "campanas" / "fixtures").glob("trayectoria_*_base.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            ts = [float(x["t_s"]) for x in csv.DictReader(fh)]
        assert all(abs((b - a) - 1.0) < 1e-6 for a, b in zip(ts, ts[1:])), f.name
