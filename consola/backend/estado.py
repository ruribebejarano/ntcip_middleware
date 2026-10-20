"""Estado compartido en memoria: cada hilo en segundo plano (mqtt_cliente,
snmp_poller, obu_local, eventos_remotos, estado_banco, pruebas) escribe su
parte aqui bajo un lock, y GET /api/estado devuelve una foto completa para
que la pantalla de monitoreo tenga algo que mostrar apenas carga, antes de
que lleguen eventos nuevos por /sse."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional


class EstadoCompartido:
    def __init__(self) -> None:
        self._lock = threading.Lock()

        self.mqtt_conectado = False
        self.mqtt_error: Optional[str] = None
        self.mensajes_mqtt: deque[dict] = deque(maxlen=400)

        self.snmp_semaforo: dict = {"red": False, "yellow": False, "green": False, "error": "sin datos todavia"}
        self.snmp_tabla_prs: list[dict] = []
        self.snmp_tiempos: dict = {}
        self.snmp_ultima_lectura_ts: float = 0.0

        self.obu: Optional[dict] = None
        self.obu_ultima_ts: float = 0.0

        self.eventos_lazo: deque[dict] = deque(maxlen=800)
        self._ultimo_ts_rsu_ns: int = 0
        self._ultimo_ts_ctrl_ns: int = 0

        self.banco: dict = {
            "tailscale": {"ok": None, "detalle": "sin verificar"},
            "rsu_ssh": {"ok": None, "detalle": "sin verificar"},
            "servicios": {"agent": None, "controller": None},
            "broker_rsu": {"ok": None, "detalle": "sin verificar"},
            "desfase_reloj": {"ok": None, "detalle": "sin verificar"},
            "ts": 0.0,
        }

        self.procesos: dict[str, dict] = {}  # nombre_prueba -> {"activo": bool, "pid": int|None, "lineas": deque}

    # --- MQTT ---
    def set_mqtt_conexion(self, conectado: bool, error: Optional[str] = None) -> None:
        with self._lock:
            self.mqtt_conectado = conectado
            self.mqtt_error = error

    def agregar_mensaje_mqtt(self, m: dict) -> None:
        with self._lock:
            self.mensajes_mqtt.appendleft(m)

    # --- SNMP ---
    def set_snmp_semaforo(self, estado: dict) -> None:
        with self._lock:
            self.snmp_semaforo = estado
            self.snmp_ultima_lectura_ts = time.time()

    def set_snmp_tabla_prs(self, filas: list[dict]) -> None:
        with self._lock:
            self.snmp_tabla_prs = filas

    def set_snmp_tiempos(self, tiempos: dict) -> None:
        with self._lock:
            self.snmp_tiempos = tiempos

    # --- OBU local ---
    def set_obu(self, datos: Optional[dict]) -> None:
        with self._lock:
            self.obu = datos
            self.obu_ultima_ts = time.time()

    # --- Eventos del lazo (RSU/controlador por SSH, OBU por MQTT) ---
    def agregar_evento_lazo(self, e: dict) -> None:
        with self._lock:
            self.eventos_lazo.appendleft(e)

    def ultimo_ts_rsu_ns(self) -> int:
        with self._lock:
            return self._ultimo_ts_rsu_ns

    def set_ultimo_ts_rsu_ns(self, v: int) -> None:
        with self._lock:
            self._ultimo_ts_rsu_ns = v

    def ultimo_ts_ctrl_ns(self) -> int:
        with self._lock:
            return self._ultimo_ts_ctrl_ns

    def set_ultimo_ts_ctrl_ns(self, v: int) -> None:
        with self._lock:
            self._ultimo_ts_ctrl_ns = v

    # --- Estado del banco ---
    def set_banco(self, datos: dict) -> None:
        with self._lock:
            self.banco = {**datos, "ts": time.time()}

    # --- Procesos de prueba (gateway/obu_emulada.py) ---
    def set_proceso(self, nombre: str, info: dict) -> None:
        with self._lock:
            self.procesos[nombre] = info

    # --- Foto completa para GET /api/estado ---
    def foto(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mqtt": {"conectado": self.mqtt_conectado, "error": self.mqtt_error,
                         "mensajes": list(self.mensajes_mqtt)[:60]},
                "snmp": {"semaforo": self.snmp_semaforo, "tabla_prs": self.snmp_tabla_prs,
                         "tiempos": self.snmp_tiempos, "ultima_lectura_ts": self.snmp_ultima_lectura_ts},
                "obu": self.obu,
                "eventos_lazo": list(self.eventos_lazo)[:200],
                "banco": self.banco,
                "procesos": {n: {"activo": p["activo"], "lineas": list(p["lineas"])[-200:]}
                             for n, p in self.procesos.items()},
            }


ESTADO = EstadoCompartido()
