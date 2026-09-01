#!/usr/bin/env python3
"""Agente SNMPv3 minimo del middleware NTCIP de la RSU (prototipo de tesis).

*** OBJETO DE PRUEBA - NO ES LA IMPLEMENTACION FINAL DE LA MIB NTCIP 1202/1211 ***
El OID expuesto aqui (1.3.6.1.4.1.99999.1.1.0, bajo un numero de empresa NO
registrado) es un entero FICTICIO que solo imita, para validar la pila SNMPv3
(USM: autenticacion SHA-1 + privacidad AES-128), la idea de un objeto de
estado agregado de fases tipo "phaseStatusCurrentGroup" de un controlador de
senal NTCIP 1202. No tiene la semantica real (bitmask de rojo/ambar/verde por
grupo de 8 fases, definida en phaseStatusGroupReds/Yellows/Greens) ni respeta
el caracter de solo-lectura de esos objetos en el estandar real -- aqui es
de lectura/escritura a proposito, para poder probar snmpget y snmpset.

Cuando se implemente la MIB 1202/1211 real, este agente debe reemplazarse por
objetos definidos a partir de las MIB instaladas en /usr/share/snmp/mibs/
(NTCIP1202-v03.mib, NTCIP1211-v02-PRS-MIB1.mib, NTCIP1211-v02-CO-MIB1.mib).

Seguridad: USM (SNMPv3) con SHA-1/AES-128 es un PUNTO DE PARTIDA de
laboratorio. La migracion planeada para produccion es a TLSTM (Transport
Security Model sobre TLS/DTLS, RFC 6353), conforme a NTCIP 1102. Las claves
de abajo son de laboratorio unicamente y no deben usarse fuera de el.

Nota de dependencia: requiere una build de pysnmp posterior al fix de
https://github.com/pysnmp/pysnmp/pull/98 (combinaciones USM SHA+AES128 rotas
en pysnmp<=7.1.29 publicado en PyPI). Ver requirements.txt / docs/agent.md
para el commit exacto instalado y el parche local aplicado.
"""

from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413.context import SnmpContext
from pysnmp.proto.rfc1902 import Integer32

LISTEN_ADDRESS = ("0.0.0.0", 1161)  # puerto no privilegiado; snmpd real sigue en 161

USER_NAME = "rsuLabUser"
AUTH_KEY = "labAuthPass123"  # SOLO laboratorio
PRIV_KEY = "labPrivPass123"  # SOLO laboratorio

TEST_SCALAR_OID = (1, 3, 6, 1, 4, 1, 99999, 1, 1)  # ...1.1.0 es la instancia
TEST_INITIAL_VALUE = 5


class _MutableTestInstance:
    """Mixin: guarda el valor ficticio en memoria y permite modificarlo por SET."""

    def __init__(self, *args, initial_value=0, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = initial_value

    def getValue(self, name, idx):
        return self.syntax.clone(self._value)

    def setValue(self, value, name, idx):
        self._value = int(value)
        return self.syntax.clone(self._value)


def build_agent() -> engine.SnmpEngine:
    snmp_engine = engine.SnmpEngine()

    config.addTransport(
        snmp_engine,
        config.udp.domainName,
        config.udp.UdpAsyncioTransport().openServerMode(LISTEN_ADDRESS),
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
        readSubTree=TEST_SCALAR_OID,
        writeSubTree=TEST_SCALAR_OID,
    )

    mib_builder = snmp_engine.getMibBuilder()
    MibScalar, MibScalarInstance = mib_builder.importSymbols(
        "SNMPv2-SMI", "MibScalar", "MibScalarInstance"
    )

    class PhaseStatusCurrentGroupTestInstance(_MutableTestInstance, MibScalarInstance):
        pass

    mib_builder.exportSymbols(
        "__RSU-TEST-MIB",
        phaseStatusCurrentGroupTest=MibScalar(
            TEST_SCALAR_OID, Integer32()
        ).setMaxAccess("readwrite"),
        phaseStatusCurrentGroupTestInstance=PhaseStatusCurrentGroupTestInstance(
            TEST_SCALAR_OID, (0,), Integer32(), initial_value=TEST_INITIAL_VALUE
        ),
    )

    snmp_context = SnmpContext(snmp_engine)
    cmdrsp.GetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.SetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.NextCommandResponder(snmp_engine, snmp_context)
    cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)

    return snmp_engine


def main() -> None:
    snmp_engine = build_agent()
    oid_str = ".".join(str(n) for n in TEST_SCALAR_OID) + ".0"
    print(f"Agente SNMPv3 de prueba (RSU/NTCIP) escuchando en "
          f"{LISTEN_ADDRESS[0]}:{LISTEN_ADDRESS[1]}")
    print(f"Usuario USM: {USER_NAME} (auth SHA-1 / priv AES-128)")
    print(f"OID de prueba (ficticio, ver cabecera del modulo): {oid_str}")

    dispatcher = snmp_engine.transportDispatcher

    try:
        # Sin jobStarted(): un agente pasivo debe caer en la rama de "modo
        # servidor" del dispatcher (run_forever), no en la de "esperar
        # trabajos pendientes" pensada para clientes SNMP (managers).
        dispatcher.runDispatcher()
    except KeyboardInterrupt:
        print("\nDeteniendo agente...")
    finally:
        dispatcher.closeDispatcher()


if __name__ == "__main__":
    main()
