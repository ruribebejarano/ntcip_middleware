"""scripts/evaluacion: selección de RSU, ruido de la trayectoria y resumen."""

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "evaluacion"))


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(f"evaluacion_{nombre}", RAIZ / "scripts" / "evaluacion" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


preparar = _cargar("preparar_ruta")
correr = _cargar("correr_emulada")
resumen = _cargar("resumen")


def _cand(acum):
    return {"nodo": SimpleNamespace(distancia_acumulada_m=acum)}


def test_elige_rsu_separadas_y_respeta_el_maximo():
    candidatas = [_cand(d) for d in (200, 300, 600, 950, 1400)]
    elegidas = preparar.elegir_separadas(candidatas, 3, 300)
    assert [c["nodo"].distancia_acumulada_m for c in elegidas] == [200, 600, 950]


def test_rutas_de_ejemplo_tienen_los_campos_necesarios():
    for conf in json.loads(preparar.RUTAS_JSON.read_text(encoding="utf-8")).values():
        assert len(conf["origen"]) == 2 and len(conf["destino"]) == 2
        assert str(conf["primer_rsu_id"]) != "1"  # el 1 es la Raspberry Pi


def test_ruido_no_mueve_filas_detenidas(tmp_path):
    base = tmp_path / "base.csv"
    with base.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh"])
        w.writerow([0, "-12.0000000", "-77.0000000", 0, 0])
        w.writerow([1, "-12.0000000", "-77.0000000", 0, 30])
    destino = tmp_path / "ruido.csv"
    correr.con_ruido(base, destino, semilla=3, sigma_m=50)
    with destino.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    assert filas[0]["lat"] == "-12.0000000"
    assert filas[1]["lat"] != "-12.0000000" or filas[1]["lon"] != "-77.0000000"


def test_intervalos_de_mp_no_mezclan_misiones():
    eventos = [
        {"tipo_evento": "MP_rx", "id_solicitud": "a", "ts_ns": 0},
        {"tipo_evento": "MP_rx", "id_solicitud": "b", "ts_ns": 100_000_000_000},
        {"tipo_evento": "MP_rx", "id_solicitud": "a", "ts_ns": 1_000_000_000},
        {"tipo_evento": "M1_tx", "id_solicitud": "a", "ts_ns": 5},
    ]
    assert resumen.intervalos_mp(eventos) == [1.0]
