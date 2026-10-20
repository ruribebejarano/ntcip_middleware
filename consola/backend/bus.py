"""Difusor de eventos en vivo hacia los clientes SSE (/sse). Los hilos en
segundo plano (mqtt_cliente, snmp_poller, obu_local, eventos_remotos,
estado_banco, pruebas, registro_comandos) llaman a `publicar()` desde
hilos normales de Python; este modulo cruza al hilo del event loop de
asyncio con call_soon_threadsafe, que es seguro de llamar desde cualquier
hilo."""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any


class BusEventos:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscriptores: set[asyncio.Queue] = set()
        self._contador = itertools.count(1)

    def fijar_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def suscribirse(self) -> asyncio.Queue:
        """Debe llamarse desde el hilo del event loop (p. ej. en el
        generador async del endpoint /sse)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscriptores.add(q)
        return q

    def desuscribirse(self, q: asyncio.Queue) -> None:
        self._subscriptores.discard(q)

    def publicar(self, tipo: str, datos: Any) -> dict:
        """Seguro de llamar desde cualquier hilo. Devuelve el evento
        publicado (con su id y marca de tiempo), por si el llamador
        tambien lo quiere guardar en el estado compartido."""
        evento = {"id": next(self._contador), "ts": time.time(), "tipo": tipo, "datos": datos}
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._publicar_en_loop, evento)
        return evento

    def _publicar_en_loop(self, evento: dict) -> None:
        for q in list(self._subscriptores):
            try:
                q.put_nowait(evento)
            except asyncio.QueueFull:
                # Cliente lento: se descarta el mas antiguo para no crecer
                # sin limite (la vista en vivo prefiere lo reciente).
                try:
                    q.get_nowait()
                    q.put_nowait(evento)
                except asyncio.QueueEmpty:
                    pass


BUS = BusEventos()
