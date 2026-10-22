"""*** LEGADO (pre-arquitectura centralizada, 2026-10-22) ***
Lee el estado local de la OBU emulada (resultados/obu_vivo/estado.json).
Desde la migración a la arquitectura centralizada, gateway/obu_emulada.py
YA NO escribe ese archivo (la posición viaja en MP hacia el servidor, que
es quien calcula la asignación de RSU/acceso; ver servidor/gestor_mision.py
y docs/CONTRATO_OBU.md) -- este módulo queda sin alimentación y el panel
que lo usa (consola/backend/mapa.py, centro_control/panel/pages/1_Lazo_V2I_en_vivo.py)
no muestra nada nuevo hasta que se adapte para leer la MR/ME del servidor
en su lugar (ver "pendiente" en docs/bitacora/2026-10-22_arquitectura-centralizada.md).
No se borra: sigue siendo válido para reproducir corridas del esquema
anterior (E2+E4) si se vuelve a correr la versión vieja de obu_emulada.py
desde el historial de git."""

from __future__ import annotations

import json
import threading
import time

from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO


def _leer() -> dict | None:
    try:
        datos = json.loads(config.OBU_ESTADO_LOCAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    datos["antiguedad_s"] = time.time() - datos.get("ts", 0)
    return datos


def _ciclo() -> None:
    ultimo = None
    while True:
        t0 = time.time()
        datos = _leer()
        if datos != ultimo:
            ESTADO.set_obu(datos)
            BUS.publicar("obu", datos)
            ultimo = datos
        time.sleep(max(0.0, 0.5 - (time.time() - t0)))


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_ciclo, name="obu-local", daemon=True)
    hilo.start()
    return hilo
