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
  mqtt_cliente.py            suscriptor MQTT 5 (rsu/#, veh/#)
  snmp_poller.py             sondeo SNMPv3 (semáforo/PRS/tiempos), 1 solo hilo
  obu_local.py               lee resultados/obu_vivo/estado.json
  eventos_remotos.py         ssh tail eventos_rsu_<id>.csv / eventos_ctrl_<id>.csv
  estado_banco.py            tailscale, systemctl, journalctl, pi.sh clock
  pruebas.py                 lanza gateway/obu_emulada.py como subproceso
  analisis.py                reusa scripts/analisis/*.py para la pantalla de ensayos
  mapa.py                    proyecta config/registro_rsu.json (gateway/geometria.py)
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
| Mapa del corredor | `GET /api/mapa` (geometría, una vez) + evento SSE `obu` (posición, cada 0.5 s desde el archivo local de la OBU) |
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

## Pruebas automatizadas

```bash
python -m pytest -q tests
```

Cubren: traducción de eventos a texto (`tests/test_traduccion_eventos.py`),
cálculo de métricas expuestas por la API de ensayos
(`tests/test_consola_analisis.py`) y persistencia/filtrado del registro de
comandos (`tests/test_consola_registro_comandos.py`).

## Seguridad y alcance

Igual que el resto del repo (ver `CLAUDE.md`): esto es un banco de pruebas
académico. La consola escucha solo en `127.0.0.1`, no tiene autenticación
propia y las credenciales SNMPv3/SSH son las de laboratorio. No exponerla
en una red compartida.
