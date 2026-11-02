"""Estado por RSU y linea de tiempo que arma consola/backend/mision.py a
partir de los mensajes observados en el broker (secuencia real tomada de
una corrida del escenario hospital_nino, 2026-10-30, resumida)."""

from consola.backend.mision import SeguidorMision

OBU = "ses-prueba"
MIS = "mis-0001"


def _sec(s: SeguidorMision) -> None:
    s.procesar(f"obu/{OBU}/mision", {"tipo": "MI", "obu_id": OBU, "clase": 1}, 0.0)
    s.procesar(f"obu/{OBU}/ruta", {"tipo": "MR", "mision_id": MIS, "version": 1, "longitud_total_m": 2928.1,
                                   "geometria": [[-12.07, -77.08], [-12.06, -77.06]],
                                   "paradas": [{"rsu_id": "4", "interseccion_id": "I4", "acceso_id": "A"},
                                               {"rsu_id": "5", "interseccion_id": "I5", "acceso_id": "B"}]}, 0.1)
    s.procesar("rsu/4/solicitudes", {"tipo": "M1", "id_solicitud": f"{MIS}-I4", "mision_id": MIS,
                                     "acceso": "A", "t_servicio": 7, "seq": 1}, 12.0)
    s.procesar("rsu/4/solicitudes", {"tipo": "M1", "id_solicitud": f"{MIS}-I4", "mision_id": MIS, "seq": 2}, 13.0)
    s.procesar("servidor/central/respuestas", {"tipo": "M2", "id_solicitud": f"{MIS}-I4", "rsu_id": "4",
                                               "estado": "concedida", "fase": "verde"}, 13.1)
    s.procesar("rsu/4/solicitudes", {"tipo": "M3", "id_solicitud": f"{MIS}-I4", "motivo": "cruce"}, 15.0)
    s.procesar("servidor/central/respuestas", {"tipo": "M2", "id_solicitud": f"{MIS}-I4", "rsu_id": "4",
                                               "estado": "cancelada", "fase": "verde", "motivo": "m3"}, 15.1)
    s.procesar("rsu/5/solicitudes", {"tipo": "M1", "id_solicitud": f"{MIS}-I5", "mision_id": MIS, "seq": 1}, 20.0)
    s.procesar("servidor/central/respuestas", {"tipo": "M2", "id_solicitud": f"{MIS}-I5", "rsu_id": "5",
                                               "estado": "cancelada", "fase": "verde", "motivo": "caducidad"}, 23.0)
    s.procesar(f"obu/{OBU}/mision", {"tipo": "MF", "obu_id": OBU, "motivo": "destino"}, 40.0)


def test_estados_por_rsu():
    s = SeguidorMision()
    _sec(s)
    f = s.foto()
    p4, p5 = f["prioridad"]["4"], f["prioridad"]["5"]
    # M3 con motivo "cruce" -> "liberada"; cualquier otro motivo -> "cancelada".
    assert p4["estado"] == "liberada" and p4["motivo"] == "cruce" and p4["desde"] == 15.0
    assert p4["renovaciones"] == 1 and p4["orden"] == 1
    assert p5["estado"] == "cancelada" and p5["motivo"] == "caducidad"
    assert f["mision"]["activa"] is False and f["mision"]["motivo_fin"] == "destino"


def test_linea_tiempo_sin_renovaciones_ni_m2_repetidos():
    s = SeguidorMision()
    _sec(s)
    tipos = [(e["tipo"], e["rsu_id"]) for e in s.foto()["linea_tiempo"]]
    assert tipos == [("MI", None), ("MR", None), ("M1", "4"), ("M2", "4"), ("M3", "4"), ("M2", "4"),
                     ("M1", "5"), ("M2", "5"), ("MF", None)]


def test_me_del_servidor_manda_y_otra_obu_se_ignora():
    s = SeguidorMision()
    _sec(s)
    s.procesar(f"obu/{OBU}/mision", {"tipo": "MI", "obu_id": OBU, "clase": 1}, 50.0)
    s.procesar(f"obu/{OBU}/ruta", {"tipo": "MR", "mision_id": "mis-0002", "paradas": [
        {"rsu_id": "4", "interseccion_id": "I4", "acceso_id": "A"}]}, 50.1)
    s.procesar(f"obu/{OBU}/estado", {"tipo": "ME", "mision_id": "mis-0002", "paradas": [
        {"rsu_id": "4", "estado": "en_cola", "eta_s": 5.0}]}, 51.0)
    s.procesar("obu/otra/estado", {"tipo": "ME", "paradas": [{"rsu_id": "4", "estado": "concedida"}]}, 52.0)
    p4 = s.foto()["prioridad"]["4"]
    assert p4["estado"] == "en_cola" and p4["eta_s"] == 5.0
    assert [e["tipo"] for e in s.foto()["linea_tiempo"]] == ["MI", "MR"]
