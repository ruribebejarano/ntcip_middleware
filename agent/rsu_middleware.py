#!/usr/bin/env python3
"""Middleware de la RSU: agente SNMPv3 + enlace V2I (MQTT) + adaptador hacia
el controlador de transito (protocolo propietario, emulado por
controller/controller_emulator.py).

*** SOLO SNMP GENERICO -- SIN MIB ESTANDARIZADA REAL TODAVIA ***
Igual que agent/rsu_snmpv3_agent.py, los OID expuestos aqui son ficticios
(bajo un numero de empresa NO registrado, 99999). El objetivo de este script
es validar el LAZO COMPLETO, no la semantica de un estandar de MIB de
transito real. Ver CLAUDE.md / docs/CRONOGRAMA.md para cuando se reemplacen
estos OID por objetos reales -- el resto de la arquitectura (MQTT + adaptador
al controlador) no deberia necesitar cambios grandes.

Tres enlaces que este proceso conecta:

1. Centro de control <-> RSU: SNMPv3 (USM SHA-1 auth / AES-128 priv), igual
   que agent/rsu_snmpv3_agent.py. Probar con
   centro_control/software_gestion.py o snmpget/snmpset reales (ver
   docs/GUIA_COMANDOS.md).
2. RSU -> Controlador: un SNMP SET sobre solicitudPrioridadTest, o un
   mensaje V2I por MQTT, dispara una conexion TCP local hacia
   controller/controller_emulator.py pidiendole que fuerce o libere la fase
   verde. faseActualTest siempre refleja en vivo la fase real del
   controlador (consulta al controlador en cada GET, no hay cache local).
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
import socket

import paho.mqtt.client as mqtt
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413.context import SnmpContext
from pysnmp.proto.rfc1902 import Integer32

SNMP_LISTEN_ADDRESS = ("0.0.0.0", 1161)  # mismo puerto que rsu_snmpv3_agent.py -- no correr ambos juntos

USER_NAME = "rsuLabUser"
AUTH_KEY = "labAuthPass123"  # SOLO laboratorio
PRIV_KEY = "labPrivPass123"  # SOLO laboratorio

FASE_OID = (1, 3, 6, 1, 4, 1, 99999, 1, 1)       # ...1.1.0, solo lectura
PRIORIDAD_OID = (1, 3, 6, 1, 4, 1, 99999, 1, 2)  # ...1.2.0, lectura/escritura
BASE_OID = (1, 3, 6, 1, 4, 1, 99999, 1)

CONTROLLER_HOST = "127.0.0.1"
CONTROLLER_PORT = 9000

MQTT_BROKER_HOST = "127.0.0.1"  # mosquitto local, en la propia RSU
MQTT_BROKER_PORT = 1883
MQTT_TOPIC = "rsu/v2i/solicitud_prioridad"

FASE_A_ENTERO = {"rojo": 1, "amarillo": 2, "verde": 3}


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


class FaseActualTestInstance:
    """Solo lectura: refleja en vivo la fase del controlador emulado."""

    def getValue(self, name, idx):
        try:
            status = controller_request({"cmd": "get_status"})
            valor = FASE_A_ENTERO.get(status.get("fase"), 0)
        except OSError as exc:
            print(f"[middleware] No se pudo consultar al controlador: {exc}")
            valor = 0
        return self.syntax.clone(valor)


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
        try:
            if activar:
                controller_request({
                    "cmd": "request_priority",
                    "vehiculo_id": "centro-control-manual",
                    "eta_seg": 0,
                })
            else:
                controller_request({"cmd": "clear_priority"})
        except OSError as exc:
            print(f"[middleware] No se pudo avisar al controlador: {exc}")
        return self.syntax.clone(1 if activar else 0)


def _on_mqtt_connect(_client, _userdata, _flags, reason_code, _properties=None):
    print(f"[middleware] Conectado al broker MQTT ({MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}), "
          f"reason_code={reason_code}")


def _on_mqtt_message(_client, _userdata, msg) -> None:
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        vehiculo_id = data["vehiculo_id"]
        eta_seg = data.get("eta_seg", 0)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"[middleware] Mensaje V2I invalido en '{msg.topic}': {exc}")
        return

    print(f"[middleware] Solicitud V2I recibida de '{vehiculo_id}' (ETA {eta_seg}s) "
          f"-> reenviando al controlador")
    try:
        controller_request({
            "cmd": "request_priority",
            "vehiculo_id": vehiculo_id,
            "eta_seg": eta_seg,
        })
    except OSError as exc:
        print(f"[middleware] No se pudo reenviar la solicitud V2I al controlador: {exc}")


def start_mqtt_listener() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rsu-middleware")
    client.on_connect = _on_mqtt_connect
    client.on_message = _on_mqtt_message
    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
    client.subscribe(MQTT_TOPIC, qos=1)
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

    mib_builder = snmp_engine.getMibBuilder()
    MibScalar, MibScalarInstance = mib_builder.importSymbols(
        "SNMPv2-SMI", "MibScalar", "MibScalarInstance"
    )

    class _FaseActualTestInstance(FaseActualTestInstance, MibScalarInstance):
        pass

    class _SolicitudPrioridadTestInstance(SolicitudPrioridadTestInstance, MibScalarInstance):
        pass

    mib_builder.exportSymbols(
        "__RSU-MIDDLEWARE-TEST-MIB",
        faseActualTest=MibScalar(FASE_OID, Integer32()).setMaxAccess("readonly"),
        faseActualTestInstance=_FaseActualTestInstance(FASE_OID, (0,), Integer32()),
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
    print(f"Controlador esperado en {CONTROLLER_HOST}:{CONTROLLER_PORT} "
          f"(correr primero controller/controller_emulator.py)\n")

    mqtt_client = start_mqtt_listener()
    snmp_engine = build_snmp_engine()

    fase_oid_str = ".".join(str(n) for n in FASE_OID) + ".0"
    prioridad_oid_str = ".".join(str(n) for n in PRIORIDAD_OID) + ".0"
    print(f"SNMP escuchando en {SNMP_LISTEN_ADDRESS[0]}:{SNMP_LISTEN_ADDRESS[1]} "
          f"(usuario USM: {USER_NAME}, auth SHA-1 / priv AES-128)")
    print(f"  {fase_oid_str} = faseActualTest (solo lectura: 1=rojo 2=amarillo 3=verde)")
    print(f"  {prioridad_oid_str} = solicitudPrioridadTest (lectura/escritura: 0/1)")
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
