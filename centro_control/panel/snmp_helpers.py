"""Lecturas SNMP de alto nivel para el panel -- construidas sobre las
primitivas de centro_control/software_gestion.py (snmp_get/snmp_walk/
AuthConfig/SnmpError), SIN reimplementar el transporte SNMPv3. Este
modulo solo sabe que OID consultar y como armar la estructura que pinta
app.py; el GET/WALK en si lo hace software_gestion.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from centro_control.software_gestion import (  # noqa: E402
    AuthConfig,
    SnmpError,
    snmp_get,
    snmp_walk,
)
from centro_control.panel import config  # noqa: E402
from centro_control.panel.ntcip_objetos import (  # noqa: E402
    NTCIP_ASC,
    PRIORITYREQUEST_COLUMNAS,
    PRIORITYREQUESTENTRY,
    nombre_estado_prs,
)

PHASESTATUSGROUPENTRY = f"{NTCIP_ASC}.4.1"  # fila 1 = fase 1 (ver ntcip_objetos.py)
_COLUMNA_POR_SUBID = {sub_id: nombre for sub_id, nombre in PRIORITYREQUEST_COLUMNAS}


def auth() -> AuthConfig:
    return AuthConfig(
        v3_user=config.SNMP_USER,
        auth_key=config.SNMP_AUTH_KEY,
        priv_key=config.SNMP_PRIV_KEY,
    )


def leer_semaforo() -> dict:
    """Lee phaseStatusGroupReds/Yellows/Greens (grupo 1, bit 0 = fase 1)
    con un solo WALK sobre phaseStatusGroupEntry en vez de 3 GET
    separados -- cada snmp_get de software_gestion.py crea su propio
    SnmpEngine, y 3 GETs independientes miden ~0.35s contra la Pi del
    banco; un solo WALK de las 4 columnas de esa fila mide ~0.15s,
    necesario para sostener un refresco de 0.5s. Devuelve
    {"red": bool, "yellow": bool, "green": bool, "error": str|None}."""
    a = auth()
    try:
        pares = snmp_walk(config.SNMP_HOST, config.SNMP_PORT, a, PHASESTATUSGROUPENTRY)
        valores = {oid.rsplit(".", 2)[1]: val for oid, val in pares}  # sub_id -> valor
        return {
            "red": valores.get("2", "0").strip() == "1",
            "yellow": valores.get("3", "0").strip() == "1",
            "green": valores.get("4", "0").strip() == "1",
            "error": None,
        }
    except SnmpError as exc:
        return {"red": False, "yellow": False, "green": False, "error": str(exc)}


def leer_priority_request_table() -> list[dict]:
    """WALK de priorityRequestEntry (10 columnas x 10 filas, tamano fijo
    por la norma) en una sola sesion SNMP, en vez de 100 GET
    independientes -- un GET por celda medía ~10s contra la Pi del banco
    (100 SnmpEngine nuevos); un solo WALK de las 100 hojas mide ~1s.
    Devuelve una lista de 10 dicts (uno por fila), con 'estado_nombre' ya
    decodificado via el enum de priorityRequestStatusInPRS."""
    a = auth()
    filas = {n: {"fila": n} for n in range(1, 11)}
    try:
        pares = snmp_walk(config.SNMP_HOST, config.SNMP_PORT, a, PRIORITYREQUESTENTRY)
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


def walk_crudo(base_oid: str) -> list[tuple[str, str]]:
    """Expone snmp_walk tal cual, por si algun boton de demo necesita un
    WALK genérico en vez de GETs puntuales."""
    a = auth()
    return list(snmp_walk(config.SNMP_HOST, config.SNMP_PORT, a, base_oid))
