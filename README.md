# NTCIP Middleware — Priorización semafórica V2I centralizada

Middleware NTCIP e infraestructura V2I para priorización semafórica de
vehículos de emergencia: un servidor central decide, a partir de la ruta
y la posición de cada vehículo, cuándo y a qué intersección pedir
prioridad; una RSU (*Roadside Unit*) traduce esa solicitud al protocolo
NTCIP del controlador de tránsito.

[Guía de comandos](docs/GUIA_COMANDOS.md) — cómo levantar el sistema completo paso a paso.

## Arquitectura

```
┌──────────── OBU (cliente delgado: arma/desarma la misión [MI/MF],  ──────┐
│   publica posición a 1 Hz [MP], recibe ruta [MR] y estado [ME])          │
│   app_obu/ — app Android (GNSS real, para un dispositivo del operador)   │
│   gateway/obu_emulada.py — OBU emulada, para pruebas y campañas          │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │ MQTT 5 sobre TLS 1.3 + mTLS (broker central)
                                ▼
┌──────────────────── SERVIDOR CENTRAL (único decisor) ─────────────────────┐
│   servidor/main.py (proceso MQTT 5)                                       │
│     servidor/rutas.py       — ruta óptima + lista ordenada de RSU/accesos │
│                                (cruzada con config/registro_rsu.json)     │
│     servidor/gestor_mision.py — ciclo de vida de la misión, ETA,          │
│                                geocerca (gateway/geometria.py)            │
│     servidor/conflictos.py  — arbitraje entre misiones                   │
└──────────────────────────────┬───────────────────────────────────────────┘
                                │ M1 (solicitud, con anticipación) / M3
                                │ (cancelación) hacia la RSU; M2 de vuelta
                                ▼
┌─────────────── RSU (Raspberry Pi, módem 4G o Ethernet) ───────────────────┐
│    agent/rsu_middleware.py    ◄────   mosquitto (broker MQTT, central)    │
│    - Agente SNMPv3 (pysnmp)                                               │
│    - Acepta M1/M3 solo del servidor (ACL + mTLS del broker)               │
│            │ TCP local (protocolo propietario emulado)                   │
│            ▼                                                              │
│    controller/controller_emulator.py                                     │
│    (rol: controlador de tránsito — emulado, sin hardware real)            │
└────────────────────────────────────────────────────────────────────────────┘

centro_control/software_gestion.py (SNMPv3 GET/SET directo a la RSU) sigue
existiendo en paralelo, sin relación con el servidor central: es la consola
de gestión NTCIP clásica (ver "Los enlaces" más abajo).
```

El servidor es la única identidad autorizada a pedir prioridad a una RSU
(la RSU no acepta solicitudes de ninguna otra identidad); la OBU no
descarga ni decide contra el registro de RSU, que vive únicamente en el
servidor. La ruta se calcula sobre un grafo vial real
(`servidor/rutas.py`, `networkx.read_graphml` sobre un `.graphml`
cacheado en `data/`), no sobre una lista estática.

### Los enlaces

1. **OBU ↔ Servidor central** — MQTT 5 sobre TLS 1.3 + mTLS
   (`scripts/seguridad/`). La OBU arma la misión (MI), publica la
   posición a 1 Hz (MP) y recibe la ruta (MR) y el estado (ME) que
   calcula `servidor/gestor_mision.py`, implementado por dos clientes
   del mismo contrato: `app_obu/` (app Android, con GNSS propio para
   posición, rumbo y velocidad) y `gateway/obu_emulada.py` (OBU emulada
   en Python, sin hardware ni operador, para pruebas y campañas de
   medición reproducibles). Ver `docs/CONTRATO_OBU.md` para el esquema
   completo de mensajes.
2. **Servidor central → RSU** — MQTT, mismo broker. El servidor envía M1
   (solicitud, con anticipación por ETA) y M3 (cancelación) a
   `rsu/{rsu_id}/solicitudes`; la RSU responde M2 por el *Response
   Topic* de MQTT 5. Implementado en `servidor/main.py` (lado servidor)
   y `agent/rsu_middleware.py` (lado RSU).
3. **RSU → Controlador** — protocolo propio simulado (JSON Lines sobre
   TCP local). Cuando llega un M1 o un `SET` SNMP de prioridad, el
   middleware le pide al controlador que fuerce/libere la fase verde.
   `controller/controller_emulator.py` hace de controlador mientras no
   haya acceso a hardware real.
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

## Seguridad del canal

TLS 1.3 + mTLS en todos los tramos MQTT (OBU↔broker, servidor↔broker,
broker↔RSU), con una CA propia (`scripts/seguridad/generar_ca.py`:
emisión, revocación con CRL, SAN del certificado del broker) y control
de acceso por tema (`scripts/seguridad/mosquitto_acl.conf`): cada OBU
solo puede publicar/suscribirse en sus propios temas; cada RSU solo
puede suscribirse a los suyos; solo el servidor puede publicar en el
tema de solicitudes de una RSU.

Un banco de pruebas reproducible (`scripts/seguridad/banco_local.py`)
genera una PKI de prueba con casos negativos (certificado vencido,
revocado, de una CA no confiable) y levanta un broker temporal para la
matriz automatizada de `tests/test_seguridad_broker.py` (handshake
TLS/mTLS, control de acceso, SNMPv3). Correr la matriz completa y
generar la evidencia:

```bash
python scripts/seguridad/correr_matriz.py
```

## Compilar e instalar la app Android de la OBU (`app_obu/`)

```bash
cd app_obu
./gradlew assembleDebug          # genera app/build/outputs/apk/debug/app-debug.apk
adb devices                      # confirmar que el dispositivo aparece
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Requiere un JDK con `JAVA_HOME` configurado y, para instalar, depuración
USB habilitada en el dispositivo. Ver `app_obu/README.md` para los
escenarios de prueba, Ajustes (certificado mTLS, broker) y la puesta en
marcha contra servidor y RSU.

## Cómo correr todo

Ver **[docs/GUIA_COMANDOS.md](docs/GUIA_COMANDOS.md)** para los comandos
exactos, en orden.

Resumen (5 procesos; el servidor y el broker pueden vivir en la misma
máquina, o en una laptop mientras no haya un servidor dedicado):

| Proceso | Dónde | Rol |
|---|---|---|
| `mosquitto` | Servidor | Broker MQTT central (TLS 1.3 + mTLS, `scripts/seguridad/`) |
| `servidor/main.py` | Servidor | Único decisor: ruta, ETA, geocerca, conflictos |
| `controller/controller_emulator.py` | RSU | Controlador de tránsito (emulado) |
| `agent/rsu_middleware.py` | RSU (módem 4G o Ethernet) | Agente SNMP (NTCIP 1202/1211) + adaptador + M1/M3 del servidor |
| `app_obu/` (o `gateway/obu_emulada.py`) | Dispositivo Android (o emulada) | OBU: cliente delgado de la misión (MI/MP/MF, recibe MR/ME) |

`centro_control/software_gestion.py` (SNMPv3 GET/SET directo a la RSU) y
`gateway/obu_simulator.py` (M1 directo a la RSU, esquema legado) siguen
funcionando para las pruebas que ya dependían de ellos, pero no son
parte del flujo de la arquitectura centralizada — ver sus docstrings.

## Caracterización del canal y campañas de medición

`scripts/campanas/lazo_centralizado.py` corre el lazo completo
(OBU→servidor→RSU→controlador) con cuotas adaptativas por condición de
llegada del semáforo (verde / ámbar-todo rojo / rojo), en local, contra
una RSU por LAN, o contra una RSU por 4G; `--tls <carpeta_pki>` lo corre
con TLS/mTLS activo. `scripts/analisis/lazo_centralizado.py` calcula la
latencia del lazo y la anticipación real a partir de las corridas; los
resultados curados están en `resultados/campana/` y `evidencia/`.

## Estructura del proyecto

```
servidor/        Servidor central (único decisor): rutas.py (ruta +
                 lista de RSU/accesos), gestor_mision.py (ciclo de
                 vida, ETA, geocerca), conflictos.py (arbitraje), main.py
agent/           Agente SNMPv3 (rsu_snmpv3_agent.py, mínimo) y middleware
                 integrado (rsu_middleware.py: SNMP + M1/M3 del servidor + adaptador)
controller/      Emulador del controlador de tránsito (protocolo propio simulado)
app_obu/         App Android de la OBU — proyecto Gradle/Kotlin
                 independiente, ver app_obu/README.md
gateway/         OBU emulada (obu_emulada.py, cliente delgado para
                 pruebas y campañas) y geometría de accesos
                 (geometria.py, reusada por el servidor)
centro_control/  Software de gestión central (software_gestion.py):
                 monitoreo continuo + comandos, con logs (independiente del servidor)
consola/         Consola web de monitoreo (FastAPI) del banco de pruebas y
                 las campañas de medición, ver docs/CONSOLA.md
scripts/seguridad/  CA propia, ACL, TLS/mTLS de Mosquitto y la matriz
                 de pruebas de seguridad (banco_local.py, correr_matriz.py)
scripts/campanas/   Campañas de medición del lazo (lazo_centralizado.py)
scripts/analisis/   Análisis y figuras a partir de las campañas
scripts/datos/   Regeneración del grafo vial cacheado (data/*.graphml)
data/            Grafo vial cacheado para servidor/rutas.py (ver data/LEEME.md)
docs/            Documentación técnica
tests/           Pruebas automatizadas (agente, middleware, servidor, seguridad)
evidencia/       Evidencia curada de corridas y verificaciones
resultados/      Resultados de campañas de medición
```

## Limitaciones conocidas

- **SNMPv3/USM, no TLSTM**: el agente SNMPv3 usa USM (SHA-1 + AES-128,
  credenciales de laboratorio en claro en el código, sin rotación de
  claves). TLSTM (RFC 6353) no está implementado — la biblioteca SNMP
  usada no tiene un modelo de transporte seguro para SNMPv3.
- **Límite de la ACL del broker**: una regla de la ACL
  (`servidor/central/respuestas`) no restringe por identidad individual
  (limitación de Mosquitto con ACL por archivo, sin roles de cliente);
  el impacto es bajo porque el servidor ignora cualquier mensaje que no
  corresponda a una solicitud que esté siguiendo — ver
  `tests/test_seguridad_broker.py` (T10).
- **Enlace I2I entre RSU vecinas**: no implementado. Si se agrega, sería
  sobre el mismo broker MQTT, sin una malla dedicada.
- **Controlador de tránsito físico**: la RSU se adapta hoy contra
  `controller/controller_emulator.py`, no contra hardware real.
- **Confiabilidad**: no hay colas ni reintentos entre el middleware y el
  controlador o el broker más allá de lo que dan por defecto
  `socket`/`paho-mqtt`. Si el controlador emulado se cae, el agente
  devuelve un valor sin semántica en vez de un error SNMP explícito.
- **Cálculo de ETA**: provisional, basado en velocidad reportada y una
  geocerca de radio fijo, no en un modelo cinemático.

## Advertencia de seguridad

Este repositorio es un banco de pruebas de laboratorio. La comunidad
SNMP configurada en `snmpd`, el esquema USM del agente propio y la
configuración por defecto de `mosquitto` (sin TLS, sin ACL) son
**exclusivamente para desarrollo local** y no deben usarse en un
despliegue real sin aplicar la configuración de `scripts/seguridad/`
(TLS 1.3 + mTLS + ACL) descrita arriba.
