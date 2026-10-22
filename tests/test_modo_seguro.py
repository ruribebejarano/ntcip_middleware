"""Modo seguro (RNF7, arquitectura centralizada): si la RSU pierde la
conexion con el broker o deja de recibir algo del servidor (M1 de
renovacion), NO debe seguir forzando prioridad en el controlador mas alla
del TTL de RF-09 (T_CAD_SEGUNDOS, agent/ntcip1211.py). Esto no es codigo
nuevo de esta migracion: agent/rsu_middleware.py ya dependia de este mismo
mecanismo (verificar_caducidad_periodica llama a
PriorityRequestServer.verificar_caducidad en un hilo que corre
INDEPENDIENTEMENTE de que lleguen o no mensajes MQTT) -- esta prueba deja
explicito, a nivel de agent/ntcip1211.py, que la propiedad se sigue
cumpliendo con la arquitectura centralizada: sin un M1 fresco del servidor
(antes, de la OBU), la solicitud se cierra sola y no hay ningun camino que
la reactive. Las pruebas de RF-09 ya existentes en test_ntcip1211.py cubren
el mecanismo subyacente (verificar_caducidad); esta prueba lo enmarca
explicitamente como el modo seguro de la RSU.

Correr con: python -m pytest tests/test_modo_seguro.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.ntcip1211 import (  # noqa: E402
    ACTIVE_PROCESSING,
    CLOSED_TIME_TO_LIVE_ERROR,
    T_CAD_SEGUNDOS,
    PriorityRequestServer,
    SolicitudPrioridadAbsoluta,
)


def _solicitud_del_servidor(**overrides) -> SolicitudPrioridadAbsoluta:
    base = dict(
        id_solicitud=1, vehiculo_id=b"srv-mis-0001", clase_tipo=1, clase_nivel=10,
        estrategia=1, t_servicio_deseado=10, t_salida_estimada=15, t_solicitud=1760000000,
    )
    base.update(overrides)
    return SolicitudPrioridadAbsoluta(**base)


class TestModoSeguroSinRenovacionDelServidor(unittest.TestCase):
    def test_solicitud_activa_caduca_sola_sin_mas_m1(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_del_servidor(), fase_actual="verde")
        self.assertEqual(fila.estado, ACTIVE_PROCESSING)
        t0 = fila.ultima_actualizacion_monotonic

        # "Se corta la conexion con el servidor" = nunca mas llega un M1 que
        # llame a PRS.refrescar(). Nadie publica nada: el UNICO camino que
        # sigue corriendo es el watchdog periodico (verificar_caducidad),
        # que no depende de recibir mensajes.
        self.assertTrue(prs.verificar_caducidad(ahora_monotonic=t0 + T_CAD_SEGUNDOS + 0.5))
        self.assertEqual(prs.fila(1).estado, CLOSED_TIME_TO_LIVE_ERROR)
        self.assertIsNone(prs.fila_activa())

    def test_no_hay_reactivacion_automatica_tras_caducar(self):
        prs = PriorityRequestServer()
        fila = prs.aceptar_solicitud(_solicitud_del_servidor(), fase_actual="amarillo")
        t0 = fila.ultima_actualizacion_monotonic
        self.assertTrue(prs.verificar_caducidad(ahora_monotonic=t0 + T_CAD_SEGUNDOS + 0.5))
        self.assertEqual(prs.fila(1).estado, CLOSED_TIME_TO_LIVE_ERROR)

        # Mucho despues (simula un broker caido por minutos): sigue
        # cerrada, no hay ningun GET/SET ni verificacion periodica que la
        # reactive sola -- el controlador se queda con su plan normal.
        self.assertFalse(prs.verificar_caducidad(ahora_monotonic=t0 + T_CAD_SEGUNDOS + 300))
        self.assertIsNone(prs.intentar_activar_cola(fase_actual="verde"))
        self.assertEqual(prs.fila(1).estado, CLOSED_TIME_TO_LIVE_ERROR)


if __name__ == "__main__":
    unittest.main()
