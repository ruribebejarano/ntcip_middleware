[Cronograma de trabajo](docs/CRONOGRAMA.md) — entrega 20 de noviembre de 2026
[Guía de comandos](docs/GUIA_COMANDOS.md) — cómo correr todo esto paso a paso

# RSU — Middleware SNMP

Prototipo de tesis de bachillerato en Ingeniería Electrónica: middleware
entre una RSU (*Roadside Unit*) y un controlador de tránsito, y el enlace
V2I hacia vehículos, sobre Raspberry Pi.

## Alcance de esta versión

Este repo se está construyendo en capas, sobre el banco de pruebas físico
del proyecto: Raspberry Pi como RSU con módem SIM7670G (4G) hacia el
servidor central, y OBU como app Android con lector OBD-II. **Esta versión
cubre los objetos reales de la MIB NTCIP (1202 y 1211) y el enlace V2I**
— los tres enlaces de la arquitectura (centro de control ↔ RSU, RSU →
controlador, OBU → RSU) — y deliberadamente **todavía no** toca:

- El modelo de seguridad definitivo (TLSTM). Se usa SNMPv3/USM tal como
  está, sin evaluar todavía su robustez — ver "Fuera de alcance por ahora".
- El enlace I2I entre RSU vecinas: cuando se implemente, será sobre el mismo
  broker MQTT por el módem 4G de cada RSU, sin una malla dedicada. Ver la
  nota de desalineación con la tesis en `CLAUDE.md`.

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
- **Cálculo de ruta sobre grafo vial real (`servidor/rutas.py`):** el
  servidor carga con `networkx.read_graphml` (sin depender de `osmnx` en
  tiempo de ejecución) un grafo de OpenStreetMap cacheado en
  `data/grafo_san_miguel_real.graphml`, que cubre tanto las intersecciones
  de `config/registro_rsu.json` como el escenario de referencia de la
  tesis (Cía. de Bomberos San Miguel N.º 83 → Hospital Centro Médico
  Naval). `cargar_grafo()` colapsa el `MultiDiGraph` que exporta OSMnx a un
  `DiGraph` simple (quedándose con la arista más corta entre cada par de
  nodos) para que `calcular_ruta()` pueda acumular distancias sin ambigüedad.
  Ver `data/LEEME.md` y `docs/bitacora/2026-10-23_grafo_escenario_referencia.md`.

## Arquitectura de esta versión

```
┌──────────── OBU (app Android + lector OBD-II, cliente delgado) ──────────┐
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
┌─────────────── Raspberry Pi (RSU, módem SIM7670G 4G) ─────────────────────┐
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
   objetivo (ver `scripts/seguridad/`). La app Android de la OBU (con
   lector OBD-II para velocidad/aceleración) arma la misión (MI), publica
   la posición a 1 Hz (MP) y recibe la ruta (MR) y el estado (ME) que
   calcula `servidor/gestor_mision.py` — `gateway/obu_emulada.py` implementa
   este contrato. Ver `docs/CONTRATO_OBU.md` para el esquema completo de
   mensajes.
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

Los OID expuestos cuelgan del número de empresa de NEMA
(`1.3.6.1.4.1.1206`): el subárbol `asc` para los objetos reales de NTCIP
1202 (estado de fase y tiempos, `phaseStatusGroupTable`/`phaseTable`) y
`scp` para NTCIP 1211 (`priorityRequestTable` y
`prgPriorityRequestAbsolute`, codificado OER). Ver el docstring de
`agent/rsu_middleware.py` y `agent/ntcip1211.py`.

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
| `agent/rsu_middleware.py` | Raspberry Pi (módem SIM7670G) | RSU: agente SNMP (NTCIP 1202/1211) + adaptador + M1/M3 del servidor |
| `gateway/obu_emulada.py` | Teléfono Android | OBU (app Android + lector OBD-II: MI/MP/MF, recibe MR/ME) |

`centro_control/software_gestion.py` (SNMPv3 GET/SET directo a la RSU) y
`gateway/obu_simulator.py` (M1 directo a la RSU, esquema legado P0-P3)
siguen funcionando para las pruebas que ya dependían de ellos, pero no son
parte del flujo de la arquitectura centralizada — ver sus docstrings.

## Lo construido hasta ahora

- **Entorno de desarrollo** en Raspberry Pi (Python venv, `pysnmp`,
  `paho-mqtt`, `net-snmp`, `mosquitto`, `git`).
- **Agente SNMPv3 mínimo de referencia** (`agent/rsu_snmpv3_agent.py`), un
  solo OID ficticio en memoria, sin controlador ni V2I — ver `docs/agent.md`.
- **Software de gestión central** (`centro_control/software_gestion.py`,
  ver `docs/SOFTWARE_GESTION.md`): monitoreo continuo con logs + comandos
  interactivos, probado desde una segunda máquina física.
- **Emulador de controlador de tránsito**
  (`controller/controller_emulator.py`): fases cíclicas + prioridad
  forzada, protocolo JSON Lines sobre TCP.
- **Middleware integrado** (`agent/rsu_middleware.py`): agente SNMPv3 +
  adaptador hacia el controlador + suscriptor MQTT para V2I, probado
  de punta a punta (SNMP GET/SET/monitoreo ↔ controlador emulado).
- **Objetos reales de la MIB NTCIP** integrados en el middleware: NTCIP
  1202 (estado de fase y tiempos, `phaseStatusGroupTable`/`phaseTable`) y
  NTCIP 1211 (`priorityRequestTable` y `prgPriorityRequestAbsolute`,
  codificado OER, `agent/ntcip1211.py`), bajo el número de empresa de NEMA
  — probados con `snmpget`/`snmpset`/`snmpwalk` reales, ver
  `evidencia/2026-10-11_agente_snmpwalk-ntcip1202.png` y
  `evidencia/2026-10-11_agente_snmpset-ntcip1211-rf06.png`.
- **Banco de pruebas físico:** Raspberry Pi como RSU, con módem SIM7670G
  para el enlace 4G hacia el servidor central, y la OBU como app Android
  con lector OBD-II (velocidad/aceleración) — ver
  `docs/CONEXION_RASPBERRY.md` y `docs/CONTRATO_OBU.md`.
- **Simulador de OBU legado** (`gateway/obu_simulator.py`): publica
  solicitudes de prioridad V2I por MQTT directamente a la RSU (esquema
  P0-P3, se mantiene funcionando como referencia).
- **Arquitectura centralizada (desde 2026-10-22):** `servidor/` (ruta,
  ETA, geocerca, conflictos) + `gateway/obu_emulada.py` como cliente
  delgado + `agent/rsu_middleware.py` aceptando M1/M3 del servidor.
  Probada de punta a punta en local con 3 escenarios reales sobre MQTT
  (lazo completo, conflicto, desvío) — ver
  `evidencia/2026-10-22_arquitectura-centralizada/`.
- **CA propia y configuración TLS/mTLS de Mosquitto** (`scripts/seguridad/`):
  generación, emisión y revocación de certificados con `openssl`, y la
  configuración de ACL (solo el servidor publica en `rsu/+/solicitudes`)
  para cuando se active el broker con TLS 1.3 + mTLS.
- **Grafo vial real ampliado al escenario de referencia (2026-10-23):**
  `data/grafo_san_miguel_real.graphml` ya cubre, además de las dos
  intersecciones del registro de RSU, la ruta Cía. de Bomberos San Miguel
  N.º 83 → Hospital Centro Médico Naval (coordenadas geocodificadas con
  Nominatim), y `servidor/rutas.py::cargar_grafo` colapsa correctamente las
  aristas paralelas que trae OSMnx en avenidas con separador físico. Ver
  `docs/bitacora/2026-10-23_grafo_escenario_referencia.md`.

## Fuera de alcance por ahora

Explícitamente pospuesto hasta que se retome el trabajo sobre seguridad y
confiabilidad:

- **Seguridad**: las credenciales USM (`labAuthPass123`/`labPrivPass123`)
  son de laboratorio, en claro en el código, sin rotación ni gestión de
  claves. TLSTM (RFC 6353) no está evaluado. El banco de pruebas corre hoy
  con `allow_anonymous true` en `mosquitto` (sin autenticar ni cifrar);
  `scripts/seguridad/` tiene la CA propia (probada: generación, emisión y
  revocación de certificados con `openssl`) y la configuración de
  Mosquitto con TLS 1.3 + mTLS + ACL, lista para activarse sobre un broker
  en ejecución — ver `docs/bitacora/2026-10-22_arquitectura-centralizada.md`
  para los comandos exactos.
- **Confiabilidad**: no hay reintentos, colas ni manejo de pérdida de
  conexión entre el middleware y el controlador o el broker MQTT más allá
  de lo que dan por defecto `socket`/`paho-mqtt`. Si el controlador emulado
  se cae, `faseActualTest` devuelve `0` (valor sin semántica) en vez de
  fallar con un error SNMP explícito — simplificación deliberada para esta
  etapa.
- **I2I** entre RSU vecinas: se implementará sobre el broker MQTT
  (4G), no sobre una malla dedicada.
- **Controlador de tránsito físico**: la RSU se adapta hoy contra
  `controller/controller_emulator.py`.

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
consola/         Consola web de monitoreo (FastAPI) del banco de pruebas y
                 las campañas de medición (OE5), ver docs/CONSOLA.md
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
