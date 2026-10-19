"""Pruebas de gateway/geometria.py (RF-03, RF-04, RF-11; ssec:zonas y
ssec:emision de main.tex). Sin red: solo geometria y la maquina de estados
de la OBU."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway.geometria import (  # noqa: E402
    ACTUALIZAR_M1,
    EMITIR_M1,
    EMITIR_M3,
    MOTIVO_CRUCE,
    MOTIVO_RUMBO,
    Acceso,
    Interseccion,
    ParametrosGeometria,
    SeguidorAcceso,
    asignar,
    cargar_registro,
    delta_psi,
    desplazar,
    proyeccion_local,
)

P = ParametrosGeometria()
LAT0, LON0 = -12.1, -77.03
# Dos intersecciones sobre una via norte-sur, separadas 400 m (A al sur, B al norte).
A = Interseccion("1", "A", LAT0, LON0, (Acceso("S", 0.0, 1), Acceso("N", 180.0, 1), Acceso("O", 90.0, 2)))
B_LAT, B_LON = desplazar(LAT0, LON0, 0.0, 400.0)
B = Interseccion("2", "B", B_LAT, B_LON, (Acceso("S", 0.0, 1), Acceso("N", 180.0, 1)))
REGISTRO = [A, B]


def test_delta_psi_sin_salto_en_cero():
    assert delta_psi(359.0, 1.0) == pytest.approx(2.0)
    assert delta_psi(10.0, 190.0) == pytest.approx(180.0)
    assert delta_psi(-90.0, 270.0) == pytest.approx(0.0)


def test_proyeccion_local_ida_y_vuelta():
    lat, lon = desplazar(LAT0, LON0, 45.0, 200.0)
    x, y = proyeccion_local(lat, lon, LAT0, LON0)
    assert x == pytest.approx(141.42, abs=0.5)
    assert y == pytest.approx(141.42, abs=0.5)


def test_asigna_acceso_sur_al_acercarse_desde_el_sur():
    lat, lon = desplazar(LAT0, LON0, 180.0, 120.0)  # 120 m al sur de A
    a = asignar(REGISTRO, lat, lon, 0.0, P)
    assert (a.interseccion_id, a.acceso_id) == ("A", "S")
    assert a.distancia_m == pytest.approx(120.0, abs=1.0)


def test_problema_ab_tras_cruzar_a_se_asigna_b():
    # 120 m al norte de A (280 m de B), rumbo norte: A sigue dentro de su
    # radio R_i pero queda detras (condicion 2 falla); B esta por delante.
    lat, lon = desplazar(LAT0, LON0, 0.0, 120.0)
    a = asignar(REGISTRO, lat, lon, 0.0, P)
    assert a.interseccion_id == "B"


def test_carril_opuesto_descartado_por_rumbo():
    # Al sur de A pero con rumbo 135 (no coincide con ningun acceso ni mira a A).
    lat, lon = desplazar(LAT0, LON0, 180.0, 100.0)
    assert asignar(REGISTRO, lat, lon, 135.0, P) is None


def test_fuera_del_radio_no_asigna():
    lat, lon = desplazar(LAT0, LON0, 180.0, P.r_i_m + 50.0)
    assert asignar([A], lat, lon, 0.0, P) is None


def _recorrido(seguidor, distancias_al_sur_de_a, rumbo=0.0):
    acciones = []
    for d in distancias_al_sur_de_a:
        lat, lon = desplazar(LAT0, LON0, 180.0, d) if d >= 0 else desplazar(LAT0, LON0, 0.0, -d)
        acciones.append([dec for dec in seguidor.actualizar(lat, lon, rumbo)])
    return acciones


def test_emite_m1_en_la_geocerca_actualiza_y_cancela_al_cruzar():
    s = SeguidorAcceso([A], P)
    pasos = _recorrido(s, [250, 200, 160, 140, 120, 60, 10, -20])
    tipos = [[d.accion for d in paso] for paso in pasos]
    assert tipos[0] == ["ninguna"]                  # 250 m: asignado, fuera de R_g
    assert tipos[3] == [EMITIR_M1]                   # 140 m <= R_g = 150 m
    assert tipos[4] == [ACTUALIZAR_M1]
    m3 = pasos[-1][0]
    assert m3.accion == EMITIR_M3 and m3.motivo == MOTIVO_CRUCE


def test_tras_cruzar_a_pasa_a_b_sin_reabrir_a():
    s = SeguidorAcceso(REGISTRO, P)
    _recorrido(s, [140, 100, 50])
    pasos = _recorrido(s, [-20, -60, -120, -250])   # ya al norte de A
    reabiertas_a = [d for paso in pasos for d in paso
                    if d.accion in (EMITIR_M1, ACTUALIZAR_M1) and d.asignacion.interseccion_id == "A"]
    assert reabiertas_a == []
    assert pasos[0][0].accion == EMITIR_M3 and pasos[0][0].asignacion.interseccion_id == "A"
    assert any(d.accion == EMITIR_M1 and d.asignacion.interseccion_id == "B" for paso in pasos for d in paso)


def test_giro_sostenido_cancela_por_rumbo_con_histeresis():
    s = SeguidorAcceso([A], P)
    _recorrido(s, [140, 120])
    # Gira a 270 (oeste) pero sigue con A "por delante" en un cono amplio:
    p_amplio = ParametrosGeometria(theta_deg=179.0)
    s.p = p_amplio
    lat, lon = desplazar(LAT0, LON0, 180.0, 110.0)
    acciones = [s.actualizar(lat, lon, 300.0) for _ in range(P.n_histeresis)]
    assert acciones[0][0].accion == ACTUALIZAR_M1     # una muestra fuera no basta
    assert acciones[-1][0].accion == EMITIR_M3 and acciones[-1][0].motivo == MOTIVO_RUMBO


def test_registro_del_repositorio_carga():
    reg = cargar_registro(Path(__file__).resolve().parent.parent / "config" / "registro_rsu.json")
    assert [i.rsu_id for i in reg] == ["1", "2"]
    assert all(len(i.accesos) == 4 for i in reg)
