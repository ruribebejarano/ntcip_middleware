"""scripts/analisis/frecuencia_actualizacion.py: intervalos de MP y de
renovaciones de M1, por solicitud y no mezclados entre solicitudes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "analisis"))
from frecuencia_actualizacion import intervalos_de_repeticion  # noqa: E402

S = 1_000_000_000


def _e(tipo, ts_s, id_sol="-"):
    return {"tipo_evento": tipo, "ts_ns": int(ts_s * S), "id_solicitud": id_sol}


def test_intervalos_de_mp():
    mp, _, _, _ = intervalos_de_repeticion([_e("MP_tx", 0), _e("MP_tx", 1), _e("MP_tx", 2.5)])
    assert mp == [1.0, 1.5]


def test_m1_no_mezcla_solicitudes_distintas():
    eventos = [_e("M1_tx", 0, "a"), _e("M1_tx", 1, "a"), _e("M1_tx", 100, "b"), _e("M1_tx", 102, "b")]
    _, m1, _, _ = intervalos_de_repeticion(eventos)
    assert sorted(m1) == [1.0, 2.0]


def test_cuenta_mi_y_mf():
    _, _, n_mi, n_mf = intervalos_de_repeticion([_e("MI_tx", 0), _e("MP_tx", 1), _e("MF_tx", 2)])
    assert (n_mi, n_mf) == (1, 1)
