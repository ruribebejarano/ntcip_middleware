"""Registro de auditoria de la consola (pantalla 3): toda accion que la
consola ejecuta o envia -- lecturas/escrituras SNMP, mensajes MQTT
publicados, comandos SSH, subprocesos lanzados, y las ordenes que la RSU
le da al controlador (leidas de sus propios eventos). Persistido en
resultados/consola/registro_comandos.jsonl (una linea JSON por entrada,
nunca se sobrescribe) y difundido por consola/backend/bus.py para que la
pantalla de comandos se actualice en vivo."""

from __future__ import annotations

import itertools
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from consola.backend import config
from consola.backend.bus import BUS

CANALES = ("MQTT", "SNMPv3", "TCP RSU->controlador", "SSH", "proceso local")


class RegistroComandos:
    def __init__(self, ruta: Path, en_memoria: int = 4000) -> None:
        self.ruta = ruta
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._contador = itertools.count(1)
        self._memoria: deque[dict] = deque(maxlen=en_memoria)
        self._cargar_existentes()

    def _cargar_existentes(self) -> None:
        if not self.ruta.exists():
            return
        try:
            lineas = self.ruta.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for linea in lineas[-self._memoria.maxlen:]:
            try:
                entrada = json.loads(linea)
            except json.JSONDecodeError:
                continue
            self._memoria.append(entrada)
        if self._memoria:
            self._contador = itertools.count(max(e.get("n", 0) for e in self._memoria) + 1)

    def registrar(self, origen: str, destino: str, canal: str, comando: Any, resultado: Any = None,
                  id_solicitud: str | None = None) -> dict:
        if canal not in CANALES:
            raise ValueError(f"canal desconocido: {canal!r} (usar uno de {CANALES})")
        entrada = {
            "n": next(self._contador),
            "ts": time.time(),
            "origen": origen,
            "destino": destino,
            "canal": canal,
            "comando": comando,
            "resultado": resultado,
            "id_solicitud": id_solicitud,
        }
        linea = json.dumps(entrada, ensure_ascii=False, default=str)
        with self._lock:
            self._memoria.append(entrada)
            with self.ruta.open("a", encoding="utf-8") as fh:
                fh.write(linea + "\n")
        BUS.publicar("comando", entrada)
        return entrada

    def listar(self, canal: str | None = None, texto: str | None = None, limite: int = 500) -> list[dict]:
        with self._lock:
            filas = list(self._memoria)
        if canal:
            filas = [f for f in filas if f["canal"] == canal]
        if texto:
            t = texto.lower()

            def coincide(f: dict) -> bool:
                return (t in str(f.get("comando", "")).lower() or t in str(f.get("resultado", "")).lower()
                        or t in str(f.get("id_solicitud") or "").lower() or t in f["origen"].lower()
                        or t in f["destino"].lower())

            filas = [f for f in filas if coincide(f)]
        return filas[-limite:][::-1]


REGISTRO = RegistroComandos(config.REGISTRO_COMANDOS_PATH)
