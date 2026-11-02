# 2026-10-30 — Consola multi-RSU, mapa en vivo y lanzador de demos sin ventanas

**Objetivo específico:** OE5 (banco de pruebas: supervisión de la validación del lazo); apoya OE1 (vista del servidor central como único decisor)  **Requerimientos:** RF-08 (estado de la solicitud visible), RNF-03 (caducidad observable); ninguno se mide aquí
**Sección de la tesis:** 4.x (banco de pruebas / herramientas de validación)
**Commit:** el de este archivo (`OE5: consola multi-RSU ...`)

## Qué se implementó

- La consola (`consola/`) muestra **todas las RSU de un registro**, no
  solo la Pi. Lee la fase de cada una por SNMPv3 (NTCIP 1202
  `phaseStatusGroupReds/Yellows/Greens`) a ~1 Hz en su propio puerto. Una
  RSU que no responde queda "sin conexión" sin frenar a las demás.
- Hay una pantalla nueva, **"Misión (varias RSU)"**: mapa en vivo (ruta MR,
  posición MP con estela, cada RSU como un semáforo coloreado por su fase y
  con un anillo del color de su estado de prioridad), una tarjeta por RSU
  (fase, estado de la solicitud, tiempo en ese estado, acceso/ETA, último
  M2, motivo) y una línea de tiempo (MI, MR, M1 por RSU, M2, M3 con motivo,
  MF).
- El mapa ya no depende de `resultados/obu_vivo/estado.json`, que ningún
  componente escribe desde la arquitectura centralizada. Ahora se alimenta
  de MR/MP/ME por MQTT, también en "Monitoreo en vivo".
- `scripts/demo/lanzar_rsus.ps1` / `detener_rsus.ps1`: levantan un
  controlador emulado y una RSU por intersección (y, si se pide, el
  servidor y la consola) **sin ventanas**, con puertos automáticos, logs en
  `resultados/demo/<fecha>/` y comprobación previa de RSU_ID repetidos.

## Cómo

- Python 3.13.3, FastAPI 0.153.0, uvicorn 0.54.0, pysnmp del commit fijado
  en `requirements.txt` (API asyncio: `pysnmp.hlapi.asyncio.getCmd`),
  Mosquitto 2.1.2. Sin dependencias nuevas.
- Archivos nuevos: `consola/backend/{demo_rsu,snmp_multi,mision}.py`,
  `consola/static/js/mision.js`, `scripts/demo/{lanzar,detener}_rsus.ps1`,
  `tests/test_consola_mision.py`.
- Archivos modificados: `consola/backend/{api,config,estado,mapa,mqtt_cliente}.py`,
  `consola/servidor.py` (`--registro`, `--estado-demo`, `--sin-navegador`),
  `consola/static/{index.html,css/estilo.css,js/{mapa,main,monitoreo,sse}.js}`,
  `docs/CONSOLA.md` (sección "Demo con varias RSU"), `.gitignore`
  (`resultados/demo/`).
- **No se tocó `agent/`, `controller/` ni `servidor/`.** El lanzador solo
  usa las variables de entorno que ya leían.
- Uso completo: `docs/CONSOLA.md`, sección "Demo con varias RSU".

## Desviaciones respecto del diseño de la tesis

- Ninguna sobre el lazo. Dos aclaraciones para no confundir en el Cap. 4:
  - "liberada" **no es un estado del contrato** (`docs/CONTRATO_OBU.md`
    §4). Es la etiqueta con la que la consola muestra una parada
    "cancelada" cuyo M3 llevó motivo `cruce`.
  - El mapa **no usa teselas de OpenStreetMap**: el pedido decía "con el
    mapa de OpenStreetMap ya usado en la consola", pero la consola nunca
    tuvo teselas (era SVG puro, sin internet, a propósito). Las calles de
    fondo salen del grafo OSM ya cacheado en `data/` (el mismo del
    servidor), leído localmente.

## Evidencia

Verificación (2026-10-30, laptop): escenario Hospital del Niño (registro
`registro_rsu_hospital_nino.json` de la rama app-obu, RSU 4, 5 y 6) con
`gateway/obu_emulada.py --factor 4`, todo levantado con
`lanzar_rsus.ps1 -ConServidor -ConConsola`. **Se corrió contra un broker
aparte en el puerto 1884** (`-BrokerPort 1884 -Forzar`) porque en ese
momento estaban abiertas las 6 ventanas de `demo_hospital_nino.ps1` con
los mismos RSU_ID contra el broker 1883 (ver "Problemas"). Línea de tiempo
observada en la consola (resumen):

```
+0.0 s  MI   OBU ses-425547 arma la misión (clase 1)
+0.0 s  MR   ruta 2928.1 m: RSU 4/A -> RSU 5/B -> RSU 6/B
+12.6 s M1   RSU 4   +12.6 s M2 concedida (verde)   +15.7 s M2 cancelada (caducidad)
+24.6 s M1   RSU 5   +26.9 s M2 concedida (verde)   +28.6 s M3 cruce
+41.6 s M1   RSU 6   +41.6 s M2 concedida (verde)   +45.1 s M3 cruce
+75.8 s MF   motivo destino
```

Las 3 RSU cambiaron de fase en el mapa y se activaron en orden (4 -> 5 -> 6).
Al detener a mano el middleware de la RSU 5, su tarjeta y su marcador
pasaron a "sin conexión" mientras la 4 y la 6 seguían actualizándose a
~1 Hz (indicador "SNMPv3 2/3 RSU"). `pytest -q tests`: 112 pruebas pasan.
Los logs de la corrida quedaron en `resultados/demo/2026-10-30T023214/`
(no versionado).

**Capturas que debe tomar el estudiante** (para el Cap. 4, en una corrida
propia contra el broker normal, sin las ventanas de `demo_hospital_nino.ps1`):

1. Pantalla "Misión (varias RSU)" antes de lanzar la OBU (3 RSU con fase, "sin misión").
2. La misma pantalla con la OBU entre la RSU 4 y la RSU 5 (ruta, estela, anillos de color).
3. La línea de tiempo completa al terminar (MI ... MF).
4. Una RSU detenida a mano, en "sin conexión", con las demás en vivo.
5. La salida de `lanzar_rsus.ps1` mostrando los puertos asignados, y la de un segundo lanzamiento que aborta por RSU_ID repetidos.

## Problemas y solución

- **Choque de RSU_ID durante la prueba.** A las 02:23 se lanzaron RSU 4/5/6
  de prueba. A las 02:27 se abrió `demo_hospital_nino.ps1` (fuera de esta
  sesión), con los mismos RSU_ID contra el mismo broker. Durante unos 3 min
  ambos juegos compartieron client_id MQTT, hasta que los de prueba se
  detuvieron a las ~02:30. El segundo intento del lanzador abortó al
  detectarlo. Para eso se mejoró la detección: ahora se lee `RSU_ID=` de la
  línea de comandos de los procesos padre (las ventanas de `demo_*.ps1`).
  El resto de la verificación se hizo en el broker 1884.
- **pysnmp sin bloquear entre RSU:** el `snmp_walk` síncrono de
  `software_gestion.py` (timeout 2 s, 1 reintento) dejaría a todas las RSU
  esperando ~4 s por cada una caída. Se usó la API asyncio de pysnmp en un
  solo hilo con una tarea por RSU. Sigue habiendo un solo hilo con pysnmp,
  y en modo multi-RSU `snmp_poller.py` no arranca.
- **`python.exe` del venv en Windows** es un lanzador que crea el
  intérprete real como hijo: `detener_rsus.ps1` mata el árbol y la
  detección de duplicados no cuenta dos veces el mismo proceso.

## Pendiente

- **Defecto del servidor encontrado con la consola (investigado, NO
  corregido: requiere tocar `servidor/` o `gateway/geometria.py`).** En la
  RSU 4 el servidor envió un solo M1 y nunca lo renovó ni lo canceló con
  M3. El watchdog RNF-03 de la RSU (`T_CAD_SEGUNDOS = 3.0`,
  `agent/ntcip1211.py`) soltó la prioridad (`rnf03_sin_actualizacion`).
  - **Causa:** la trayectoria se acerca a la RSU 4 por La Mar, se desvía una
    cuadra por Calle Napo y vuelve a La Mar. La geocerca (`SeguidorAcceso`)
    asigna RSU 4/A a 297 m (t=14 s). En t=26 s el vehículo gira al sur
    (rumbo 182,9°) a 187 m de la intersección: deja de estar "por delante"
    y la geocerca lo trata como **cruce**. Por eso marca la intersección
    como `_excluida` hasta que el vehículo se aleje más de R_i + margen =
    350 m, y eso no pasa nunca, porque el vehículo vuelve sin salir de
    ~205 m. Así, la geocerca no vuelve a emitir EMITIR_M1/ACTUALIZAR_M1
    para la RSU 4. El único M1 sale por la anticipación por ETA (RF8,
    t=49 s, a 69 m), que no tiene renovación propia: el servidor solo
    renueva por decisión de la geocerca. Tampoco hay M3 `cruce`, porque la
    geocerca nunca consideró vigente esa solicitud. Además, el cruce por
    avance sobre la ruta (`MARGEN_CRUCE_M`, `servidor/gestor_mision.py:80`)
    está definido pero no se usa en ninguna parte.
  - **Reproducción:** es determinista y no depende del factor. Se
    reprodujo offline pasando `trayectoria_hospital_nino.csv` por
    `GestorMision` con reloj simulado: M1 en t=49 y ninguna decisión de
    geocerca para la RSU 4 después de t=25. La RSU 5 sí recibe EMITIR_M1
    a 148 m y renovaciones a 1 Hz.
  - **Impacto a velocidad real (`--factor 1`, 2026-10-30 02:45, broker
    aparte, `resultados/demo/2026-10-30T024239/`):** M1 a 68,9 m y
    caducidad 3,2 s después, con el vehículo a **40 m** de la intersección.
    El vehículo pasa por el centro 8 s después del M1, así que llega a la
    intersección ~5 s después de que la RSU ya soltó la prioridad. Con
    `--factor 4` no se notaba porque el vehículo cruzaba antes de la
    caducidad.
  - **Corrección mínima propuesta (pendiente de aprobación):** en
    `servidor/gestor_mision.py::procesar_mp`, renovar cada parada en
    solicitada/en_cola/concedida a cada MP aunque la geocerca no la
    confirme, y cerrarla con M3 `cruce` cuando
    `distancia_recorrida_m > distancia_llegada_m + MARGEN_CRUCE_M`. Es el
    criterio por avance sobre la ruta que el servidor ya puede calcular y
    que la constante sugiere que estaba previsto. Alternativa (cambia la
    semántica de ssec:emision): en `SeguidorAcceso`, tratar como "cruce" y
    excluir la intersección solo si el vehículo estuvo cerca del centro
    (p. ej. ≤ R_g); un giro lejano sería "rumbo_divergente", sin exclusión.
    En ambos casos, agregar la trayectoria con rodeo como prueba de
    regresión.
- Si se quiere detectar RSU_ID repetidos también en procesos lanzados a
  mano desde una terminal, el cambio mínimo sería en `agent/rsu_middleware.py`
  (no hecho, requiere aprobación): publicar un mensaje retenido de presencia
  `rsu/<RSU_ID>/presencia` con *last will* "desconectada". El lanzador lo
  consultaría en el broker antes de arrancar.
- Paneles "Semáforo RSU" y "priorityRequestTable" de *Monitoreo en vivo*
  sin datos en modo multi-RSU (ver limitaciones en `docs/CONSOLA.md`).
