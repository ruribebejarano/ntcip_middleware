#!/usr/bin/env python3
"""Middleware de la RSU: agente SNMPv3 + enlace V2I (MQTT) + adaptador hacia
el controlador de transito (protocolo propietario, emulado por
controller/controller_emulator.py).

*** OBJETOS NTCIP 1202 REALES (lectura de fase y tiempos); NTCIP 1211
(solicitud de prioridad) TODAVIA FICTICIO ***
Desde P2 (ver docs/PLAN_IMPLEMENTACION.md), el lado de LECTURA de este
agente -- estado de fase y parametros de tiempo -- usa los objetos reales
de la norma NTCIP 1202 v03B, verificados a mano contra
NTCIP-1202v03.35e-aspublished.pdf (no solo el .mib extraido automaticamente
del PDF, que tiene errores conocidos de orden de campos en las tablas; ver
E:\\Tesis\\respaldos\\extraccion_ntcip1202\\LEEME.md). Cita exigida por la
licencia de redistribucion: "Derived from NTCIP 1202. Copyright by
AASHTO / ITE / NEMA. Used by permission."

Se modela UNA sola fase (phaseNumber=1), dentro de phaseStatusGroupNumber=1,
bit 0 ("Bit 0: Phase # = (phaseStatusGroupNumber * 8) - 7" en la norma) --
consistente con el alcance de esta etapa (sin arbitraje entre fases
concurrentes, ver ssec:alcance en main.tex). El objeto solicitudPrioridadTest
(lado de ESCRITURA, equivalente a NTCIP 1211) sigue siendo ficticio -- bajo
el numero de empresa NO registrado 99999 -- hasta P3.

Tres enlaces que este proceso conecta:

1. Centro de control <-> RSU: SNMPv3 (USM SHA-1 auth / AES-128 priv), igual
   que agent/rsu_snmpv3_agent.py. Probar con
   centro_control/software_gestion.py o snmpget/snmpset reales (ver
   docs/GUIA_COMANDOS.md).
2. RSU -> Controlador: un SNMP SET sobre solicitudPrioridadTest, o un
   mensaje V2I por MQTT, dispara una conexion TCP local hacia
   controller/controller_emulator.py pidiendole que fuerce o libere la fase
   verde. Los objetos de phaseStatusGroupTable y phaseTable siempre reflejan
   en vivo el estado y los tiempos reales del controlador (consulta en cada
   GET, no hay cache local).
3. OBU -> RSU (V2I): un mensaje MQTT en MQTT_TOPIC (publicado por
   gateway/obu_simulator.py) dispara el mismo pedido de prioridad que un
   SNMP SET manual desde el centro de control.

Requiere, en la misma maquina (la RSU):
- controller/controller_emulator.py corriendo (puerto 9000 por defecto).
- Un broker mosquitto corriendo en localhost:1883, accesible tambien desde
  la red para que gateway/obu_simulator.py (en otra maquina) pueda publicar.
  Ver docs/GUIA_COMANDOS.md para la configuracion minima.

Ver docs/agent.md para el bug conocido de pysnmp (USM SHA+AES128) y el
parche necesario -- este script tiene la misma dependencia de pysnmp que
agent/rsu_snmpv3_agent.py.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413.context import SnmpContext
from pysnmp.proto.rfc1902 import Integer32

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import EVT_M1_RX, EVT_SNMP_SET_TX, EventLogger  # noqa: E402

SNMP_LISTEN_ADDRESS = ("0.0.0.0", 1161)  # mismo puerto que rsu_snmpv3_agent.py -- no correr ambos juntos

USER_NAME = "rsuLabUser"
AUTH_KEY = "labAuthPass123"  # SOLO laboratorio
PRIV_KEY = "labPrivPass123"  # SOLO laboratorio

# Ficticio, bajo un numero de empresa NO registrado: lado de ESCRITURA
# (equivalente a NTCIP 1211), todavia no implementado con objetos reales.
PRIORIDAD_OID = (1, 3, 6, 1, 4, 1, 99999, 1, 2)  # ...1.2.0, lectura/escritura
BASE_OID = (1, 3, 6, 1, 4, 1, 99999, 1)

# Objetos REALES de NTCIP 1202 v03B (rama "asc.phase"; "asc" = devices.1,
# "phase" = asc.1; devices es del enterprise 1206 = NEMA). Verificados a
# mano contra NTCIP-1202v03.35e-aspublished.pdf, clausulas 5.2.2.4 (verde
# minimo), 5.2.2.8 (amarillo), 5.2.2.9 (todo rojo), 5.2.4.1-5.2.4.3 (estado
# de fase). Ver el docstring del modulo para la cita de licencia.
NTCIP_ASC_OID = (1, 3, 6, 1, 4, 1, 1206, 4, 2, 1)     # subarbol expuesto por SNMP
PHASE_OID = NTCIP_ASC_OID + (1,)                       # phase = asc.1

MAXPHASES_OID = PHASE_OID + (1,)                       # S, RO, unidad: phase
PHASETABLE_OID = PHASE_OID + (2,)
PHASEENTRY_OID = PHASETABLE_OID + (1,)
PHASENUMBER_COL_OID = PHASEENTRY_OID + (1,)            # S, RO, unidad: phase
PHASEMINGREEN_COL_OID = PHASEENTRY_OID + (4,)          # P, RW, unidad: second        (NTCIP: 1-255)
PHASEYELLOWCHANGE_COL_OID = PHASEENTRY_OID + (8,)      # P, RW, unidad: tenth second  (NTCIP: 3-255)
PHASEREDCLEAR_COL_OID = PHASEENTRY_OID + (9,)          # P, RW, unidad: tenth second  (NTCIP: 0-255)

MAXPHASEGROUPS_OID = PHASE_OID + (3,)                  # S, RO, unidad: group
PHASESTATUSGROUPTABLE_OID = PHASE_OID + (4,)
PHASESTATUSGROUPENTRY_OID = PHASESTATUSGROUPTABLE_OID + (1,)
PHASESTATUSGROUPNUMBER_COL_OID = PHASESTATUSGROUPENTRY_OID + (1,)  # S, RO, unidad: group
PHASESTATUSGROUPREDS_COL_OID = PHASESTATUSGROUPENTRY_OID + (2,)    # S, RO, bitmask (sin unidad fisica)
PHASESTATUSGROUPYELLOWS_COL_OID = PHASESTATUSGROUPENTRY_OID + (3,)
PHASESTATUSGROUPGREENS_COL_OID = PHASESTATUSGROUPENTRY_OID + (4,)

# Fase simulada unica (phaseNumber=1), en el grupo de estado 1, bit 0:
# "Bit 0: Phase # = (phaseStatusGroupNumber * 8) - 7" -> para grupo 1, bit 0 = fase 1.
FILA_UNICA = (1,)

CONTROLLER_HOST = "127.0.0.1"
CONTROLLER_PORT = 9000

MQTT_BROKER_HOST = "127.0.0.1"  # mosquitto local, en la propia RSU
MQTT_BROKER_PORT = 1883
MQTT_TOPIC = "rsu/v2i/solicitud_prioridad"

# Identificador de esta RSU en el banco de pruebas (hay dos, ver CLAUDE.md).
# No cambia ningun puerto ni topico, solo el nombre del nodo en el registro
# de eventos (eventos_rsu_<RSU_ID>.csv) y en el id_solicitud sintetico que
# se genera para las solicitudes de prioridad hechas a mano por SNMP (no
# originadas por una OBU, ver SolicitudPrioridadTestInstance.setValue).
RSU_ID = os.environ.get("RSU_ID", "1")
EVENTOS = EventLogger(f"rsu_{RSU_ID}")


def controller_request(payload: dict, timeout: float = 2.0) -> dict:
    """Un pedido, una respuesta. Conexion TCP nueva cada vez -- trafico bajo,
    no hace falta mantener una conexion persistente para esta maqueta."""
    with socket.create_connection((CONTROLLER_HOST, CONTROLLER_PORT), timeout=timeout) as sock:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        sock.settimeout(timeout)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8"))


class _ValorConstanteInstance:
    """Objetos escalares/columna que no dependen del controlador (tamanos
    de tabla fijos: una sola fase, un solo grupo de estado)."""

    _valor = 0

    def getValue(self, name, idx):
        return self.syntax.clone(self._valor)


class MaxPhasesInstance(_ValorConstanteInstance):
    _valor = 1


class MaxPhaseGroupsInstance(_ValorConstanteInstance):
    _valor = 1


class PhaseNumberInstance(_ValorConstanteInstance):
    _valor = 1


class PhaseStatusGroupNumberInstance(_ValorConstanteInstance):
    _valor = 1


class PhaseMinimumGreenInstance:
    """phaseMinimumGreen (NTCIP 1202, clausula 5.2.2.4): segundos, 1-255."""

    def getValue(self, name, idx):
        try:
            valor = controller_request({"cmd": "get_timing"})["phase_minimum_green"]
        except OSError as exc:
            print(f"[middleware] No se pudo consultar tiempos al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)

    def setValue(self, value, name, idx):
        try:
            controller_request({"cmd": "set_timing", "phase_minimum_green": int(value)})
        except OSError as exc:
            print(f"[middleware] No se pudo actualizar phaseMinimumGreen: {exc}")
        return self.syntax.clone(int(value))


class PhaseYellowChangeInstance:
    """phaseYellowChange (clausula 5.2.2.8): decimas de segundo, 3-255."""

    def getValue(self, name, idx):
        try:
            valor = controller_request({"cmd": "get_timing"})["phase_yellow_change"]
        except OSError as exc:
            print(f"[middleware] No se pudo consultar tiempos al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)

    def setValue(self, value, name, idx):
        try:
            controller_request({"cmd": "set_timing", "phase_yellow_change": int(value)})
        except OSError as exc:
            print(f"[middleware] No se pudo actualizar phaseYellowChange: {exc}")
        return self.syntax.clone(int(value))


class PhaseRedClearInstance:
    """phaseRedClear (clausula 5.2.2.9): decimas de segundo, 0-255."""

    def getValue(self, name, idx):
        try:
            valor = controller_request({"cmd": "get_timing"})["phase_red_clear"]
        except OSError as exc:
            print(f"[middleware] No se pudo consultar tiempos al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)

    def setValue(self, value, name, idx):
        try:
            controller_request({"cmd": "set_timing", "phase_red_clear": int(value)})
        except OSError as exc:
            print(f"[middleware] No se pudo actualizar phaseRedClear: {exc}")
        return self.syntax.clone(int(value))


class _PhaseStatusBitInstance:
    """Bit 0 del grupo de estado 1 (unica fase simulada): 1 si esa salida
    esta activa, 0 si no (clausulas 5.2.4.2 a 5.2.4.4 -- Reds/Yellows/Greens,
    cada una un bitmask de 8 fases; aqui solo el bit 0 tiene significado)."""

    _clave_estado = ""  # "red" | "yellow" | "green", ver controller_emulator.py status()

    def getValue(self, name, idx):
        try:
            status = controller_request({"cmd": "get_status"})
            valor = 1 if status.get(self._clave_estado) else 0
        except OSError as exc:
            print(f"[middleware] No se pudo consultar al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)


class PhaseStatusGroupRedsInstance(_PhaseStatusBitInstance):
    _clave_estado = "red"


class PhaseStatusGroupYellowsInstance(_PhaseStatusBitInstance):
    _clave_estado = "yellow"


class PhaseStatusGroupGreensInstance(_PhaseStatusBitInstance):
    _clave_estado = "green"


class SolicitudPrioridadTestInstance:
    """Lectura/escritura: SET dispara o libera la prioridad en el controlador."""

    def getValue(self, name, idx):
        try:
            status = controller_request({"cmd": "get_status"})
            valor = 1 if status.get("prioridad_activa") else 0
        except OSError as exc:
            print(f"[middleware] No se pudo consultar al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)

    def setValue(self, value, name, idx):
        activar = int(value) != 0
        # No hay OBU de origen en este camino (SET manual desde el centro de
        # control, p. ej. centro_control/software_gestion.py): se genera un
        # id_solicitud sintetico propio, para poder distinguirlo en el
        # registro de eventos de una solicitud V2I real.
        id_solicitud = f"snmp-manual-{uuid.uuid4().hex[:8]}"
        try:
            if activar:
                EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="snmp_manual", accion="request_priority")
                controller_request({
                    "cmd": "request_priority",
                    "vehiculo_id": "centro-control-manual",
                    "eta_seg": 0,
                    "id_solicitud": id_solicitud,
                })
            else:
                EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="snmp_manual", accion="clear_priority")
                controller_request({"cmd": "clear_priority", "id_solicitud": id_solicitud})
        except OSError as exc:
            print(f"[middleware] No se pudo avisar al controlador: {exc}")
        return self.syntax.clone(1 if activar else 0)


def _on_mqtt_connect(client, _userdata, _flags, reason_code, _properties=None):
    print(f"[middleware] Conectado al broker MQTT ({MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}), "
          f"reason_code={reason_code}")
    # Resuscribirse en cada conexion (no solo la primera vez): si el broker
    # se reinicia o la red se cae un momento, el cliente se reconecta solo
    # (loop_start ya lo maneja) pero pierde la suscripcion del lado del
    # broker si no se repite aqui. Antes esto solo se hacia una vez en
    # start_mqtt_listener(), lo que dejaba al middleware "sordo" tras
    # cualquier reconexion sin ningun error visible (ver bitacora
    # 2026-10-11_arranque-servicios-y-smoke-test.md).
    client.subscribe(MQTT_TOPIC, qos=1)


def _on_mqtt_message(_client, _userdata, msg) -> None:
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        vehiculo_id = data["vehiculo_id"]
        eta_seg = data.get("eta_seg", 0)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"[middleware] Mensaje V2I invalido en '{msg.topic}': {exc}")
        return

    id_solicitud = data.get("id_solicitud") or f"sin-id-{uuid.uuid4().hex[:8]}"
    if "id_solicitud" not in data:
        print(f"[middleware] Aviso: mensaje V2I sin id_solicitud, se genero uno "
              f"({id_solicitud}) solo para el registro de eventos.")

    print(f"[middleware] Solicitud V2I recibida de '{vehiculo_id}' (ETA {eta_seg}s) "
          f"-> reenviando al controlador")
    EVENTOS.log(EVT_M1_RX, id_solicitud, vehiculo_id=vehiculo_id, eta_seg=eta_seg, topic=msg.topic)
    try:
        EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="v2i", accion="request_priority")
        controller_request({
            "cmd": "request_priority",
            "vehiculo_id": vehiculo_id,
            "eta_seg": eta_seg,
            "id_solicitud": id_solicitud,
        })
    except OSError as exc:
        print(f"[middleware] No se pudo reenviar la solicitud V2I al controlador: {exc}")


def start_mqtt_listener() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rsu-middleware")
    client.on_connect = _on_mqtt_connect
    client.on_message = _on_mqtt_message
    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
    client.loop_start()
    print(f"[middleware] Escuchando solicitudes V2I en "
          f"mqtt://{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}/{MQTT_TOPIC}")
    return client


def build_snmp_engine() -> engine.SnmpEngine:
    snmp_engine = engine.SnmpEngine()

    config.addTransport(
        snmp_engine,
        config.udp.domainName,
        config.udp.UdpAsyncioTransport().openServerMode(SNMP_LISTEN_ADDRESS),
    )

    config.addV3User(
        snmp_engine,
        USER_NAME,
        config.usmHMACSHAAuthProtocol,
        AUTH_KEY,
        config.usmAesCfb128Protocol,
        PRIV_KEY,
    )

    config.addVacmUser(
        snmp_engine,
        3,  # securityModel: USM
        USER_NAME,
        "authPriv",
        readSubTree=BASE_OID,
        writeSubTree=BASE_OID,
    )
    # Segunda region de la misma vista: el subarbol real de NTCIP 1202.
    # addVacmUser vuelve a crear el mismo grupo/acceso (idempotente para el
    # mismo securityName/securityModel/securityLevel) y agrega esta region
    # a la vista existente, no la reemplaza -- por eso el usuario queda con
    # acceso a AMBOS subarboles (el ficticio 99999 y el real 1206).
    config.addVacmUser(
        snmp_engine,
        3,
        USER_NAME,
        "authPriv",
        readSubTree=NTCIP_ASC_OID,
        writeSubTree=NTCIP_ASC_OID,
    )

    mib_builder = snmp_engine.getMibBuilder()
    MibScalar, MibScalarInstance, MibTable, MibTableRow, MibTableColumn = mib_builder.importSymbols(
        "SNMPv2-SMI", "MibScalar", "MibScalarInstance", "MibTable", "MibTableRow", "MibTableColumn"
    )

    class _SolicitudPrioridadTestInstance(SolicitudPrioridadTestInstance, MibScalarInstance):
        pass

    class _MaxPhasesInstance(MaxPhasesInstance, MibScalarInstance):
        pass

    class _MaxPhaseGroupsInstance(MaxPhaseGroupsInstance, MibScalarInstance):
        pass

    class _PhaseNumberInstance(PhaseNumberInstance, MibScalarInstance):
        pass

    class _PhaseMinimumGreenInstance(PhaseMinimumGreenInstance, MibScalarInstance):
        pass

    class _PhaseYellowChangeInstance(PhaseYellowChangeInstance, MibScalarInstance):
        pass

    class _PhaseRedClearInstance(PhaseRedClearInstance, MibScalarInstance):
        pass

    class _PhaseStatusGroupNumberInstance(PhaseStatusGroupNumberInstance, MibScalarInstance):
        pass

    class _PhaseStatusGroupRedsInstance(PhaseStatusGroupRedsInstance, MibScalarInstance):
        pass

    class _PhaseStatusGroupYellowsInstance(PhaseStatusGroupYellowsInstance, MibScalarInstance):
        pass

    class _PhaseStatusGroupGreensInstance(PhaseStatusGroupGreensInstance, MibScalarInstance):
        pass

    mib_builder.exportSymbols(
        "__RSU-MIDDLEWARE-TEST-MIB",
        # --- NTCIP 1202 v03B real: tiempos de fase (phaseTable) ---
        maxPhases=MibScalar(MAXPHASES_OID, Integer32()).setMaxAccess("readonly"),
        maxPhasesInstance=_MaxPhasesInstance(MAXPHASES_OID, (0,), Integer32()),
        phaseTable=MibTable(PHASETABLE_OID),
        phaseEntry=MibTableRow(PHASEENTRY_OID).setIndexNames(
            (0, "__RSU-MIDDLEWARE-TEST-MIB", "phaseNumber")
        ),
        phaseNumber=MibTableColumn(PHASENUMBER_COL_OID, Integer32()).setMaxAccess("readonly"),
        phaseNumberInstance=_PhaseNumberInstance(PHASENUMBER_COL_OID, FILA_UNICA, Integer32()),
        phaseMinimumGreen=MibTableColumn(PHASEMINGREEN_COL_OID, Integer32()).setMaxAccess("readwrite"),
        phaseMinimumGreenInstance=_PhaseMinimumGreenInstance(
            PHASEMINGREEN_COL_OID, FILA_UNICA, Integer32()
        ),
        phaseYellowChange=MibTableColumn(PHASEYELLOWCHANGE_COL_OID, Integer32()).setMaxAccess("readwrite"),
        phaseYellowChangeInstance=_PhaseYellowChangeInstance(
            PHASEYELLOWCHANGE_COL_OID, FILA_UNICA, Integer32()
        ),
        phaseRedClear=MibTableColumn(PHASEREDCLEAR_COL_OID, Integer32()).setMaxAccess("readwrite"),
        phaseRedClearInstance=_PhaseRedClearInstance(PHASEREDCLEAR_COL_OID, FILA_UNICA, Integer32()),
        # --- NTCIP 1202 v03B real: estado de fase (phaseStatusGroupTable) ---
        maxPhaseGroups=MibScalar(MAXPHASEGROUPS_OID, Integer32()).setMaxAccess("readonly"),
        maxPhaseGroupsInstance=_MaxPhaseGroupsInstance(MAXPHASEGROUPS_OID, (0,), Integer32()),
        phaseStatusGroupTable=MibTable(PHASESTATUSGROUPTABLE_OID),
        phaseStatusGroupEntry=MibTableRow(PHASESTATUSGROUPENTRY_OID).setIndexNames(
            (0, "__RSU-MIDDLEWARE-TEST-MIB", "phaseStatusGroupNumber")
        ),
        phaseStatusGroupNumber=MibTableColumn(
            PHASESTATUSGROUPNUMBER_COL_OID, Integer32()
        ).setMaxAccess("readonly"),
        phaseStatusGroupNumberInstance=_PhaseStatusGroupNumberInstance(
            PHASESTATUSGROUPNUMBER_COL_OID, FILA_UNICA, Integer32()
        ),
        phaseStatusGroupReds=MibTableColumn(PHASESTATUSGROUPREDS_COL_OID, Integer32()).setMaxAccess("readonly"),
        phaseStatusGroupRedsInstance=_PhaseStatusGroupRedsInstance(
            PHASESTATUSGROUPREDS_COL_OID, FILA_UNICA, Integer32()
        ),
        phaseStatusGroupYellows=MibTableColumn(
            PHASESTATUSGROUPYELLOWS_COL_OID, Integer32()
        ).setMaxAccess("readonly"),
        phaseStatusGroupYellowsInstance=_PhaseStatusGroupYellowsInstance(
            PHASESTATUSGROUPYELLOWS_COL_OID, FILA_UNICA, Integer32()
        ),
        phaseStatusGroupGreens=MibTableColumn(
            PHASESTATUSGROUPGREENS_COL_OID, Integer32()
        ).setMaxAccess("readonly"),
        phaseStatusGroupGreensInstance=_PhaseStatusGroupGreensInstance(
            PHASESTATUSGROUPGREENS_COL_OID, FILA_UNICA, Integer32()
        ),
        # --- Ficticio (P3: reemplazar por NTCIP 1211 real) ---
        solicitudPrioridadTest=MibScalar(PRIORIDAD_OID, Integer32()).setMaxAccess("readwrite"),
        solicitudPrioridadTestInstance=_SolicitudPrioridadTestInstance(
            PRIORIDAD_OID, (0,), Integer32()
        ),
    )

    snmp_context = SnmpContext(snmp_engine)
    cmdrsp.GetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.SetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.NextCommandResponder(snmp_engine, snmp_context)
    cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)

    return snmp_engine


def main() -> None:
    print("=== Middleware RSU: SNMP + V2I (MQTT) + adaptador de controlador ===")
    print(f"RSU_ID={RSU_ID} -- registro de eventos en {EVENTOS.path}")
    print(f"Controlador esperado en {CONTROLLER_HOST}:{CONTROLLER_PORT} "
          f"(correr primero controller/controller_emulator.py)\n")

    mqtt_client = start_mqtt_listener()
    snmp_engine = build_snmp_engine()

    def _oid_str(oid: tuple[int, ...], fila: tuple[int, ...] = FILA_UNICA) -> str:
        return ".".join(str(n) for n in (oid + fila))

    prioridad_oid_str = ".".join(str(n) for n in PRIORIDAD_OID) + ".0"
    print(f"SNMP escuchando en {SNMP_LISTEN_ADDRESS[0]}:{SNMP_LISTEN_ADDRESS[1]} "
          f"(usuario USM: {USER_NAME}, auth SHA-1 / priv AES-128)")
    print("  NTCIP 1202 v03B real (fase unica, phaseNumber=1, grupo de estado 1 bit 0):")
    print(f"    {_oid_str(MAXPHASES_OID, (0,))} = maxPhases (RO)")
    print(f"    {_oid_str(PHASEMINGREEN_COL_OID)} = phaseMinimumGreen (RW, segundos)")
    print(f"    {_oid_str(PHASEYELLOWCHANGE_COL_OID)} = phaseYellowChange (RW, decimas de seg.)")
    print(f"    {_oid_str(PHASEREDCLEAR_COL_OID)} = phaseRedClear (RW, decimas de seg.)")
    print(f"    {_oid_str(MAXPHASEGROUPS_OID, (0,))} = maxPhaseGroups (RO)")
    print(f"    {_oid_str(PHASESTATUSGROUPREDS_COL_OID)} = phaseStatusGroupReds (RO, bit 0)")
    print(f"    {_oid_str(PHASESTATUSGROUPYELLOWS_COL_OID)} = phaseStatusGroupYellows (RO, bit 0)")
    print(f"    {_oid_str(PHASESTATUSGROUPGREENS_COL_OID)} = phaseStatusGroupGreens (RO, bit 0)")
    print(f"  {prioridad_oid_str} = solicitudPrioridadTest (ficticio, RW: 0/1 -- P3 lo reemplaza por NTCIP 1211)")
    print("\nCtrl+C para detener.\n")

    dispatcher = snmp_engine.transportDispatcher
    try:
        dispatcher.runDispatcher()
    except KeyboardInterrupt:
        print("\nDeteniendo middleware...")
    finally:
        dispatcher.closeDispatcher()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
