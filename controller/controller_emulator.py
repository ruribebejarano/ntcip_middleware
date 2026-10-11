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

Ciclo de fases: a partir de esta version (P2, OE3), el ciclo normal usa
TIEMPOS REALES de NTCIP 1202 (ver agent/rsu_middleware.py para los objetos
expuestos por SNMP), no constantes arbitrarias:

    verde        -- phaseMinimumGreen (segundos, NTCIP 1206.4.2.1.1.2.1.4)
    amarillo     -- phaseYellowChange (decimas de segundo, .2.1.8)
    todo_rojo    -- phaseRedClear (decimas de segundo, .2.1.9)
    rojo_general -- NO es un objeto NTCIP: tiempo en que (fuera de esta
                     maqueta de una sola fase) otras fases tendrian verde.
                     Configurable, sin equivalente normativo.

"todo_rojo" y "rojo_general" se funden en un unico estado de salida "red"
a nivel de bit de estado (ver phaseStatusGroupReds en el middleware): la
norma no distingue el despeje del resto del rojo a ese nivel, solo en los
parametros de tiempo.

Protocolo (JSON Lines sobre TCP, un objeto JSON por linea, una linea de
respuesta por cada linea de pedido):

    Pedido:     {"cmd": "get_status"}
    Respuesta:  {"fase": "verde"|"amarillo"|"todo_rojo"|"rojo_general",
                 "red": bool, "yellow": bool, "green": bool,
                 "prioridad_activa": bool, "prioridad_de": str|null}

    Pedido:     {"cmd": "get_timing"}
    Respuesta:  {"phase_minimum_green": int (s), "phase_yellow_change": int (decimas de s),
                 "phase_red_clear": int (decimas de s), "rojo_general_seg": int (s, no NTCIP)}

    Pedido:     {"cmd": "set_timing", "phase_minimum_green": N?, "phase_yellow_change": N?,
                 "phase_red_clear": N?, "rojo_general_seg": N?}
                (cualquier subconjunto de campos; los omitidos no cambian)
    Respuesta:  igual que get_timing, ya actualizado

    Pedido:     {"cmd": "request_priority", "vehiculo_id": "...", "eta_seg": N, "id_solicitud": "..."}
    Respuesta:  igual que get_status, ya con la prioridad aplicada (fase forzada a verde)

    Pedido:     {"cmd": "clear_priority", "id_solicitud": "..."}
    Respuesta:  igual que get_status, ya sin prioridad

Comportamiento: las fases ciclan solas (verde -> amarillo -> todo_rojo ->
rojo_general -> verde...) salvo que haya una solicitud de prioridad activa,
en cuyo caso el controlador sostiene "verde" -- igual que una fase de
preemption real para un vehiculo de emergencia (EVP) -- hasta que se pida
clear_priority o venza PRIORITY_HOLD_SECONDS.

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

PRIORITY_HOLD_SECONDS = 15.0

# Valores por defecto de los parametros de tiempo (NTCIP 1202, rangos del
# estandar entre parentesis). No son los tiempos de ninguna interseccion
# real: configurables por argumento o por set_timing.
DEFAULT_PHASE_MINIMUM_GREEN_S = 8     # segundos (rango NTCIP: 1-255)
DEFAULT_PHASE_YELLOW_CHANGE_DS = 30   # decimas de segundo = 3.0 s (rango NTCIP: 3-255, i.e. 0.3-25.5 s)
DEFAULT_PHASE_RED_CLEAR_DS = 20       # decimas de segundo = 2.0 s (rango NTCIP: 0-255, i.e. 0-25.5 s)
DEFAULT_ROJO_GENERAL_S = 8            # segundos, sin equivalente NTCIP (ver docstring del modulo)

# Mismo identificador que agent/rsu_middleware.py (ver RSU_ID ahi): cada
# controlador emulado esta asociado 1 a 1 con la RSU que lo consulta.
RSU_ID = os.environ.get("RSU_ID", "1")


class Controller:
    def __init__(
        self,
        eventos: EventLogger | None = None,
        phase_minimum_green_s: int = DEFAULT_PHASE_MINIMUM_GREEN_S,
        phase_yellow_change_ds: int = DEFAULT_PHASE_YELLOW_CHANGE_DS,
        phase_red_clear_ds: int = DEFAULT_PHASE_RED_CLEAR_DS,
        rojo_general_s: int = DEFAULT_ROJO_GENERAL_S,
    ) -> None:
        self._lock = threading.Lock()
        self._phase_minimum_green_s = phase_minimum_green_s
        self._phase_yellow_change_ds = phase_yellow_change_ds
        self._phase_red_clear_ds = phase_red_clear_ds
        self._rojo_general_s = rojo_general_s
        self._phase_idx = 0
        self._phase_started = time.monotonic()
        self._priority_vehicle: str | None = None
        self._priority_request_id = "-"
        self._priority_until = 0.0
        self._eventos = eventos
        self._fase_logueada: str | None = None

    # --- Ciclo de fases -----------------------------------------------

    def _cycle_locked(self) -> list[tuple[str, float]]:
        """Duraciones vigentes en SEGUNDOS, recalculadas en cada llamada
        para reflejar cambios aplicados por set_timing en vivo."""
        return [
            ("verde", float(self._phase_minimum_green_s)),
            ("amarillo", self._phase_yellow_change_ds / 10.0),
            ("todo_rojo", self._phase_red_clear_ds / 10.0),
            ("rojo_general", float(self._rojo_general_s)),
        ]

    def _fase_actual_locked(self) -> str:
        if self._priority_vehicle is not None:
            return "verde"
        return self._cycle_locked()[self._phase_idx][0]

    @staticmethod
    def _estado_ntcip(fase: str) -> tuple[bool, bool, bool]:
        """(red, yellow, green) -- la norma no distingue todo_rojo de
        rojo_general a nivel de bit de salida, ver docstring del modulo."""
        if fase == "verde":
            return (False, False, True)
        if fase == "amarillo":
            return (False, True, False)
        return (True, False, False)  # todo_rojo o rojo_general

    def _log_si_cambio_locked(self, id_solicitud: str = "-", **extra) -> None:
        """Registra ctrl_fase_cambio solo si la fase visible realmente
        cambio desde el ultimo evento logueado (evita duplicar un evento
        por cada poll de estado que no cambia nada)."""
        fase = self._fase_actual_locked()
        if fase == self._fase_logueada:
            return
        self._fase_logueada = fase
        # print() ademas del registro CSV: sin esto, el ciclo normal (fuera
        # de una solicitud de prioridad) no deja ningun rastro visible en
        # journalctl -- se detecto al intentar capturar evidencia de un
        # ciclo completo para la bitacora (2026-10-11).
        print(f"[controlador] Fase -> {fase} ({extra.get('motivo', '?')})")
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
            cycle = self._cycle_locked()
            _name, duration = cycle[self._phase_idx]
            if time.monotonic() - self._phase_started >= duration:
                self._phase_idx = (self._phase_idx + 1) % len(cycle)
                self._phase_started = time.monotonic()
                self._log_si_cambio_locked(motivo="ciclo_normal")

    # --- API expuesta a _handle_client ---------------------------------

    def status(self) -> dict:
        with self._lock:
            self._advance_locked()
            fase = self._fase_actual_locked()
            # Captura tambien el cambio aplicado por request_priority/
            # clear_priority justo antes de este status() (es un no-op si
            # ya se logueo ahi, porque _fase_logueada ya coincide).
            self._log_si_cambio_locked(self._priority_request_id, motivo="poll")
            red, yellow, green = self._estado_ntcip(fase)
            return {
                "fase": fase,
                "red": red,
                "yellow": yellow,
                "green": green,
                "prioridad_activa": self._priority_vehicle is not None,
                "prioridad_de": self._priority_vehicle,
            }

    def timing(self) -> dict:
        with self._lock:
            return {
                "phase_minimum_green": self._phase_minimum_green_s,
                "phase_yellow_change": self._phase_yellow_change_ds,
                "phase_red_clear": self._phase_red_clear_ds,
                "rojo_general_seg": self._rojo_general_s,
            }

    def set_timing(
        self,
        phase_minimum_green: int | None = None,
        phase_yellow_change: int | None = None,
        phase_red_clear: int | None = None,
        rojo_general_seg: int | None = None,
    ) -> dict:
        with self._lock:
            if phase_minimum_green is not None:
                self._phase_minimum_green_s = int(phase_minimum_green)
            if phase_yellow_change is not None:
                self._phase_yellow_change_ds = int(phase_yellow_change)
            if phase_red_clear is not None:
                self._phase_red_clear_ds = int(phase_red_clear)
            if rojo_general_seg is not None:
                self._rojo_general_s = int(rojo_general_seg)
            print(f"[controlador] Tiempos actualizados: verde={self._phase_minimum_green_s}s "
                  f"amarillo={self._phase_yellow_change_ds/10:.1f}s "
                  f"todo_rojo={self._phase_red_clear_ds/10:.1f}s "
                  f"rojo_general={self._rojo_general_s}s")
        return self.timing()

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
            elif cmd == "get_timing":
                response = controller.timing()
            elif cmd == "set_timing":
                response = controller.set_timing(
                    phase_minimum_green=request.get("phase_minimum_green"),
                    phase_yellow_change=request.get("phase_yellow_change"),
                    phase_red_clear=request.get("phase_red_clear"),
                    rojo_general_seg=request.get("rojo_general_seg"),
                )
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
    parser.add_argument("--phase-minimum-green", type=int, default=DEFAULT_PHASE_MINIMUM_GREEN_S,
                         help="segundos (NTCIP phaseMinimumGreen, rango 1-255)")
    parser.add_argument("--phase-yellow-change", type=int, default=DEFAULT_PHASE_YELLOW_CHANGE_DS,
                         help="decimas de segundo (NTCIP phaseYellowChange, rango 3-255)")
    parser.add_argument("--phase-red-clear", type=int, default=DEFAULT_PHASE_RED_CLEAR_DS,
                         help="decimas de segundo (NTCIP phaseRedClear, rango 0-255)")
    parser.add_argument("--rojo-general", type=int, default=DEFAULT_ROJO_GENERAL_S,
                         help="segundos (sin equivalente NTCIP, ver docstring del modulo)")
    args = parser.parse_args()

    eventos = EventLogger(f"ctrl_{RSU_ID}")
    controller = Controller(
        eventos=eventos,
        phase_minimum_green_s=args.phase_minimum_green,
        phase_yellow_change_ds=args.phase_yellow_change,
        phase_red_clear_ds=args.phase_red_clear,
        rojo_general_s=args.rojo_general,
    )
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, args.port))
    server.listen()

    print(f"Emulador de controlador de transito escuchando en {LISTEN_HOST}:{args.port}")
    print("(protocolo propietario simulado, JSON Lines -- ver cabecera del modulo)")
    print(f"RSU_ID={RSU_ID} -- registro de eventos en {eventos.path}")
    t = controller.timing()
    print(f"Tiempos: verde={t['phase_minimum_green']}s "
          f"amarillo={t['phase_yellow_change']/10:.1f}s "
          f"todo_rojo={t['phase_red_clear']/10:.1f}s "
          f"rojo_general={t['rojo_general_seg']}s")
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
