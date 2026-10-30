# Consola web del centro de control

Aplicación propia (FastAPI + JavaScript sin paso de compilación) para
supervisar el banco de pruebas en vivo y revisar las campañas de medición
(OE5). Pensada para la demo con el asesor y para la sustentación.

**No reemplaza** `centro_control/panel/` (Streamlit): ese panel se mantiene
tal cual. La consola es la vista de grado "industrial" para mostrar y
compartir; el panel de Streamlit sigue siendo la referencia rápida en
Python puro.

## Instalar

Desde la raíz del repo, con el entorno virtual activado:

```bash
pip install -r centro_control/requirements.txt   # agrega fastapi y uvicorn
```

(`requirements.txt` de la raíz y de `agent/` no cambian: la consola corre
en la laptop/PC, no en la Raspberry Pi.)

## Configurar

```bash
cp consola/.env.example consola/.env
```

Editar `consola/.env` si la RSU, el broker o el alias SSH no son los de
laboratorio por defecto (ver `consola/.env.example`). `consola/.env` no se
commitea.

## Arrancar

```bash
python consola/servidor.py
```

Abre `http://127.0.0.1:8080/` en el navegador por defecto (y, si no lo
abre solo, hay que abrirlo a mano). **Escucha solo en 127.0.0.1**: no es
accesible desde otra máquina de la red, a propósito — ver la nota de
seguridad al final.

Si la Raspberry Pi o el broker no responden, la consola sigue
funcionando: los indicadores de la barra superior lo muestran (punto rojo
+ texto), no se cae ni bloquea el resto de la pantalla.

## Arquitectura (resumen)

```
consola/servidor.py          punto de entrada, arranca uvicorn
consola/backend/
  api.py                     rutas FastAPI + SSE (/sse)
  estado.py                  foto en memoria de todo lo que se muestra
  bus.py                     difusor de eventos hacia los clientes SSE
  mqtt_cliente.py            suscriptor MQTT 5 (rsu/#, veh/#, obu/#, servidor/+/respuestas)
  mision.py                  misión vista desde el broker: MI/MR/MP/ME/M1/M2/M3/MF -> estado por RSU + línea de tiempo
  snmp_poller.py             sondeo SNMPv3 de UNA RSU (semáforo/PRS/tiempos), 1 solo hilo
  snmp_multi.py              sondeo SNMPv3 de VARIAS RSU (fase NTCIP 1202, ~1 Hz c/u), modo multi-RSU
  demo_rsu.py                registro de RSU + estado.json del lanzador -> RSU a mostrar y su puerto SNMP
  obu_local.py               LEGADO: lee resultados/obu_vivo/estado.json (ya no lo escribe nadie)
  eventos_remotos.py         ssh tail eventos_rsu_<id>.csv / eventos_ctrl_<id>.csv
  estado_banco.py            tailscale, systemctl, journalctl, pi.sh clock
  pruebas.py                 lanza gateway/obu_emulada.py como subproceso
  analisis.py                reusa scripts/analisis/*.py para la pantalla de ensayos
  mapa.py                    proyecta el registro (gateway/geometria.py) + calles del grafo OSM de data/
  registro_comandos.py       auditoría -> resultados/consola/registro_comandos.jsonl
consola/static/              HTML + CSS + JS (sin build, sin CDN)
```

No se duplica ninguna lógica de transporte ni de cálculo: todo lo anterior
llama a los módulos ya existentes del repo (`centro_control/software_gestion.py`,
`centro_control/panel/ntcip_objetos.py`, `gateway/geometria.py`,
`scripts/analisis/lazo_emulado.py`, `scripts/analisis/graficos_campana.py`,
`common/events.py`, `common/traduccion_eventos.py`).

**Nota sobre graficos:** se dibujan en SVG nativo (`consola/static/js/graficos.js`),
sin ninguna librería de terceros. Se decidió así en vez de vendorizar
uPlot/Chart.js porque las cuatro figuras necesarias (CDF, cajas, dispersión,
serie) son simples y esto evita cualquier dependencia de red o de licencia
de un archivo vendorizado — la consola sigue funcionando sin internet por
construcción, no porque se haya descargado algo una vez.

### Dato clave: pysnmp + asyncio en Windows

`snmp_poller.py` corre en **un solo hilo** (no uno por cadencia) a propósito:
`pysnmp.hlapi` crea y cierra su propio event loop de asyncio en cada
GET/WALK. En Windows (`ProactorEventLoop`, el que usa uvicorn por defecto),
dos llamadas concurrentes desde hilos distintos corrompen el "self-pipe"
del loop del proceso y terminan tumbando el servidor entero. Además,
`consola/servidor.py` fuerza `asyncio.WindowsSelectorEventLoopPolicy()`
antes de arrancar uvicorn, por el mismo motivo (confirmado en pruebas
locales contra una RSU real: sin este cambio, el servidor se caía a los
pocos minutos con `OSError: [WinError 87]` dentro de asyncio). Si se porta
esto a Linux, este problema no debería reaparecer (no hay ProactorEventLoop
ahí), pero conviene no deshacer la serialización sin volver a probar un
rato largo contra SNMP real.

## Qué muestra cada pantalla y de dónde sale cada dato

### 1. Monitoreo en vivo

| Elemento | Fuente |
|---|---|
| Indicadores de la barra superior (broker, RSU, SNMPv3, controlador, relojes) | `estado_banco.py` (cada 15 s) + `mqtt_cliente.py` (conexión) + `snmp_poller.py` (último error) |
| Fila de métricas (solicitudes activas, L, RTT, PDR, fase) | Cálculo aproximado en el navegador a partir de los eventos SSE de esta sesión (`monitoreo.js`) — **no** es la métrica con rigor estadístico; esa está en "Ensayos y métricas" |
| Mapa en vivo | `GET /api/mapa` (registro, una vez) + `GET /api/mapa/calles` (calles del grafo OSM de `data/`) + eventos SSE `mision` (ruta MR), `mision_pos` (MP), `rsu_fase` y `rsu_prioridad`; ver "Demo con varias RSU" |
| Semáforo (NTCIP 1202) | evento SSE `snmp_semaforo`, cada 0.5 s |
| priorityRequestTable (NTCIP 1211) | evento SSE `snmp_prs`, cada 2 s |
| Ficha de la OBU | evento SSE `obu` |
| Tráfico MQTT | evento SSE `mqtt` (todo lo publicado en `rsu/#` y `veh/#`) |
| Eventos del lazo | evento SSE `evento_lazo`, traducido por `common/traduccion_eventos.py` a partir de `eventos_rsu_<id>.csv` / `eventos_ctrl_<id>.csv` traídos por SSH cada 3 s |
| Botones de prueba | `POST /api/pruebas/<nombre>/iniciar` lanza `gateway/obu_emulada.py` como subproceso (mismas trayectorias que `scripts/demo_lazo.sh`); "Detener" lo mata |

### 2. Ensayos y métricas

Lee `resultados/lazo_emulado/<corrida>/` (generadas con
`scripts/campanas/lazo_emulado.py`). Los números y gráficos (CDF del RTT,
cajas por tramo, espera del despeje, serie de RTT) usan **las mismas
funciones** que `scripts/analisis/lazo_emulado.py` y
`scripts/analisis/graficos_campana.py` — la consola solo las llama y
dibuja el resultado en SVG. "Exportar figuras (PDF)" corre
`graficos_campana.py` como subproceso y deja los archivos en
`<corrida>/figuras/` (PDF, PNG y la tabla LaTeX), igual que hacerlo a
mano. "Comparar condiciones" llama a `/api/ensayos/comparar` con dos o
más corridas etiquetadas y calcula el intervalo de Wilson al 95% del PDR
(fórmula estándar, sin dependencias nuevas).

### 3. Registro de comandos

Cada SNMP GET/WALK, mensaje MQTT observado, `ssh` corrido y subproceso
lanzado por la consola se registra con
`consola/backend/registro_comandos.py` en
`resultados/consola/registro_comandos.jsonl` (no se versiona, ver
`.gitignore`; se puede descargar desde la pantalla). También se registran
ahí las órdenes que la RSU le da al controlador (`request_priority`,
`activar_cola_rf06`, `clear_priority_m3`, `rechazada`, `caducidad`),
leídas de los mismos eventos que traduce la pantalla de monitoreo.

## Demo con varias RSU

Sirve para ver una misión completa sobre varias intersecciones desde una
sola pantalla, sin una ventana por RSU ni por controlador.

**1. Levantar todo** (un controlador emulado y una RSU por intersección,
más el servidor central y la consola, en segundo plano y sin ventanas;
Mosquitto ya debe estar corriendo):

```bash
powershell -ExecutionPolicy Bypass -File scripts\demo\lanzar_rsus.ps1 -Registro E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_hospital_nino.json -ConServidor -ConConsola
```

La consola abre el navegador en `http://127.0.0.1:8080/`, directamente en
la pantalla **Misión (varias RSU)**.

**2. Lanzar la OBU emulada:**

```bash
.venv\Scripts\python.exe gateway\obu_emulada.py --broker-host 127.0.0.1 --factor 4 --trayectoria E:\Tesis\ntcip_app\app_obu\pruebas\trayectoria_hospital_nino.csv
```

**3. Detener todo:**

```bash
powershell -ExecutionPolicy Bypass -File scripts\demo\detener_rsus.ps1
```

### Qué hace el lanzador (`scripts/demo/lanzar_rsus.ps1`)

- Lee el registro de RSU y, por cada intersección, levanta un
  `controller/controller_emulator.py` y un `agent/rsu_middleware.py` con
  `Start-Process -WindowStyle Hidden`. Les pasa las mismas variables de
  entorno que esos programas ya leen (`RSU_ID`, `SNMP_PORT`,
  `CONTROLLER_PORT`, `MQTT_BROKER_HOST/PORT`, `RSU_EVENTOS_DIR`). No cambia
  nada de `agent/`, `controller/` ni `servidor/`.
- Asigna los puertos solo: el primer UDP libre desde 1170 para SNMP y el
  primer TCP libre desde 9100 para el controlador (`-SnmpBase`, `-CtrlBase`).
- Deja todo en `resultados/demo/<fecha>/`: un `.log` y un `.err.log` por
  proceso, los `eventos_*.csv` de cada RSU en `rsu<id>/` y los del servidor
  en `servidor/`, y `estado.json` (puertos y PID). Copia ese estado a
  `resultados/demo/actual.json`. Nada de esto se versiona (`.gitignore`).
- **Antes de lanzar nada, comprueba que no haya RSU_ID repetidos.**
  Revisa que el registro no repita `rsu_id`. Revisa que ninguna corrida
  anterior del lanzador tenga vivo un middleware con esos RSU_ID. Revisa
  que ningún otro `rsu_middleware.py` de la máquina los use: busca `RSU_ID=`
  en la línea de comandos del proceso y de sus padres, que es donde lo
  dejan las ventanas de `app_obu/pruebas/demo_*.ps1`. Con `-ConServidor`,
  revisa además que no haya ya otro `servidor/main.py`. Si algo choca,
  aborta y dice qué PID es. Un proceso lanzado a mano con `$env:RSU_ID` en
  una terminal no muestra su RSU_ID desde fuera, así que ese caso aborta
  como "RSU_ID desconocido". `-Forzar` se salta la comprobación, pero solo
  tiene sentido si el otro proceso usa **otro broker**: el choque es por
  broker, porque ambos usan el mismo client_id MQTT
  `rsu-middleware-<RSU_ID>`.
- Opciones: `-Rsus 4,6` (solo esas RSU), `-Broker`/`-BrokerPort`,
  `-ConServidor` (servidor central con `REGISTRO_RSU_PATH` = ese registro),
  `-ConConsola` (consola con `--estado-demo`), `-SinNavegador`.
- `detener_rsus.ps1` solo detiene los PID que registró el lanzador, con sus
  procesos hijos (el `python.exe` del venv es un lanzador que crea el
  intérprete real como hijo). `-Todas` recorre todas las corridas de
  `resultados/demo/`. `-SinConsola` deja la consola abierta para revisar
  la línea de tiempo.

### Cómo sabe la consola qué RSU mostrar

La consola entra en **modo multi-RSU** (`consola/backend/demo_rsu.py`) si
se arranca con `python consola/servidor.py --estado-demo resultados/demo/actual.json`
(es lo que hace `-ConConsola`) o con `--registro <registro.json>`:

- las RSU salen del registro (del `--registro`, o del campo `registro` del
  estado del lanzador);
- el puerto SNMP de cada una sale del `estado.json` del lanzador. Una RSU
  del registro que no esté ahí se sondea en `SNMP_HOST:SNMP_PORT` de
  `consola/.env` solo si su `rsu_id` es `RSU_ID` (la Pi). Si no, aparece
  "sin conexión" con el motivo "sin puerto SNMP conocido": no se inventa
  un puerto.

Sin ninguno de los dos argumentos, la consola se comporta como antes (una
sola RSU, la de `consola/.env`).

### Qué muestra la pantalla "Misión (varias RSU)"

| Elemento | Fuente |
|---|---|
| Fase de cada RSU | `consola/backend/snmp_multi.py`: un GET SNMPv3 por RSU a ~1 Hz de `phaseStatusGroupReds/Yellows/Greens` (NTCIP 1202, los que ya expone `agent/rsu_middleware.py`), cada una en su puerto |
| "sin conexión" | sin respuesta en 0,8 s (`SNMP_MULTI_TIMEOUT_S`). Cada RSU tiene su propia tarea asyncio, así que una RSU caída no frena el sondeo de las demás |
| Estado de la solicitud por RSU | `consola/backend/mision.py`: el de la parada en el último ME del servidor, adelantado por M1/M2/M3 cuando llegan antes. Estados del contrato (`docs/CONTRATO_OBU.md` §4): pendiente, solicitada, en cola, concedida, en espera, rechazada, cancelada. **"liberada" es una etiqueta de la consola, no del contrato**: es una parada cancelada cuyo M3 llevó motivo `cruce` (el vehículo ya cruzó). Con cualquier otro motivo (desvío, conflicto, botón, destino, tiempo máximo, o `caducidad` del watchdog de la RSU) se muestra "cancelada" con su motivo |
| Tiempo en ese estado | reloj de la consola (el instante en que vio el cambio); se congela con el MF |
| Mapa en vivo | ruta del MR, posición del MP con su estela, y cada RSU como un semáforo con la luz de su fase y un anillo del color de su estado de prioridad. Rueda: zoom; arrastrar: mover; doble clic: encuadrar |
| Calles de fondo | grafo vial de OpenStreetMap ya cacheado en `data/grafo_san_miguel_real.graphml` (el mismo que usa `servidor/rutas.py`), leído localmente. Sin teselas, sin CDN y sin servicios externos |
| Línea de tiempo | MI, MR (y recálculos), el primer M1 a cada RSU (las renovaciones a 1 Hz solo se cuentan), cada M2 que cambia de estado, M3 con su motivo y MF |

La consola solo **escucha** (`obu/#`, `rsu/#`, `servidor/+/respuestas`):
no publica ni decide nada. MP y ME (≈1 Hz) alimentan el mapa y las
tarjetas, pero no se listan en "Tráfico MQTT" ni en el registro de
comandos.

Limitaciones conocidas:

- En modo multi-RSU no corre `snmp_poller.py`, para no tener dos hilos con
  pysnmp a la vez (ver la nota de más arriba). Por eso los paneles
  "Semáforo RSU" y "priorityRequestTable" de *Monitoreo en vivo* quedan sin
  datos. Los indicadores "RSU", "Controlador" y "Relojes" de la barra
  superior siguen siendo los de la Raspberry Pi por SSH (`estado_banco.py`).
- La consola sigue una misión a la vez (la última con MI). Si se abre con
  la misión ya armada, la adopta cuando llega el siguiente MR (un
  recálculo); antes de eso no la ve.
- El estado de la solicitud es lo que viaja por el broker: no se lee la
  `priorityRequestTable` (NTCIP 1211) de cada RSU por SNMP.

## Pruebas automatizadas

```bash
python -m pytest -q tests
```

Cubren: traducción de eventos a texto (`tests/test_traduccion_eventos.py`),
cálculo de métricas expuestas por la API de ensayos
(`tests/test_consola_analisis.py`), persistencia/filtrado del registro de
comandos (`tests/test_consola_registro_comandos.py`) y estado por RSU / línea
de tiempo de la misión (`tests/test_consola_mision.py`).

## Seguridad y alcance

Igual que el resto del repo (ver `CLAUDE.md`): esto es un banco de pruebas
académico. La consola escucha solo en `127.0.0.1`, no tiene autenticación
propia y las credenciales SNMPv3/SSH son las de laboratorio. No exponerla
en una red compartida.
