#!/usr/bin/env python3
"""Punto de entrada unico de la consola web del centro de control.

Uso (desde la raiz del repo):
    python consola/servidor.py

Arranca uvicorn en 127.0.0.1 (SOLO localhost, ver docs/CONSOLA.md) y abre
el navegador. Configuracion en consola/.env (ver consola/.env.example)."""

from __future__ import annotations

import asyncio
import sys
import threading
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

if sys.platform == "win32":
    # pysnmp.hlapi (consola/backend/snmp_poller.py) crea y cierra su propio
    # event loop de asyncio en cada GET/WALK, desde un hilo en segundo
    # plano. Con el ProactorEventLoop que usa Windows por defecto, eso
    # corrompe el "self-pipe" del loop principal de uvicorn ("Cannot run
    # the event loop while another loop is running", luego errores de
    # asyncio hasta tumbar el servidor) -- se reprodujo en pruebas locales
    # contra una RSU real. El SelectorEventLoop no tiene ese problema (no
    # usa IOCP) y es suficiente aqui: nada en esta app depende de
    # subprocesos asincronos de asyncio (los de consola/backend/pruebas.py
    # usan subprocess.Popen normal, sin asyncio).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402

from consola.backend import config  # noqa: E402


def _abrir_navegador(url: str) -> None:
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()


def main() -> None:
    url = f"http://{config.CONSOLA_HOST}:{config.CONSOLA_PORT}/"
    print(f"=== Consola del centro de control === {url}")
    print(f"MQTT: {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}  "
          f"SNMP: {config.SNMP_HOST}:{config.SNMP_PORT}  SSH: {config.SSH_HOST_ALIAS}")
    if not config.ENV_ENCONTRADO:
        print("Aviso: consola/.env no encontrado, usando valores de laboratorio por defecto "
              "(ver consola/.env.example).")
    _abrir_navegador(url)
    uvicorn.run("consola.backend.api:app", host=config.CONSOLA_HOST, port=config.CONSOLA_PORT, log_level="info")


if __name__ == "__main__":
    main()
