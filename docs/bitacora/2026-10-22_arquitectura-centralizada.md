# 2026-10-22 — Migración a la arquitectura centralizada (el servidor decide)

**Objetivo específico:** OE1 (arquitectura), OE4 (OBU/V2I), OE5 (lazo completo)
**Requerimientos:** RF-03, RF-04, RF-07, RF-08 (nuevo), RF-09, RF-10, RF-11; nuevos de gestión de misión, ruta y conflictos (ver inventario de redacción)
**Sección de la tesis:** `ssec:sel_direccionamiento` (reescrita), nuevas `ssec:ruta_servidor` y `ssec:conflictos` → Capítulo 4
**Commits:** `528801f`, `de633c7`, `acfd928`, `03e9d3a`, `7c8222c`, `bb09050` y los de Fase 4 (ver el reporte final de la sesión)

## Qué se implementó

El sistema migra de un esquema donde la OBU decidía localmente a qué RSU
dirigirse (E2+E4) a uno centralizado: un **servidor central** (paquete
nuevo `servidor/`) es el único decisor. Calcula la ruta al armar la misión
(`servidor/rutas.py`, NetworkX sobre un grafo cacheado — real para San
Miguel/Lima, sintético para pruebas), obtiene la lista ordenada de
RSU/accesos cruzándola con `config/registro_rsu.json` (que pasa a vivir
SOLO en el servidor), estima el ETA a cada RSU y envía la solicitud con
anticipación (`servidor/gestor_mision.py`), verifica la posición real con
la geocerca (`gateway/geometria.py::SeguidorAcceso`, reusada tal cual pero
alimentada con la posición MP en el servidor, no en la OBU) y arbitra
conflictos entre misiones (`servidor/conflictos.py`). La OBU
(`gateway/obu_emulada.py`) pasa a ser un cliente delgado: arma/desarma la
misión y publica su posición a 1 Hz; ya no decide nada. La RSU
(`agent/rsu_middleware.py`) no cambia conceptualmente, solo acepta M1/M3
del servidor en vez de la OBU, con RF-05/06/09 y el modo seguro (RNF7) sin
cambios de comportamiento (verificado con pruebas nuevas, ver abajo).

## Justificación de la decisión (para `ssec:sel_direccionamiento`)

1. **Las ventajas de E2+E4 no se sostienen en una arquitectura 4G.** Sin IP
   pública en la RSU, el M1 de la OBU en E2+E4 también pasa por el broker
   del servidor central — la diferencia entre ambos esquemas es solo el
   procesamiento adicional en el servidor (del orden de milisegundos)
   frente a la latencia 4G [DATO: medir en campo]. El punto único de falla
   es el mismo en ambos esquemas (servidor + broker), mitigado igual con
   redundancia y el modo seguro de la RSU (RNF7).
2. **Solo un decisor central puede cubrir lo que un despliegue real
   necesita:** arbitraje entre vehículos en conflicto, seguridad por
   identidad única autorizada a ordenar a la RSU (con revocación por OBU),
   anticipación por ETA en vez de geocerca fija, autorización/auditoría
   centralizada, un registro de RSU único y actualizado, y una app más
   simple.
3. **Coincide con la práctica comercial de preempción por red celular**
   (Glance de Applied Information, Opticom de GTT/Whelen Cloud Platform):
   ambos coordinan desde la nube con el GPS del vehículo. [CITAR: las dos
   URL del prompt de arquitectura centralizada, agregar al `.bib` de la
   tesis — no se tiene acceso a ese repositorio desde aquí].

## Alternativas descartadas

- **Mantener E2+E4** (la OBU decide localmente): descartado por las
  razones de la sección anterior — no se sostiene mejor que E3 en una
  arquitectura 4G con broker central, y no permite arbitraje de conflictos
  ni revocación por identidad.
- **OSRM/GraphHopper/OpenRouteService** para el cálculo de ruta: se
  mantiene OSMnx/NetworkX (ya evaluado en el prompt original); esas
  alternativas quedan como opción futura si el grafo cacheado con OSMnx no
  escala.
- **Geocodificar el escenario de referencia** (Cía. de Bomberos San Miguel
  N.º 83 → Hospital Centro Médico Naval) para acotar el grafo real: se
  intentó con Nominatim y no resolvió los nombres (ver más abajo); se usó
  en su lugar la caja que envuelve las dos intersecciones reales ya
  presentes en `config/registro_rsu.json`.

## Cómo (detalle técnico)

- **Enrutamiento:** `servidor/rutas.py` separa la carga del grafo
  (`networkx.read_graphml`, sin requerir `osmnx`) de su regeneración
  (`scripts/datos/regenerar_grafo.py`, sí requiere `osmnx` + internet).
  **Sí había acceso a internet en este entorno** (verificado con `curl` y
  con una descarga real de Overpass vía `osmnx` 2.1.1): se descargó
  `data/grafo_san_miguel_real.graphml` (415 nodos, 725 aristas) para la
  caja que envuelve `OSM-C24` y `OSM-C902` (las dos intersecciones de
  `config/registro_rsu.json`) + ~650 m de margen. **No** se pudo
  geocodificar "Compañía de Bomberos San Miguel N.º 83" ni "Hospital
  Centro Médico Naval" con Nominatim (`ox.geocode` devolvió "could not
  geocode" para ambos) — no se inventaron sus coordenadas; el grafo
  descargado puede no cubrir la ruta completa del escenario de referencia
  de la tesis. [DATO: el autor debe confirmar esas dos coordenadas y
  volver a correr `scripts/datos/regenerar_grafo.py` con una caja mayor si
  quedan fuera].
- **Grafo sintético de pruebas:** `servidor/rutas.py::construir_grafo_sintetico()`
  (recta de 7 nodos) y `construir_grafo_cruce_sintetico()` (cruce de 4
  brazos, para el arbitraje de conflictos), ambos con coordenadas
  inventadas y documentados como tales.
- **Mensajes:** MI/MP/MF (OBU→servidor), MR/ME (servidor→OBU), M1/M3
  (servidor→RSU), M2 (RSU→servidor, mismo mecanismo de Response Topic de
  MQTT 5 que ya existía) — especificación completa en
  `docs/CONTRATO_OBU.md`.
- **Seguridad:** `scripts/seguridad/generar_ca.py` (CA de laboratorio con
  `openssl`: init/emitir/revocar/listar) y
  `scripts/seguridad/mosquitto_acl.conf` + `mosquitto_tls.conf` (TLS 1.3 +
  mTLS + ACL: solo el servidor publica en `rsu/+/solicitudes`; cada OBU
  solo en sus propios temas). El CN de cada certificado es el RSU_ID/obu_id
  tal cual, para que las reglas `pattern ... %u` de Mosquitto funcionen sin
  enumerar identidades de antemano.
- **Pruebas nuevas:** 22 pruebas (`tests/test_rutas.py`,
  `test_conflictos.py`, `test_gestor_mision.py`, `test_modo_seguro.py`),
  todas con el grafo sintético (sin red). Total de la suite: 65 (en
  `master`, antes de esta rama) → 88 (al cierre de esta sesión).

## Desviaciones respecto del diseño original del prompt

- **MI incluye `origen`** (lat/lon), no solo `obu_id/clase/destino` como
  dice la tabla mínima del prompt — necesario para que el servidor calcule
  la ruta de inmediato al armar la misión, en vez de esperar la primera MP
  (que también está implementado como fallback, pero no está probado con
  hardware real). Documentado en `docs/CONTRATO_OBU.md`.
- **La anticipación por ETA y la verificación por geocerca conviven**
  dentro de `servidor/gestor_mision.py::procesar_mp`: el ETA dispara el
  primer M1 (RF8), y `SeguidorAcceso` (geocerca) se usa para las
  renovaciones y la cancelación al cruzar — es una integración de diseño
  no especificada en detalle en el prompt original, documentada en el
  docstring del módulo y marcada donde corresponde `[REVISAR con asesor]`.
- **La ACL deja escribible el tema de respuestas del servidor para
  cualquier cliente autenticado** (no solo la RSU que originó la
  solicitud) — limitación de Mosquitto (no distingue "rol" de cliente sin
  un plugin), documentada y marcada `[REVISAR con asesor]` en
  `scripts/seguridad/mosquitto_acl.conf`. El impacto real es bajo porque
  `servidor/gestor_mision.py::procesar_m2` ignora cualquier `id_solicitud`
  que no esté en seguimiento.

## Evidencia

`evidencia/2026-10-22_arquitectura-centralizada/`:

- `correr_e2e.sh` + `servidor.txt`, `obu.txt`, `rsu_sint1.txt`,
  `rsu_sint2.txt`, `controller_sint1.txt`, `controller_sint2.txt`,
  `eventos_*.csv` — escenario de lazo completo (dos RSU consecutivas).
- `correr_e2e_conflicto.sh` + `obu_a_conflicto.txt`, `obu_b_conflicto.txt`,
  `rsu_conflicto.txt`, `servidor_conflicto.txt`,
  `controller_conflicto.txt` — escenario de conflicto (arbitraje real,
  con promoción de la solicitud en espera).
- `correr_e2e_desvio.sh` + `obu_desvio.txt`, `rsu_desvio_sint*.txt`,
  `servidor_desvio.txt`, `controller_desvio_sint*.txt` — escenario de
  desvío (tres recálculos de ruta en vivo).
- `NOTAS.md` — detalle de los tres escenarios, incluido el hallazgo de que
  `agent/ntcip1211.py` solo reconoce `clase_tipo=1` (RF-05), lo que impide
  demostrar el desempate por clase de `servidor/conflictos.py` contra la
  RSU real sin ampliar esa lista (sí está cubierto por
  `tests/test_conflictos.py` de forma aislada).

Las tres pruebas corrieron contra el servicio Mosquitto 2.1.2 **ya
instalado y corriendo** en esta máquina (`127.0.0.1:1883`,
`allow_anonymous true`, sin TLS en estas corridas) — no se instaló nada
nuevo ni se simuló el broker.

**CA propia probada de verdad** (no solo revisada): `init` (clave RSA 4096
+ cert autofirmado 10 años), `emitir --tipo servidor|rsu|obu` (clave RSA
2048, CSR, firma con `openssl ca`, `openssl verify` exitoso contra la CA),
`revocar` (regenera la CRL) y `listar` (muestra `V`/`R` por certificado) —
ver la sesión de comandos en el historial de esta rama (no se guardó un
archivo de evidencia separado para esto, los comandos están en el
docstring de `scripts/seguridad/generar_ca.py`).

## Problemas y solución

- **Nominatim no geocodificó el escenario de referencia real** ("Compañía
  de Bomberos San Miguel N.º 83", "Hospital Centro Médico Naval") →
  se usó en su lugar la caja que envuelve las dos intersecciones ya
  presentes en `config/registro_rsu.json`, documentando la limitación en
  `data/LEEME.md` en vez de inventar coordenadas.
- **Proyección sobre la ruta solo por nodo más cercano daba falsos
  desvíos** en tramos rectos largos sin intersecciones intermedias (hasta
  ~medio espaciado entre nodos) → se cambió
  `servidor/rutas.py::proyectar_sobre_ruta` a una proyección real sobre el
  segmento más cercano de la polilínea (clamp a `[0,1]` en el plano local
  tangente a cada segmento), no solo sobre el nodo.
- **El primer intento del escenario de conflicto no mostró ningún
  conflicto**: se habían usado clases distintas (2 y 1) para poder probar
  el desempate por clase, pero RF-05 (`agent/ntcip1211.py`) solo reconoce
  `clase_tipo=1` y rechazó a la misión de clase 2 antes de que el servidor
  llegara a evaluar el conflicto. Se corrigió usando la misma clase en
  ambas misiones (desempate por ETA) — ver `NOTAS.md` para el detalle
  completo, incluida la limitación resultante para demostrar el criterio
  de clase contra la RSU real.
- **No se pudo instalar `pytest`/`networkx`/`osmnx` en el mismo entorno de
  Python en el primer intento**: el repositorio tiene un `.venv` con las
  dependencias del proyecto (`pysnmp`, `paho-mqtt`, `pytest`) y, por
  separado, el Python global del sistema donde se instaló `osmnx` primero
  → se reinstalaron `networkx`/`osmnx` también dentro de `.venv` para que
  toda la suite de pruebas corra en un solo entorno consistente.

## Pendiente

- **Raspberry Pi real**: no disponible en este entorno. Repetir cualquiera
  de los tres escenarios de `evidencia/2026-10-22_arquitectura-centralizada/`
  contra la Pi, siguiendo `docs/ARRANQUE_BROKER_LAPTOP.md` /
  `docs/CONEXION_RASPBERRY.md` para los comandos exactos (cambiar
  `--broker-host` y correr `agent/rsu_middleware.py` +
  `controller/controller_emulator.py` en la Pi).
- **TLS 1.3 + mTLS reales**: la CA y la configuración de Mosquitto están
  listas (`scripts/seguridad/`) pero no se probaron contra un broker real
  en ejecución. Comandos exactos en el docstring de
  `scripts/seguridad/generar_ca.py`.
- ~~**Coordenadas reales del escenario de referencia** (Cía. de Bomberos San
  Miguel N.º 83 → Hospital Centro Médico Naval): confirmarlas y, si quedan
  fuera de la caja actual, volver a correr
  `scripts/datos/regenerar_grafo.py` con un área mayor.~~ Resuelto el
  2026-10-23, ver `docs/bitacora/2026-10-23_grafo_escenario_referencia.md`.
- **Consola de monitoreo** (`consola/`, `centro_control/panel/`): el mapa
  en vivo seguía leyendo `resultados/obu_vivo/estado.json`, que
  `gateway/obu_emulada.py` ya no escribe. Quedó marcado como legado (ver
  docstrings de `consola/backend/obu_local.py` y
  `centro_control/panel/pages/1_Lazo_V2I_en_vivo.py`) en vez de adaptado:
  falta construir la vista que consuma MR/ME del servidor.
- **Scripts de análisis** (`scripts/analisis/*.py`) y de campañas
  (`scripts/campanas/*.py`, `scripts/trayectorias/generar.py`): no se
  actualizaron con los tramos nuevos (OBU→servidor, procesamiento,
  servidor→RSU) ni con los escenarios de conflicto/desvío como campaña
  repetible — quedó fuera de esta sesión por prioridad (Fase 3 núcleo +
  Fase 4 documentación primero).
- **Política de retención de la posición MP** (Ley N.º 29733): sin definir
  [DATO: plazo de retención por definir].
- Ver también los `[DATO]`, `[CITAR]` y `[REVISAR con asesor]` repartidos
  en `servidor/rutas.py`, `servidor/gestor_mision.py`,
  `servidor/conflictos.py`, `docs/CONTRATO_OBU.md` y
  `scripts/seguridad/mosquitto_acl.conf`.
