# Demo en vivo para el asesor: lazo de priorización con OBU emulada

## La forma simple: un solo comando

En Git Bash, **desde cualquier carpeta**:

```bash
/e/Tesis/ntcip_middleware/scripts/demo_lazo.sh
```

El script se ubica solo en la carpeta del repositorio y corre las pruebas una
por una. En cada una muestra el comando que ejecuta, explica qué demuestra y,
al final, una **línea de tiempo en español** que junta lo que hicieron la OBU
(laptop), la RSU y el controlador (Raspberry Pi), en orden. Entre prueba y
prueba espera un Enter.

| Prueba | Qué muestra |
|---|---|
| 0 | Estado del banco: Tailscale, Mosquitto, servicios de la Pi, conexión de la RSU al broker y **a qué temas está suscrita** |
| 1 | Que la RSU solo escucha su tema: un M1 a mano en `rsu/1` (reacciona) y en `rsu/2` (no pasa nada) |
| 2 | NTCIP 1202 por SNMPv3, traducido: verde mínimo, ámbar, todo rojo y qué luz está encendida |
| 3 | Lazo completo: solicitud, espera de despeje, verde, cancelación al cruzar |
| 4 | Dos intersecciones seguidas (problema A/B) |
| 5 | Clase no reconocida (RF-05) |
| 6 | Caducidad (RF-09): la OBU se corta sola al recibir el verde |
| 7 | Vehículo detenido 20 s en la cola |
| 8 | Pruebas unitarias |
| 9 | Diagrama de secuencia de la última solicitud (se abre la imagen) |

Opciones: `--solo 3` (una sola prueba), `--desde 4` (de la 4 en adelante),
`--sin-pausas`. Todo queda guardado en `evidencia/demo_lazo_<fecha>/`, una
prueba por archivo. Al final imprime un resumen con ✔ o ✘ por prueba.

Las pruebas 3 a 7 tardan entre 1 y 2 minutos cada una (la primera solicitud sale
a los ~40 s del recorrido). Si el tiempo es corto: `--solo 0`, `--solo 3`,
`--solo 6`.

El resto de este documento es la versión manual, comando por comando, por si
hace falta mostrar algo por separado.

---

## 0. Antes de la reunión (15 minutos antes)

Encender la Raspberry Pi al menos 10 minutos antes, para que su reloj (chrony)
se estabilice.

**PowerShell (admin):**

```powershell
Get-Service mosquitto                 # debe decir Running
w32tm /resync /force
```

**Git Bash:**

```bash
cd /e/Tesis/ntcip_middleware
tailscale status                      # laptopricardoub y rsu-01 en la lista
scripts/check_pi.sh                   # "OK: la Pi responde por SSH"
scripts/pi.sh status agent            # active (running)
scripts/pi.sh status controller       # active (running)
ssh rsu "journalctl -u rsu-agent -n 30 --no-pager" | grep "Conectado al broker"
scripts/pi.sh clock
```

Si `agent` o `controller` no están activos:

```bash
scripts/pi.sh start controller
scripts/pi.sh start agent
```

Si en el log de `rsu-agent` no aparece `Conectado al broker MQTT (100.121.77.97:1883)`:
revisar que Mosquitto esté corriendo en la laptop y reiniciar con
`scripts/pi.sh restart agent`.

## Ventanas que conviene tener abiertas

Abrir **4 ventanas de Git Bash**, todas en `/e/Tesis/ntcip_middleware`, y
dejarlas lado a lado:

| Ventana | Qué muestra | Comando |
|---|---|---|
| A | La RSU en vivo (Raspberry Pi) | `ssh -t rsu "journalctl -u rsu-agent -f -n 0"` |
| B | El controlador en vivo (Raspberry Pi) | `ssh -t rsu "journalctl -u rsu-controller -f -n 0"` |
| C | Los mensajes que pasan por el broker | ver abajo |
| D | Donde se lanzan las pruebas | — |

Ventana C (muestra M1, M2 y M3 tal como viajan por el broker):

```bash
"/c/Program Files (x86)/mosquitto/mosquitto_sub.exe" -h 127.0.0.1 -v -t 'rsu/#' -t 'veh/#'
```

### Vista visual: panel "Lazo V2I en vivo"

Para la reunión conviene proyectar el panel en lugar de (o además de) las
ventanas A a C. En una ventana de Git Bash aparte:

```bash
.venv/Scripts/streamlit.exe run centro_control/panel/app.py
```

Se abre en el navegador (http://localhost:8501). En la barra lateral, elegir
**Lazo V2I en vivo**. Muestra, actualizándose solo:

- Mapa con las dos intersecciones reales, su geocerca R_g (círculo azul), su
  radio R_i (anillo gris), los cuatro accesos y la trayectoria. El vehículo es
  un punto que cambia de color: gris sin solicitud, naranja recibida, verde
  concedida, rojo rechazada. El acceso asignado se pinta de naranja.
- Semáforo de la RSU 1, leído por SNMPv3 (NTCIP 1202) cada 0,5 s.
- Ficha de la OBU: velocidad, distancia, intersección y acceso, solicitud,
  `seq`, último estado M2 y RTT.
- Lista de mensajes que pasan por el broker (M1, M2, M3) con su hora.

La posición del vehículo **no** viaja por MQTT: la OBU emulada la escribe en
un archivo local (`resultados/obu_vivo/estado.json`) y el panel lo lee. Así se
respeta la minimización de datos de la tesis.

Requisito: en `centro_control/panel/.env`, `SNMP_HOST=rsu-01` (ya no la IP de
casa) y `MQTT_BROKER_HOST=127.0.0.1`.

---

## Prueba 1. Arquitectura: broker central y RSU conectada por Tailscale

**Qué se demuestra:** la RSU no aloja el broker; se conecta como cliente al
broker central (esquema E2+E4), por una conexión saliente que funcionaría
igual detrás del CGNAT de una red 4G.

Ventana D:

```bash
tailscale status
ssh rsu "journalctl -u rsu-agent -n 30 --no-pager" | grep -E "Escuchando|Conectado"
```

**Qué señalar:** `Conectado al broker MQTT (100.121.77.97:1883), reason_code=Success`
y los temas `rsu/1/solicitudes` (M1/M3) y `rsu/v2i/solicitud_prioridad` (legado).

## Prueba 2. Supervisión NTCIP 1202 por SNMPv3 desde el centro de control

**Qué se demuestra:** el centro de control lee los objetos reales de NTCIP 1202
(tiempos y estado de fase) con SNMPv3 autenticado y cifrado, desde fuera de la
red local de la RSU.

Ventana D:

```bash
.venv/Scripts/python.exe centro_control/software_gestion.py walk --host rsu-01 --port 1161 \
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 \
  1.3.6.1.4.1.1206.4.2.1 2>&1
```

**Qué señalar:**

| OID (final) | Objeto | Valor esperado |
|---|---|---|
| `...1.2.1.4.1` | phaseMinimumGreen | 8 (s) |
| `...1.2.1.8.1` | phaseYellowChange | 30 (décimas = 3,0 s) |
| `...1.2.1.9.1` | phaseRedClear | 20 (décimas = 2,0 s) |
| `...1.4.1.2.1` / `.3.1` / `.4.1` | phaseStatusGroupReds / Yellows / Greens | uno de los tres en 1 |

Repetir el comando unos segundos después: el bit de estado cambia porque el
controlador sigue su ciclo.

## Prueba 3. Lazo completo: emisión, espera de despeje, verde y cancelación

**Qué se demuestra:** RF-11 (identificación de intersección y acceso), RF-03
(emisión en la geocerca y actualización a 1 Hz), RF-06 (no se interrumpe un
intervalo de seguridad), RF-07 (traducción a NTCIP 1211), RF-08 (M2 con el
estado real de la fase) y RF-04 (cancelación al cruzar).

Ventana D:

```bash
.venv/Scripts/python.exe gateway/obu_emulada.py --broker-host 127.0.0.1 \
  --trayectoria resultados/trayectorias/transversal_a_s1.csv
```

Dura unos 75 s. La primera solicitud sale a los ~40 s, cuando el vehículo
entra en la geocerca de 150 m. Mientras tanto se puede explicar que la OBU
recibe una muestra por segundo y que la posición nunca sale de ella.

**Qué señalar en cada ventana:**

| Ventana | Línea | Qué significa |
|---|---|---|
| D (OBU) | `M1 nueva -> rsu/1 OSM-C24/O a ~142 m` | la OBU eligió la intersección y el acceso, y emitió M1 |
| C (broker) | `rsu/1/solicitudes {"tipo": "M1", ... "seq": 1}` | M1 sin posición: solo intersección, acceso, clase, velocidad, hora y contador |
| A (RSU) | `en cola (readyQueued) ... (RF-06)` | si llegó en ámbar o todo rojo, la RSU espera el fin del despeje |
| B (controlador) | `Fase -> verde (solicitud_prioridad)` | la prioridad se aplicó |
| D (OBU) | `estado=recibida` → `estado=concedida fase=verde` | M2 con el estado real; el verde se avisa apenas ocurre |
| C (broker) | `seq` sube de 1 en 1 cada segundo | actualizaciones a 1 Hz (RNF-02) |
| D (OBU) | `M3 -> rsu/1 (cruce)` | la intersección quedó detrás: cancelación |
| B (controlador) | `Fase -> rojo_general (liberacion_manual)` | el controlador vuelve a su ciclo |
| D (OBU) | `Fin: M1 enviados=13, M3 enviados=1, M2 recibidos=15` | cada mensaje tuvo su respuesta |

Si la solicitud llega con el controlador ya en verde, no aparece la línea de
espera: se concede de inmediato.

## Prueba 4. Dos intersecciones seguidas (problema A/B) y enrutamiento por tema

**Qué se demuestra:** después de cruzar la intersección A, la OBU la descarta
porque quedó detrás y pasa a la siguiente (B), aunque A siga más cerca. Cada
solicitud viaja solo al tema de su intersección.

Ventana D:

```bash
.venv/Scripts/python.exe gateway/obu_emulada.py --broker-host 127.0.0.1 \
  --trayectoria resultados/trayectorias/avenida_ab_s1.csv
```

Dura unos 2 minutos.

**Qué señalar:**

- `M1 nueva -> rsu/1 OSM-C24/S`, luego `M3 -> rsu/1 (cruce)`.
- Unos 25 s después: `M1 nueva -> rsu/2 OSM-C902/S`. En la ventana C, los
  mensajes pasan a `rsu/2/solicitudes`.
- Las solicitudes a `rsu/2` **no reciben M2**: no hay una RSU 2 desplegada.
  Muestra que el broker entrega cada mensaje solo a quien está suscrito a ese
  tema; la RSU 1 no las ve.

### 4b (opcional). Segunda RSU en la laptop

Para cerrar también las solicitudes a la intersección B, abrir 2 ventanas más
de Git Bash **antes** de lanzar la prueba 4:

```bash
# ventana E: controlador de la RSU 2
RSU_ID=2 RSU_EVENTOS_DIR=resultados/rsu2 .venv/Scripts/python.exe controller/controller_emulator.py --port 9001

# ventana F: middleware de la RSU 2, conectado al mismo broker
RSU_ID=2 RSU_EVENTOS_DIR=resultados/rsu2 SNMP_PORT=1162 CONTROLLER_PORT=9001 MQTT_BROKER_HOST=127.0.0.1 \
  .venv/Scripts/python.exe agent/rsu_middleware.py
```

Ahora la segunda solicitud también recibe M2 y se concede. Detener las
ventanas E y F con Ctrl+C al terminar.

## Prueba 5. Rechazo de una clase no reconocida (RF-05)

**Qué se demuestra:** la RSU solo acepta clases de vehículo de emergencia; una
clase no reconocida nunca llega al controlador.

Ventana D:

```bash
.venv/Scripts/python.exe gateway/obu_emulada.py --broker-host 127.0.0.1 --clase-tipo 5 \
  --trayectoria resultados/trayectorias/transversal_a_s1.csv
```

**Qué señalar:**

- OBU: `M2 <- ... estado=rechazada`; desde ahí la OBU deja de actualizar esa solicitud.
- RSU (ventana A): `M1 de 'ses-...' rechazado (clase_no_reconocida)`.
- Controlador (ventana B): **no** aparece `solicitud_prioridad`.

## Prueba 6. Caducidad: el vehículo deja de transmitir (RF-09)

**Qué se demuestra:** si la OBU pierde la conexión o se apaga a mitad de la
aproximación, la RSU libera el controlador sola a los 3 s, sin esperar M3.

Ventana D: lanzar la prueba 3 y, **apenas aparezca `estado=concedida`**,
presionar **Ctrl+C**.

```bash
.venv/Scripts/python.exe gateway/obu_emulada.py --broker-host 127.0.0.1 \
  --trayectoria resultados/trayectorias/transversal_a_s1.csv
```

**Qué señalar** (unos 3 s después del Ctrl+C):

- RSU (ventana A): `Solicitud caducada por falta de actualizacion (RF-09, T_cad=3s ...) -> liberando prioridad`.
- Controlador (ventana B): `Prioridad liberada manualmente, vuelve al ciclo normal`.
- Broker (ventana C): `veh/.../respuestas ... "estado": "cancelada", "motivo": "caducidad"`.

## Prueba 7. Vehículo detenido en la cola

**Qué se demuestra:** el caso que motiva la tesis. Un vehículo detenido 20 s a
80 m de la intersección mantiene su solicitud: cada M1 renueva la prioridad en
el controlador, y el verde se sostiene hasta que cruza.

Ventana D:

```bash
.venv/Scripts/python.exe gateway/obu_emulada.py --broker-host 127.0.0.1 \
  --trayectoria resultados/trayectorias/detenido_en_cola_s1.csv
```

Dura unos 95 s.

**Qué señalar:**

- Controlador (ventana B): `Prioridad solicitada por 'ses-...'` cada segundo,
  sin volver al ciclo normal mientras el vehículo está detenido.
- OBU: `concedida` se mantiene unos 30 s, hasta `M3 -> rsu/1 (cruce)`.
- Pregunta abierta para el asesor: ¿debe existir un tope máximo de verde
  sostenido para un vehículo detenido? (TODO de `ssec:emision`).

## Prueba 8. Medición: campaña corta y análisis

**Qué se demuestra:** cómo se obtienen las métricas del Capítulo 4 (tasa de
entrega, ida y vuelta M1/M2, tiempo hasta el verde, acierto de acceso).

Campaña corta (un escenario, una repetición, ~1,5 min):

```bash
.venv/Scripts/python.exe scripts/campanas/lazo_emulado.py --broker-host 127.0.0.1 \
  --escenarios transversal_a --repeticiones 1
```

Traer los eventos de la RSU y analizar (usar el nombre de carpeta que imprime
la campaña al terminar):

```bash
scripts/pi.sh fetch
ls resultados/lazo_emulado/
.venv/Scripts/python.exe scripts/analisis/lazo_emulado.py \
  --dir resultados/lazo_emulado/<corrida> --dir resultados/rsu/eventos
```

**Qué señalar:**

| Línea | Qué significa |
|---|---|
| `PDR M1/M3: 1.000 (14/14)` | todos los mensajes únicos enviados llegaron a la RSU |
| `Acierto de acceso: 1.000` | la OBU eligió la intersección y el acceso correctos |
| `RTT M1/M2 ... mediana=...` | ida y vuelta medida solo con el reloj de la OBU |
| `t_V2I` | cruza dos relojes: tiene el margen de ~16 ms del desfase medido |
| `M1 -> verde en el controlador` | incluye la espera del despeje si llegó en ámbar o todo rojo |

La campaña completa (3 escenarios × 5 repeticiones, ~30 min) se corre fuera de
la reunión con `--repeticiones 5`.

**Diagrama de secuencia del recorrido** (figura para la tesis, una por
solicitud, con la fase real del controlador debajo):

```bash
.venv/Scripts/python.exe -m pip install matplotlib      # solo la primera vez
.venv/Scripts/python.exe scripts/analisis/secuencia_recorrido.py \
  --dir resultados/lazo_emulado/<corrida> --dir resultados/rsu/eventos --todas
```

Las imágenes quedan en `evidencia/secuencias/`. El título de cada una resume lo
que pasó (por ejemplo, "Verde concedido 5,0 s después del primer M1: esperó el
fin del despeje (RF-06)").

## Prueba 9. Pruebas unitarias

```bash
.venv/Scripts/python.exe -m pip install pytest      # solo la primera vez
.venv/Scripts/python.exe -m pytest -q tests
```

Debe terminar en `29 passed`. Cubren la codificación OER de NTCIP 1211, RF-05,
RF-06, RF-09, la geometría de asignación (problema A/B, carril opuesto,
histéresis) y la cancelación.

---

## Si algo falla durante la reunión

| Síntoma | Qué hacer |
|---|---|
| `ssh rsu` no responde | `tailscale status`; si `rsu-01` aparece *offline*, revisar que la Pi esté encendida y con internet |
| La OBU no recibe ningún M2 | Ventana A: ¿la RSU dice `Conectado al broker`? Si no, `scripts/pi.sh restart agent` |
| `Connection refused` al broker | PowerShell (admin): `Restart-Service mosquitto` |
| El `walk` no devuelve nada | `scripts/pi.sh status agent`; el puerto es 1161 |
| Todo falla | Plan B: mostrar `evidencia/2026-10-19_*.txt` y su versión en PNG, y la bitácora `docs/bitacora/2026-10-19_lazo-obu-emulada.md` |

## Al terminar

Detener las ventanas A, B y C con Ctrl+C. Para guardar la evidencia de lo que
se mostró:

```bash
ssh rsu "journalctl -u rsu-agent --since '30 min ago' --no-pager" > evidencia/AAAA-MM-DD_demo-asesor_rsu.txt
ssh rsu "journalctl -u rsu-controller --since '30 min ago' --no-pager" > evidencia/AAAA-MM-DD_demo-asesor_controlador.txt
```
