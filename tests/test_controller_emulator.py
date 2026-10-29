"""Pruebas de controller/controller_emulator.py::Controller -- el ciclo de
fases normal (sin solicitud de prioridad activa).

El caso central (test_fase_correcta_tras_intervalo_largo_sin_consultas)
reproduce el defecto de banco de pruebas corregido el 2026-10-29: antes,
Controller._advance_locked() avanzaba COMO MAXIMO UNA fase por llamada a
status(), asi que una consulta que llega mucho despues de la anterior (lo
normal: nada hace poll al controlador mientras no hay una solicitud
activa, ver agent/rsu_middleware.py) reportaba la fase siguiente a la
ultima conocida, no la fase real segun el tiempo transcurrido. Con el
reloj viejo (ciclo de 21 s: verde 8 + amarillo 3 + todo_rojo 2 +
rojo_general 8) y un intervalo de, por ejemplo, 33 s sin consultas desde
la construccion (fase inicial "verde"), el codigo viejo reportaba
"amarillo" (un paso desde "verde") en vez de "todo_rojo" (33 % 21 = 12 s,
que cae en el tramo [11, 13) de todo_rojo). Este test falla con el
comportamiento anterior y pasa con el corregido (ver
docs/bitacora/2026-10-29_fase-controlador-emulado.md)."""

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
        # El codigo anterior a 2026-10-29 habria reportado "amarillo" (un
        # solo paso desde "verde"), no la fase real.
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
    amarillo ([8, 11) s). El codigo anterior tambien habria dado
    "amarillo" aqui (coincide con el primer paso), asi que esta prueba por
    si sola NO habria detectado el defecto -- se mantiene como la
    verificacion de la formulacion pedida, y
    test_fase_correcta_tras_intervalo_largo_sin_consultas (33 s, cae en
    todo_rojo) es la que de verdad distingue el comportamiento viejo del
    corregido."""
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
        # epoch -> cae justo al INICIO de rojo_general ([13, 21) s).
        estado = ctrl.status()
        assert estado["fase"] == "rojo_general", (
            f"tras liberar la prioridad a los 13 s de reloj real, se esperaba 'rojo_general' "
            f"(el ciclo de fondo siguio corriendo); salio {estado['fase']!r}."
        )
