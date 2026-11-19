#!/usr/bin/env python3
"""Emulador del controlador de transito (protocolo propietario simulado).

*** EMULADOR, NO ES UN CONTROLADOR REAL ***
Sustituye al hardware real del controlador semaforico (el "Regulador RSIM" /
controlador Indra mencionado en CLAUDE.md) para poder desarrollar y probar
el middleware de la RSU sin depender de acceso a ese hardware (riesgo R5).
Con acceso al controlador real, este archivo se reemplaza por el adaptador que hable su protocolo
propietario real (ver "MANUAL DE PROGRAMAR CONTROL INDRA" en el material de
referencia citado en CLAUDE.md) -- la interfaz hacia agent/rsu_middleware.py
(el protocolo JSON Lines de abajo) es exactamente el punto de reemplazo.

Ciclo de fases: el ciclo normal usa
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

La fase nominal se calcula por modulo de un reloj continuo
(Controller._fase_en_offset_locked), no avanzando un paso por cada llamada
a status(): nada hace poll al controlador mientras no hay una solicitud
activa, y un avance por pasos dejaria la fase reportada atrasada.

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

Modo multifase (--fases-conflicto): por defecto, una solicitud
que llega en "rojo_general" recibe el verde de inmediato, como si ninguna
otra fase tuviera verde. Un controlador real no puede hacer eso: si el
grupo solicitado esta en rojo es porque otra fase tiene verde, y esa fase
debe cumplir su verde minimo, su ambar y su todo rojo antes de ceder
(ecuacion de T_desp de la tesis). Con --fases-conflicto 28,20 el
"rojo_general" pasa a ser la secuencia de esas fases (verde de cada una +
ambar + todo rojo, con los tiempos de phaseYellowChange/phaseRedClear), y
una solicitud que llega en medio de ella espera ese despeje: mientras
espera, el grupo sigue reportando "rojo_general" y la prioridad cuenta su
tiempo de sostenimiento desde que se concede el verde. --verde-plan fija la
duracion del verde del grupo solicitado en el plan (por defecto, el verde
minimo). Tiempos de referencia: tabla 21-23 del manual del
controlador INDRA (ejemplo E06-01: ambar 3 s, rojo-rojo 1 s, verde minimo
5 s, verdes de plan 50/28/20 s).

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
        desfase_s: float = 0.0,
        verde_plan_s: float | None = None,
        fases_conflicto_s: list[float] | None = None,
        verde_min_conflicto_s: float | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._phase_minimum_green_s = phase_minimum_green_s
        self._phase_yellow_change_ds = phase_yellow_change_ds
        self._phase_red_clear_ds = phase_red_clear_ds
        self._rojo_general_s = rojo_general_s
        # Modo multifase (ver docstring del modulo): None/[] = comportamiento
        # anterior (verde inmediato en rojo_general).
        self._verde_plan_s = verde_plan_s
        self._fases_conflicto_s = [float(g) for g in (fases_conflicto_s or [])]
        self._verde_min_conflicto_s = verde_min_conflicto_s
        # Instante (monotonic) en que se concede el verde a una solicitud que
        # llego durante el verde de una fase en conflicto; None si no hay espera.
        self._verde_en: float | None = None
        # Ancla del ciclo normal: un reloj CONTINUO desde la construccion,
        # nunca se reinicia ni se congela (ver _fase_normal_locked). Una
        # solicitud de prioridad activa SOLO sobre-escribe lo que se
        # REPORTA (fuerza "verde"); el ciclo de fondo sigue corriendo
        # igual, asi que al liberar la prioridad se reporta la fase real
        # segun el tiempo transcurrido, no una congelada desde antes de
        # la prioridad.
        # desfase_s (campaña de ruta completa): arranca el ciclo como si
        # ya hubieran pasado desfase_s segundos desde el inicio del verde,
        # para que varios controladores lanzados juntos no queden en fase.
        # Con 0 (por defecto) el comportamiento es el de siempre.
        self._desfase_s = float(desfase_s)
        self._epoch = time.monotonic() - self._desfase_s
        # Mismo instante en reloj de pared (ns): inicio de un verde del plan.
        # Con esto el análisis puede saber la fase del plan en cualquier
        # instante sin depender de los polls.
        self._epoch_wall_ns = time.time_ns() - int(self._desfase_s * 1e9)
        self._priority_vehicle: str | None = None
        self._priority_request_id = "-"
        self._priority_until = 0.0
        self._eventos = eventos
        self._fase_logueada: str | None = None
        # Salida de la prioridad: al liberar, el grupo no salta a
        # la fase del plan. Respeta el verde mínimo desde que empezó el verde,
        # pasa por ámbar y todo rojo, y retoma el plan cuando este está en
        # verde o en rojo general (nunca entra al plan a mitad de un ámbar o
        # un todo rojo). _salida_ambar: instante (monotonic) en que empieza
        # el ámbar de salida; None fuera de una salida.
        self._salida_ambar: float | None = None
        self._verde_desde = 0.0

    # --- Ciclo de fases -----------------------------------------------

    def _cycle_locked(self) -> list[tuple[str, float]]:
        """Duraciones vigentes en SEGUNDOS, recalculadas en cada llamada
        para reflejar cambios aplicados por set_timing en vivo."""
        verde = float(self._verde_plan_s) if self._verde_plan_s is not None else float(self._phase_minimum_green_s)
        return [
            ("verde", verde),
            ("amarillo", self._phase_yellow_change_ds / 10.0),
            ("todo_rojo", self._phase_red_clear_ds / 10.0),
            ("rojo_general", self._rojo_general_efectivo_locked()),
        ]

    def _rojo_general_efectivo_locked(self) -> float:
        """Duracion del rojo_general: en modo multifase, la suma de las fases
        en conflicto con su ambar y su todo rojo; si no, rojo_general_s."""
        if not self._fases_conflicto_s:
            return float(self._rojo_general_s)
        transicion = self._phase_yellow_change_ds / 10.0 + self._phase_red_clear_ds / 10.0
        return sum(g + transicion for g in self._fases_conflicto_s)

    def _espera_conflicto_locked(self, ahora: float) -> float:
        """Modo multifase: segundos hasta poder dar el verde a una solicitud
        que llega en `ahora` durante el rojo_general del plan. La fase en
        conflicto en curso cumple su verde minimo (desde que empezo su
        verde), y luego su ambar y su todo rojo (T_desp de la tesis). Si
        llega durante una de esas transiciones, espera lo que le falta."""
        if not self._fases_conflicto_s:
            return 0.0
        cycle = self._cycle_locked()
        total = sum(d for _, d in cycle)
        inicio_rg = sum(d for nombre, d in cycle if nombre != "rojo_general")
        u = ((ahora - self._epoch) % total) - inicio_rg
        if u < 0:
            return 0.0
        ambar = self._phase_yellow_change_ds / 10.0
        todo_rojo = self._phase_red_clear_ds / 10.0
        vmin = (float(self._verde_min_conflicto_s) if self._verde_min_conflicto_s is not None
                else float(self._phase_minimum_green_s))
        for g in self._fases_conflicto_s:
            if u < g:
                return max(0.0, min(vmin, g) - u) + ambar + todo_rojo
            u -= g
            if u < ambar + todo_rojo:
                return ambar + todo_rojo - u
            u -= ambar + todo_rojo
        return 0.0

    def _fase_en_offset_locked(self, offset_s: float) -> str:
        """Fase nominal a `offset_s` segundos desde self._epoch, calculada
        de una vez por modulo del ciclo TOTAL vigente -- no por pasos: nada
        hace poll al controlador mientras no hay una solicitud en curso, y
        avanzar UNA fase por llamada a status() dejaria reportada una fase
        atrasada. Con el modulo, no importa cuanto
        tiempo paso sin consultar: la fase devuelta es siempre la correcta
        segun el reloj."""
        cycle = self._cycle_locked()
        total = sum(duracion for _, duracion in cycle)
        if total <= 0:
            return cycle[0][0]
        t = offset_s % total
        acumulado = 0.0
        for nombre, duracion in cycle:
            acumulado += duracion
            if t < acumulado:
                return nombre
        return cycle[-1][0]

    def _fase_normal_locked(self) -> str:
        """Fase del ciclo normal (sin prioridad) en este instante -- el
        reloj de fondo (self._epoch) NUNCA se pausa ni se reinicia, ni
        siquiera durante una solicitud de prioridad activa (ver
        _fase_actual_locked): asi, al liberar la prioridad, esta funcion
        ya refleja el tiempo que de verdad paso, sin necesitar "saltar" a
        ningun estado guardado de antes de la prioridad."""
        return self._fase_en_offset_locked(time.monotonic() - self._epoch)

    def _inicio_verde_plan_locked(self, ahora: float) -> float:
        """Instante (monotonic) en que empezó el verde del plan en curso;
        solo tiene sentido si el plan está en verde en `ahora`."""
        total = sum(d for _, d in self._cycle_locked())
        if total <= 0:
            return ahora
        return ahora - ((ahora - self._epoch) % total)

    def _iniciar_salida_locked(self, liberacion: float) -> None:
        """Programa la salida de la prioridad liberada en `liberacion`: el
        ámbar empieza cuando se cumple el verde mínimo (si ya se cumplió,
        de inmediato)."""
        self._salida_ambar = max(liberacion, self._verde_desde + self._phase_minimum_green_s)

    def _fase_actual_locked(self) -> str:
        if self._priority_vehicle is not None:
            if self._verde_en is not None and time.monotonic() < self._verde_en:
                return "rojo_general"  # la fase en conflicto todavia despeja
            return "verde"
        if self._salida_ambar is not None:
            t = time.monotonic() - self._salida_ambar
            ambar = self._phase_yellow_change_ds / 10.0
            todo_rojo = self._phase_red_clear_ds / 10.0
            if t < 0:
                return "verde"
            if t < ambar:
                return "amarillo"
            if t < ambar + todo_rojo:
                return "todo_rojo"
            plan = self._fase_normal_locked()
            if plan in ("verde", "rojo_general"):
                self._salida_ambar = None  # plan recuperado
                return plan
            return "rojo_general"  # el plan sigue en su ámbar/todo rojo: el grupo espera en rojo
        return self._fase_normal_locked()

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
        # journalctl.
        print(f"[controlador] Fase -> {fase} ({extra.get('motivo', '?')})")
        if self._eventos is not None:
            self._eventos.log(
                EVT_CTRL_FASE_CAMBIO,
                id_solicitud,
                fase=fase,
                prioridad_activa=self._priority_vehicle is not None,
                **extra,
            )

    def _sincronizar_locked(self) -> None:
        """Pone al dia _fase_logueada/el log de eventos con la fase que
        corresponde AHORA (ver _fase_actual_locked) -- no "avanza" nada
        manualmente, solo detecta caducidad de prioridad y deja que
        _log_si_cambio_locked (llamado aqui y de nuevo en status()) lea la
        fase real."""
        if self._priority_vehicle is not None and time.monotonic() >= self._priority_until:
            vehiculo_vencido = self._priority_vehicle
            id_vencido = self._priority_request_id
            print(f"[controlador] Prioridad de '{vehiculo_vencido}' vencio, "
                  f"sale por ambar y todo rojo")
            self._priority_vehicle = None
            self._verde_en = None
            self._iniciar_salida_locked(self._priority_until)
            self._log_liberacion_locked(id_vencido, "caducidad_prioridad", vehiculo_id=vehiculo_vencido)
        elif self._priority_vehicle is None:
            self._log_si_cambio_locked(motivo="ciclo_normal")

    # --- API expuesta a _handle_client ---------------------------------

    def status(self) -> dict:
        with self._lock:
            self._sincronizar_locked()
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
                # campos adicionales; el middleware no los usa
                "fase_plan": self._fase_normal_locked(),
                "en_salida": self._salida_ambar is not None,
            }

    def timing(self) -> dict:
        with self._lock:
            return {
                "phase_minimum_green": self._phase_minimum_green_s,
                "phase_yellow_change": self._phase_yellow_change_ds,
                "phase_red_clear": self._phase_red_clear_ds,
                "rojo_general_seg": self._rojo_general_s,
                # modo multifase; el middleware no los usa
                "verde_plan_seg": self._verde_plan_s,
                "fases_conflicto_seg": list(self._fases_conflicto_s),
                "verde_min_conflicto_seg": self._verde_min_conflicto_s,
                "rojo_general_efectivo_seg": self._rojo_general_efectivo_locked(),
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
        espera = 0.0
        with self._lock:
            ahora = time.monotonic()
            fase_previa = self._fase_actual_locked()
            if self._priority_vehicle is None and fase_previa == "verde":
                # ya estaba en verde: el verde mínimo cuenta desde su inicio
                self._verde_desde = (self._verde_desde if self._salida_ambar is not None
                                     else self._inicio_verde_plan_locked(ahora))
                self._verde_en = None
            elif self._priority_vehicle is None:
                # Modo multifase: si el plan está en el verde (o la transición)
                # de una fase en conflicto, el verde llega cuando esta despeja.
                if fase_previa == "rojo_general" and self._salida_ambar is None:
                    espera = self._espera_conflicto_locked(ahora)
                self._verde_en = ahora + espera if espera > 0 else None
                self._verde_desde = ahora + espera
            self._salida_ambar = None
            self._priority_vehicle = vehiculo_id
            # El sostenimiento máximo cuenta desde que se concede el verde.
            inicio_verde = self._verde_en if (self._verde_en is not None and self._verde_en > ahora) else ahora
            self._priority_until = inicio_verde + PRIORITY_HOLD_SECONDS
            self._priority_request_id = id_solicitud
            self._log_si_cambio_locked(
                id_solicitud, motivo="solicitud_prioridad", vehiculo_id=vehiculo_id, eta_seg=eta_seg
            )
            if espera > 0:
                # Registra el cambio a verde en su instante, sin esperar al
                # siguiente poll (el análisis mide A_v desde ese evento).
                timer = threading.Timer(espera + 0.005, self._conceder_tras_despeje, args=(id_solicitud,))
                timer.daemon = True
                timer.start()
        if espera > 0:
            print(f"[controlador] Prioridad solicitada por '{vehiculo_id}' (ETA {eta_seg}s) "
                  f"-> verde en {espera:.2f}s, tras el despeje de la fase en conflicto")
        else:
            print(f"[controlador] Prioridad solicitada por '{vehiculo_id}' (ETA {eta_seg}s) "
                  f"-> fase forzada a verde por {PRIORITY_HOLD_SECONDS:.0f}s")

    def _conceder_tras_despeje(self, id_solicitud: str) -> None:
        with self._lock:
            if self._priority_vehicle is None or self._priority_request_id != id_solicitud:
                return  # cancelada mientras esperaba el despeje
            self._log_si_cambio_locked(id_solicitud, motivo="verde_tras_despeje_conflicto")

    def clear_priority(self, id_solicitud: str = "-") -> None:
        with self._lock:
            id_para_log = id_solicitud if id_solicitud != "-" else self._priority_request_id
            if self._priority_vehicle is None:
                return  # nada que liberar (p. ej. M3 tras una caducidad)
            ahora = time.monotonic()
            self._priority_vehicle = None
            if self._verde_en is not None and ahora < self._verde_en:
                # cancelada antes de recibir el verde: el grupo nunca salió del rojo
                self._verde_en = None
                self._log_liberacion_locked(id_para_log, "liberacion_manual_sin_verde")
                return
            self._verde_en = None
            self._iniciar_salida_locked(ahora)
            self._log_liberacion_locked(id_para_log, "liberacion_manual")
        print("[controlador] Prioridad liberada manualmente, sale por ambar y todo rojo")

    def _log_liberacion_locked(self, id_solicitud: str, motivo: str, **extra) -> None:
        """Registra SIEMPRE la liberación (aunque la fase visible siga en
        verde por el verde mínimo o la salida): con fase_plan, la fase que el
        plan tenía en ese instante (la que el vehículo habría encontrado sin
        prioridad, ver llegadas_verde_contrafactual.py)."""
        fase = self._fase_actual_locked()
        self._fase_logueada = fase
        print(f"[controlador] Fase -> {fase} ({motivo})")
        if self._eventos is not None:
            self._eventos.log(EVT_CTRL_FASE_CAMBIO, id_solicitud, fase=fase, prioridad_activa=False,
                              motivo=motivo, fase_plan=self._fase_normal_locked(), **extra)


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
    parser.add_argument("--desfase-s", type=float, default=0.0,
                         help="segundos ya transcurridos del ciclo al arrancar (0 = arranca en verde)")
    parser.add_argument("--verde-plan", type=float, default=None,
                         help="segundos de verde del grupo solicitado en el plan (por defecto, el verde minimo)")
    parser.add_argument("--fases-conflicto", default="",
                         help="verdes de plan de las fases en conflicto, en s, separados por coma "
                              "(p. ej. 28,20); activa el modo multifase y reemplaza --rojo-general")
    parser.add_argument("--verde-min-conflicto", type=float, default=None,
                         help="verde minimo de las fases en conflicto, en s (por defecto, --phase-minimum-green)")
    args = parser.parse_args()
    fases_conflicto = [float(x) for x in args.fases_conflicto.split(",") if x.strip()]

    eventos = EventLogger(f"ctrl_{RSU_ID}")
    controller = Controller(
        eventos=eventos,
        phase_minimum_green_s=args.phase_minimum_green,
        phase_yellow_change_ds=args.phase_yellow_change,
        phase_red_clear_ds=args.phase_red_clear,
        rojo_general_s=args.rojo_general,
        desfase_s=args.desfase_s,
        verde_plan_s=args.verde_plan,
        fases_conflicto_s=fases_conflicto,
        verde_min_conflicto_s=args.verde_min_conflicto,
    )
    t0 = controller.timing()
    eventos.log("ctrl_inicio", "-", desfase_s=args.desfase_s, epoch_wall_ns=controller._epoch_wall_ns,
                verde_s=t0["phase_minimum_green"], amarillo_ds=t0["phase_yellow_change"],
                todo_rojo_ds=t0["phase_red_clear"], rojo_general_s=t0["rojo_general_efectivo_seg"],
                verde_plan_s=t0["verde_plan_seg"], fases_conflicto_s=t0["fases_conflicto_seg"],
                verde_min_conflicto_s=t0["verde_min_conflicto_seg"])
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, args.port))
    server.listen()

    print(f"Emulador de controlador de transito escuchando en {LISTEN_HOST}:{args.port}")
    print("(protocolo propietario simulado, JSON Lines -- ver cabecera del modulo)")
    print(f"RSU_ID={RSU_ID} -- registro de eventos en {eventos.path}")
    print(f"Desfase inicial del ciclo: {args.desfase_s:.2f} s")
    t = controller.timing()
    print(f"Tiempos: verde={t['phase_minimum_green']}s "
          f"amarillo={t['phase_yellow_change']/10:.1f}s "
          f"todo_rojo={t['phase_red_clear']/10:.1f}s "
          f"rojo_general={t['rojo_general_efectivo_seg']}s")
    if fases_conflicto:
        print(f"Modo multifase: verde de plan={t['verde_plan_seg']}s, fases en conflicto={fases_conflicto} s, "
              f"verde minimo en conflicto={t['verde_min_conflicto_seg'] or t['phase_minimum_green']}s")
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
