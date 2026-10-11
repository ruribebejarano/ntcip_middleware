#!/usr/bin/env python3
"""Emulador del controlador de transito (protocolo propietario simulado).

*** EMULADOR, NO ES UN CONTROLADOR REAL ***
Sustituye al hardware real del controlador semaforico (el "Regulador RSIM" /
controlador Indra mencionado en CLAUDE.md) para poder desarrollar y probar
el middleware de la RSU sin depender de acceso a ese hardware (ver
Cronograma, Semana 4, decision de reducir riesgo R5). Cuando haya acceso al controlador
real, este archivo se reemplaza por el adaptador que hable su protocolo
propietario real (ver "MANUAL DE PROGRAMAR CONTROL INDRA" en el material de
referencia citado en CLAUDE.md) -- la interfaz hacia agent/rsu_middleware.py
(el protocolo JSON Lines de abajo) es exactamente el punto de reemplazo.

Protocolo (JSON Lines sobre TCP, un objeto JSON por linea, una linea de
respuesta por cada linea de pedido):

    Pedido:     {"cmd": "get_status"}
    Respuesta:  {"fase": "rojo"|"amarillo"|"verde",
                 "prioridad_activa": bool, "prioridad_de": str|null}

    Pedido:     {"cmd": "request_priority", "vehiculo_id": "...", "eta_seg": N}
    Respuesta:  igual que get_status, ya con la prioridad aplicada

    Pedido:     {"cmd": "clear_priority"}
    Respuesta:  igual que get_status, ya sin prioridad

Comportamiento: las fases ciclan solas (rojo -> verde -> amarillo -> rojo...)
salvo que haya una solicitud de prioridad activa, en cuyo caso el controlador
sostiene "verde" -- igual que una fase de preemption real para un vehiculo de
emergencia (EVP) -- hasta que se pida clear_priority o venza PRIORITY_HOLD_SECONDS.

Solo escucha en localhost: el unico cliente esperado es el adaptador del
middleware (agent/rsu_middleware.py), en la misma Raspberry Pi. No expone
nada a la red -- eso lo hace el middleware, vía SNMP.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import EVT_CTRL_FASE_CAMBIO, EventLogger  # noqa: E402

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9000

CYCLE = [("rojo", 8.0), ("verde", 8.0), ("amarillo", 3.0)]
PRIORITY_HOLD_SECONDS = 15.0

# Mismo identificador que agent/rsu_middleware.py (ver RSU_ID ahi): cada
# controlador emulado esta asociado 1 a 1 con la RSU que lo consulta.
RSU_ID = os.environ.get("RSU_ID", "1")


class Controller:
    def __init__(self, eventos: EventLogger | None = None) -> None:
        self._lock = threading.Lock()
        self._phase_idx = 0
        self._phase_started = time.monotonic()
        self._priority_vehicle: str | None = None
        self._priority_request_id = "-"
        self._priority_until = 0.0
        self._eventos = eventos
        self._fase_logueada: str | None = None

    def _fase_actual_locked(self) -> str:
        return "verde" if self._priority_vehicle is not None else CYCLE[self._phase_idx][0]

    def _log_si_cambio_locked(self, id_solicitud: str = "-", **extra) -> None:
        """Registra ctrl_fase_cambio solo si la fase visible realmente
        cambio desde el ultimo evento logueado (evita duplicar un evento
        por cada poll de get_status que no cambia nada)."""
        fase = self._fase_actual_locked()
        if fase == self._fase_logueada:
            return
        self._fase_logueada = fase
        if self._eventos is not None:
            self._eventos.log(
                EVT_CTRL_FASE_CAMBIO,
                id_solicitud,
                fase=fase,
                prioridad_activa=self._priority_vehicle is not None,
                **extra,
            )

    def _advance_locked(self) -> None:
        if self._priority_vehicle is not None:
            if time.monotonic() >= self._priority_until:
                vehiculo_vencido = self._priority_vehicle
                id_vencido = self._priority_request_id
                print(f"[controlador] Prioridad de '{vehiculo_vencido}' vencio, "
                      f"vuelve al ciclo normal")
                self._priority_vehicle = None
                self._log_si_cambio_locked(
                    id_vencido, motivo="caducidad_prioridad", vehiculo_id=vehiculo_vencido
                )
            else:
                return
        else:
            name, duration = CYCLE[self._phase_idx]
            if time.monotonic() - self._phase_started >= duration:
                self._phase_idx = (self._phase_idx + 1) % len(CYCLE)
                self._phase_started = time.monotonic()
                self._log_si_cambio_locked(motivo="ciclo_normal")

    def status(self) -> dict:
        with self._lock:
            self._advance_locked()
            fase = self._fase_actual_locked()
            # Captura tambien el cambio aplicado por request_priority/
            # clear_priority justo antes de este status() (es un no-op si
            # ya se logueo ahi, porque _fase_logueada ya coincide).
            self._log_si_cambio_locked(self._priority_request_id, motivo="poll")
            return {
                "fase": fase,
                "prioridad_activa": self._priority_vehicle is not None,
                "prioridad_de": self._priority_vehicle,
            }

    def request_priority(self, vehiculo_id: str, eta_seg: float, id_solicitud: str = "-") -> None:
        with self._lock:
            self._priority_vehicle = vehiculo_id
            self._priority_until = time.monotonic() + PRIORITY_HOLD_SECONDS
            self._priority_request_id = id_solicitud
            self._log_si_cambio_locked(
                id_solicitud, motivo="solicitud_prioridad", vehiculo_id=vehiculo_id, eta_seg=eta_seg
            )
        print(f"[controlador] Prioridad solicitada por '{vehiculo_id}' (ETA {eta_seg}s) "
              f"-> fase forzada a verde por {PRIORITY_HOLD_SECONDS:.0f}s")

    def clear_priority(self, id_solicitud: str = "-") -> None:
        with self._lock:
            id_para_log = id_solicitud if id_solicitud != "-" else self._priority_request_id
            self._priority_vehicle = None
            self._log_si_cambio_locked(id_para_log, motivo="liberacion_manual")
        print("[controlador] Prioridad liberada manualmente, vuelve al ciclo normal")


def _handle_client(conn: socket.socket, controller: Controller) -> None:
    with conn:
        reader = conn.makefile("r", encoding="utf-8")
        writer = conn.makefile("w", encoding="utf-8")
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                writer.write(json.dumps({"error": "JSON invalido"}) + "\n")
                writer.flush()
                continue

            cmd = request.get("cmd")
            id_solicitud = request.get("id_solicitud", "-")
            if cmd == "get_status":
                response = controller.status()
            elif cmd == "request_priority":
                controller.request_priority(
                    request.get("vehiculo_id", "?"), request.get("eta_seg", 0), id_solicitud
                )
                response = controller.status()
            elif cmd == "clear_priority":
                controller.clear_priority(id_solicitud)
                response = controller.status()
            else:
                response = {"error": f"comando desconocido: {cmd!r}"}

            writer.write(json.dumps(response) + "\n")
            writer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    args = parser.parse_args()

    eventos = EventLogger(f"ctrl_{RSU_ID}")
    controller = Controller(eventos=eventos)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, args.port))
    server.listen()

    print(f"Emulador de controlador de transito escuchando en {LISTEN_HOST}:{args.port}")
    print("(protocolo propietario simulado, JSON Lines -- ver cabecera del modulo)")
    print(f"RSU_ID={RSU_ID} -- registro de eventos en {eventos.path}")
    print("Ctrl+C para detener.\n")

    try:
        while True:
            conn, _addr = server.accept()
            threading.Thread(target=_handle_client, args=(conn, controller), daemon=True).start()
    except KeyboardInterrupt:
        print("\nDeteniendo emulador de controlador...")
    finally:
        server.close()


if __name__ == "__main__":
    main()
