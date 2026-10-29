# 2026-10-29 — App OBU: fix de serialización MQTT, RSU_ID del escenario PUCP y nota sobre OSM-PUCP-04

**Objetivo específico:** OE4 (app Android de la OBU)
**Sección de la tesis:** 3.4 Diseño de la OBU
**Commit:** este commit
**Worktree:** `E:\Tesis\ntcip_app`, rama `app-obu`

## Qué se implementó

### 1. Bug real contra el servidor: "tipo desconocido ... None"

El APK compilado a las 11:44 de hoy (commit `8707630`) seguía mandando MI/MP/MF
sin el campo `"tipo"` en el JSON. Causa: `MqttObuClient.kt` creaba su `Json`
con `ignoreUnknownKeys = true` pero **sin** `encodeDefaults = true`.
`MensajeMI`/`MensajeMP`/`MensajeMF` declaran `val tipo: String = "MI"` (etc.)
como valor por defecto -- y ese valor NUNCA cambia, así que
kotlinx.serialization lo trataba como "coincide con el default, se omite".
`servidor/main.py::_on_message` leía ese MI sin `tipo` e imprimía
`"tipo desconocido en obu/{obu_id}/mision: None"`, sin armar la misión.

- **Fix:** `Mensajes.kt` ahora expone `val jsonObu: Json = Json {
  ignoreUnknownKeys = true; encodeDefaults = true }` como el serializador
  único (antes vivía privado dentro de `MqttObuClient.kt`); `MqttObuClient`
  lo reutiliza en vez de crear su propia instancia.
- **Prueba de regresión (`JsonObuTest.kt`):** serializa un MI/MP/MF con
  `jsonObu` (el MISMO objeto que usa `MqttObuClient`, no una copia) y
  verifica que el JSON resultante trae `"tipo"` y el resto de campos del
  contrato (`docs/CONTRATO_OBU.md`). **Verificado que la prueba de verdad
  detecta el bug:** con `encodeDefaults = false` (el estado de antes del
  fix) las 3 pruebas fallan exactamente en la aserción de `"tipo"`; con
  `encodeDefaults = true` pasan las 3. `./gradlew testDebugUnitTest`:
  12/12 pruebas verdes (3 nuevas + las 9 que ya existían).
- **APK recompilado:** `./gradlew assembleDebug` -- `app-debug.apk` queda
  con fecha **2026-10-29 14:57** (hora de la laptop), reemplazando al de
  las 11:44.

### 2. Confirmado: lo demás no se tocó ni se rompió

- **Modo simulado "bajo techo"** (sin GPS real): sigue como lo dejó el
  commit `8707630` (`MainActivity.iniciarSeguimientoIdle()` no exige
  `ACCESS_FINE_LOCATION` cuando `modoSimulado=true`, para poder obtener
  `ultimaPosicion` de `FuenteSimulada` y habilitar el botón sin permiso de
  ubicación concedido). El permiso SÍ sigue siendo obligatorio para
  arrancar el foreground service (`permisosOk()` en
  `actualizarBotonAccion()`), pero eso es una exigencia de Android sobre el
  TIPO de servicio (`FOREGROUND_SERVICE_TYPE_LOCATION`), no de esta app, y
  no depende de si la posición es real o simulada -- no es una
  contradicción con lo anterior, está documentado así en
  `app_obu/README.md`, sección "Modo simulado". No se modificó ningún
  archivo de este flujo en esta sesión.
- **Reenvío del MI si falla la conexión: NO EXISTE.** Se buscó
  explícitamente (único punto de llamada a `enviarMI` en
  `ObuSessionService.kt`, dentro de `lifecycleScope.launch { runCatching {
  cliente.conectar() }; cliente.enviarMI(...) }`) y no hay ninguna lógica
  que reintente el MI si `conectar()` falla ni si la conexión se cae y se
  reconecta después (el callback `onConexion` solo registra el evento
  `conexion_mqtt`, no reenvía nada). Si `conectar()` lanza una excepción
  antes de que `MqttObuClient` guarde su `cliente` interno, la llamada a
  `enviarMI()` que sigue es un no-op silencioso (`cliente?.publishWith()`
  sobre un `cliente` nulo): el MI se pierde sin aviso y sin reintento. Esto
  se reporta aquí tal cual -- **no se implementó** ninguna corrección (no
  fue parte del encargo de esta sesión, y diseñar el reintento correcto
  -- cuántos intentos, qué backoff, cómo evitar un MI duplicado si el
  primero sí llegó -- es una decisión de diseño que le toca decidir a
  quien lo pida explícitamente). [DATO: pendiente decidir e implementar.]

### 3. Colisión de `RSU_ID` entre "Prueba en mesa" y "Escenario PUCP"

`app_obu/README.md` (sección "Escenario PUCP", agregada en el commit
anterior) decía que bastaba usar puertos SNMP/control distintos para poder
correr ese escenario junto con la "Prueba en mesa" si ya estaba corriendo.
Eso es incorrecto: ambas usaban `RSU_ID=2`, y `agent/rsu_middleware.py`
arma su client_id MQTT como `rsu-middleware-{RSU_ID}` -- dos procesos con
el mismo `RSU_ID` contra el mismo broker usan el mismo client_id, y
Mosquitto expulsa al que tenía la conexión más antigua cada vez que el otro
se conecta, en un bucle de conexión/desconexión (visto de verdad el
2026-10-28). Los puertos SNMP/control son locales a cada proceso y nunca
chocan entre sí -- no tienen nada que ver con este problema.

- **Fix:** `app_obu/pruebas/registro_rsu_pucp.json` ahora usa `rsu_id=3`
  (nunca usado por `registro_rsu_mesa.json`, que sigue en `rsu_id=2`, ni
  por la Pi real, `rsu_id=1`), y los comandos de PowerShell del README
  usan `RSU_ID=3`. Con esto, el "Escenario PUCP" puede correr al mismo
  tiempo que la "Prueba en mesa" sin pisarse. El README también deja
  explícito que, si en cambio se reutiliza `RSU_ID=2` a propósito, hay que
  **detener antes** el controlador/middleware de la "Prueba en mesa" --
  nunca correr dos `rsu_middleware.py` con el mismo `RSU_ID` a la vez.
- **Reverificado end-to-end con `RSU_ID=3`** (controlador + RSU 3 emulada +
  servidor con `registro_rsu_pucp.json` + `gateway/obu_emulada.py` con
  `trayectoria_pucp.csv`): M1 a los ~26 s de misión (17 s de anticipación
  antes de la RSU), M2 `concedida`, M3 `motivo="cruce"` de la propia OBU al
  pasar (t≈43 s) que la RSU usa para liberar la prioridad, y `MF
  motivo="destino"` al terminar la trayectoria (t≈105 s) -- una secuencia
  más limpia que la corrida anterior (que había usado `RSU_ID=2` antes de
  este fix y terminó por caducidad/timeout en vez de M3). Ver
  `app_obu/README.md`, sección "Escenario PUCP", para los comandos exactos.

### 4. `OSM-PUCP-04` no está etiquetada `highway=traffic_signals`

Al documentar el escenario PUCP (commit anterior) se afirmó que
`RSU-PUCP-04` (`osm/salida_osm/candidatas_pucp.csv`) era un "centroide real
de nodos `highway=traffic_signals`" sin aclarar que esa etiqueta viene de
una descarga Overpass **propia** de `osm/osm_lima_rsu.py`
(`agrupar_intersecciones`), de otra fecha, separada de
`data/grafo_san_miguel_real.graphml` (el grafo que de verdad enruta en este
escenario). Se revisó el nodo `316803089` de ESE grafo (el más cercano al
centroide de `RSU-PUCP-04`, <5 m) y sus atributos son solo `y`, `x`,
`street_count` -- **sin** `highway=traffic_signals`. Es decir: hay
evidencia de un semáforo real cerca de ese punto en el estudio de `osm/`,
pero el grafo de enrutamiento de este escenario no lo confirma en ESE nodo
puntual. Se corrigió la redacción en `app_obu/README.md` y en
`app_obu/pruebas/registro_rsu_pucp.json` (campo `origen.interseccion_candidata`)
para decir explícitamente que `OSM-PUCP-04` es una **intersección
candidata** del estudio OSM, asumida como RSU para el banco de pruebas, no
una confirmación de semáforo en el grafo que enruta. [DATO: confirmar en
campo si esa intersección tiene semáforo real antes de citarla como tal en
la tesis.]

## Evidencia

- `app_obu/app/build/outputs/apk/debug/app-debug.apk`, 2026-10-29 14:57,
  `./gradlew assembleDebug` limpio.
- `./gradlew testDebugUnitTest`: 12/12 verdes
  (`app_obu/app/build/test-results/testDebugUnitTest/`).
- Verificación end-to-end con `RSU_ID=3` descrita arriba (sin capturas:
  banco de pruebas en consola, no en la tablet -- la prueba en mesa real
  contra el APK sigue pendiente, ver bitácora de la Etapa 1).

## Pendiente

- Reenvío de MI si falla la conexión inicial o se cae y reconecta a medio
  camino: no implementado (ver sección 2 de arriba).
- Prueba en mesa real contra la tablet con el APK de las 14:57 (pendiente
  desde la Etapa 1).
- Confirmar en campo si `OSM-PUCP-04` tiene semáforo real.
