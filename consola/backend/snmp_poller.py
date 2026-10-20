"""Sondeo SNMPv3 periodico para la consola: semaforo cada 0.5 s,
priorityRequestTable cada 2 s, tiempos de fase cada 10 s.

Reutiliza el transporte de centro_control/software_gestion.py (snmp_get,
snmp_walk, AuthConfig) y las constantes/decodificadores de
centro_control/panel/ntcip_objetos.py -- NO reimplementa el GET/WALK
SNMPv3. La unica diferencia con centro_control/panel/snmp_helpers.py es
que ese modulo fija el host/usuario desde centro_control/panel/.env; aqui
se usan los de consola/.env (consola/backend/config.py), que pueden
apuntar a una RSU distinta."""

from __future__ import annotations

import threading
import time

from centro_control.panel.ntcip_objetos import (
    NTCIP_ASC,
    PRIORITYREQUEST_COLUMNAS,
    PRIORITYREQUESTENTRY,
    nombre_estado_prs,
)
from centro_control.software_gestion import AuthConfig, SnmpError, snmp_get, snmp_walk
from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

PHASESTATUSGROUPENTRY = f"{NTCIP_ASC}.4.1"
PHASE_MIN_GREEN_OID = f"{NTCIP_ASC}.2.1.4.1"
PHASE_YELLOW_OID = f"{NTCIP_ASC}.2.1.8.1"
PHASE_RED_CLEAR_OID = f"{NTCIP_ASC}.2.1.9.1"

_COLUMNA_POR_SUBID = {sub_id: nombre for sub_id, nombre in PRIORITYREQUEST_COLUMNAS}


def _auth() -> AuthConfig:
    return AuthConfig(v3_user=config.SNMP_USER, auth_key=config.SNMP_AUTH_KEY, priv_key=config.SNMP_PRIV_KEY)


def _destino() -> str:
    return f"RSU {config.RSU_ID} ({config.SNMP_HOST}:{config.SNMP_PORT})"


def _leer_semaforo() -> dict:
    a = _auth()
    try:
        pares = snmp_walk(config.SNMP_HOST, config.SNMP_PORT, a, PHASESTATUSGROUPENTRY)
        valores = {oid.rsplit(".", 2)[1]: val for oid, val in pares}
        return {"red": valores.get("2", "0").strip() == "1", "yellow": valores.get("3", "0").strip() == "1",
                "green": valores.get("4", "0").strip() == "1", "error": None}
    except SnmpError as exc:
        return {"red": False, "yellow": False, "green": False, "error": str(exc)}


def _leer_tabla_prs() -> list[dict]:
    a = _auth()
    filas = {n: {"fila": n} for n in range(1, 11)}
    try:
        pares = list(snmp_walk(config.SNMP_HOST, config.SNMP_PORT, a, PRIORITYREQUESTENTRY))
    except SnmpError:
        pares = []
    for oid, valor in pares:
        try:
            sub_id_str, fila_str = oid.rsplit(".", 2)[1:]
            sub_id, num_fila = int(sub_id_str), int(fila_str)
        except (ValueError, IndexError):
            continue
        nombre_col = _COLUMNA_POR_SUBID.get(sub_id)
        if nombre_col and num_fila in filas:
            filas[num_fila][nombre_col] = valor
    resultado = []
    for n in range(1, 11):
        fila = filas[n]
        fila["estado_nombre"] = nombre_estado_prs(fila.get("priorityRequestStatusInPRS", ""))
        resultado.append(fila)
    return resultado


def _leer_tiempos() -> dict:
    a = _auth()
    tiempos = {}
    for clave, oid, divisor, unidad in (
        ("verde_minimo_s", PHASE_MIN_GREEN_OID, 1, "s"),
        ("ambar_s", PHASE_YELLOW_OID, 10, "s"),
        ("todo_rojo_s", PHASE_RED_CLEAR_OID, 10, "s"),
    ):
        try:
            _, valor = snmp_get(config.SNMP_HOST, config.SNMP_PORT, a, oid)
            tiempos[clave] = float(valor) / divisor
        except (SnmpError, ValueError):
            tiempos[clave] = None
    tiempos["error"] = None if any(v is not None for k, v in tiempos.items() if k != "error") else "sin respuesta SNMP"
    return tiempos


def _ciclo() -> None:
    """Un solo hilo para las tres cadencias (0.5 s / 2 s / 10 s), en vez de
    un hilo por cadencia: pysnmp.hlapi crea/maneja su propio event loop de
    asyncio en cada llamada sincrona, y en Windows (ProactorEventLoop) dos
    llamadas concurrentes desde hilos distintos corrompen el event loop del
    proceso ("Cannot run the event loop while another loop is running",
    luego errores en el self-pipe de asyncio que tumban hasta el loop de
    uvicorn). Serializar aqui evita el problema sin tocar pysnmp."""
    t_tabla = t_tiempos = 0.0
    while True:
        t0 = time.time()

        estado = _leer_semaforo()
        cambio = estado != ESTADO.snmp_semaforo
        ESTADO.set_snmp_semaforo(estado)
        BUS.publicar("snmp_semaforo", estado)
        if cambio:
            REGISTRO.registrar("Consola", _destino(), "SNMPv3",
                               {"accion": "WALK", "oid": PHASESTATUSGROUPENTRY}, estado)

        if t0 - t_tabla >= 2.0:
            t_tabla = t0
            filas = _leer_tabla_prs()
            ESTADO.set_snmp_tabla_prs(filas)
            BUS.publicar("snmp_prs", filas)
            REGISTRO.registrar("Consola", _destino(), "SNMPv3",
                               {"accion": "WALK", "oid": PRIORITYREQUESTENTRY},
                               {"filas_activas": sum(1 for f in filas if f["estado_nombre"] != "idleNotValid")})

        if t0 - t_tiempos >= 10.0:
            t_tiempos = t0
            tiempos = _leer_tiempos()
            ESTADO.set_snmp_tiempos(tiempos)
            BUS.publicar("snmp_tiempos", tiempos)
            REGISTRO.registrar("Consola", _destino(), "SNMPv3",
                               {"accion": "GET", "oids": [PHASE_MIN_GREEN_OID, PHASE_YELLOW_OID, PHASE_RED_CLEAR_OID]},
                               tiempos)

        time.sleep(max(0.0, 0.5 - (time.time() - t0)))


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_ciclo, name="snmp-poller", daemon=True)
    hilo.start()
    return hilo
