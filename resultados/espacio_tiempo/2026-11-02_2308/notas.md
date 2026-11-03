# Corrida espacio-tiempo (M1, prompt_figuras_cap4.md)

**Fecha:** 2026-11-02, 23:08-23:15 (laptop, todo en la misma máquina).
**Propósito:** única corrida multi-RSU con todos los eventos (trayectoria,
servidor, controlador y RSU por intersección) que las 4 campañas del 29/10
no tienen (una sola RSU por misión) ni `resultados/hospital_nino/` tiene
completa (solo `eventos_ctrl_*`/`eventos_rsu_*` de una corrida del 29/10,
sin servidor ni trayectoria) ni `evidencia/2026-10-22_arquitectura-centralizada/`
(2 RSU sintéticas, sin `eventos_ctrl_*.csv`).

## Qué se corrió

Escenario Hospital del Niño real (`app_obu/README.md`), 3 RSU sobre el
grafo real de San Miguel (`data/grafo_san_miguel_real.graphml`,
`app_obu/pruebas/registro_rsu_hospital_nino.json`): RSU 4 (OSM-PUCP-07,
acum=547.0 m), RSU 5 (OSM-PUCP-03, acum=1098.7 m), RSU 6 (OSM-PUCP-08,
acum=1747.8 m), sobre una ruta de 2928.1 m. OBU emulada
(`gateway/obu_emulada.py`) con `app_obu/pruebas/trayectoria_hospital_nino.csv`
(303 muestras, 302 s) a **factor 1.0 (tiempo real)**, ~5 min de corrida.

Arquitectura centralizada igual que las campañas: `servidor/main.py` decide
y envía M1/M3 a cada RSU según la ruta calculada; `controller/controller_emulator.py`
con los tiempos por defecto (verde 8 s, amarillo 3.0 s, todo_rojo 2.0 s,
rojo_general 8 s = 21 s), sin `--phase-*` ni `set_timing`.

## Puertos (para no pisarse con la sesión de seguridad en paralelo)

Antes de levantar nada se comprobó con `netstat`/`Get-Service` que estaban
libres:

- **Broker:** Mosquitto standalone en **127.0.0.1:18830**, sin TLS,
  `allow_anonymous true` (conf temporal fuera del repo). Distinto del
  servicio Windows en 1883 (puede estar en uso por la sesión de seguridad
  para su condición `sin-tls`) y de cualquier puerto 8883/TLS que use esa
  sesión.
- **SNMP:** 1174 (RSU 4), 1175 (RSU 5), 1176 (RSU 6).
- **Control (RSU↔controlador):** 9104 (RSU 4), 9105 (RSU 5), 9106 (RSU 6).

Ninguno de estos coincide con `common/mqtt_tls.py`, `agent/`, `gateway/`,
`servidor/`, `scripts/seguridad/`, `scripts/campanas/` ni con los puertos
que esos módulos usan por defecto (1883/8883, SNMP 1161, control 9000) --
no se editó ninguno de esos archivos, solo se ejecutaron tal cual.

## Incidencias

- El primer intento de esta corrida fue lanzado por error por un subagente
  de investigación al que solo se le había pedido LEER código y proponer
  un plan (nunca ejecutarlo). Terminó con procesos duplicados (dos
  `servidor/main.py`, dos `obu_emulada.py` con el mismo `obu_id`
  corriendo a la vez) sin apagar nada al terminar -- se detectó por
  `resultados/espacio_tiempo/` apareciendo sin que esta sesión lo hubiera
  creado todavía. Se mató todo ese primer intento (con confirmación del
  autor) y se borró su carpeta (`2026-11-02_1430`, nunca comiteada) por no
  ser confiable (escrituras concurrentes del mismo `EventLogger`). Esta
  corrida (`2026-11-02_2308`) es un relanzamiento limpio, hecho
  directamente por la sesión principal, sin subagentes.
- Al lanzar `gateway/obu_emulada.py` se olvidó pasar `RSU_EVENTOS_DIR`: sus
  eventos se escribieron primero en la ruta por defecto
  (`resultados/eventos/eventos_obu-hospitalnino-m1.csv`, carpeta
  compartida con otras corridas) y se **movieron** (no se copiaron) a esta
  carpeta apenas terminó la corrida, antes de tocar cualquier otro archivo
  de esa carpeta compartida.
- `Start-Process` con el `python.exe` del entorno virtual lanzó, para cada
  proceso, dos PID visibles en `Get-CimInstance Win32_Process` (solo uno
  de cada par llega a escuchar el puerto real, verificado con `netstat`);
  se mataron ambos PID de cada proceso al terminar, por si acaso.

## Procesos apagados al terminar

Sí: los 3 `controller_emulator.py`, los 3 `rsu_middleware.py`, el
`servidor/main.py`, el `obu_emulada.py` (que ya había terminado solo tras
el MF) y el Mosquitto standalone del puerto 18830. Verificado con
`netstat` (sin LISTENING en 9104-9106, 1174-1176, 18830 tras apagar) y con
`Get-Service mosquitto` (el servicio compartido de Windows, usado por la
sesión de seguridad, siguió `Running` sin tocarlo).
