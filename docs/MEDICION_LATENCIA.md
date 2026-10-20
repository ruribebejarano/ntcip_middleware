# Medición de la latencia del lazo de priorización

Este documento describe cómo se mide hoy la latencia del lazo OBU → broker →
RSU → controlador → M2 de vuelta, con la OBU emulada (`gateway/obu_emulada.py`,
ver `docs/LAZO_EMULADO.md`). Todo lo que sigue sale directamente de
`common/events.py`, `gateway/obu_emulada.py`, `agent/rsu_middleware.py`,
`controller/controller_emulator.py`, `scripts/analisis/lazo_emulado.py` y de
la bitácora `docs/bitacora/2026-10-19_lazo-obu-emulada.md`: no hay cifras
inventadas en este documento.

## 1. El lazo y dónde se registra cada evento

```
   OBU (laptop)              broker MQTT             RSU (Raspberry Pi)            Controlador
  ───────────────          ───────────────          ───────────────────          ───────────────
       │                                                     │                          │
       │  [muestra]  <- lee fila de la trayectoria            │                          │
       │  (antes de decidir geometria)                        │                          │
       │                                                      │                          │
       │──── M1 (tipo=M1) ─────────▶│                         │                          │
       │  [M1_tx]                   │──── M1 ────────────────▶│                          │
       │  (reloj OBU)                                          │  [M1_rx]                 │
       │                                                       │  (reloj RSU)             │
       │                                                       │                          │
       │                                                       │  RF-05 (clase) + RF-06   │
       │                                                       │  (limite operacional)    │
       │                                                       │                          │
       │                              ┌── fase seguible ───────┤                          │
       │                              │   [snmp_set_tx         │──── SET NTCIP 1211 ─────▶│
       │                              │    accion=              │                         │
       │                              │    request_priority]    │                         │
       │                              │                          │◀──── resp. ────────────│
       │                              │                                                   │  [ctrl_fase_cambio
       │                              │                                                   │   fase=verde,
       │                              │                                                   │   motivo=
       │                              │                                                   │   solicitud_prioridad]
       │                              │                                                   │   (reloj controlador)
       │                              │
       │                              └── fase en ambar/todo rojo ──┐
       │                                 [snmp_set_tx                │
       │                                  accion=en_cola_despeje]    │  (en cola, no se
       │                                 (reloj RSU)                 │   reenvia todavia)
       │                                                             │
       │                                      ... termina el despeje │
       │                                 [snmp_set_tx                │
       │                                  accion=activar_cola_rf06]  │──── SET NTCIP 1211 ─────▶│
       │                                 (reloj RSU, watchdog)       │                          │
       │                                                             │◀──── resp. ──────────────│
       │                                                             │                [ctrl_fase_cambio
       │                                                             │                 fase=verde]
       │
       │◀─── M2 (estado=recibida|concedida|rechazada|cancelada) ────│──── M2 ──────────────────│
       │  [M2_rx, rtt_ms]            │                              │  [M2_tx]
       │  (reloj OBU)                                                │  (reloj RSU)
       │
       │── M1 (1 Hz, mientras el vehiculo sigue en el acceso) ──▶ ... se repite M1_rx / snmp_set_tx
       │                                                           (renueva T_cad, RF-09)
       │
       │── M3 (cruce o cancelacion, motivo) ─────────────────────▶│
       │  [M3_tx]                    │                             │  [M3_rx]
       │                                                            │  [snmp_set_tx accion=clear_priority_m3]
       │                                                            │──── clear_priority ─────▶│
       │                                                            │                [ctrl_fase_cambio
       │                                                            │                 fase=rojo_general,
       │                                                            │                 motivo=liberacion_manual]
       │◀─── M2 (estado=cancelada) ──────────────────────────────│──── M2 ──────────────────│

   Si la OBU deja de renovar M1 y pasan T_cad=3s (RF-09/RNF-03), sin M3:
       RSU  [caducidad, motivo=rnf03_sin_actualizacion(_en_cola)]  -> libera igual, publica M2 "cancelada"
```

### 1.1 Qué registra cada evento, en qué archivo y con el reloj de qué equipo

Todos los eventos usan el mismo formato CSV (`common/events.py`, clase
`EventLogger`): una fila por evento, con `ts_ns` (`time.time_ns()`, epoch +
nanosegundos), `nodo`, `tipo_evento`, `id_solicitud` y `extra_json`. Cada
proceso escribe su **propio** archivo `eventos_<nodo>.csv` en
`resultados/eventos/` (o en `RSU_EVENTOS_DIR`, ver sección 2): no hay un
archivo compartido entre máquinas en tiempo real.

| Evento | Quién lo registra (archivo, función) | Nodo / reloj | Cuándo |
|---|---|---|---|
| `muestra` | `gateway/obu_emulada.py`, método `correr()` | `obu` (laptop) | Al leer cada fila del CSV de trayectoria, **antes** de llamar a `seguidor.actualizar()` (antes de la decisión de geometría). `extra.t_tray_s` identifica la fila. |
| `M1_tx` | `gateway/obu_emulada.py`, método `_m1()` | `obu` (laptop) | Al publicar M1 (nueva solicitud o actualización 1 Hz). `extra`: `seq`, `rsu_id`, `interseccion_id`, `acceso`, `verdad_interseccion`, `verdad_acceso`, `t_tray_s`. |
| `M1_rx` | `agent/rsu_middleware.py`, función `_procesar_m1()` | `rsu_<RSU_ID>` (Raspberry Pi) | Al recibir M1 por MQTT, antes de RF-05/RF-06. `extra.duplicado` marca una reentrega (`seq` ya visto). |
| `snmp_set_tx` | `agent/rsu_middleware.py`, función `procesar_solicitud_prioridad()` (acciones `request_priority`, `en_cola_despeje`, `rechazada`), `verificar_caducidad_periodica()` (`activar_cola_rf06`), `_procesar_m3()` (`clear_priority_m3`) | `rsu_<RSU_ID>` (Raspberry Pi) | Cuando la RSU decide qué hacer con la solicitud: escribirla ya (`request_priority`), encolarla por RF-06 (`en_cola_despeje`), activarla al terminar el despeje (`activar_cola_rf06`, hilo watchdog), rechazarla por RF-05 (`rechazada`), o liberarla por M3 (`clear_priority_m3`). `extra.accion` distingue el caso; `extra.origen` es `"v2i"`, `"snmp"` o `"watchdog"`. |
| `ctrl_fase_cambio` | `controller/controller_emulator.py`, método `_log_si_cambio_locked()` (llamado desde `request_priority()`, `clear_priority()`, `status()` y `_advance_locked()`) | `ctrl_<RSU_ID>` (Raspberry Pi, mismo proceso que el controlador emulado) | Solo cuando la fase visible realmente cambia (no en cada poll). `extra.motivo`: `solicitud_prioridad`, `liberacion_manual`, `caducidad_prioridad`, `ciclo_normal` o `poll`. |
| `M2_tx` | `agent/rsu_middleware.py`, función `_publicar_m2()` | `rsu_<RSU_ID>` (Raspberry Pi) | Al publicar M2 hacia la OBU (Response Topic de MQTT 5). `extra.estado`: `recibida`, `concedida`, `rechazada`, `cancelada`. |
| `M2_rx` | `gateway/obu_emulada.py`, método `_on_message()` | `obu` (laptop) | Al recibir M2. `extra.rtt_ms` = tiempo entre el envío de la M1/M3 correspondiente (Correlation Data) y esta llegada, con el reloj de la propia OBU (`time.monotonic_ns()`, no `time.time_ns()`: no le afecta un salto del reloj de pared). |
| `M3_tx` | `gateway/obu_emulada.py`, método `_m3()` | `obu` (laptop) | Al publicar M3 (cruce o cancelación). `extra.motivo`. |
| `M3_rx` | `agent/rsu_middleware.py`, función `_procesar_m3()` | `rsu_<RSU_ID>` (Raspberry Pi) | Al recibir M3. |
| `caducidad` | `agent/rsu_middleware.py`, función `verificar_caducidad_periodica()` | `rsu_<RSU_ID>` (Raspberry Pi) | Cuando el hilo de vigilancia (RF-09/RNF-03) detecta que la solicitud activa o en cola lleva más de `T_CAD_SEGUNDOS` sin actualizarse, sin que haya llegado M3. |
| `broker_rx` | `scripts/testigo_broker.py` (nuevo, sección 6) | `testigo` (máquina del broker) | Al recibir cualquier mensaje M1/M2/M3 como suscriptor adicional. |

### 1.2 Cómo se correlacionan los eventos

- **`id_solicitud`**: generado por la OBU al emitir el primer M1 de una
  solicitud (`f"{vehiculo_id}-{uuid4().hex[:8]}"`, `gateway/obu_emulada.py`),
  y propagado tal cual por todos los mensajes (M1/M2/M3) y todos los eventos
  de esa solicitud, en las tres máquinas. Es la clave con la que
  `scripts/analisis/lazo_emulado.py` agrupa los eventos de un mismo lazo,
  venga del archivo que venga.
- **`seq`**: contador de secuencia de M1/M3 dentro de una solicitud (parte
  del payload JSON, no de `common/events.py`), usado para: (a) distinguir el
  M1 que *abre* la solicitud (`seq=1`) de sus actualizaciones a 1 Hz; (b)
  detectar duplicados a nivel de aplicación (`_es_duplicado()` en
  `agent/rsu_middleware.py`, marca `extra.duplicado=true` en el evento, no
  descarta la fila del CSV); (c) como *Correlation Data* de MQTT 5
  (`"<id_solicitud>:<seq>"`), que es lo que permite a la OBU emparejar cada
  M2 con el M1/M3 que lo originó sin guardar un diccionario por tema.
- El evento `muestra` es la única excepción: se registra con
  `id_solicitud="-"` porque todavía no existe una solicitud en el instante en
  que se lee la fila (ver sección 6.1). Se empareja con el M1/M3 de esa misma
  fila por `(nodo, t_tray_s)`, no por `id_solicitud`.

### 1.3 Cómo se traen los eventos de la Raspberry Pi

`scripts/pi.sh fetch [host]` copia (`rsync` o `scp`) la carpeta `resultados/`
completa de la Pi a `resultados/<host>/` en la laptop. El análisis
(`scripts/analisis/lazo_emulado.py`) acepta varias carpetas con `--dir`
(se puede repetir) y busca `eventos_*.csv` también en subcarpetas, así que una
corrida local (con la carpeta de la campaña) más los eventos traídos de la Pi
se combinan con:

```bash
python3 scripts/analisis/lazo_emulado.py \
    --dir resultados/lazo_emulado/<corrida> \
    --dir resultados/rsu/eventos
```

## 2. Métricas: fórmula, relojes y confiabilidad

Todas las fórmulas usan los eventos de la sección 1 (`ts_ns` en nanosegundos;
las columnas de `lazo_por_solicitud.csv` ya están en milisegundos). `t0` es
siempre `M1_tx` con `seq=1` de esa solicitud.

| Métrica | Fórmula | Reloj(es) | Confiabilidad |
|---|---|---|---|
| **RTT M1/M2** | `M2_rx.rtt_ms` (ya calculado en la propia OBU: `t_rx − t_tx`, Correlation Data) | Solo el de la OBU | **La más robusta de esta etapa**: no depende de sincronizar relojes entre máquinas. |
| **RTT/2** | `rtt_mediana_ms / 2` por solicitud | Solo el de la OBU | Estimación del tramo de ida (≈ `t_V2I`) sin sincronizar relojes; asume ida y vuelta simétricas, lo que no siempre es cierto (el camino de vuelta puede incluir una consulta `get_status` al controlador que el de ida no tiene). |
| **t_V2I** | `M1_rx(seq 1).ts_ns − t0` | OBU y RSU | Cruza dos relojes: válida solo si están sincronizados (chrony en la Pi, W32Time en la laptop) o si OBU y RSU corren en la misma máquina. |
| **t_RSU** | `decision.ts_ns − M1_rx(seq 1).ts_ns`, con `decision` el primer `snmp_set_tx` con `accion` en {`request_priority`, `en_cola_despeje`} | Solo el de la RSU | Un solo reloj: no depende de sincronización. |
| **t_OBU** | `t0 − muestra.ts_ns` (misma fila, mismo `t_tray_s`) | Solo el de la OBU | Un solo reloj. Requiere el evento `muestra` (sección 6.1); `None` si no está. |
| **t_up** | `broker_rx(M1).ts_ns − t0` | OBU y broker (testigo) | Cruza dos relojes; cota **superior** del tramo real (el testigo agrega su propio procesamiento). Requiere `scripts/testigo_broker.py` corriendo (sección 6.2). |
| **t_down** | `M1_rx(seq 1).ts_ns − broker_rx(M1).ts_ns` | Broker (testigo) y RSU | Ídem: cota superior, cruza dos relojes. |
| **t_NTCIP** | No aislado hoy como evento propio: queda dentro de `t_RSU` (la escritura SNMP ocurre dentro de `procesar_solicitud_prioridad()`, en el mismo tramo que RF-05/RF-06). | — | Ver sección 5: `L = t_adq + t_OBU + t_V2I + t_RSU + t_NTCIP`, con `t_NTCIP` hoy fundido en `t_RSU` por no haber un evento intermedio entre "RSU decide escribir" y "RSU terminó de escribir". |
| **L (RNF-01)** | `decision.ts_ns − t0` (= `t_V2I + t_RSU`, con `decision` igual que en `t_RSU`) | OBU y RSU | Es la latencia que exige RNF-01 ($L \le 1$ s, percentil 95): termina en la **decisión** de la RSU (escribir o encolar), no en que el controlador llegue a verde. |
| **T_desp** | `activacion.ts_ns − cola.ts_ns`, con `cola` el `snmp_set_tx` de `accion=en_cola_despeje` y `activacion` el de `accion=activar_cola_rf06` | Solo el de la RSU | Un solo reloj. Solo existe si la solicitud llegó en ámbar o todo rojo (RF-06); si no se encoló, es `None`. |
| **t_hasta_verde_con_despeje** | `ctrl_fase_cambio(fase=verde).ts_ns − t0` | OBU y controlador | Incluye `T_desp` cuando lo hubo: **no es L**, es aproximadamente `L + T_desp` (más el procesamiento del `request_priority` reenviado). Útil para leer el lazo completo de un vistazo, no para RNF-01. |
| **PDR** | `mensajes M1+M3 únicos recibidos por la RSU (por seq) / M1+M3 enviados` | Solo el de la RSU (cuenta eventos propios) | Un solo reloj. |
| **Tasa de acierto de acceso** | `M1 cuya (interseccion_id, acceso) == (verdad_interseccion, verdad_acceso) / M1 enviados` | — (comparación lógica, no de tiempos) | Depende de la verdad de terreno que trae cada trayectoria sintética (`scripts/trayectorias/generar.py`), no de un GNSS real. |

## 3. Relación con `main.tex` (`ssec:metricas`, ecuación `eq:latencia`)

```
L = t_adq + t_OBU + t_V2I + t_RSU + t_NTCIP  <=  1 s       (RNF-01)
T_act = L + T_desp + T_m                                    (ec. de activación)
```

Qué tramo se mide hoy y cuál no:

| Tramo | ¿Se mide hoy? | Detalle |
|---|---|---|
| `t_adq` (adquisición OBD-II/GNSS) | **No.** | La posición y la velocidad salen de un CSV (`scripts/trayectorias/generar.py`), no de un receptor GNSS ni de un lector OBD-II: no hay un instante de "adquisición" que medir en esta etapa. Ver sección 6.1 para el plan cuando exista `gateway/obd_reader.py`. |
| `t_OBU` | **Sí**, desde esta instrumentación (sección 6.1). | `M1_tx − muestra`. |
| `t_V2I` | Sí, si los relojes están sincronizados o todo corre en una sola máquina. | Incluye `t_up` + `t_broker` + `t_down` (sección 6.2), hoy sin desagregar salvo que el testigo del broker esté corriendo. |
| `t_up` (OBU → broker) | Solo con el testigo del broker corriendo (sección 6.2). | Cota superior. |
| `t_broker` (procesamiento interno de Mosquitto) | **No instrumentado.** | Ver sección 6.3: no es medible con un cliente MQTT, solo con una captura de paquetes en la máquina del broker. |
| `t_down` (broker → RSU) | Solo con el testigo del broker corriendo (sección 6.2). | Cota superior. |
| `t_RSU` | Sí. | Incluye RF-05 (clase), RF-06 (límite operacional) y la escritura SNMP (`t_NTCIP`, sin aislar). |
| `T_desp` | Sí, cuando la solicitud se encola (RF-06). | Se reporta **aparte** de `L`, conforme a `T_act = L + T_desp + T_m`. |
| `T_m` (margen de seguridad) | No es una medición: es un parámetro de diseño (`ssec:*` de main.tex), no un evento del banco. | — |

## 4. Sincronización de relojes

- **Raspberry Pi (RSU y controlador emulado):** `chrony`, configurado contra
  `time.cloudflare.com` (ver `scripts/chrony/rsu-lab.conf`).
- **Laptop (OBU y broker):** servicio `W32Time` de Windows, misma referencia
  (`time.cloudflare.com`).
- **`scripts/pi.sh clock [host]`** consulta el desfase de ambas máquinas
  contra esa misma referencia **antes de cada campaña** (`chronyc sources -v`
  en la Pi, `w32tm /stripchart` en la laptop) y lo deja en el log de la
  campaña.
- El desfase medido se traduce directamente en incertidumbre de los tramos
  que cruzan reloj (`t_V2I`, `t_up`, `t_down`, `t_OBU` si la muestra y el M1
  estuvieran en máquinas distintas, lo que no ocurre: ambos son de la OBU).
  Si la Pi está desfasada `d_rsu` ms y la laptop `d_obu` ms respecto de la
  misma referencia, el error máximo de `t_V2I` es `|d_rsu − d_obu|` ms. La
  bitácora del 19/10 registró `Pi −8.7 ms, laptop +7.5 a +8.5 ms`
  (≈16 ms de desfase entre ambas) **antes** del ajuste de Mosquitto descrito
  en la sección 5; con un `t_V2I` del orden de unos pocos ms, ese desfase es
  comparable a la propia magnitud medida, no despreciable.
- Por eso **RTT** (sección 2) es la métrica preferida para reportar sin
  reservas: un solo reloj, sin este problema. **RTT/2** es la forma de
  aproximar el tramo de ida con la misma garantía, cuando no se puede abrir
  el RTT en sus partes con relojes sincronizados de confianza.

## 5. Ajustes que afectan la medición

- **`set_tcp_nodelay true` en Mosquitto** (algoritmo de Nagle desactivado):
  sin este ajuste, el RTT M1/M2 medido en el banco local fue de **~44 ms**
  (con un `t_V2I` de apenas 0.5 ms, es decir, el Nagle del *socket* de salida
  de M2 agregaba ~40 ms por sí solo); con el ajuste bajó a **~2.4 ms**
  (`docs/bitacora/2026-10-19_lazo-obu-emulada.md`, sección "Problemas y
  solución"; configuración en `docs/LAZO_EMULADO.md`, sección "Antes de
  medir"). **Hay que aplicarlo en el broker antes de cualquier campaña que
  vaya a reportarse**, y declararlo en la configuración del Capítulo IV.
- **`--factor 1`** (tiempo real) en `gateway/obu_emulada.py` y
  `scripts/campanas/lazo_emulado.py`: a `--factor 4` la solicitud podía caer
  en ámbar y el vehículo cruzar antes de que terminara el despeje
  (bitácora 19/10). Las campañas que se vayan a reportar deben correrse a
  `--factor 1`; un factor mayor sirve solo para iterar rápido durante el
  desarrollo, no para medir.

## 6. Tramos pendientes y cómo se medirán

### 6.1 `t_OBU` (de la muestra al envío del M1) — YA INSTRUMENTADO

`gateway/obu_emulada.py` registra ahora un evento `muestra` (`EVT_MUESTRA`,
`common/events.py`) en el instante en que se lee cada fila de la trayectoria,
**antes** de llamar a `seguidor.actualizar()` (antes de la decisión de
geometría). `t_OBU = M1_tx.ts_ns − muestra.ts_ns`, con el reloj de la propia
OBU, emparejando por `(nodo, t_tray_s)` — ver `scripts/analisis/lazo_emulado.py`,
función `_indice_muestras()`. Esto ya se puede medir en la próxima campaña.

### 6.2 `t_up` y `t_down` (OBU → broker y broker → RSU) — YA INSTRUMENTADO

`scripts/testigo_broker.py` (nuevo) es un cliente MQTT que corre en la
**misma máquina que el broker**, se suscribe a `rsu/#` y `veh/#`, y registra
un evento `broker_rx` (`EVT_BROKER_RX`) con la hora de llegada de cada
mensaje (`id_solicitud` y `seq`/`seq_ref` tomados del JSON). Como comparte
reloj con el broker:

```
t_up   ~= broker_rx(M1) - M1_tx        (reloj OBU, reloj broker)
t_down ~= M1_rx         - broker_rx(M1) (reloj broker, reloj RSU)
```

El testigo agrega un suscriptor más al broker, y su propio tiempo de entrega
(deserializar el JSON, escribir el evento) se suma al camino medido: **`t_up`
y `t_down` calculados así son una cota superior del tiempo real de cada
tramo**, nunca una subestimación. `scripts/analisis/lazo_emulado.py` ya
calcula ambos cuando encuentra eventos `broker_rx` en los `--dir` indicados
(`None` si no los encuentra, como hasta ahora).

Para que `t_up` represente el tramo celular real (y no un valor cercano a
cero): **la OBU debe correr en un equipo distinto al del broker, conectado
por datos móviles** (el teléfono con Termux + Tailscale, u otra PC con el
hotspot del celular) — no en la misma laptop que aloja Mosquitto. Hoy, con la
OBU corriendo en la misma laptop que el broker (ver bitácora 19/10), `t_up`
sería prácticamente cero y no representaría el enlace celular que la tesis
caracteriza (`ssec:sel_v2i`).

### 6.3 `t_broker` (procesamiento interno de Mosquitto) — NO INSTRUMENTABLE así

No es medible con un cliente MQTT, ni con el testigo de la sección 6.2: un
suscriptor solo ve el mensaje después de que Mosquitto ya lo reenvió, nunca el
instante exacto de entrada y salida dentro del propio broker. Mientras tanto,
`t_broker` queda incluido dentro de `t_up + t_down` (sección 3). Como
alternativa, se puede estimar con una captura de paquetes (Wireshark) corrida
en la máquina del broker, comparando el instante del paquete `PUBLISH` que
entra (OBU → broker) con el del `PUBLISH` que sale (broker → RSU) del mismo
mensaje — no implementado en este repositorio.

### 6.4 `t_adq` (adquisición OBD-II / GNSS) — PENDIENTE, plan documentado

No aplica mientras la posición y la velocidad salgan de un CSV
(`scripts/trayectorias/generar.py`). Plan para cuando exista
`gateway/obd_reader.py` (lectura real por `python-OBD`, PID `0x0D`, 1 Hz):
registrar un evento `obd_pedido` al enviar la consulta al adaptador ELM327 y
`obd_respuesta` al recibirla, con `t_adq = obd_respuesta.ts_ns −
obd_pedido.ts_ns` (un solo reloj, el de la OBU). Para el componente GNSS de
la posición, usar la diferencia entre la marca de tiempo del *fix* que
reporta el receptor y la hora de lectura de la aplicación. Ninguno de los dos
eventos existe todavía en el código: **TODO** antes de reportar `t_adq` en el
Capítulo IV.

## 7. Cómo reproducir una medición

```bash
# 1. Generar trayectorias y correr una campaña (tiempo real, 5 repeticiones
#    por escenario por defecto son 3; ajustar con --repeticiones):
python3 scripts/campanas/lazo_emulado.py --broker-host <host-del-broker> \
    --repeticiones 5 --factor 1

# 2. (Opcional, para t_up/t_down) correr el testigo en la MISMA maquina que
#    el broker, ANTES del paso 1, apuntando RSU_EVENTOS_DIR a la carpeta que
#    va a crear la campana (o moviendo despues su eventos_testigo.csv ahi):
RSU_EVENTOS_DIR=resultados/lazo_emulado/<corrida> python3 scripts/testigo_broker.py

# 3. Si la RSU corre en la Raspberry Pi, traer sus eventos (y los del
#    controlador) a la laptop:
scripts/pi.sh fetch

# 4. Analizar (combina la carpeta de la campana con los eventos traidos de
#    la Pi; agregar tantos --dir como carpetas con eventos_*.csv haga falta):
python3 scripts/analisis/lazo_emulado.py \
    --dir resultados/lazo_emulado/<corrida> \
    --dir resultados/rsu/eventos
```

La salida queda en `<corrida>/lazo_por_solicitud.csv` (una fila por
solicitud, todas las métricas de la sección 2) y `<corrida>/lazo_resumen.json`
(agregado: mediana, p95, media, máximo de cada métrica, y si `L` cumple RNF-01
en el percentil 95).

**Estado al escribir este documento:** no existe todavía ninguna corrida en
`resultados/lazo_emulado/` (el único recorrido real registrado hasta ahora,
descrito en `docs/bitacora/2026-10-19_lazo-obu-emulada.md`, se ejecutó a mano
con `gateway/obu_emulada.py` directamente, sin pasar por
`scripts/campanas/lazo_emulado.py`, así que no quedó guardado con esta
estructura de carpeta). Los números de esa bitácora (RTT M1/M2 de 14.2 ms y
11.1 ms, por ejemplo) son de un solo recorrido de demostración, no de una
campaña: no deben reportarse como una caracterización estadística en el
Capítulo IV. Para tener una corrida real con la que completar la sección de
resultados hace falta ejecutar el procedimiento de esta sección contra un
broker real (Mosquitto, con `set_tcp_nodelay true`) y una RSU real (Pi o
banco local, `docs/LAZO_EMULADO.md`); no se generaron números nuevos para
este documento.
