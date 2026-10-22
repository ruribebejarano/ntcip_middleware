#!/usr/bin/env python3
"""Middleware de la RSU: agente SNMPv3 + enlace V2I (MQTT) + adaptador hacia
el controlador de transito (protocolo propietario, emulado por
controller/controller_emulator.py).

*** OBJETOS NTCIP 1202 REALES (lectura de fase y tiempos), verificados
contra la norma oficial publicada. OBJETOS NTCIP 1211 REALES (solicitud
de prioridad), pero contra un BORRADOR SIN VERIFICAR -- ver mas abajo. ***

NTCIP 1202 (P2, ver docs/PLAN_IMPLEMENTACION.md): el lado de LECTURA de
este agente -- estado de fase y parametros de tiempo -- usa los objetos
reales de la norma NTCIP 1202 v03B, verificados a mano contra
NTCIP-1202v03.35e-aspublished.pdf (no solo el .mib extraido automaticamente
del PDF, que tiene errores conocidos de orden de campos en las tablas; ver
E:\\Tesis\\respaldos\\extraccion_ntcip1202\\LEEME.md). Cita exigida por la
licencia de redistribucion: "Derived from NTCIP 1202. Copyright by
AASHTO / ITE / NEMA. Used by permission."

Se modela UNA sola fase (phaseNumber=1), dentro de phaseStatusGroupNumber=1,
bit 0 ("Bit 0: Phase # = (phaseStatusGroupNumber * 8) - 7" en la norma) --
consistente con el alcance de esta etapa (sin arbitraje entre fases
concurrentes, ver ssec:alcance en main.tex).

NTCIP 1211 (P3): priorityRequestTable (lectura) y prgPriorityRequestAbsolute
(escritura, OCTET STRING OER-codificado) usan los nombres y el orden de
campos del BORRADOR v02A-SE03 (2017) de NTCIP1211v02_PRS-MIB1 -- NO existe,
al momento de escribir esto, una copia del documento oficial v02 (2014)
disponible (se solicito a ntcip@nema.org, ver
E:\\Tesis\\redaccion\\correo_nema.md). Ademas, el OID base `scp` (del que
cuelgan estos objetos) viene de un modulo de soporte reconstruido
(NTCIP8004v02) con ese nodo marcado como NO confirmado contra una fuente
autoritativa. Ver agent/ntcip1211.py para el detalle completo de esta
limitacion y de la codificacion.

Cuatro enlaces que este proceso conecta:

1. Centro de control <-> RSU: SNMPv3 (USM SHA-1 auth / AES-128 priv), igual
   que agent/rsu_snmpv3_agent.py. Probar con
   centro_control/software_gestion.py o snmpget/snmpset reales (ver
   docs/GUIA_COMANDOS.md).
2. RSU -> Controlador: un SNMP SET sobre prgPriorityRequestAbsolute, o un
   mensaje V2I por MQTT, dispara una conexion TCP local hacia
   controller/controller_emulator.py pidiendole que fuerce o libere la fase
   verde -- en ambos casos pasando por PriorityRequestServer.aceptar_solicitud()
   (agent/ntcip1211.py), que aplica RF-05 (clase reconocida) y RF-06 (limites
   operacionales) antes de reenviar. Los objetos de phaseStatusGroupTable y
   phaseTable siempre reflejan en vivo el estado y los tiempos reales del
   controlador (consulta en cada GET, no hay cache local).
3. Servidor central -> RSU (arquitectura centralizada, 2026-10-22), dos
   caminos por el mismo tema rsu/{RSU_ID}/solicitudes:
   - M1/M3 del SERVIDOR (servidor/gestor_mision.py vía servidor/main.py):
     M1 crea o renueva la solicitud (ahora con anticipación por ETA, no
     solo al cruzar la geocerca local de la OBU: la geocerca se evalúa EN
     EL SERVIDOR, ver gateway/geometria.py), M3 la cancela, y la RSU
     responde M2 (recibida/en cola/concedida/rechazada/cancelada) en el
     Response Topic de MQTT 5 que trae el propio mensaje -- sin cambios en
     esa mecánica, solo cambia QUIÉN la usa. Ver docs/LAZO_EMULADO.md y
     docs/CONTRATO_OBU.md.
   - Legado (P0-P3, antes de la arquitectura centralizada): M1/M3 directo
     de gateway/obu_emulada.py (la OBU decidía la RSU/acceso localmente) o
     un mensaje en MQTT_TOPIC (gateway/obu_simulator.py), sin respuesta ni
     cancelación. Esta RSU sigue aceptando ambos formatos por compatibilidad
     con pruebas y evidencia ya levantada (ver evidencia/), pero el diseño
     vigente de la tesis es que SOLO el servidor publique en este tema.
   *** Seguridad: la restricción de que solo el servidor pueda publicar en
   `rsu/+/solicitudes` se hace cumplir en el BROKER (ACL de Mosquitto +
   identidad mTLS, ver scripts/seguridad/), NO en este código -- este
   proceso no tiene manera de verificar, a partir del payload JSON, quién
   lo publicó. Si el broker no tiene esa ACL configurada (ver el estado
   real en docs/bitacora/2026-10-22_arquitectura-centralizada.md),
   cualquier publicador en este tema puede activar una solicitud, igual
   que en el esquema anterior. ***
4. Caducidad (RF-09/RNF-03): un hilo en segundo plano verifica cada medio
   segundo si la solicitud activa lleva mas de T_CAD_SEGUNDOS sin
   actualizarse (ver agent/ntcip1211.py) y, si es asi, libera la prioridad
   en el controlador.

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
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413.context import SnmpContext
from pysnmp.proto.rfc1902 import Integer32, OctetString
from pysnmp.smi import error as smi_error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import (  # noqa: E402
    EVT_CADUCIDAD,
    EVT_M1_RX,
    EVT_M2_TX,
    EVT_M3_RX,
    EVT_SNMP_SET_TX,
    EventLogger,
)
from agent.ntcip1211 import (  # noqa: E402
    ACTIVE_PROCESSING,
    CLOSED_CANCELED,
    CLOSED_TIME_TO_LIVE_ERROR,
    READY_QUEUED,
    T_CAD_SEGUNDOS,
    ErrorLongitud,
    ErrorRangoCampo,
    PriorityRequestServer,
    SolicitudPrioridadAbsoluta,
    SolicitudRechazada,
    TAMANO_BYTES as NTCIP1211_TAMANO_BYTES,
    codificar as ntcip1211_codificar,
    decodificar as ntcip1211_decodificar,
)

# Puertos y broker configurables por variable de entorno, para poder correr
# dos RSU en la misma maquina (banco emulado) o apuntar a otro broker
# (Mosquitto central, EMQX) sin tocar el codigo. Los valores por defecto son
# los de siempre: nada cambia si no se definen.
SNMP_LISTEN_ADDRESS = ("0.0.0.0", int(os.environ.get("SNMP_PORT", "1161")))  # mismo puerto que rsu_snmpv3_agent.py -- no correr ambos juntos

USER_NAME = "rsuLabUser"
AUTH_KEY = "labAuthPass123"  # SOLO laboratorio
PRIV_KEY = "labPrivPass123"  # SOLO laboratorio

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

# Objetos NTCIP 1211 v02 (BORRADOR v02A-SE03, SIN VERIFICAR -- ver docstring
# del modulo y agent/ntcip1211.py). `scp` (Signal Control Priority) sale del
# modulo de soporte reconstruido NTCIP8004v02, con este nodo marcado como NO
# confirmado contra una fuente autoritativa: scp = devices.5 (devices es el
# mismo nodo padre de "asc", es decir NTCIP_ASC_OID sin el ultimo ".1").
DEVICES_OID = NTCIP_ASC_OID[:-1]  # quita el ".1" final de "asc" = devices.1
SCP_OID = DEVICES_OID + (5,)  # scp = devices.5 (NO confirmado)
PRIORITY_REQUEST_SERVER_OID = SCP_OID + (1,)   # priorityRequestServer = scp.1
PRIORITY_REQUEST_MESSAGES_OID = SCP_OID + (2,)  # priorityRequestMessages = scp.2

PRGPRIORITYREQUESTABSOLUTE_OID = PRIORITY_REQUEST_MESSAGES_OID + (8,)  # write-only, OCTET STRING(29)

PRIORITYREQUESTTABLE_OID = PRIORITY_REQUEST_SERVER_OID + (1,)
PRIORITYREQUESTENTRY_OID = PRIORITYREQUESTTABLE_OID + (1,)
# (sub_id, nombre SNMP, campo en agent.ntcip1211._FilaPRS, tipo pysnmp)
# Columnas 1-10 del borrador (ver agent/ntcip1211.py); 11-14 (TimeToLive,
# TimeOfServiceDesiredInPRS, TimeOfEstimatedDepartureInPRS, TimeOfRequest)
# quedan fuera de esta primera implementacion -- no se usan en la logica
# actual (RF-05/06/09) y agregarlas es directo si hacen falta despues.
PRIORITYREQUEST_COLUMNAS = [
    (1, "priorityRequestEntryNumber", "numero", Integer32),
    (2, "priorityRequestID", "id_solicitud", Integer32),
    (3, "priorityRequestVehicleID", "vehiculo_id", OctetString),
    (4, "priorityRequestVehicleClassType", "clase_tipo", Integer32),
    (5, "priorityRequestVehicleClassLevel", "clase_nivel", Integer32),
    (6, "priorityRequestServiceStrategyNumber", "estrategia", Integer32),
    (7, "priorityRequestTimeOfServiceDesired", "t_servicio_deseado", Integer32),
    (8, "priorityRequestTimeOfEstimatedDeparture", "t_salida_estimada", Integer32),
    (9, "priorityRequestStatusInPRS", "estado", Integer32),
    (10, "priorityRequestTimeOfMessage", "t_mensaje", Integer32),
]
NUM_FILAS_PRIORITY_REQUEST = 10  # fijo por la norma ("number of rows... is 10")

CONTROLLER_HOST = "127.0.0.1"
CONTROLLER_PORT = int(os.environ.get("CONTROLLER_PORT", "9000"))

# Broker MQTT. Por defecto, el mosquitto de la propia RSU (como hasta P3);
# con MQTT_BROKER_HOST se apunta al broker central del diseno (E2+E4,
# ssec:sel_direccionamiento), que es la arquitectura de la tesis.
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
# Tema LEGADO (P0-P3): un solo tema para todas las RSU, mensaje con
# eta_seg. Se mantiene para gateway/obu_simulator.py y scripts/demo_asesor.sh.
MQTT_TOPIC = "rsu/v2i/solicitud_prioridad"

# Identificador de esta RSU en el banco de pruebas (hay dos, ver CLAUDE.md).
# No cambia ningun puerto ni topico, solo el nombre del nodo en el registro
# de eventos (eventos_rsu_<RSU_ID>.csv) y en el id_solicitud sintetico que
# se genera para las solicitudes de prioridad hechas a mano por SNMP.
RSU_ID = os.environ.get("RSU_ID", "1")
EVENTOS = EventLogger(f"rsu_{RSU_ID}")

# Tema por RSU del esquema E2 (ssec:sel_direccionamiento y ssec:rsu_sw de
# main.tex): la OBU publica M1/M3 en rsu/{id}/solicitudes y la RSU responde
# M2 en el Response Topic de MQTT 5 que trae cada mensaje
# (veh/{id}/respuestas), con el mismo Correlation Data.
MQTT_TOPIC_SOLICITUDES = f"rsu/{RSU_ID}/solicitudes"

# M1 no trae ETA (tab:mensajes): la RSU completa
# priorityRequestTimeOfServiceDesired con un valor NOMINAL (ssec:mw_1211,
# "L_zona / v_d"), declarado como estimacion y no como medicion.
T_SERVICIO_NOMINAL_S = int(os.environ.get("T_SERVICIO_NOMINAL_S", "10"))

# Estado del PRS (NTCIP 1211): una sola fila activa a la vez, ver
# agent/ntcip1211.py. Compartido entre el camino SNMP SET y el camino MQTT
# V2I -- ambos pasan por PRS.aceptar_solicitud().
PRS = PriorityRequestServer()
PRS_LOCK = threading.Lock()

# agent/ntcip1211.py es logica NTCIP pura (sin nocion de common/events.py):
# su _FilaPRS.id_solicitud es el priorityRequestID numerico (1..255, ver
# _id_numerico_para abajo), no el id_solicitud de M1/eventos (string). Para
# que el watchdog pueda loguear la activacion tardia de una fila en cola
# (RF-06) con el MISMO id de evento que uso el SET/mensaje original (y asi
# scripts/analisis/latencia_tramos.py pueda cruzarlos), se guarda aqui el
# ultimo id de evento visto para la fila 1 -- protegido por PRS_LOCK, igual
# que la propia fila.
_ULTIMO_ID_EVENTO = ""

# priorityRequestID es un entero 1..255 (NTCIP), pero nuestro id_solicitud
# de V2I es un string (ver common/events.py). Se asigna un numero por
# vehiculo_id la primera vez que se ve, y se reutiliza en mensajes
# siguientes del mismo vehiculo_id -- eso es lo que permite distinguir una
# solicitud NUEVA (crea fila) de una ACTUALIZACION periodica de la misma
# solicitud (refresca el plazo de caducidad, RF-09) en vez de revalidar
# RF-05/RF-06 en cada mensaje.
_siguiente_id_numerico = 1
_id_numerico_por_vehiculo: dict[str, int] = {}


def _id_numerico_para(vehiculo_id: str) -> int:
    global _siguiente_id_numerico
    if vehiculo_id not in _id_numerico_por_vehiculo:
        _id_numerico_por_vehiculo[vehiculo_id] = _siguiente_id_numerico
        _siguiente_id_numerico = (_siguiente_id_numerico % 255) + 1
    return _id_numerico_por_vehiculo[vehiculo_id]


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


def _reenviar_request_priority(
    vehiculo_id: bytes, t_servicio_deseado: int, id_solicitud_evento: str
) -> None:
    """Un unico punto para el SNMP SET/M1 "cmd": "request_priority" hacia el
    controlador, reusado tanto por una activacion inmediata (fase ya segura)
    como por la activacion tardia de una fila que esperaba en readyQueued
    (ver verificar_caducidad_periodica)."""
    try:
        controller_request({
            "cmd": "request_priority",
            "vehiculo_id": vehiculo_id.decode("utf-8", errors="replace"),
            "eta_seg": t_servicio_deseado,
            "id_solicitud": id_solicitud_evento,
        })
    except OSError as exc:
        print(f"[middleware] No se pudo reenviar la solicitud al controlador: {exc}")


def procesar_solicitud_prioridad(
    s: SolicitudPrioridadAbsoluta, id_solicitud_evento: str, origen: str
) -> None:
    """Punto de entrada compartido por el SET SNMP de prgPriorityRequestAbsolute
    y por el mensaje V2I MQTT: aplica RF-05/RF-06 (agent/ntcip1211.py) antes
    de reenviar al controlador. `id_solicitud_evento` es el id de
    common/events.py (string); `origen` es "snmp" o "v2i", para el registro
    de eventos. Levanta SolicitudRechazada solo si RF-05 (clase no
    reconocida) no se cumple -- el llamador decide que hacer con eso (error
    SNMP, o solo loguear si viene de MQTT, que no tiene un canal de
    respuesta sincrono hacia la OBU todavia, ver TODO en _on_mqtt_message).
    RF-06 (limite operacional) ya NO rechaza: si el controlador esta en
    amarillo/todo_rojo, la fila queda en readyQueued (agent/ntcip1211.py) y
    NO se reenvia al controlador todavia -- lo hace el watchdog
    (verificar_caducidad_periodica) cuando termine el despeje, siempre que
    la solicitud siga vigente (TTL de RF-09)."""
    global _ULTIMO_ID_EVENTO
    renovar_en_controlador = False
    with PRS_LOCK:
        if PRS.refrescar(s.id_solicitud):
            _ULTIMO_ID_EVENTO = id_solicitud_evento
            renovar_en_controlador = PRS.fila(1).estado == ACTIVE_PROCESSING
    if renovar_en_controlador:
        # La actualizacion (M1 con seq+1) renueva el plazo RF-09 en la RSU
        # Y la prioridad en el controlador: sin esto, el controlador emulado
        # soltaba el verde a los PRIORITY_HOLD_SECONDS (15 s) aunque la OBU
        # siguiera renovando -- visto con un vehiculo detenido 20 s en cola
        # (escenario detenido_en_cola, bitacora 2026-10-19). Si la OBU deja
        # de renovar, la caducidad RF-09 libera igual a los 3 s.
        _reenviar_request_priority(s.vehiculo_id, s.t_servicio_deseado, id_solicitud_evento)
        return
    with PRS_LOCK:
        if PRS.refrescar(s.id_solicitud):
            return  # en cola (readyQueued, RF-06): solo renovar el plazo (RF-09)

        try:
            status = controller_request({"cmd": "get_status"})
            fase_actual = status.get("fase", "?")
        except OSError as exc:
            raise SolicitudRechazada(
                "controlador_no_disponible", f"no se pudo consultar al controlador: {exc}"
            )

        fila = PRS.aceptar_solicitud(s, fase_actual=fase_actual)
        _ULTIMO_ID_EVENTO = id_solicitud_evento

    if fila.estado == READY_QUEUED:
        print(f"[middleware] Solicitud de '{s.vehiculo_id.decode('utf-8', errors='replace')}' "
              f"en cola (readyQueued): fase actual '{fase_actual}' en despeje "
              f"(RF-06); se activa al terminar, si sigue vigente (TTL={T_CAD_SEGUNDOS:.0f}s)")
        EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud_evento, origen=origen,
                    accion="en_cola_despeje", fase=fase_actual)
        return  # no se reenvia al controlador todavia -- ver verificar_caducidad_periodica

    EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud_evento, origen=origen, accion="request_priority")
    _reenviar_request_priority(s.vehiculo_id, s.t_servicio_deseado, id_solicitud_evento)


def verificar_caducidad_periodica() -> None:
    """Hilo en segundo plano (RF-09/RNF-03): corre mientras el proceso este
    vivo, revisa cada medio segundo:

    1. Si la solicitud activa -- o en cola (readyQueued, RF-06) -- lleva
       mas de T_CAD_SEGUNDOS sin actualizarse: caduca, y si estaba activa
       (ya forzando verde en el controlador) se le avisa que libere.
    2. Si no caduco y hay una fila en readyQueued, consulta la fase actual
       del controlador: si el despeje ya termino, la activa (RF-06) y
       recien ahi reenvia el "request_priority" que se habia pospuesto en
       procesar_solicitud_prioridad."""
    while True:
        time.sleep(0.5)
        with PRS_LOCK:
            fila_antes = PRS.fila(1)
            estaba_en_cola = fila_antes.estado == READY_QUEUED
            id_evento_fila = _ULTIMO_ID_EVENTO
            caduco_ahora = PRS.verificar_caducidad()
            fila_activada = None
            if not caduco_ahora and estaba_en_cola:
                try:
                    status = controller_request({"cmd": "get_status"})
                    fase_actual = status.get("fase", "?")
                except OSError as exc:
                    print(f"[middleware] No se pudo consultar al controlador para la cola RF-06: {exc}")
                    fase_actual = None
                if fase_actual is not None:
                    fila_activada = PRS.intentar_activar_cola(fase_actual)
                    if fila_activada is not None:
                        vehiculo_id = fila_activada.vehiculo_id
                        t_servicio_deseado = fila_activada.t_servicio_deseado

        if caduco_ahora:
            motivo = "rnf03_sin_actualizacion_en_cola" if estaba_en_cola else "rnf03_sin_actualizacion"
            print(f"[middleware] Solicitud caducada por falta de actualizacion "
                  f"(RF-09, T_cad={T_CAD_SEGUNDOS:.0f}s, estaba_en_cola={estaba_en_cola}) "
                  f"-> liberando prioridad")
            EVENTOS.log(EVT_CADUCIDAD, id_evento_fila, motivo=motivo)
            topic_resp = _RESPUESTA_POR_ID.pop(id_evento_fila, None)
            if topic_resp:
                _publicar_m2(id_evento_fila, "cancelada", topic_resp, None, motivo="caducidad")
            if not estaba_en_cola:
                # Si estaba en cola nunca se forzo verde en el controlador
                # (RF-06 pospuso el reenvio): no hace falta avisarle que
                # libere algo que nunca le llego a pedir.
                try:
                    controller_request({"cmd": "clear_priority"})
                except OSError as exc:
                    print(f"[middleware] No se pudo avisar la caducidad al controlador: {exc}")
        elif fila_activada is not None:
            print(f"[middleware] Fin del despeje: se activa la solicitud en cola "
                  f"'{vehiculo_id.decode('utf-8', errors='replace')}' (RF-06) -> reenviando al controlador")
            EVENTOS.log(EVT_SNMP_SET_TX, id_evento_fila, origen="watchdog",
                        accion="activar_cola_rf06")
            _reenviar_request_priority(vehiculo_id, t_servicio_deseado, id_evento_fila)
            # Pasos 5-8 de fig:secuencia: la RSU informa el verde por M2 en
            # cuanto lo obtiene, sin esperar al siguiente M1 de la OBU (que
            # llegaria hasta 1 s despues, RNF-02).
            topic_resp = _RESPUESTA_POR_ID.get(id_evento_fila)
            if topic_resp:
                id_num = _ID_NUMERICO_POR_SOLICITUD.get(id_evento_fila)
                if id_num is not None:
                    _publicar_m2(id_evento_fila, _estado_m2(id_num), topic_resp, None, origen="watchdog")


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


class PrgPriorityRequestAbsoluteInstance:
    """NTCIP 1211 (borrador, ver docstring del modulo): write-only, OCTET
    STRING de 29 bytes OER-codificados (agent/ntcip1211.py). El GET siempre
    devuelve una cadena vacia -- el objeto es write-only per la norma; el
    resultado de una solicitud se lee con priorityRequestTable, no aqui."""

    def getValue(self, name, idx):
        return self.syntax.clone(b"")

    def setValue(self, value, name, idx):
        datos = bytes(value)
        try:
            solicitud = ntcip1211_decodificar(datos)
        except ErrorLongitud as exc:
            raise smi_error.WrongLengthError(idx=idx, name=name, msg=str(exc))
        except ErrorRangoCampo as exc:
            raise smi_error.WrongValueError(idx=idx, name=name, msg=str(exc))

        id_evento = f"snmp-{solicitud.vehiculo_id.decode('utf-8', errors='replace') or 'sin-vehiculo'}"
        try:
            # Solo RF-05 (clase no reconocida) o el controlador inalcanzable
            # llegan aqui como SolicitudRechazada: RF-06 ya no rechaza, deja
            # la fila en readyQueued (ver procesar_solicitud_prioridad) y
            # el SET se acepta igual -- el resultado se sigue leyendo en
            # priorityRequestTable, no en la respuesta de este SET.
            procesar_solicitud_prioridad(solicitud, id_evento, origen="snmp")
        except SolicitudRechazada as exc:
            raise smi_error.WrongValueError(idx=idx, name=name, msg=f"{exc.motivo}: {exc}")
        return self.syntax.clone(datos)


class _PriorityRequestColumnaInstance:
    """Columna generica de priorityRequestTable: lee el campo `_campo` de
    PRS.fila(numero), donde `numero` es el indice de fila que
    MibScalarInstance guarda en self.instId (ver build_snmp_engine, donde se
    crea una instancia de esta clase por cada (columna, fila))."""

    _campo = ""

    def getValue(self, name, idx):
        numero_fila = self.instId[0]
        with PRS_LOCK:
            # Antes de reportar, aplica la caducidad pendiente (RF-09): si
            # nadie esta corriendo verificar_caducidad_periodica() (p. ej.
            # en una prueba unitaria), un GET igual ve el estado al dia.
            PRS.verificar_caducidad()
            fila = PRS.fila(numero_fila)
            valor = getattr(fila, self._campo)
        return self.syntax.clone(valor)


_MQTT_CLIENT: mqtt.Client | None = None

# Ultimo contador de secuencia visto por id_solicitud (M1/M3, tab:mensajes):
# deteccion de duplicados a nivel de aplicacion (ssec:seg_replay), p. ej.
# ante una reentrega QoS 1 tras una reconexion.
_ULTIMA_SEQ: dict[str, int] = {}
# Response Topic de cada solicitud V2I vigente, para avisar por M2 una
# cancelacion que la propia RSU decide (caducidad, RF-09).
_RESPUESTA_POR_ID: dict[str, str] = {}
_ID_NUMERICO_POR_SOLICITUD: dict[str, int] = {}


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
    client.subscribe([(MQTT_TOPIC, 1), (MQTT_TOPIC_SOLICITUDES, 1)])


def _on_mqtt_message(_client, _userdata, msg) -> None:
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[middleware] Mensaje V2I invalido en '{msg.topic}': {exc}")
        return

    tipo = data.get("tipo") if isinstance(data, dict) else None
    if msg.topic == MQTT_TOPIC or tipo is None:
        _procesar_m1_legado(msg, data)
    elif tipo == "M1":
        _procesar_m1(msg, data)
    elif tipo == "M3":
        _procesar_m3(msg, data)
    else:
        print(f"[middleware] Tipo de mensaje V2I desconocido en '{msg.topic}': {tipo!r}")


# ---------------------------------------------------------------------------
# M1/M2/M3 (tab:mensajes de main.tex) por el tema de esta RSU
# ---------------------------------------------------------------------------


def _respuesta_de(msg) -> tuple[str | None, bytes | None]:
    """Response Topic y Correlation Data de MQTT 5 (None si no vienen)."""
    props = getattr(msg, "properties", None)
    topic = getattr(props, "ResponseTopic", None) if props is not None else None
    corr = getattr(props, "CorrelationData", None) if props is not None else None
    return topic, corr


def _publicar_m2(id_solicitud: str, estado: str, response_topic: str | None,
                 correlation: bytes | None, seq_ref: int | None = None, **extra) -> None:
    """M2 EstadoPrioridad: identificador, estado (recibida, concedida,
    rechazada, cancelada) y fase activa (tab:mensajes)."""
    if not response_topic or _MQTT_CLIENT is None:
        return
    try:
        fase = controller_request({"cmd": "get_status"}).get("fase", "?")
    except OSError:
        fase = "?"
    cuerpo = {"tipo": "M2", "id_solicitud": id_solicitud, "estado": estado, "fase": fase,
              "rsu_id": RSU_ID, "ts_ms": int(time.time() * 1000)}
    if seq_ref is not None:
        cuerpo["seq_ref"] = seq_ref
    cuerpo.update(extra)
    props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
    if correlation is not None:
        props.CorrelationData = correlation
    _MQTT_CLIENT.publish(response_topic, json.dumps(cuerpo), qos=1, properties=props)
    EVENTOS.log(EVT_M2_TX, id_solicitud, estado=estado, fase=fase, seq_ref=seq_ref, topic=response_topic)


def _estado_m2(id_numerico: int) -> str:
    """Estado de la solicitud segun la fila del PRS y la fase real del
    controlador (RF-08): 'concedida' solo cuando el controlador ya esta en
    verde con la solicitud activa."""
    with PRS_LOCK:
        fila = PRS.fila(1)
        estado_prs = fila.estado if fila.id_solicitud == id_numerico else None
    if estado_prs == ACTIVE_PROCESSING:
        try:
            fase = controller_request({"cmd": "get_status"}).get("fase")
        except OSError:
            fase = None
        return "concedida" if fase == "verde" else "recibida"
    if estado_prs == READY_QUEUED:
        return "recibida"
    return "cancelada"


def _es_duplicado(id_solicitud: str, seq: int) -> bool:
    ultima = _ULTIMA_SEQ.get(id_solicitud)
    if ultima is not None and seq <= ultima:
        return True
    _ULTIMA_SEQ[id_solicitud] = seq
    return False


def _procesar_m1(msg, data: dict) -> None:
    """M1 (tab:mensajes): desde la arquitectura centralizada lo publica el
    servidor (servidor/gestor_mision.py::_cuerpo_m1), con campos minimos
    id_solicitud/clase/acceso/t_servicio -- ya no "vehiculo_id" (acepta
    "obu_id" o "mision_id" en su lugar, solo para el registro de eventos y
    el id_solicitud numerico de NTCIP 1211) ni "interseccion_id" (la RSU ya
    sabe cual es su propia interseccion). El camino legado
    (gateway/obu_emulada.py anterior a 2026-10-22) sigue aceptandose: si
    llega "vehiculo_id" se usa ese; si no, "obu_id"/"mision_id"."""
    response_topic, correlation = _respuesta_de(msg)
    try:
        id_solicitud = str(data["id_solicitud"])
        vehiculo_id = str(data.get("vehiculo_id") or data.get("obu_id") or data.get("mision_id") or "desconocido")
        seq = int(data["seq"])
        clase_tipo = int(data.get("clase", 1))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[middleware] M1 invalido en '{msg.topic}': {exc}")
        return

    duplicado = _es_duplicado(id_solicitud, seq)
    EVENTOS.log(EVT_M1_RX, id_solicitud, seq=seq, vehiculo_id=vehiculo_id,
                interseccion_id=data.get("interseccion_id"), acceso=data.get("acceso"),
                velocidad_kmh=data.get("velocidad_kmh"), ts_obu_ms=data.get("ts_ms"),
                duplicado=duplicado, topic=msg.topic)
    if duplicado:
        print(f"[middleware] M1 duplicado ({id_solicitud}, seq={seq}): ignorado")
        return
    if response_topic:
        _RESPUESTA_POR_ID[id_solicitud] = response_topic

    if id_solicitud not in _ID_NUMERICO_POR_SOLICITUD:
        _ID_NUMERICO_POR_SOLICITUD[id_solicitud] = _id_numerico_para(f"m1:{id_solicitud}")
    id_numerico = _ID_NUMERICO_POR_SOLICITUD[id_solicitud]

    # Traduccion M1 -> NTCIP 1211 (RF-07): t_servicio_deseado usa el ETA
    # real que calculo el servidor (campo "t_servicio", RF8) si vino en el
    # mensaje; si no (camino legado, o un M1 sin ese campo), se usa el
    # valor nominal de siempre.
    t_servicio_deseado = int(data.get("t_servicio", T_SERVICIO_NOMINAL_S)) or T_SERVICIO_NOMINAL_S
    t_servicio_deseado = max(1, min(65535, t_servicio_deseado))
    solicitud = SolicitudPrioridadAbsoluta(
        id_solicitud=id_numerico,
        vehiculo_id=vehiculo_id.encode("utf-8")[:17],
        clase_tipo=clase_tipo,
        clase_nivel=10,
        estrategia=1,
        t_servicio_deseado=t_servicio_deseado,
        t_salida_estimada=min(65535, t_servicio_deseado + 5),
        t_solicitud=int(time.time()),
    )
    try:
        procesar_solicitud_prioridad(solicitud, id_solicitud, origen="v2i")
    except SolicitudRechazada as exc:
        print(f"[middleware] M1 de '{vehiculo_id}' rechazado ({exc.motivo}): {exc}")
        EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="v2i", accion="rechazada", motivo=exc.motivo)
        _publicar_m2(id_solicitud, "rechazada", response_topic, correlation, seq_ref=seq, motivo=exc.motivo)
        return

    _publicar_m2(id_solicitud, _estado_m2(id_numerico), response_topic, correlation, seq_ref=seq)


def _procesar_m3(msg, data: dict) -> None:
    """M3 CancelacionPrioridad (RF-04): libera la prioridad en el
    controlador si la solicitud estaba activa; si estaba en cola (RF-06),
    solo la cierra, porque al controlador todavia no se le pidio nada."""
    response_topic, correlation = _respuesta_de(msg)
    try:
        id_solicitud = str(data["id_solicitud"])
        seq = int(data["seq"])
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[middleware] M3 invalido en '{msg.topic}': {exc}")
        return
    duplicado = _es_duplicado(id_solicitud, seq)
    EVENTOS.log(EVT_M3_RX, id_solicitud, seq=seq, motivo=data.get("motivo"),
                ts_obu_ms=data.get("ts_ms"), duplicado=duplicado, topic=msg.topic)
    if duplicado:
        return

    id_numerico = _ID_NUMERICO_POR_SOLICITUD.get(id_solicitud)
    era_activa = False
    with PRS_LOCK:
        fila = PRS.fila(1)
        if id_numerico is not None and fila.id_solicitud == id_numerico:
            era_activa = fila.estado == ACTIVE_PROCESSING
            PRS.cancelar()
    if era_activa:
        print(f"[middleware] M3 de '{id_solicitud}' ({data.get('motivo')}) -> liberando prioridad")
        EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="v2i", accion="clear_priority_m3")
        try:
            controller_request({"cmd": "clear_priority", "id_solicitud": id_solicitud})
        except OSError as exc:
            print(f"[middleware] No se pudo liberar la prioridad en el controlador: {exc}")
    _RESPUESTA_POR_ID.pop(id_solicitud, None)
    _publicar_m2(id_solicitud, "cancelada", response_topic, correlation, seq_ref=seq, motivo="m3")


def _procesar_m1_legado(msg, data: dict) -> None:
    """Camino de P0-P3 (gateway/obu_simulator.py, demo_asesor.sh): un M1
    simplificado con eta_seg, sin seq ni Response Topic. Sin cambios de
    comportamiento respecto de la version anterior."""
    try:
        vehiculo_id = data["vehiculo_id"]
        eta_seg = data.get("eta_seg", 0)
    except (KeyError, TypeError) as exc:
        print(f"[middleware] Mensaje V2I invalido en '{msg.topic}': {exc}")
        return

    id_solicitud = data.get("id_solicitud") or f"sin-id-{uuid.uuid4().hex[:8]}"
    if "id_solicitud" not in data:
        print(f"[middleware] Aviso: mensaje V2I sin id_solicitud, se genero uno "
              f"({id_solicitud}) solo para el registro de eventos.")

    print(f"[middleware] Solicitud V2I recibida de '{vehiculo_id}' (ETA {eta_seg}s) "
          f"-> reenviando al controlador")
    EVENTOS.log(EVT_M1_RX, id_solicitud, vehiculo_id=vehiculo_id, eta_seg=eta_seg, topic=msg.topic)

    # Traduccion V2I (M1, JSON) -> NTCIP 1211 (RF-07): M1 no trae todos los
    # campos de prgPriorityRequestAbsolute (ver tab:mensajes de main.tex,
    # que solo define id_solicitud/vehiculo_id/eta_seg/clase/etc. a nivel de
    # diseno, no 1:1 con los 8 campos OER). Mapeo adoptado, documentado en
    # la bitacora de P3:
    # - clase_tipo: toma "clase_tipo" del mensaje si viene, si no asume 1
    #   (maxima precedencia) -- gateway/obu_simulator.py ya lo envia.
    # - clase_nivel: 10 (minimo sub-nivel), M1 no distingue niveles dentro
    #   de una clase.
    # - estrategia: 1 (unica estrategia implementada en esta etapa).
    # - t_servicio_deseado: eta_seg, redondeado y acotado a [1, 65535].
    # - t_salida_estimada: t_servicio_deseado + 5 s de margen (M1 no trae
    #   una estimacion de salida separada de la de llegada).
    clase_tipo = int(data.get("clase_tipo", 1))
    t_servicio_deseado = max(1, min(65535, round(float(eta_seg)) or 1))
    solicitud = SolicitudPrioridadAbsoluta(
        id_solicitud=_id_numerico_para(vehiculo_id),
        vehiculo_id=vehiculo_id.encode("utf-8")[:17],
        clase_tipo=clase_tipo,
        clase_nivel=10,
        estrategia=1,
        t_servicio_deseado=t_servicio_deseado,
        t_salida_estimada=min(65535, t_servicio_deseado + 5),
        t_solicitud=int(time.time()),
    )
    try:
        procesar_solicitud_prioridad(solicitud, id_solicitud, origen="v2i")
    except SolicitudRechazada as exc:
        print(f"[middleware] Solicitud V2I de '{vehiculo_id}' rechazada ({exc.motivo}): {exc}")
        EVENTOS.log(EVT_SNMP_SET_TX, id_solicitud, origen="v2i", accion="rechazada", motivo=exc.motivo)


def start_mqtt_listener() -> mqtt.Client:
    global _MQTT_CLIENT
    # MQTT 5 (ssec:sel_protocolo_app): Response Topic y Correlation Data
    # para el par M1/M2. Los mensajes legados (MQTT 3.1.1 del simulador
    # antiguo) se siguen recibiendo igual: el broker traduce entre versiones.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"rsu-middleware-{RSU_ID}",
                         protocol=mqtt.MQTTv5)
    client.on_connect = _on_mqtt_connect
    client.on_message = _on_mqtt_message
    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
    client.loop_start()
    _MQTT_CLIENT = client
    print(f"[middleware] Escuchando solicitudes V2I en mqtt://{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} "
          f"temas '{MQTT_TOPIC_SOLICITUDES}' (M1/M3) y '{MQTT_TOPIC}' (legado)")
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
        readSubTree=NTCIP_ASC_OID,
        writeSubTree=NTCIP_ASC_OID,
    )
    # Segunda region de la misma vista: el subarbol de NTCIP 1211 (scp).
    # addVacmUser vuelve a crear el mismo grupo/acceso (idempotente para el
    # mismo securityName/securityModel/securityLevel) y agrega esta region
    # a la vista existente, no la reemplaza -- por eso el usuario queda con
    # acceso a AMBOS subarboles (1202 bajo asc, 1211 bajo scp).
    config.addVacmUser(
        snmp_engine,
        3,
        USER_NAME,
        "authPriv",
        readSubTree=SCP_OID,
        writeSubTree=SCP_OID,
    )

    mib_builder = snmp_engine.getMibBuilder()
    MibScalar, MibScalarInstance, MibTable, MibTableRow, MibTableColumn = mib_builder.importSymbols(
        "SNMPv2-SMI", "MibScalar", "MibScalarInstance", "MibTable", "MibTableRow", "MibTableColumn"
    )

    class _PrgPriorityRequestAbsoluteInstance(PrgPriorityRequestAbsoluteInstance, MibScalarInstance):
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

    class _PriorityRequestColumnaSNMP(_PriorityRequestColumnaInstance, MibScalarInstance):
        pass

    # priorityRequestTable: 10 filas fijas x 10 columnas (ver
    # PRIORITYREQUEST_COLUMNAS). Se genera en un bucle -- serian 100
    # objetos MibTableColumn/MibScalarInstance si se escribieran a mano uno
    # por uno, como se hizo para phaseTable/phaseStatusGroupTable (que solo
    # necesitaban 1 fila cada una).
    priority_request_symbols: dict = {}
    for sub_id, nombre_col, campo, tipo_pysnmp in PRIORITYREQUEST_COLUMNAS:
        columna_oid = PRIORITYREQUESTENTRY_OID + (sub_id,)

        class _Col(_PriorityRequestColumnaSNMP):
            _campo = campo

        priority_request_symbols[nombre_col] = MibTableColumn(
            columna_oid, tipo_pysnmp()
        ).setMaxAccess("readonly")
        for numero_fila in range(1, NUM_FILAS_PRIORITY_REQUEST + 1):
            priority_request_symbols[f"{nombre_col}Instance{numero_fila}"] = _Col(
                columna_oid, (numero_fila,), tipo_pysnmp()
            )

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
        # --- NTCIP 1211 v02 real (BORRADOR SIN VERIFICAR, ver docstring del
        # modulo y agent/ntcip1211.py) ---
        # La norma declara este objeto ACCESS write-only, pero pysnmp no
        # reconoce ese nivel de acceso (solo chequea 'readonly'/'readwrite'/
        # 'readcreate' en SNMPv2-SMI.py; cualquier otro string, incluido
        # 'writeonly', bloquea tambien el SET -- confirmado con un snmpset
        # real que devolvio notWritable). Se declara 'readwrite' para que el
        # SET funcione, y se preserva la semantica write-only en la propia
        # instancia: getValue() siempre devuelve una cadena vacia (ver
        # PrgPriorityRequestAbsoluteInstance), nunca el ultimo valor
        # escrito.
        prgPriorityRequestAbsolute=MibScalar(
            PRGPRIORITYREQUESTABSOLUTE_OID, OctetString()
        ).setMaxAccess("readwrite"),
        prgPriorityRequestAbsoluteInstance=_PrgPriorityRequestAbsoluteInstance(
            PRGPRIORITYREQUESTABSOLUTE_OID, (0,), OctetString()
        ),
        priorityRequestTable=MibTable(PRIORITYREQUESTTABLE_OID),
        priorityRequestTableEntry=MibTableRow(PRIORITYREQUESTENTRY_OID).setIndexNames(
            (0, "__RSU-MIDDLEWARE-TEST-MIB", "priorityRequestEntryNumber")
        ),
        **priority_request_symbols,
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

    watchdog = threading.Thread(target=verificar_caducidad_periodica, daemon=True)
    watchdog.start()

    def _oid_str(oid: tuple[int, ...], fila: tuple[int, ...] = FILA_UNICA) -> str:
        return ".".join(str(n) for n in (oid + fila))

    prg_oid_str = ".".join(str(n) for n in PRGPRIORITYREQUESTABSOLUTE_OID) + ".0"
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
    print("  NTCIP 1211 v02 BORRADOR SIN VERIFICAR (ver docstring del modulo):")
    print(f"    {prg_oid_str} = prgPriorityRequestAbsolute (WO, OCTET STRING de {NTCIP1211_TAMANO_BYTES} bytes)")
    print(f"    {_oid_str(PRIORITYREQUESTENTRY_OID + (9,), (1,))} = priorityRequestStatusInPRS fila 1 (RO)")
    print(f"    (10 filas x 10 columnas, ver PRIORITYREQUEST_COLUMNAS)")
    print(f"  Caducidad (RF-09/RNF-03): T_CAD={T_CAD_SEGUNDOS:.0f}s, revisada cada 0.5s")
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
