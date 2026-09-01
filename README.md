# RSU NTCIP Middleware

Prototipo de tesis de bachillerato en Ingeniería Electrónica: middleware NTCIP
y agente SNMPv3 para una Unidad de Borde de Carretera (RSU, *Roadside Unit*)
sobre Raspberry Pi, como parte de un sistema V2I/I2I basado en Wi-SUN.

## Objetivo de la tesis

Diseñar e implementar un prototipo funcional de RSU capaz de exponer
información de estado de un controlador de semáforo (siguiendo los objetos
definidos por las normas NTCIP 1202 y NTCIP 1211) mediante un agente SNMP,
sirviendo como middleware entre el controlador de tránsito y aplicaciones de
gestión (V2I) y otras RSU vecinas (I2I).

## Arquitectura

```
                 ┌─────────────────────────────┐
                 │   Controlador de tránsito    │
                 │  (referencia NTCIP 1202/1211)│
                 └──────────────┬──────────────┘
                                │ SNMP (agente NTCIP)
                 ┌──────────────┴──────────────┐
                 │   RSU (Raspberry Pi)         │
                 │  - Middleware NTCIP          │
                 │  - Agente SNMPv3 (pysnmp)    │
                 │  - Gateway OBD-II (futuro)   │
                 └───┬────────────────────┬─────┘
         V2I (Wi-Fi / 4G)          I2I (Wi-SUN)
                 │                        │
        ┌────────┴────────┐      ┌────────┴────────┐
        │ Centro de gestión│      │   RSU vecinas   │
        │  / vehículos     │      │  (malla Wi-SUN) │
        └──────────────────┘      └─────────────────┘
```

- **Canal V2I (Vehicle-to-Infrastructure)**: comunicación Wi-Fi/4G entre la
  RSU y vehículos o el centro de gestión de tránsito.
- **Canal I2I (Infrastructure-to-Infrastructure)**: comunicación de malla
  Wi-SUN entre RSU vecinas.
- **Middleware NTCIP**: traduce entre el protocolo NTCIP (SNMP sobre las MIB
  1202/1211) y los demás componentes del sistema.

## Estado actual del desarrollo

- [x] Entorno de desarrollo en Raspberry Pi (Python venv, pysnmp, paho-mqtt,
      net-snmp, mosquitto, git).
- [x] Agente de referencia `snmpd` configurado con comunidad de prueba
      **solo para laboratorio** (ver comentario en `snmpd.conf`; en
      producción se migrará a SNMPv3 con TLSTM).
- [x] MIB de NTCIP 1202 y 1211 extraídas de los estándares públicos en PDF
      (`ntcip.org`) e instaladas en `/usr/share/snmp/mibs/` para pruebas con
      `snmpwalk`/`snmptranslate`.
      ⚠️ **No son el archivo MIB oficial de NEMA** (ese requiere solicitud a
      `ntcip@nema.org`); además los módulos de soporte (`NTCIP8004v02`,
      `NEMA-SMI`, `NEMA-SMI2`) son *stubs* no oficiales con al menos un OID
      placeholder (`scp` bajo `devices.5`) pendiente de confirmar contra el
      MIB real.
- [x] Agente SNMPv3 propio (`agent/rsu_snmpv3_agent.py`) con `pysnmp`,
      autenticación SHA-1 + privacidad AES-128 (USM), exponiendo un OID de
      prueba ficticio (`1.3.6.1.4.1.99999.1.1.0`, equivalente conceptual a
      `phaseStatusCurrentGroup`, no es la implementación final de la MIB
      1202). Probado con `snmpget`/`snmpset` reales, incluyendo acceso vía
      la IP LAN de la Raspberry Pi (ver `docs/agent.md`).
      ⚠️ Requiere una build de `pysnmp` con un fix aún no publicado en PyPI
      (bug conocido de USM SHA+AES128, ver `docs/agent.md` y
      `requirements.txt`) — revisar periódicamente si ya hay versión oficial.
- [ ] Validación manual del lector OBD-II con app comercial (Torque / Car
      Scanner) antes de desarrollar el gateway propio.
- [ ] Raspberry Pi como Access Point Wi-Fi (`hostapd` + `dnsmasq`) para el
      banco de pruebas.
- [ ] Gateway OBD-II → I2I/V2I (`gateway/`).

## Estructura del proyecto

```
agent/    Agente SNMPv3 propio (pysnmp) — middleware NTCIP
gateway/  Gateway OBD-II y lógica de integración V2I/I2I (pendiente)
docs/     Documentación técnica y de tesis
tests/    Pruebas del agente y del middleware
```

## Advertencia de seguridad

Este repositorio es un prototipo académico. La comunidad SNMP configurada en
`snmpd` y el esquema USM del agente propio son **exclusivamente para el banco
de pruebas de laboratorio** y no deben usarse en un despliegue real. El
esquema de seguridad objetivo para producción es SNMPv3 con TLSTM (RFC 6353),
conforme a NTCIP 1102.
