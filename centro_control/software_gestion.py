#!/usr/bin/env python3
"""Software de gestión central (SNMP) -- simula el sistema que, en un centro
de control de tránsito real, monitorea y envía comandos a las RSU en campo.

Por ahora es genérico: solo sabe hacer GET/SET/WALK sobre los OID que
expone `agent/rsu_middleware.py`, sin depender de ninguna MIB estandarizada
en particular -- eso es una capa que se agrega más adelante (ver
CLAUDE.md). Pensado para correr en Python puro (pysnmp), sin depender de
tener `net-snmp` instalado en la máquina que hace de "centro de control"
(p. ej. la laptop, en Windows).

Modos de uso:

    Interactivo (menú con logs -- pensado para explorar/demostrar el lazo):
        python3 centro_control/software_gestion.py interactive \\
            --host <IP_RSU> --v3-user rsuLabUser \\
            --auth-key labAuthPass123 --priv-key labPrivPass123

    Monitoreo continuo (logs periódicos, sin menú, para dejarlo corriendo):
        python3 centro_control/software_gestion.py monitor \\
            --host <IP_RSU> --v3-user rsuLabUser \\
            --auth-key labAuthPass123 --priv-key labPrivPass123 --interval 5

    Comandos puntuales (scripting/automatización):
        python3 centro_control/software_gestion.py get --host <IP_RSU> ... <oid>
        python3 centro_control/software_gestion.py set --host <IP_RSU> ... <oid> <valor>
        python3 centro_control/software_gestion.py walk --host <IP_RSU> ... <oid_base>

Ver docs/GUIA_COMANDOS.md para el flujo completo (RSU + controlador + OBU).
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from typing import Optional

from pysnmp.hlapi import (
    CommunityData,
    ContextData,
    Integer,
    ObjectIdentity,
    ObjectType,
    OctetString,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    getCmd,
    nextCmd,
    setCmd,
    usmAesCfb128Protocol,
    usmHMACSHAAuthProtocol,
)

DEFAULT_PORT = 1161

FASE_OID = "1.3.6.1.4.1.99999.1.1.0"
PRIORIDAD_OID = "1.3.6.1.4.1.99999.1.2.0"
FASE_NOMBRE = {"1": "rojo", "2": "amarillo", "3": "verde"}

log = logging.getLogger("software_gestion")


@dataclass
class AuthConfig:
    """Community (v2c) o usuario USM (v3) -- una de las dos cosas."""

    community: Optional[str] = None
    v3_user: Optional[str] = None
    auth_key: Optional[str] = None
    priv_key: Optional[str] = None

    def to_pysnmp(self):
        if self.community is not None:
            return CommunityData(self.community, mpModel=1)  # mpModel=1 -> v2c
        if self.v3_user is not None:
            return UsmUserData(
                self.v3_user,
                authKey=self.auth_key,
                privKey=self.priv_key,
                authProtocol=usmHMACSHAAuthProtocol,
                privProtocol=usmAesCfb128Protocol,
            )
        raise ValueError("Hay que pasar --community (v2c) o --v3-user (v3)")


class SnmpError(RuntimeError):
    pass


def _target(host: str, port: int) -> UdpTransportTarget:
    return UdpTransportTarget((host, port), timeout=2, retries=1)


def snmp_get(host: str, port: int, auth: AuthConfig, oid: str):
    engine = SnmpEngine()
    iterator = getCmd(
        engine, auth.to_pysnmp(), _target(host, port), ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    error_indication, error_status, error_index, var_binds = next(iterator)
    iterator.close()
    if error_indication:
        raise SnmpError(str(error_indication))
    if error_status:
        raise SnmpError(f"{error_status.prettyPrint()} en {var_binds[int(error_index) - 1] if error_index else '?'}")
    name, value = var_binds[0]
    return str(name), value.prettyPrint()


def snmp_set(host: str, port: int, auth: AuthConfig, oid: str, value, value_type: str = "int"):
    if value_type == "int":
        typed_value = Integer(int(value))
    elif value_type == "str":
        typed_value = OctetString(str(value))
    elif value_type == "bytes":
        # Para OCTET STRING binarios (p. ej. prgPriorityRequestAbsolute,
        # NTCIP 1211, 29 bytes OER -- ver agent/ntcip1211.py): `value` ya
        # debe venir como bytes/bytearray codificados por el llamador.
        # OctetString(str(value)) corrompería los bytes crudos (tipo "str"
        # de arriba), por eso es un tipo aparte, no una variante de "str".
        typed_value = OctetString(bytes(value))
    else:
        raise ValueError(f"Tipo de valor no soportado: {value_type} (usar 'int', 'str' o 'bytes')")

    engine = SnmpEngine()
    iterator = setCmd(
        engine, auth.to_pysnmp(), _target(host, port), ContextData(),
        ObjectType(ObjectIdentity(oid), typed_value),
    )
    error_indication, error_status, error_index, var_binds = next(iterator)
    iterator.close()
    if error_indication:
        raise SnmpError(str(error_indication))
    if error_status:
        raise SnmpError(f"{error_status.prettyPrint()} en {var_binds[int(error_index) - 1] if error_index else '?'}")
    name, value = var_binds[0]
    return str(name), value.prettyPrint()


def snmp_walk(host: str, port: int, auth: AuthConfig, base_oid: str):
    """Generador de (oid, valor) recorriendo base_oid con GETNEXT en cadena."""
    engine = SnmpEngine()
    iterator = nextCmd(
        engine, auth.to_pysnmp(), _target(host, port), ContextData(),
        ObjectType(ObjectIdentity(base_oid)), lexicographicMode=False,
    )
    for error_indication, error_status, error_index, var_binds in iterator:
        if error_indication:
            raise SnmpError(str(error_indication))
        if error_status:
            raise SnmpError(error_status.prettyPrint())
        for name, value in var_binds:
            yield str(name), value.prettyPrint()


def _build_auth_from_args(args) -> AuthConfig:
    if args.community:
        return AuthConfig(community=args.community)
    if args.v3_user:
        return AuthConfig(v3_user=args.v3_user, auth_key=args.auth_key, priv_key=args.priv_key)
    raise SystemExit("Falta --community o --v3-user/--auth-key/--priv-key")


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", required=True, help="IP de la RSU (ej. 192.168.18.163)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--community", help="Comunidad SNMPv2c")
    p.add_argument("--v3-user", help="Usuario USM SNMPv3 (ej. rsuLabUser)")
    p.add_argument("--auth-key", help="Contrasena de autenticacion SHA-1 (v3)")
    p.add_argument("--priv-key", help="Contrasena de privacidad AES-128 (v3)")


def _leer_estado(host: str, port: int, auth: AuthConfig) -> dict:
    _, fase_raw = snmp_get(host, port, auth, FASE_OID)
    _, prioridad_raw = snmp_get(host, port, auth, PRIORIDAD_OID)
    return {
        "fase": FASE_NOMBRE.get(fase_raw, f"desconocida({fase_raw})"),
        "prioridad_activa": prioridad_raw == "1",
    }


def cmd_monitor(args, auth: AuthConfig) -> int:
    log.info("Monitoreo continuo iniciado sobre %s:%s (Ctrl+C para detener)", args.host, args.port)
    try:
        while True:
            try:
                estado = _leer_estado(args.host, args.port, auth)
                log.info(
                    "fase=%s  prioridad_activa=%s",
                    estado["fase"], "si" if estado["prioridad_activa"] else "no",
                )
            except SnmpError as exc:
                log.error("Error consultando a la RSU: %s", exc)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Monitoreo detenido por el usuario.")
    return 0


def cmd_interactive(args, auth: AuthConfig) -> int:
    log.info("Software de gestion central -- conectado a %s:%s", args.host, args.port)
    menu = (
        "\n[1] Ver estado actual (fase + prioridad)"
        "\n[2] Activar solicitud de prioridad manual"
        "\n[3] Liberar prioridad"
        "\n[4] Monitoreo continuo (Ctrl+C para volver al menu)"
        "\n[5] Salir\n"
    )
    while True:
        print(menu)
        try:
            opcion = input("Opcion: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            log.info("Cerrando software de gestion.")
            return 0

        if opcion == "1":
            try:
                estado = _leer_estado(args.host, args.port, auth)
                log.info(
                    "fase=%s  prioridad_activa=%s",
                    estado["fase"], "si" if estado["prioridad_activa"] else "no",
                )
            except SnmpError as exc:
                log.error("Error consultando a la RSU: %s", exc)
        elif opcion == "2":
            try:
                snmp_set(args.host, args.port, auth, PRIORIDAD_OID, 1, "int")
                log.info("Comando enviado: activar solicitud de prioridad")
            except SnmpError as exc:
                log.error("No se pudo activar la prioridad: %s", exc)
        elif opcion == "3":
            try:
                snmp_set(args.host, args.port, auth, PRIORIDAD_OID, 0, "int")
                log.info("Comando enviado: liberar prioridad")
            except SnmpError as exc:
                log.error("No se pudo liberar la prioridad: %s", exc)
        elif opcion == "4":
            cmd_monitor(args, auth)
        elif opcion == "5":
            log.info("Cerrando software de gestion.")
            return 0
        else:
            print("Opcion invalida.")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="Leer un OID puntual")
    _add_common_args(p_get)
    p_get.add_argument("oid")

    p_set = sub.add_parser("set", help="Escribir un OID (formato valor: int:45 o str:hola)")
    _add_common_args(p_set)
    p_set.add_argument("oid")
    p_set.add_argument("value")

    p_walk = sub.add_parser("walk", help="Recorrer una subrama de OIDs")
    _add_common_args(p_walk)
    p_walk.add_argument("base_oid")

    p_monitor = sub.add_parser("monitor", help="Monitoreo continuo con logs (fase + prioridad)")
    _add_common_args(p_monitor)
    p_monitor.add_argument("--interval", type=float, default=5.0, help="Segundos entre lecturas")

    p_interactive = sub.add_parser("interactive", help="Menu interactivo (monitoreo + comandos)")
    _add_common_args(p_interactive)
    p_interactive.add_argument(
        "--interval", type=float, default=5.0,
        help="Segundos entre lecturas del modo monitoreo (opcion 4 del menu)",
    )

    args = parser.parse_args()
    auth = _build_auth_from_args(args)

    if args.cmd == "monitor":
        return cmd_monitor(args, auth)
    if args.cmd == "interactive":
        return cmd_interactive(args, auth)

    try:
        if args.cmd == "get":
            name, value = snmp_get(args.host, args.port, auth, args.oid)
            log.info("%s = %s", name, value)
        elif args.cmd == "set":
            type_, _, raw_value = args.value.partition(":")
            if not raw_value:
                raise SystemExit("El valor debe tener formato tipo:valor, ej. int:45")
            name, value = snmp_set(args.host, args.port, auth, args.oid, raw_value, type_)
            log.info("%s = %s", name, value)
        elif args.cmd == "walk":
            count = 0
            for name, value in snmp_walk(args.host, args.port, auth, args.base_oid):
                log.info("%s = %s", name, value)
                count += 1
            if count == 0:
                log.info("(sin resultados)")
    except SnmpError as exc:
        log.error("Error SNMP: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
