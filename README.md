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
- **Direccionamiento por servidor central (arquitectura vigente desde
  2026-10-22):** el servidor calcula la ruta (`servidor/rutas.py`) al armar
  la misión y decide qué RSU y cuándo, cruzando esa ruta con
  `config/registro_rsu.json` (que vive **solo** en el servidor). La OBU no
  descarga ninguna copia del registro ni decide la RSU/el acceso por su
  cuenta: es un cliente delgado (`gateway/obu_emulada.py`) que arma/desarma
  la misión y publica su posición. La geocerca de
  `gateway/geometria.py` (clase `SeguidorAcceso`) se reutiliza tal cual,
  pero ahora corre en el servidor como **verificación final**, no como
  criterio de decisión. Ver `docs/CONTRATO_OBU.md` (especificación de
  mensajes) y `docs/bitacora/2026-10-22_arquitectura-centralizada.md`
  (justificación y evolución del diseño).
  - **Etapa previa del desarrollo (válida como antecedente, no vigente):**
    el prototipo inicial usaba el esquema E2+E4 (la OBU decidía
    localmente, con una copia local estática del registro). Esa etapa
    quedó documentada y su evidencia se conserva en `evidencia/` y
    `resultados/` — ver `docs/bitacora/2026-10-19_lazo-obu-emulada.md` y
    `docs/bitacora/2026-10-22_modo-semiautomatico-y-ruta.md` (ambas con
    una nota al final señalando que fueron superadas por la arquitectura
    centralizada).

## Arquitectura de esta versión

```
┌──────────────────── OBU (laptop/celular, cliente delgado) ───────────────┐
│   gateway/obu_emulada.py — arma/desarma la misión (MI/MF),               │
│   publica posición a 1 Hz (MP); recibe ruta (MR) y estado (ME)           │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │ MQTT (broker central)
                                ▼
┌──────────────────── SERVIDOR CENTRAL (único decisor) ─────────────────────┐
│   servidor/main.py (proceso MQTT 5)                                       │
│     servidor/rutas.py       — ruta óptima + lista ordenada de RSU/accesos │
│                                (cruzada con config/registro_rsu.json)     │
│     servidor/gestor_mision.py — ciclo de vida de la misión, ETA (RF8),    │
│                                geocerca (gateway/geometria.py, reusada)   │
│     servidor/conflictos.py  — arbitraje entre misiones                   │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │ M1 (solicitud, con anticipación) / M3
                                │ (cancelación) hacia la RSU; M2 de vuelta
                                ▼
┌──────────────────────── Raspberry Pi (RSU) ───────────────────────────────┐
│    agent/rsu_middleware.py    ◄────   mosquitto (broker MQTT, central)    │
│    - Agente SNMPv3 (pysnmp)                                               │
│    - Acepta M1/M3 SOLO del servidor (ACL del broker, scripts/seguridad/)  │
│            │ TCP local (protocolo propietario emulado)                   │
│            ▼                                                              │
│    controller/controller_emulator.py                                     │
│    (rol: controlador de tránsito — EMULADO, sin hardware real)            │
└────────────────────────────────────────────────────────────────────────────┘

centro_control/software_gestion.py (SNMPv3 GET/SET directo a la RSU) sigue
existiendo en paralelo, sin relación con el servidor central: es la consola
de gestión NTCIP clásica (ver "Los enlaces" más abajo).
```

### Los enlaces

1. **OBU ↔ Servidor central** — MQTT 5, con TLS 1.3 + mTLS en el diseño
   objetivo (ver `scripts/seguridad/`). `gateway/obu_emulada.py` arma la
   misión (MI), publica la posición a 1 Hz (MP) y recibe la ruta (MR) y el
   estado (ME) que calcula `servidor/gestor_mision.py`. Ver
   `docs/CONTRATO_OBU.md` para el esquema completo de mensajes.
2. **Servidor central → RSU** — MQTT, mismo broker. El servidor envía M1
   (solicitud, con anticipación por ETA) y M3 (cancelación) a
   `rsu/{rsu_id}/solicitudes`; la RSU responde M2 por el Response Topic de
   MQTT 5. Implementado en `servidor/main.py` (lado servidor) y
   `agent/rsu_middleware.py` (lado RSU, sin cambios de comportamiento más
   allá de aceptar estos campos).
3. **RSU → Controlador** — protocolo propio simulado (JSON Lines sobre TCP
   local). Cuando llega un M1 o un `SET` SNMP de prioridad, el middleware
   le pide al controlador que fuerce/libere la fase verde.
   `controller/controller_emulator.py` hace de controlador real mientras no
   haya acceso al hardware (ver `CLAUDE.md`, riesgo R5).
4. **Centro de control ↔ RSU** — SNMPv3 (USM: auth SHA-1 / privacidad
   AES-128), sin relación con el servidor central: es una consola de
   gestión clásica que hace `GET`/`SET` directo sobre la RSU
   (`centro_control/software_gestion.py`, ver `docs/SOFTWARE_GESTION.md`).

Los OID expuestos (`1.3.6.1.4.1.99999.1.1.0` y `.1.2.0`, bajo un número de
empresa **no registrado**) son ficticios y genéricos — no corresponden a
ningún estándar de MIB en particular todavía. Ver el docstring de
`agent/rsu_middleware.py`.

## Cómo correr todo (arquitectura centralizada)

Ver **[docs/GUIA_COMANDOS.md](docs/GUIA_COMANDOS.md)** para los comandos
exactos, en orden, y
**[evidencia/2026-10-22_arquitectura-centralizada/](evidencia/2026-10-22_arquitectura-centralizada/)**
para tres escenarios ya corridos de punta a punta (lazo completo,
conflicto, desvío) con sus scripts de orquestación
(`correr_e2e*.sh`) como referencia directa de los comandos.

Resumen (5 procesos; el servidor y el broker pueden vivir en la misma
máquina, o en la laptop mientras no haya un servidor dedicado):

| Proceso | Dónde | Rol |
|---|---|---|
| `mosquitto` | Servidor/laptop | Broker MQTT central (TLS 1.3 + mTLS en el diseño objetivo, ver `scripts/seguridad/`) |
| `servidor/main.py` | Servidor/laptop | Único decisor: ruta, ETA, geocerca, conflictos |
| `controller/controller_emulator.py` | Raspberry Pi | Controlador de tránsito (emulado) |
| `agent/rsu_middleware.py` | Raspberry Pi | RSU: agente SNMP + adaptador + M1/M3 del servidor |
| `gateway/obu_emulada.py` | Laptop/celular | OBU (cliente delgado: MI/MP/MF, recibe MR/ME) |

`centro_control/software_gestion.py` (SNMPv3 GET/SET directo a la RSU) y
`gateway/obu_simulator.py` (M1 directo a la RSU, esquema legado P0-P3)
siguen funcionando para las pruebas que ya dependían de ellos, pero no son
parte del flujo de la arquitectura centralizada — ver sus docstrings.

## Fuera de alcance por ahora

Explícitamente pospuesto hasta que se retome el trabajo sobre seguridad,
confiabilidad y la MIB estandarizada real:

- **Seguridad**: las credenciales USM (`labAuthPass123`/`labPrivPass123`)
  son de laboratorio, en claro en el código, sin rotación ni gestión de
  claves. TLSTM (RFC 6353) no está evaluado. El banco de pruebas corre hoy
  con `allow_anonymous true` en `mosquitto` (sin autenticar ni cifrar);
  `scripts/seguridad/` tiene la CA propia (probada: generación, emisión y
  revocación de certificados con `openssl`) y la configuración de
  Mosquitto con TLS 1.3 + mTLS + ACL, pero **no se probó contra un broker
  real** en este entorno de desarrollo — ver
  `docs/bitacora/2026-10-22_arquitectura-centralizada.md` para los
  comandos exactos pendientes.
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
- [x] Simulador de OBU (`gateway/obu_simulator.py`, esquema legado): publica
      solicitudes de prioridad V2I por MQTT.
- [x] **Arquitectura centralizada (2026-10-22)**: `servidor/` (ruta, ETA,
      geocerca, conflictos) + `gateway/obu_emulada.py` como cliente delgado
      + `agent/rsu_middleware.py` aceptando M1/M3 del servidor. Prueba de
      punta a punta local con 3 escenarios (lazo completo, conflicto,
      desvío) sobre MQTT real — ver
      `evidencia/2026-10-22_arquitectura-centralizada/`.
- [ ] CA/TLS/mTLS reales contra un broker en ejecución (la CA en sí se
      probó, el broker con esa configuración no — ver
      `scripts/seguridad/`).
- [ ] Prueba end-to-end de los enlaces juntos, en hardware real (Raspberry
      Pi + servidor/laptop en la misma red) — ver `docs/GUIA_COMANDOS.md`.
      Lo integrado hasta ahora se probó en una sola máquina de desarrollo
      (sin Raspberry Pi disponible en este entorno).
- [ ] Validación manual del lector OBD-II con app comercial (Torque / Car
      Scanner) antes de que `gateway/obu_simulator.py` deje de ser un
      simulador y pase a leer datos reales.
- [ ] Raspberry Pi como Access Point Wi-Fi (`hostapd` + `dnsmasq`) para el
      banco de pruebas.
- [ ] MIB estandarizada real reemplazando los OID ficticios.

## Estructura del proyecto

```
servidor/        Servidor central (único decisor, 2026-10-22): rutas.py
                 (ruta + lista de RSU/accesos), gestor_mision.py (ciclo de
                 vida, ETA, geocerca), conflictos.py (arbitraje), main.py
agent/           Agente SNMPv3 (rsu_snmpv3_agent.py, mínimo) y middleware
                 integrado (rsu_middleware.py: SNMP + M1/M3 del servidor + adaptador)
controller/      Emulador del controlador de tránsito (protocolo propio simulado)
gateway/         OBU emulada (obu_emulada.py, cliente delgado) y geometría
                 de accesos (geometria.py, reusada por el servidor)
centro_control/  Software de gestión central (software_gestion.py):
                 monitoreo continuo + comandos, con logs (independiente del servidor)
consola/         Consola web de monitoreo (FastAPI); el mapa en vivo de la
                 misión está pendiente de adaptarse a MR/ME, ver docs/CONSOLA.md
scripts/seguridad/  CA propia, ACL y configuración TLS/mTLS de Mosquitto (P4)
scripts/datos/   Regeneración del grafo vial cacheado (data/*.graphml)
data/            Grafo vial cacheado para servidor/rutas.py (ver data/LEEME.md)
docs/            Documentación técnica y de tesis
tests/           Pruebas automatizadas (agente, middleware, servidor)
```

## Advertencia de seguridad

Este repositorio es un prototipo académico. La comunidad SNMP configurada en
`snmpd`, el esquema USM del agente propio y la configuración de `mosquitto`
son **exclusivamente para el banco de pruebas de laboratorio** y no deben
usarse en un despliegue real. El esquema de seguridad objetivo para
producción es SNMPv3 con TLSTM (RFC 6353) — ver "Fuera de alcance por ahora".
