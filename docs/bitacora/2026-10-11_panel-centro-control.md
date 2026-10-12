# 2026-10-11 — Panel web de supervision del centro de control

**Objetivo especifico:** OE3 (middleware NTCIP) / banco de pruebas
**Requerimientos:** RF-05, RF-06, RF-07, RF-08, RF-09, RF-10, RNF-03 (vista de supervision, no agrega requerimientos nuevos)
**Seccion de la tesis:** implementacion del centro de control (pendiente de redactar en main.tex)
**Commit:** `<pendiente de completar>`

## Que se implemento

`centro_control/panel/`: panel web (Streamlit) que corre en la laptop y
muestra, todo leido en vivo por SNMPv3 de la RSU real:

- Un semaforo animado (HTML/CSS) con el estado de `phaseStatusGroupReds`/
  `Yellows`/`Greens` (grupo 1, fase 1), refrescado cada 0.5s.
- `priorityRequestTable` completa (10 filas), con `priorityRequestStatusInPRS`
  decodificado al nombre real del enum (`readyQueued`, `activeProcessing`,
  etc.), refrescada cada 2s.
- Estado del banco (la Pi responde por SSH, los 3 servicios activos, el
  desfase de reloj Pi/laptop), bajo demanda (boton).
- Linea de tiempo de los ultimos eventos y latencia aproximada por tramo
  por `id_solicitud`, cruzando los `eventos_*.csv` de las 3 maquinas.
- 5 botones de "casos de prueba" que reimplementan (no invocan) las
  acciones SNMP de los pasos 0, 1, 3, 4/5 y 6 de `scripts/demo_asesor.sh`.

## Como

- **Reuso de `centro_control/software_gestion.py`**: el panel importa
  `snmp_get`/`snmp_set`/`snmp_walk`/`AuthConfig`/`SnmpError` tal cual, sin
  copiarlos (`centro_control/panel/snmp_helpers.py`). Los OID reales de
  NTCIP 1202/1211 (que `software_gestion.py` no tenia -- solo los del
  agente SNMPv3 minimo original) se declararon aparte en
  `ntcip_objetos.py`, verificados contra las constantes de
  `agent/rsu_middleware.py`.
- **Unico cambio a `software_gestion.py`**: se agrego un tercer
  `value_type="bytes"` a `snmp_set()` (ademas de los existentes `"int"`/
  `"str"`), necesario para escribir los 29 bytes OER crudos de
  `prgPriorityRequestAbsolute` -- `value_type="str"` hace
  `OctetString(str(value))`, que corrompe bytes binarios. Es una suma, no
  una duplicacion: el resto de la funcion (validacion, `setCmd`, manejo de
  errores) se reutiliza sin cambios, y los tipos `"int"`/`"str"` existentes
  no se tocaron.
- **Rendimiento SNMP (hallazgo no trivial)**: `snmp_get()` crea un
  `SnmpEngine()` nuevo en cada llamada. Leer `priorityRequestTable` con
  100 GET individuales (10 columnas x 10 filas) midio ~10s contra la Pi
  del banco -- inviable para un refresco de 0.5-2s. Se cambio a un solo
  `snmp_walk()` por tabla/grupo (una sola sesion SNMP, GETNEXT encadenado):
  ~1s para las 100 celdas de `priorityRequestTable`, ~0.15s para las 4
  celdas de `phaseStatusGroupEntry` (en vez de 3 GET separados a ~0.35s
  total). Documentado en los docstrings de `snmp_helpers.py`.
- **Credenciales en `.env`**: `centro_control/panel/config.py` carga
  `SNMP_HOST`/`PORT`/`USER`/`AUTH_KEY`/`PRIV_KEY` con `python-dotenv` desde
  `centro_control/panel/.env` (no commiteado, `.env`/`.env.*` ya estaban en
  `.gitignore` -- se agrego una excepcion `!.env.example` para poder
  commitear la plantilla). Si no hay `.env`, cae a los mismos valores de
  laboratorio que el resto del repo, con un aviso visible en la interfaz.
  **No se tocaron** las credenciales hardcodeadas de
  `agent/rsu_middleware.py` ni de `scripts/demo_asesor.sh` -- fuera del
  alcance de este cambio, documentado explicitamente en `.env.example`.
- **Botones de caso de prueba, reimplementados, no invocados**:
  `scripts/demo_asesor.sh` es un script bash interactivo con pausas,
  pensado para una demo guiada en vivo (espera activamente la fase
  correcta del controlador antes de cada paso) -- no esta hecho para que
  algo externo dispare "solo el paso 4". `demo_acciones.py` reimplementa
  la misma accion SNMP de punta a punta en Python (usando los mismos
  helpers), pero **sin forzar ni esperar una fase concreta**: el boton de
  RF-06 reporta lo que de verdad pase segun la fase del controlador en el
  momento del clic (encolada o activada de inmediato), igual que lo haria
  un operador real usando el panel sin coordinar con el ciclo del
  semaforo. No se modifico `demo_asesor.sh` (ya probado y listo para la
  reunion de manana).
- **Linea de tiempo de eventos**: reutiliza `common/events.py`
  (`iter_eventos`) y `scripts/analisis/latencia_tramos.py`
  (`agrupar_por_solicitud`, `calcular_latencias`) sin reimplementar el
  cruce por `id_solicitud` ni el calculo de latencias. Como esas funciones
  esperan todos los `eventos_*.csv` en un mismo directorio y los de
  `ctrl`/`rsu` viven en la Pi mientras que el de `obu` (si se corrio
  localmente) vive en la laptop, se agrego un boton "Traer eventos de la
  Pi" (corre `scripts/pi.sh fetch`, ya existente) y
  `eventos_panel.py` copia los CSV relevantes a
  `resultados/panel_vivo/` (agregado a `.gitignore`, se regenera solo)
  antes de llamar a las funciones de `latencia_tramos.py`.
- Dependencias nuevas (`.venv` y `centro_control/requirements.txt`):
  `streamlit==1.65.0`, `python-dotenv==1.2.4`. `playwright` se instalo
  solo para las capturas de pantalla de esta bitacora, no es una
  dependencia del panel en si (no se agrego a requirements.txt).

## Desviaciones respecto del diseno de la tesis

Ninguna de diseno -- es una herramienta de supervision adicional para el
centro de control, no un requerimiento funcional nuevo. `software_gestion.py`
gano un `value_type` mas en `snmp_set()` (ver "Como"), backward-compatible.

## Evidencia

- `evidencia/2026-10-11_panel_vista-general.png`: vista general del panel
  en vivo -- semaforo en rojo (real, leido de la Pi en el momento de la
  captura) y `priorityRequestTable` con una fila cerrada por caducidad de
  una prueba anterior.
- `evidencia/2026-10-11_panel_caso-prueba-ntcip1202.png`: linea de tiempo
  de eventos + el boton "NTCIP 1202: snmpwalk de fase" ejecutado, con el
  resultado real (los objetos NTCIP 1202 y sus valores vigentes).
- `evidencia/2026-10-11_panel_caso-prueba-rf06.png`: el boton "NTCIP 1211:
  SET con clase reconocida" ejecutado -- SET aceptado, fila 1 de
  `priorityRequestTable` en `activeProcessing`.

## Problemas y solucion

- **100 GET individuales para `priorityRequestTable` median ~10s** (ver
  "Como" -- cada `snmp_get()` crea su propio `SnmpEngine`). Resuelto
  cambiando a un solo `snmp_walk()` por tabla, ~10x mas rapido.
- **`subprocess.run(["bash", ...])` en Windows resuelve a
  `C:\Windows\System32\bash.exe` (el lanzador de WSL), no a Git Bash** --
  falla con `execvpe(/bin/bash) failed: No such file or directory` porque
  los scripts del repo usan sintaxis de Git Bash. Resuelto buscando
  `C:\Program Files\Git\bin\bash.exe` explicitamente en vez de confiar en
  que "bash" del PATH resuelva al binario correcto (`demo_acciones.py`,
  `_BASH_EXE`).
- **`UnicodeDecodeError` leyendo la salida de `pi.sh status`**:
  `subprocess.run(..., text=True)` en Windows decodifica con cp1252 (el
  codepage por defecto), que revienta con cualquier caracter no-ASCII que
  venga de `journalctl` en la Pi (acentos, viñetas) -- perdia en silencio
  la salida completa de ese paso. Resuelto decodificando manualmente como
  UTF-8 (`errors="replace"`) en vez de usar `text=True`.

## Pendiente

- Insertar las 3 capturas en la seccion de implementacion del centro de
  control de `main.tex` (no hecho en esta sesion -- solo se generaron y
  guardaron en `evidencia/`, siguiendo el mismo patron que la figura del
  mapa de bytes de `prgPriorityRequestAbsolute`).
- El panel no tiene un boton para el paso 2 (ciclo completo del
  controlador, ~25s de observacion pasiva) ni el 7 (lazo V2I completo via
  MQTT) de `demo_asesor.sh` -- el primero no es una accion puntual que
  tenga sentido como boton, y el segundo requeriria un cliente MQTT ademas
  de SNMP; no implementado, posible trabajo futuro si hace falta para la
  demo.
- No se probo el panel con dos RSU simultaneas (el banco de pruebas hoy
  solo tiene una levantada, ver bitacora de Prompt B / Capitulo III).
