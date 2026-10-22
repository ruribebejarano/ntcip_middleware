# Prueba de punta a punta local — arquitectura centralizada (fase 3.8)

**Fecha:** 2026-10-22. **Broker:** servicio Mosquitto 2.1.2 ya instalado y
corriendo en esta máquina (`127.0.0.1:1883`, `allow_anonymous true`, sin
TLS en esta prueba — ver `scripts/seguridad/` para la configuración con
TLS/mTLS, no probada contra un broker real en este entorno). **No** se usó
un broker de prueba lanzado a mano: se usó el servicio de Windows ya activo
(`Get-Service mosquitto` → `Running`), con su `mosquitto.conf` real
(`listener 1883 0.0.0.0`, `allow_anonymous true`).

Todos los procesos corrieron en esta misma máquina (no hay Raspberry Pi
disponible en este entorno): `controller/controller_emulator.py`,
`agent/rsu_middleware.py`, `servidor/main.py` y `gateway/obu_emulada.py`
como procesos Python independientes, comunicados por ese broker. Grafo del
servidor: **sintético** en los tres escenarios (`GRAFO_SINTETICO=recta` o
`GRAFO_SINTETICO=cruce`, ver `servidor/rutas.py`), con un registro de RSU
sintético específico para cada escenario (`registro_rsu_e2e*.json` en esta
carpeta) — **no** es `config/registro_rsu.json` real.

## Escenario 1 — lazo completo, dos RSU consecutivas (`correr_e2e.sh`)

Ruta recta sintética A→G (ver `servidor/rutas.py::construir_grafo_sintetico`)
con dos RSU (`SINT-1` en C, `SINT-2` en F), reproducida a factor 8
(`trayectoria_recta_e2e.csv`, 45 muestras cada 20 m).

Lo que muestra la evidencia (`servidor.txt`, `obu.txt`, `rsu_sint1.txt`,
`rsu_sint2.txt`, `controller_sint*.txt`, `eventos_*.csv`):
- MI arma la misión; el servidor calcula la ruta y publica MR con las 2 RSU
  en orden correcto.
- MP a 1 Hz (aquí, a 8 Hz de reloj real por el factor); ME refleja
  `pendiente` → `solicitada` → `concedida` para SINT-1.
- M1 anticipado (`t_servicio=8.0`, el valor de `ANTICIPACION_MINIMA_S`) y
  renovaciones (`seq` 2..8) mientras la OBU sigue dentro de la geocerca.
- El controlador de SINT-1 fuerza verde (`controller_sint1.txt`:
  "Prioridad solicitada... -> fase forzada a verde por 15s") y la RSU
  responde `concedida` (`eventos_servidor.csv`: `M2_rx estado=concedida
  fase=verde`).
- Al cruzar, el servidor cancela (M3 motivo=`cruce`) y el controlador
  "libera manualmente, vuelve al ciclo normal".
- Para SINT-2, la solicitud llega durante el despeje (`rsu_sint2.txt`:
  "en cola (readyQueued): fase actual 'amarillo'") y el vehículo cruza
  **antes** de que termine el despeje (factor 8 es más rápido que el
  tiempo de amarillo/todo rojo del controlador emulado): la RSU cierra la
  solicitud sin haber llegado a activarla (RF-06 + cruce). **Esto es un
  efecto esperado de acelerar la reproducción (factor 8), no un error** —
  con `--factor 1` el margen de anticipación (RF8) alcanzaría para que el
  despeje termine antes de que el vehículo llegue. [REVISAR con asesor] si
  conviene correr la prueba de referencia en tiempo real para medir esto
  con precisión, en vez de acelerada.
- MF al llegar a G.

## Escenario 2 — conflicto (`correr_e2e_conflicto.sh`)

Cruce sintético (`servidor/rutas.py::construir_grafo_cruce_sintetico`), una
sola RSU (`X-RSU`) con dos accesos incompatibles (`S` grupo 1, `O` grupo
2). Dos OBU emuladas casi simultáneas: `obu-e2e-a` (S→N) y `obu-e2e-b`
(O→E), reproducidas a factor 8.

**Hallazgo real durante esta prueba** (no un error de
`servidor/conflictos.py`): el primer intento usó clase 2 para la misión A y
clase 1 para la B, para poder comprobar el desempate por clase. El RSU
emulado (`agent/ntcip1211.py::CLASES_EMERGENCIA_RECONOCIDAS = {1}`) **solo
reconoce la clase 1** — RF-05 rechazó la solicitud de A antes de que el
servidor llegara a evaluar el conflicto (A pasó a `rechazada` en
~5-10 ms, antes de que B pidiera). Se corrigió la prueba usando clase 1
para ambas misiones, de forma que el arbitraje desempate por ETA en vez de
por clase (ver `servidor/conflictos.py::_gana`). **Esto significa que, con
el banco de pruebas actual, el criterio "gana la clase de mayor prioridad"
de `servidor/conflictos.py` NO se puede demostrar de punta a punta contra
la RSU real sin ampliar `CLASES_EMERGENCIA_RECONOCIDAS`** (que está fuera
del alcance de esta migración: RF-05 no se tocó). El desempate por clase sí
está cubierto por `tests/test_conflictos.py` (sin RSU real, directo sobre
el módulo).

Lo que muestra la evidencia (con clase 1 en ambas, `obu_a_conflicto.txt`,
`obu_b_conflicto.txt`, `rsu_conflicto.txt`, `eventos_servidor.csv`):
- B pide primero y la RSU la concede (`concedida`).
- A pide después; `servidor/conflictos.py` evalúa el conflicto
  (`conflicto_arbitrado`: `atendidos=[mis-6fbd2cb3]` (A),
  `en_espera=[mis-e8781558]` (B)) y A gana por ETA.
- El servidor cancela la solicitud de B con M3 `motivo=conflicto`; la RSU
  confirma "liberando prioridad" (estaba `activeProcessing`, es decir ya
  tenía el verde forzado).
- La OBU B ve en ME: `estado=en_espera, conflicto=true`.
- Ambas terminan con MF al llegar a su destino.

## Escenario 3 — desvío (`correr_e2e_desvio.sh`)

Misma ruta recta A→G que el escenario 1, pero la trayectoria
(`trayectoria_desvio_e2e.csv`) se desvía ~100 m al este en las muestras de
los 300/320/340 m (más allá de `UMBRAL_DESVIO_M=60 m`) y luego vuelve a la
línea original.

Lo que muestra la evidencia (`obu_desvio.txt`, `eventos_servidor.csv`):
- Tras cruzar SINT-1, la excursión dispara **tres** `ruta_recalculada`
  consecutivas (una por cada muestra fuera de umbral), cada una con
  `motivo=desvio`. La nueva ruta pasa de 2 paradas a 1 (SINT-1 ya se había
  cruzado) — consistente, no es una regresión de paradas ya atendidas.
  La OBU recibe tres MR nuevas (`MR <- ruta de 1 RSU, 578.2 m`) en el
  mismo lapso.
- La misión sigue con SINT-2 con normalidad después del desvío
  (`solicitada`) y termina con MF al llegar al destino (desplazado por la
  excursión, pero el grafo sintético solo tiene nodos sobre la línea
  original, así que la ruta recalculada vuelve a esa línea).

## Lo que NO se probó aquí (bloqueo real)

- **Raspberry Pi real**: no hay una disponible en este entorno. Los
  comandos para repetir cualquiera de los tres escenarios contra la Pi son
  los mismos `correr_e2e*.sh`, cambiando `--broker-host` del `servidor` y
  de `gateway/obu_emulada.py` a la IP/alias Tailscale de la Pi, y corriendo
  `agent/rsu_middleware.py` y `controller/controller_emulator.py` *en* la
  Pi en vez de en la laptop (ver `docs/ARRANQUE_BROKER_LAPTOP.md` y
  `docs/CONEXION_RASPBERRY.md`).
- **TLS 1.3 + mTLS reales** (`scripts/seguridad/mosquitto_tls.conf`): no se
  levantó un Mosquitto con esa configuración en este entorno (ver el
  docstring de `scripts/seguridad/generar_ca.py` para los comandos
  exactos). Lo que SÍ se probó end-to-end fue la propia CA
  (`scripts/seguridad/generar_ca.py init/emitir/revocar/listar`, con
  `openssl verify` real) — ver
  `docs/bitacora/2026-10-22_arquitectura-centralizada.md`.
- **Grafo real** (`data/grafo_san_miguel_real.graphml`): se descargó y se
  probó que carga y enruta (ver `tests/test_rutas.py` usa el sintético, no
  el real — no hay una prueba automatizada sobre el grafo real todavía,
  [REVISAR con asesor] si conviene agregar una). Los tres escenarios de
  esta carpeta usan el grafo sintético a propósito, para que las
  distancias y los tiempos sean exactos y reproducibles.
