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


def test_rsu_manual_se_asocian_al_nodo_mas_cercano_en_orden_de_ruta():
    geo = [SimpleNamespace(lat=-12.0 + i * 0.001, lon=-77.0, distancia_acumulada_m=i * 110.6) for i in range(6)]
    ruta = SimpleNamespace(geometria=geo)
    puntos = [[-12.0 + 4 * 0.001, -77.0001],   # nodo 4, a ~11 m
              [-12.0 + 2 * 0.001, -77.0],      # nodo 2
              [-12.0 + 2 * 0.001, -77.00005],  # mismo nodo 2: se omite
              [-12.0 + 3 * 0.001, -77.01]]     # a ~1 km de la ruta: se omite
    elegidas = preparar.candidatas_manuales(ruta, puntos)
    assert [c["indice"] for c in elegidas] == [2, 4]


def test_rutas_con_rsu_manual_traen_puntos_validos():
    for conf in json.loads(preparar.RUTAS_JSON.read_text(encoding="utf-8")).values():
        for punto in conf.get("rsu_manual", []):
            assert len(punto) == 2 and -90 <= punto[0] <= 90 and -180 <= punto[1] <= 180


def _ev(tipo, t_s, mision, **extra):
    return {"tipo_evento": tipo, "id_solicitud": mision, "ts_ns": int(t_s * 1e9), "extra": extra}


def test_error_del_eta_con_el_paso_real_por_el_centro():
    # Recorrido recto hacia el norte a 10 m/s; la RSU está 150 m adelante del inicio.
    lat0, lon0 = -12.1, -77.03
    centro = (lat0 + 150 / 110574, lon0)
    eventos = []
    for t in range(0, 25):
        eventos.append(_ev("MP_rx", t, "m1", lat=lat0 + 10 * t / 110574, lon=lon0, velocidad_kmh=36.0))
        restante = 150 - 10 * t
        if restante > 0:
            # el servidor estima con 20 % de optimismo: ETA = 0,8 * real
            eventos.append(_ev("eta_estimado", t, "m1", rsu_id="7", eta_s=0.8 * restante / 10))
    filas = resumen.error_eta(eventos, {"7": centro})
    assert len(filas) == 1
    f = filas[0]
    assert abs(f["eta_s"] - 8.0) <= 2.0
    assert abs(f["error_eta_s"] - 0.25 * f["eta_s"]) < 0.05  # real = eta / 0,8
    assert f["con_detencion"] is False


def test_error_del_eta_marca_detencion():
    lat0, lon0 = -12.1, -77.03
    centro = (lat0 + 100 / 110574, lon0)
    eventos, pos = [], 0.0
    for t in range(0, 30):
        v = 0.0 if 3 <= t < 8 else 10.0
        eventos.append(_ev("MP_rx", t, "m1", lat=lat0 + pos / 110574, lon=lon0, velocidad_kmh=v * 3.6))
        if 100 - pos > 0:
            eventos.append(_ev("eta_estimado", t, "m1", rsu_id="7", eta_s=(100 - pos) / 10))
        pos += v
    filas = resumen.error_eta(eventos, {"7": centro})
    assert len(filas) == 1 and filas[0]["con_detencion"] is True
    assert filas[0]["error_eta_s"] > 0  # la detención hace llegar más tarde de lo estimado


def test_grafo_propio_por_ruta_y_comando_de_descarga():
    """Sin campo "grafo" se usa el grafo compartido; con él, el de la ruta, y
    el comando sugerido cubre origen, destino y RSU a mano con margen."""
    assert preparar.ruta_grafo({}) == preparar.rutas_mod.GRAFO_REAL_DEFAULT
    assert preparar.ruta_grafo({"grafo": "data/x.graphml"}) == RAIZ / "data" / "x.graphml"
    conf = {"origen": [-12.05, -76.95], "destino": [-12.055, -76.98], "rsu_manual": [[-12.06, -76.97]]}
    cmd = preparar.comando_grafo_propio(conf, RAIZ / "data" / "x.graphml")
    assert "--norte -12.04400" in cmd and "--sur -12.06600" in cmd
    assert "--este -76.94400" in cmd and "--oeste -76.98600" in cmd
    assert cmd.endswith("--salida data/x.graphml")


def test_error_eta_al_solicitar_usa_el_ultimo_eta_antes_del_m1():
    """La geocerca pide prioridad a ~150 m: no hay ETA cercano a 8 s, pero sí el
    último antes del M1. Vehículo a 10 m/s hacia la RSU; el servidor estimaba
    12 s cuando faltaban 15 s de verdad -> error +3 s."""
    from gateway.geometria import desplazar
    centro = (-12.05, -76.96)
    ns = 1_000_000_000
    eventos = []
    for k in range(0, 31):  # de 300 m al sur hasta pasar el centro
        lat, lon = desplazar(*centro, 180.0, 300.0 - 10.0 * k)
        eventos.append({"tipo_evento": "MP_rx", "id_solicitud": "mis-1", "ts_ns": k * ns,
                        "extra": {"lat": lat, "lon": lon, "velocidad_kmh": 36.0}})
    for k, eta in ((14, 17.0), (15, 12.0)):
        eventos.append({"tipo_evento": "eta_estimado", "id_solicitud": "mis-1", "ts_ns": k * ns,
                        "extra": {"rsu_id": "2", "eta_s": eta, "distancia_restante_m": 300.0 - 10.0 * k}})
    eventos.append({"tipo_evento": "M1_tx", "id_solicitud": "mis-1-OSM-1", "ts_ns": 15 * ns + 1,
                    "extra": {"mision_id": "mis-1", "rsu_id": "2", "t_servicio": 8.0, "seq": 1}})
    filas = resumen.error_eta_al_solicitar(eventos, {"2": centro})
    assert len(filas) == 1
    f = filas[0]
    assert f["abierta_por"] == "geocerca"
    assert f["eta_al_solicitar_s"] == 12.0
    assert abs(f["t_real_hasta_centro_al_solicitar_s"] - 15.0) < 0.1
    assert abs(f["error_eta_al_solicitar_s"] - 3.0) < 0.1
    assert f["con_detencion_al_solicitar"] is False
