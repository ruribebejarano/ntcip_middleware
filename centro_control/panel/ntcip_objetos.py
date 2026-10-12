"""Constantes NTCIP 1202/1211 para el panel de supervision.

*** NO duplica la logica SNMP: solo declara los OID como texto (formato
que pide centro_control.software_gestion.snmp_get/snmp_walk/snmp_set) y
unas funciones de decodificacion de valores. El transporte SNMPv3 (USM,
GET/SET/WALK) vive en centro_control/software_gestion.py y se importa tal
cual, sin copiarlo. ***

Los valores de aqui deben coincidir EXACTAMENTE con los que declara
agent/rsu_middleware.py (ahi es donde se definen los objetos reales del
agente); si ese archivo cambia un OID, este modulo queda desactualizado y
hay que actualizarlo a mano -- no hay una fuente unica compartida porque
agent/rsu_middleware.py usa tuplas de enteros (formato pysnmp de bajo
nivel) y este panel usa strings "a.b.c" (formato pysnmp.hlapi, el que usa
software_gestion.py).
"""

from __future__ import annotations

# --- NTCIP 1202 v03B: phaseStatusGroupTable (grupo 1, bit 0 = fase 1) ---
NTCIP_ASC = "1.3.6.1.4.1.1206.4.2.1.1"
PHASESTATUSGROUPREDS = f"{NTCIP_ASC}.4.1.2.1"
PHASESTATUSGROUPYELLOWS = f"{NTCIP_ASC}.4.1.3.1"
PHASESTATUSGROUPGREENS = f"{NTCIP_ASC}.4.1.4.1"

# --- NTCIP 1211 v02 (borrador v02A-SE03): priorityRequestTable ---
SCP = "1.3.6.1.4.1.1206.4.2.5"
PRIORITYREQUESTENTRY = f"{SCP}.1.1.1"
NUM_FILAS_PRIORITY_REQUEST = 10
PRGPRIORITYREQUESTABSOLUTE = f"{SCP}.2.8.0"  # write-only, OCTET STRING(29) OER

# (sub_id, nombre de columna) -- mismo orden que PRIORITYREQUEST_COLUMNAS
# en agent/rsu_middleware.py.
PRIORITYREQUEST_COLUMNAS = [
    (1, "priorityRequestEntryNumber"),
    (2, "priorityRequestID"),
    (3, "priorityRequestVehicleID"),
    (4, "priorityRequestVehicleClassType"),
    (5, "priorityRequestVehicleClassLevel"),
    (6, "priorityRequestServiceStrategyNumber"),
    (7, "priorityRequestTimeOfServiceDesired"),
    (8, "priorityRequestTimeOfEstimatedDeparture"),
    (9, "priorityRequestStatusInPRS"),
    (10, "priorityRequestTimeOfMessage"),
]


def oid_columna_fila(sub_id: int, fila: int) -> str:
    """OID de una columna x fila de priorityRequestTable, ej. columna 9
    (priorityRequestStatusInPRS), fila 1 -> '...1.1.1.9.1'."""
    return f"{PRIORITYREQUESTENTRY}.{sub_id}.{fila}"


# priorityRequestStatusInPRS: enum real de la norma (PRS-MIB1 clausula 9,
# ver agent/ntcip1211.py, donde se declaran los mismos 15 valores como
# constantes IDLE_NOT_VALID=1 ... CLOSED_FLASH=15).
PRIORITY_REQUEST_STATUS = {
    1: "idleNotValid",
    2: "readyQueued",
    3: "readyOverridden",
    4: "activeProcessing",
    5: "activeCancel",
    6: "activeOverride",
    7: "activeNotOverridden",
    8: "closedCanceled",
    9: "reserviceError",
    10: "closedTimeToLiveError",
    11: "closedTimerError",
    12: "closedStrategyError",
    13: "closedCompleted",
    14: "activeAdjustNotNeeded",
    15: "closedFlash",
}


def nombre_estado_prs(valor: str | int) -> str:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return str(valor)
    return PRIORITY_REQUEST_STATUS.get(n, f"desconocido({n})")
