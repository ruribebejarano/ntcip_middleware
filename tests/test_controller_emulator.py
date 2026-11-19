"""Pruebas de controller/controller_emulator.py::Controller -- el ciclo de
fases normal (sin solicitud de prioridad activa).

El caso central (test_fase_correcta_tras_intervalo_largo_sin_consultas)
verifica que la fase se calcula segun el tiempo transcurrido y no
avanzando COMO MAXIMO UNA fase por llamada a status(): nada hace poll al
controlador mientras no hay una solicitud activa (ver
agent/rsu_middleware.py), asi que una consulta puede llegar mucho despues
de la anterior. Con el ciclo de 21 s (verde 8 + amarillo 3 + todo_rojo 2 +
rojo_general 8) y 33 s sin consultas desde la construccion (fase inicial
"verde"), la fase correcta es "todo_rojo" (33 % 21 = 12 s, tramo [11, 13));
un avance por pasos reportaria "amarillo"."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from controller.controller_emulator import Controller  # noqa: E402

# Mismo ciclo por defecto que controller_emulator.py (DEFAULT_*): verde 8 s,
# amarillo 3.0 s, todo_rojo 2.0 s, rojo_general 8.0 s = 21 s total.
CICLO_TOTAL_S = 21.0


class _RelojFalso:
    """Reemplaza time.monotonic() por un contador que el test controla
    explicitamente -- nada avanza "solo", a diferencia del reloj real."""

    def __init__(self, inicio: float = 1000.0) -> None:
        self.t = inicio

    def __call__(self) -> float:
        return self.t


def test_fase_correcta_tras_intervalo_largo_sin_consultas():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()  # epoch = reloj.t = 1000.0, fase inicial "verde"
        assert ctrl.status()["fase"] == "verde"

        # Avanza 33 s SIN ninguna consulta intermedia (simula el patron
        # real: nada hace poll al controlador entre repeticiones de la
        # campana). 33 % 21 = 12 s -> cae en todo_rojo ([11, 13) s).
        # Un avance por pasos reportaria "amarillo" (un solo paso desde
        # "verde"), no la fase real.
        reloj.t += 33.0
        estado = ctrl.status()
        assert estado["fase"] == "todo_rojo", (
            f"se esperaba 'todo_rojo' (33 s % {CICLO_TOTAL_S:.0f} s = 12 s, dentro de [11,13) s); "
            f"salio {estado['fase']!r} -- si esto da 'amarillo', volvio el defecto de avance de un "
            f"solo paso por consulta."
        )
        assert estado["red"] is True and estado["yellow"] is False and estado["green"] is False


def test_fase_correcta_tras_50s_sin_consultas_formulacion_pedida():
    """Formulacion literal pedida: consultar tras 50 s sin consultas debe
    dar la fase correcta, no un paso. 50 % 21 = 8.0 s, justo el limite
    verde/amarillo -- se usa 50.5 s para no depender de un empate de
    punto flotante en el limite exacto: 50.5 % 21 = 8.5 s, dentro de
    amarillo ([8, 11) s). Un avance por pasos tambien daria "amarillo"
    aqui (coincide con el primer paso); el caso que distingue ambos
    calculos es test_fase_correcta_tras_intervalo_largo_sin_consultas
    (33 s, cae en todo_rojo)."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t += 50.5
        assert ctrl.status()["fase"] == "amarillo"


def test_multiples_vueltas_de_ciclo_sin_consultas():
    """2 ciclos completos + 15 s (2*21 + 15 = 57 s) -> 57 % 21 = 15 s,
    dentro de rojo_general ([13, 21) s). El codigo viejo habria dado
    "amarillo" otra vez (sigue siendo un solo paso desde "verde")."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t += 2 * CICLO_TOTAL_S + 15.0
        assert ctrl.status()["fase"] == "rojo_general"


def test_ciclo_normal_sigue_avanzando_fase_a_fase_con_consultas_frecuentes():
    """Regresion: con consultas frecuentes (como el watchdog de 0.5 s en
    agent/rsu_middleware.py mientras hay una solicitud en cola), el ciclo
    debe seguir viendose como antes: verde -> amarillo -> todo_rojo ->
    rojo_general -> verde, en orden, sin saltarse ni repetir fases."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        vistas = [ctrl.status()["fase"]]
        # Avanza en pasos pequeños (0.5 s, como el watchdog real) hasta
        # cubrir mas de un ciclo completo.
        paso = 0.5
        for _ in range(int((CICLO_TOTAL_S * 1.5) / paso)):
            reloj.t += paso
            fase = ctrl.status()["fase"]
            if fase != vistas[-1]:
                vistas.append(fase)
        assert vistas[:5] == ["verde", "amarillo", "todo_rojo", "rojo_general", "verde"]


def test_prioridad_deja_el_ciclo_de_fondo_coherente_al_liberar():
    """El reloj de fondo NO se pausa durante una solicitud de prioridad
    activa: al liberarla, la fase reportada debe reflejar el tiempo real
    transcurrido (incluido el tiempo que duro la prioridad), no quedar
    congelada en la fase de antes de pedirla."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t += 1.0  # sigue en verde (< 8 s)
        assert ctrl.status()["fase"] == "verde"

        ctrl.request_priority("veh-1", eta_seg=5.0, id_solicitud="req-1")
        assert ctrl.status()["fase"] == "verde"  # forzado por la prioridad

        # Mientras la prioridad esta activa, "pasan" 12 s de reloj real
        # (menos que PRIORITY_HOLD_SECONDS=15, se libera a mano antes).
        reloj.t += 12.0
        ctrl.clear_priority("req-1")

        # El reloj de fondo nunca se detuvo: van 1 + 12 = 13 s desde el
        # epoch -> el plan cae justo al INICIO de rojo_general ([13, 21) s).
        estado = ctrl.status()
        assert estado["fase_plan"] == "rojo_general"
        # Salida de la prioridad: el verde mínimo (desde el verde del plan,
        # t=0) ya se cumplió, así que sale por ámbar (3 s) y todo rojo (2 s)
        # y recién a los 18 s retoma el plan, que sigue en rojo_general.
        assert estado["fase"] == "amarillo" and estado["en_salida"]
        reloj.t += 3.0
        assert ctrl.status()["fase"] == "todo_rojo"
        reloj.t += 2.0
        estado = ctrl.status()
        assert estado["fase"] == "rojo_general" and not estado["en_salida"]


def test_salida_de_prioridad_respeta_verde_minimo_y_no_entra_a_mitad_de_ambar():
    """Liberada antes de cumplir el verde mínimo, la prioridad sigue en verde
    hasta cumplirlo; y si al terminar el todo rojo de salida el plan está en
    su propio ámbar/todo rojo, el grupo espera en rojo hasta que el plan
    llegue a rojo_general."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t += 10.0  # plan en amarillo ([8, 11) s): el grupo está en ámbar
        ctrl.request_priority("veh-1", eta_seg=5.0, id_solicitud="req-1")  # verde desde t=10
        reloj.t += 2.0  # t=12: liberada a los 2 s, verde mínimo hasta t=18
        ctrl.clear_priority("req-1")
        assert ctrl.status()["fase"] == "verde"
        reloj.t += 6.0  # t=18: empieza el ámbar de salida
        assert ctrl.status()["fase"] == "amarillo"
        reloj.t += 5.0  # t=23: termina el todo rojo; plan en verde ([21, 29) s)
        assert ctrl.status()["fase"] == "verde"
        assert not ctrl.status()["en_salida"]


def test_liberar_sin_prioridad_activa_no_inicia_salida():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t += 1.0
        ctrl.clear_priority("req-x")
        estado = ctrl.status()
        assert estado["fase"] == "verde" and not estado["en_salida"]


def test_desfase_inicial_adelanta_el_ciclo():
    """Campaña de ruta completa: --desfase-s arranca el ciclo ya avanzado;
    con 0 (por defecto) arranca en verde, como siempre."""
    from controller.controller_emulator import Controller

    assert Controller().status()["fase"] == "verde"
    assert Controller(desfase_s=9.0).status()["fase"] == "amarillo"   # 8 s verde + 1 s
    assert Controller(desfase_s=12.0).status()["fase"] == "todo_rojo"  # 8 + 3 + 1
    assert Controller(desfase_s=15.0).status()["fase"] == "rojo_general"
    assert Controller(desfase_s=21.5).status()["fase"] == "verde"      # vuelta completa


# --- Modo multifase: tiempos del manual INDRA ------------ ----------------
# Ciclo: verde de plan 50 s + ámbar 3 + rojo-rojo 1 (t = 0..54), fase B
# 28 s + 4 (54..86), fase C 20 s + 4 (86..110). Verde mínimo 5 s.

def _ctrl_indra():
    return Controller(phase_minimum_green_s=5, phase_yellow_change_ds=30, phase_red_clear_ds=10,
                      verde_plan_s=50, fases_conflicto_s=[28, 20])


def test_multifase_ciclo_de_110_s():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        assert ctrl.timing()["rojo_general_efectivo_seg"] == 56.0
        for dt, fase in ((49.9, "verde"), (50.5, "amarillo"), (53.5, "todo_rojo"),
                         (60.0, "rojo_general"), (109.9, "rojo_general"), (110.1, "verde")):
            reloj.t = 1000.0 + dt
            assert ctrl.status()["fase"] == fase, (dt, fase)


def test_multifase_llegada_al_inicio_de_fase_en_conflicto_espera_despeje_completo():
    """Llega 1 s después de empezar el verde de B: B cumple su verde mínimo
    (4 s más), ámbar 3 s y rojo-rojo 1 s -> verde a los 8 s."""
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        reloj.t = 1000.0 + 55.0
        ctrl.request_priority("amb", 8, "s1")
        assert ctrl.status()["fase"] == "rojo_general"
        reloj.t += 7.9
        assert ctrl.status()["fase"] == "rojo_general"
        reloj.t += 0.2
        assert ctrl.status()["fase"] == "verde"


def test_multifase_llegada_con_verde_minimo_cumplido_solo_espera_ambar_y_rojo_rojo():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        reloj.t = 1000.0 + 70.0  # 16 s dentro del verde de B
        ctrl.request_priority("amb", 8, "s1")
        reloj.t += 3.9
        assert ctrl.status()["fase"] == "rojo_general"
        reloj.t += 0.2
        assert ctrl.status()["fase"] == "verde"


def test_multifase_llegada_en_transicion_de_conflicto_espera_lo_que_falta():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        reloj.t = 1000.0 + 108.5  # rojo-rojo de C, faltan 1,5 s para el verde del plan
        ctrl.request_priority("amb", 8, "s1")
        reloj.t += 1.4
        assert ctrl.status()["fase"] == "rojo_general"
        reloj.t += 0.2
        assert ctrl.status()["fase"] == "verde"


def test_multifase_renovacion_no_reinicia_la_espera_y_cancelar_antes_del_verde_no_da_verde():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        reloj.t = 1000.0 + 55.0
        ctrl.request_priority("amb", 8, "s1")  # verde a los 8 s
        reloj.t += 4.0
        ctrl.request_priority("amb", 7, "s1")  # renovación (M1 seq+1)
        reloj.t += 4.1
        assert ctrl.status()["fase"] == "verde"

        ctrl2 = _ctrl_indra()
        reloj.t = ctrl2._epoch + 55.0
        ctrl2.request_priority("amb", 8, "s2")
        reloj.t += 2.0
        ctrl2.clear_priority("s2")
        estado = ctrl2.status()
        assert estado["fase"] == "rojo_general" and not estado["prioridad_activa"]
        assert not ctrl2.status()["en_salida"]


def test_multifase_sostenimiento_cuenta_desde_el_verde():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = _ctrl_indra()
        reloj.t = 1000.0 + 55.0
        ctrl.request_priority("amb", 8, "s1")  # verde a t+8, sostenimiento hasta t+8+15
        reloj.t += 22.9
        assert ctrl.status()["prioridad_activa"]
        reloj.t += 0.2
        assert not ctrl.status()["prioridad_activa"]


def test_sin_multifase_rojo_general_sigue_dando_verde_inmediato():
    reloj = _RelojFalso()
    with patch("controller.controller_emulator.time.monotonic", reloj):
        ctrl = Controller()
        reloj.t = 1000.0 + 15.0  # rojo_general del ciclo por defecto (13..21)
        ctrl.request_priority("amb", 8, "s1")
        assert ctrl.status()["fase"] == "verde"
