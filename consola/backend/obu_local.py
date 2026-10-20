"""Lee el estado local de la OBU emulada (resultados/obu_vivo/estado.json,
escrito por gateway/obu_emulada.py) cada 0.5 s. La posicion NUNCA viaja por
MQTT (ssec:minimizacion de main.tex): esta es la unica fuente de la
posicion del vehiculo para el mapa de la consola, igual que en
centro_control/panel/pages/1_Lazo_V2I_en_vivo.py."""

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
