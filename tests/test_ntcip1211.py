"""Tests del subconjunto de NTCIP 1211 (agent/ntcip1211.py): codec OER de
prgPriorityRequestAbsolute, y los casos que pide
docs/PLAN_IMPLEMENTACION.md P3: RF-06 (limites, ahora cola+activacion
automatica en vez de rechazo), RF-09 (caducidad, incluida la de una
solicitud en cola) y RF-05 (clase no reconocida).

Correr con: python -m pytest tests/test_ntcip1211.py -v
(o python -m unittest tests.test_ntcip1211 si no hay pytest instalado).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.ntcip1211 import (  # noqa: E402
    ACTIVE_PROCESSING,
    CLOSED_TIME_TO_LIVE_ERROR,
    READY_QUEUED,
    TAMANO_BYTES,
    ErrorLongitud,
    ErrorRangoCampo,
    PriorityRequestServer,
    SolicitudPrioridadAbsoluta,
    SolicitudRechazada,
    codificar,
    decodificar,
)


def _solicitud_valida(**overrides) -> SolicitudPrioridadAbsoluta:
    base = dict(
        id_solicitud=7,
        vehiculo_id=b"ambulancia-01",
        clase_tipo=1,
        clase_nivel=1,
        estrategia=1,
        t_servicio_deseado=8,
        t_salida_estimada=12,
        t_solicitud=1760000000,
    )
    base.update(overrides)
    return SolicitudPrioridadAbsoluta(**base)


class TestCodecOER(unittest.TestCase):
    def test_tamano_fijo_29_bytes(self):
        self.assertEqual(TAMANO_BYTES, 29)

    def test_ida_y_vuelta(self):
        original = _solicitud_valida()
        datos = codificar(original)
        self.assertEqual(len(datos), 29)
        recuperada = decodificar(datos)
        self.assertEqual(recuperada.id_solicitud, original.id_solicitud)
        self.assertEqual(recuperada.vehiculo_id, original.vehiculo_id)
        self.assertEqual(recuperada.clase_tipo, original.clase_tipo)
        self.assertEqual(recuperada.clase_nivel, original.clase_nivel)
        self.assertEqual(recuperada.estrategia, original.estrategia)
        self.assertEqual(recuperada.t_servicio_deseado, original.t_servicio_deseado)
        self.assertEqual(recuperada.t_salida_estimada, original.t_salida_estimada)
        self.assertEqual(recuperada.t_solicitud, original.t_solicitud)

    def test_ida_y_vuelta_valores_limite(self):
        """1/255/65535/4294967295 -- los extremos de cada rango declarado."""
        original = _solicitud_valida(
            id_solicitud=255,
            clase_tipo=10,
            clase_nivel=10,
            estrategia=255,
            t_servicio_deseado=65535,
            t_salida_estimada=65535,
            t_solicitud=4294967295,
        )
        recuperada = decodificar(codificar(original))
        self.assertEqual(recuperada.id_solicitud, 255)
        self.assertEqual(recuperada.t_solicitud, 4294967295)

    def test_vehiculo_id_mas_corto_se_rellena_y_se_recupera_sin_relleno(self):
        original = _solicitud_valida(vehiculo_id=b"v1")
        datos = codificar(original)
        self.assertEqual(len(datos), 29)
        recuperada = decodificar(datos)
        self.assertEqual(recuperada.vehiculo_id, b"v1")

    def test_rechaza_longitud_distinta_de_29_al_decodificar(self):
        with self.assertRaises(ErrorLongitud):
            decodificar(b"\x00" * 28)
        with self.assertRaises(ErrorLongitud):
            decodificar(b"\x00" * 30)
        with self.assertRaises(ErrorLongitud):
            decodificar(b"")

    def test_rechaza_campo_fuera_de_rango_al_codificar(self):
        with self.assertRaises(ErrorRangoCampo):
            codificar(_solicitud_valida(clase_tipo=0))  # rango valido: 1..10
        with self.assertRaises(ErrorRangoCampo):
            codificar(_solicitud_valida(clase_tipo=11))
        with self.assertRaises(ErrorRangoCampo):
            codificar(_solicitud_valida(id_solicitud=0))  # rango valido: 1..255

    def test_rechaza_vehiculo_id_demasiado_largo(self):
        with self.assertRaises(ErrorRangoCampo):
            codificar(_solicitud_valida(vehiculo_id=b"x" * 18))


class TestRF05ClaseNoReconocida(unittest.TestCase):
    def test_clase_reconocida_se_acepta(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(clase_tipo=1), fase_actual="rojo_general")
        self.assertEqual(fila.clase_tipo, 1)

    def test_clase_no_reconocida_se_rechaza(self):
        prs = PriorityRequestServer()
        with self.assertRaises(SolicitudRechazada) as ctx:
            prs.aceptar_solicitud(_solicitud_valida(clase_tipo=5), fase_actual="rojo_general")
        self.assertEqual(ctx.exception.motivo, "clase_no_reconocida")
        # No debe haber quedado ninguna fila activa tras el rechazo.
        self.assertIsNone(prs.fila_activa())


class TestRF06LimitesOperacionales(unittest.TestCase):
    def test_se_encola_durante_amarillo(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="amarillo")
        self.assertEqual(fila.estado, READY_QUEUED)

    def test_se_encola_durante_todo_rojo(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="todo_rojo")
        self.assertEqual(fila.estado, READY_QUEUED)

    def test_se_acepta_durante_verde_o_rojo_general(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="verde")
        self.assertEqual(fila.estado, ACTIVE_PROCESSING)
        prs.completar()
        prs2 = PriorityRequestServer()
        fila2 = prs2.aceptar_solicitud(_solicitud_valida(), fase_actual="rojo_general")
        self.assertEqual(fila2.estado, ACTIVE_PROCESSING)

    def test_se_activa_al_terminar_el_despeje_dentro_del_ttl(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="amarillo")
        self.assertEqual(fila.estado, READY_QUEUED)
        # Todavia en despeje: no hay nada que activar.
        self.assertIsNone(prs.intentar_activar_cola(fase_actual="todo_rojo"))
        self.assertEqual(fila.estado, READY_QUEUED)
        # Termina el despeje (vuelve a verde), todavia dentro del TTL de 3s.
        activada = prs.intentar_activar_cola(fase_actual="verde")
        self.assertIsNotNone(activada)
        self.assertEqual(activada.estado, ACTIVE_PROCESSING)
        self.assertEqual(activada.id_solicitud, fila.id_solicitud)

    def test_caduca_en_cola_si_el_despeje_tarda_mas_que_el_ttl(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="amarillo")
        t0 = fila.ultima_actualizacion_monotonic
        # Sigue en despeje, y ya paso el TTL sin que se active: caduca.
        self.assertTrue(prs.verificar_caducidad(ahora_monotonic=t0 + 3.5))
        self.assertEqual(fila.estado, CLOSED_TIME_TO_LIVE_ERROR)
        # Una vez caducada, aunque termine el despeje ya no se activa.
        self.assertIsNone(prs.intentar_activar_cola(fase_actual="verde"))
        self.assertEqual(fila.estado, CLOSED_TIME_TO_LIVE_ERROR)


class TestRF09Caducidad(unittest.TestCase):
    def test_no_caduca_si_se_refresca_a_tiempo(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="verde")
        # Simula el paso del tiempo sin llegar a T_CAD, luego un refresh.
        t0 = fila.ultima_actualizacion_monotonic
        self.assertFalse(prs.verificar_caducidad(ahora_monotonic=t0 + 2.0))
        self.assertTrue(prs.refrescar(fila.id_solicitud, ahora_monotonic=t0 + 2.0))
        self.assertFalse(prs.verificar_caducidad(ahora_monotonic=t0 + 2.0 + 2.5))

    def test_caduca_pasado_t_cad_sin_actualizar(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_valida(), fase_actual="verde")
        t0 = fila.ultima_actualizacion_monotonic
        self.assertTrue(prs.verificar_caducidad(ahora_monotonic=t0 + 3.5))
        self.assertIsNone(prs.fila_activa())

    def test_verificar_caducidad_es_no_op_sin_solicitud_activa(self):
        prs = PriorityRequestServer()
        self.assertFalse(prs.verificar_caducidad())


if __name__ == "__main__":
    unittest.main()
