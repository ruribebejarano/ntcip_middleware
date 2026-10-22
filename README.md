[Cronograma de trabajo](docs/CRONOGRAMA.md) — entrega 20 de noviembre de 2026
[Guía de comandos](docs/GUIA_COMANDOS.md) — cómo correr todo esto paso a paso

# RSU — Middleware SNMP

Prototipo de tesis de bachillerato en Ingeniería Electrónica: middleware
entre una RSU (*Roadside Unit*) y un controlador de tránsito, y el enlace
V2I hacia vehículos, sobre Raspberry Pi.

## Alcance de esta versión

Este repo se está construyendo en capas. **Esta versión cubre solo el
mecanismo de gestión SNMP genérico y el enlace V2I** — los tres enlaces de
la arquitectura (centro de control ↔ RSU, RSU → controlador, OBU → RSU) —
y deliberadamente **todavía no** toca:

- Ninguna MIB estandarizada de tránsito real (se usan OID ficticios, ver
  más abajo). Es una capa posterior, ver `CLAUDE.md`.
- El modelo de seguridad definitivo (TLSTM). Se usa SNMPv3/USM tal como
  está, sin evaluar todavía su robustez — ver "Fuera de alcance por ahora".
- El enlace I2I entre RSU vecinas: cuando se implemente, será sobre el mismo
  broker MQTT por 4G/Ethernet, sin malla Wi-SUN dedicada (no hay LaunchPad
  CC1352P disponible). Ver la nota de desalineación con la tesis en
  `CLAUDE.md`.
- Hardware real: no hace falta lector OBD-II ni un controlador de tránsito
  físico. **Todo el lazo se emula con una sola Raspberry Pi + una PC.**

Alineado con el alcance vigente de la tesis (`main.tex`, secciones
`ssec:alcance` y `ssec:rf`):

- **Sin cálculo de ETA cinemático**: la OBU emite la solicitud con un
  criterio provisional de geocerca de radio fijo alrededor de la línea de
  detención, no con un tiempo estimado de llegada.
- **Sin NTCIP 1209** (datos de detección): no hay sensor físico ni dato de
  tránsito general que exponer en el banco de pruebas.
- **Direccionamiento OBU → RSU por el esquema E2+E4**: la OBU descarga al
  iniciar una copia local estática de la lista de RSU y de la geometría de
  accesos, y selecciona localmente la RSU y el acceso; no depende de IP
  pública, VPN ni de resolución por el centro de control.
  **[REVISAR: decisión servidor vs OBU, 2026-10-22]** Esto describe el
  esquema anterior a la decisión de modo semiautomático y ruta por servidor
  (`E:\Tesis\prompt_modo_semiautomatico_ruta.md`): con esa decisión, es el
  **servidor central** el que decide qué RSU y cuándo, a partir de la ruta
  que calcula al armar la misión; la OBU deja de seleccionar la RSU y el
  acceso por su cuenta, y la geocerca pasa de criterio de decisión a
  verificación final de que la posición real coincide con el acceso
  esperado. Ver la nota equivalente en `CLAUDE.md` y el inventario de qué
  habría que adaptar en el código.

## Arquitectura de esta versión

```
┌──────────────────────────── PC (laptop, cualquier SO) ───────────────────┐
│                                                                            │
│   centro_control/software_gestion.py    gateway/obu_simulator.py         │
│   (rol: centro de control)               (rol: OBU / vehículo, simulada) │
│            │  SNMPv3 GET/SET                │  MQTT publish              │
└────────────┼───────────────────────────────┼─────────────────────────────┘
             │                                │
             │        Wi-Fi / LAN (canal V2I) │
             │                                │
┌────────────┼────────────────────────────────┼──────── Raspberry Pi (RSU) ─┐
│            ▼                                ▼                            │
│    agent/rsu_middleware.py    ◄────   mosquitto (broker MQTT local)       │
│    - Agente SNMPv3 (pysnmp)                                               │
│    - Suscriptor MQTT (V2I)                                                │
│            │                                                              │
│            │ TCP local (protocolo propietario emulado)                   │
│            ▼                                                              │
│    controller/controller_emulator.py                                     │
│    (rol: controlador de tránsito — EMULADO, sin hardware real)            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Los tres enlaces

1. **Centro de control ↔ RSU** — SNMPv3 (USM: auth SHA-1 / privacidad
   AES-128). El centro de control hace `GET` sobre `faseActualTest` (fase
   vigente del semáforo) y puede hacer `SET` sobre `solicitudPrioridadTest`
   (forzar/liberar prioridad a mano). Implementado en
   `agent/rsu_middleware.py`; el lado del centro de control es
   `centro_control/software_gestion.py` — una consola con logs que
   **monitorea continuamente y envía comandos**, simulando un software de
   gestión real (ver `docs/SOFTWARE_GESTION.md`).
2. **RSU → Controlador** — protocolo propio simulado (JSON Lines sobre TCP
   local). Cuando llega un `SET` de prioridad o una solicitud V2I por MQTT,
   el middleware le pide al controlador que fuerce/libere la fase verde.
   `controller/controller_emulator.py` hace de controlador real mientras no
   haya acceso al hardware (ver `CLAUDE.md`, riesgo R5).
3. **OBU → RSU (V2I)** — MQTT. `gateway/obu_simulator.py` simula la futura
   aplicación del operador: publica una solicitud de prioridad con
   `vehiculo_id` y `eta_seg` hacia el tópico que escucha el middleware.
   Dispara exactamente el mismo camino hacia el controlador que un `SET`
   manual desde el centro de control (leg 2).

Los OID expuestos (`1.3.6.1.4.1.99999.1.1.0` y `.1.2.0`, bajo un número de
empresa **no registrado**) son ficticios y genéricos — no corresponden a
ningún estándar de MIB en particular todavía. Ver el docstring de
`agent/rsu_middleware.py`.

## Cómo correr todo (Raspberry Pi + PC)

Ver **[docs/GUIA_COMANDOS.md](docs/GUIA_COMANDOS.md)** para los comandos
exactos, en orden, incluyendo la configuración mínima de `mosquitto` para
que acepte conexiones desde la PC.

Resumen (3 procesos, 2 máquinas):

| Proceso | Máquina | Rol |
|---|---|---|
| `controller/controller_emulator.py` | Raspberry Pi | Controlador de tránsito (emulado) |
| `agent/rsu_middleware.py` | Raspberry Pi | RSU: agente SNMP + adaptador + suscriptor V2I |
| `mosquitto` | Raspberry Pi | Broker MQTT local (canal V2I) |
| `centro_control/software_gestion.py` | PC | Centro de control: monitoreo continuo + comandos, con logs |
| `gateway/obu_simulator.py` | PC | OBU simulada (publica solicitud V2I) |

## Fuera de alcance por ahora

Explícitamente pospuesto hasta que se retome el trabajo sobre seguridad,
confiabilidad y la MIB estandarizada real:

- **Seguridad**: las credenciales USM (`labAuthPass123`/`labPrivPass123`)
  son de laboratorio, en claro en el código, sin rotación ni gestión de
  claves. TLSTM (RFC 6353) no está evaluado. `mosquitto` se configura con
  `allow_anonymous true` para el banco de pruebas — no autentica ni cifra.
- **Confiabilidad**: no hay reintentos, colas ni manejo de pérdida de
  conexión entre el middleware y el controlador o el broker MQTT más allá
  de lo que dan por defecto `socket`/`paho-mqtt`. Si el controlador emulado
  se cae, `faseActualTest` devuelve `0` (valor sin semántica) en vez de
  fallar con un error SNMP explícito — simplificación deliberada para esta
  etapa.
- **MIB estandarizada real**: objetos, semántica y codificación de un
  estándar de tránsito real (ver `CLAUDE.md`).
- **I2I** entre RSU vecinas: se implementará sobre el broker MQTT
  (4G/Ethernet), no sobre una malla dedicada.
- **Hardware real**: lector OBD-II, controlador de tránsito físico.

## Estado actual del desarrollo

- [x] Entorno de desarrollo en Raspberry Pi (Python venv, pysnmp, paho-mqtt,
      net-snmp, mosquitto, git).
- [x] Agente SNMPv3 mínimo de referencia (`agent/rsu_snmpv3_agent.py`), un
      solo OID ficticio en memoria, sin controlador ni V2I — ver
      `docs/agent.md`.
- [x] Software de gestión central (`centro_control/software_gestion.py`,
      ver `docs/SOFTWARE_GESTION.md`): monitoreo continuo con logs +
      comandos interactivos, probado desde una segunda máquina física.
- [x] Emulador de controlador de tránsito (`controller/controller_emulator.py`):
      fases cíclicas + prioridad forzada, protocolo JSON Lines sobre TCP.
- [x] Middleware integrado (`agent/rsu_middleware.py`): agente SNMPv3 +
      adaptador hacia el controlador + suscriptor MQTT para V2I. Probado
      end-to-end (SNMP GET/SET/monitoreo ↔ controlador emulado).
- [x] Simulador de OBU (`gateway/obu_simulator.py`): publica solicitudes de
      prioridad V2I por MQTT.
- [ ] Prueba end-to-end de los 3 enlaces juntos, en hardware real (Raspberry
      Pi + PC en la misma red) — ver `docs/GUIA_COMANDOS.md`. Lo integrado
      hasta ahora se probó en una sola máquina de desarrollo.
- [ ] Validación manual del lector OBD-II con app comercial (Torque / Car
      Scanner) antes de que `gateway/obu_simulator.py` deje de ser un
      simulador y pase a leer datos reales.
- [ ] Raspberry Pi como Access Point Wi-Fi (`hostapd` + `dnsmasq`) para el
      banco de pruebas.
- [ ] MIB estandarizada real reemplazando los OID ficticios.

## Estructura del proyecto

```
agent/           Agente SNMPv3 (rsu_snmpv3_agent.py, mínimo) y middleware
                 integrado (rsu_middleware.py: SNMP + V2I + adaptador)
controller/      Emulador del controlador de tránsito (protocolo propio simulado)
gateway/         Simulador de OBU (obu_simulator.py) — futuro gateway OBD-II real
centro_control/  Software de gestión central (software_gestion.py):
                 monitoreo continuo + comandos, con logs
docs/            Documentación técnica y de tesis
tests/           (vacío por ahora) Pruebas automatizadas del agente y del middleware
```

## Advertencia de seguridad

Este repositorio es un prototipo académico. La comunidad SNMP configurada en
`snmpd`, el esquema USM del agente propio y la configuración de `mosquitto`
son **exclusivamente para el banco de pruebas de laboratorio** y no deben
usarse en un despliegue real. El esquema de seguridad objetivo para
producción es SNMPv3 con TLSTM (RFC 6353) — ver "Fuera de alcance por ahora".
