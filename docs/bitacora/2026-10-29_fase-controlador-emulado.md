# 2026-10-29 — Defecto de banco de pruebas en el controlador emulado; campaña estratificada por condición de llegada

**Objetivo específico:** OE5 (campaña de medición del lazo, cobertura de las
3 condiciones de llegada: verde / ámbar-todo_rojo / rojo)
**Requerimientos:** RNF-01 (latencia L), RF6 (cola de despeje), RF8
(anticipación real)
**Sección de la tesis:** 4.3–4.5 (campaña y resultados) / 4.8 (limitaciones)
**Commit:** `60cac6f` (corrección del controlador, desplegada a la Pi);
commit de esta sesión con el runner/análisis/figuras/campañas pendiente al
cierre de esta entrada (ver abajo)

## Qué se implementó

1. **Corregido el defecto de banco de pruebas** diagnosticado al cierre de
   la sesión anterior (`docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md`):
   `controller/controller_emulator.py::Controller` avanzaba **un solo paso**
   de fase por cada llamada a `status()`, sin importar cuánto tiempo real
   hubiera pasado. Como nada hace poll al controlador mientras no hay una
   solicitud activa (ni entre repeticiones de una campaña), la fase
   reportada quedaba siempre congelada en "amarillo" — las 40 solicitudes
   de la campaña del 2026-10-28 decidieron ahí, nunca en verde ni en
   rojo_general, aunque la pausa aleatoria sí variaba el tiempo real
   transcurrido.
2. **Campaña re-diseñada con cuotas adaptativas por condición de llegada**
   (verde / ámbar-todo_rojo / rojo_general) en vez de un número fijo de
   repeticiones, pedido explícitamente para poder ejercitar las 3
   condiciones de forma controlada sin fijar un objetivo de fase de
   antemano (se descartó la espera activa antes de lanzar la OBU: entre
   el lanzamiento y la decisión de la RSU pasan varios segundos variables,
   más con 4G, así que un objetivo fijado de antemano apuntaría a la fase
   equivocada).
3. **Dos defectos nuevos encontrados y corregidos al ejercitar por primera
   vez las llegadas en verde y en rojo** (ninguno es un defecto del
   middleware real, `agent/rsu_middleware.py`): ver "Problemas y solución".
4. **Análisis con desglose por condición de llegada**: `t_verde`, `T_desp`
   y anticipación real (además de RTT_srv, t_RSU, L), antes solo
   agregadas.
5. **Las cuatro campañas repetidas** (lazo y desvío × local y pi-lan) con
   el controlador corregido y el runner con cuotas.

## Cómo

### 1. Corrección del controlador (`controller/controller_emulator.py`)

Reemplazado el avance de un solo paso por un **reloj continuo**
(`Controller._epoch`, fijado una sola vez en el constructor) y la fase
calculada por **módulo del ciclo total vigente** en cada consulta
(`_fase_en_offset_locked`), no por pasos. Revisado `request_priority`/
`clear_priority`: no necesitaron cambios — como el reloj de fondo nunca se
pausa (la prioridad solo sobre-escribe lo que se *reporta*, fuerza
"verde"), al liberar la prioridad la fase calculada ya refleja el tiempo
real transcurrido, sin necesitar "saltar" a ningún estado guardado de
antes de pedirla.

`tests/test_controller_emulator.py` (nuevo, 5 pruebas): la central,
`test_fase_correcta_tras_intervalo_largo_sin_consultas`, simula 33 s sin
ninguna consulta y verifica que se reporte la fase que corresponde por
reloj (`todo_rojo`, 33 % 21 = 12 s) y no "amarillo" (lo que daba el código
anterior, verificado con `git stash` antes de comitear: 3 de las 5 pruebas
fallan contra el código viejo).

Instrumentación menor en `agent/rsu_middleware.py` (sin cambio de
comportamiento): el camino de concesión inmediata de prioridad ahora
también loguea el campo `fase` en el evento `snmp_set_tx`, igual que ya
hacía el camino de cola (`en_cola_despeje`) — necesario para poder
clasificar TODA solicitud por su condición de llegada, no solo las que se
encolan.

Desplegado a la Pi: `scripts/pi.sh deploy rsu` (commit `60cac6f`),
`scripts/pi.sh restart controller rsu && scripts/pi.sh restart agent rsu`,
verificado `scripts/pi.sh status` de ambos (activos).

### 2. Cuotas adaptativas (`scripts/campanas/lazo_centralizado.py`)

`--repeticiones` fijo reemplazado por `--meta-por-condicion` (4 por
defecto) y `--tope-repeticiones` (18 por defecto): el runner sigue
lanzando repeticiones hasta que verde, ámbar/todo_rojo y rojo_general
tengan cada una al menos la meta, o hasta el tope. La pausa aleatoria no
se tocó. `config.json` registra `meta_por_condicion`, `tope_repeticiones`,
`conteo_por_condicion`, `meta_por_condicion_cubierta`, `tope_alcanzado` y
`condicion_por_repeticion`.

### 3. Análisis por condición (`scripts/analisis/lazo_centralizado.py`)

`condicion_de_fase()` agrupa verde / amarillo+todo_rojo
(`FASES_NO_INTERRUMPIBLES`, `agent/ntcip1211.py`) / rojo_general.
`analizar()` agrega `fase_decision` y `condicion_llegada` a cada fila de
`lazo_por_parada.csv`, agrega `t_verde_ms`/`T_desp_ms` al resumen global
(antes no se acumulaban a ningún lado) y un bloque
`por_condicion_llegada` con las 6 métricas de latencia filtradas por
condición. `scripts/analisis/graficos_campana_centralizada.py` agrega
`tabla_condicion.tex` (nueva, una fila por métrica/config/condición).

### 4. Las cuatro campañas

Gestión del agente de la Pi entre configuraciones: `scripts/pi.sh stop
agent rsu` antes de las dos campañas `config=local` (verificado inactivo
por `_verificar_pi_agente_inactivo`), `scripts/pi.sh start agent rsu`
antes de las dos `config=pi-lan` (verificado activo junto con el
controlador por `_verificar_pi_activa`, más el chequeo de camino directo
por Tailscale y modo de red ya existentes).

| Corrida | verde | ámbar/todo_rojo | rojo | Resultado |
|---|---|---|---|---|
| `20261029-005510_lazo_local` | 5 | 3 | 10 | tope alcanzado (ámbar corto) |
| `20261029-012758_desvio_local` | 11 | 2 | 5 | tope alcanzado (ámbar corto) |
| `20261029-020001_lazo_pi-lan` | 6 | 4 | 8 | cuotas cubiertas |
| `20261029-023433_desvio_pi-lan` | 4 | 4 | 10 | cuotas cubiertas |

`ambar_todo_rojo` es la condición más corta del ciclo (3+2=5 s de 21 s,
~24 %): no cubrir la meta de 4 en 18 repeticiones en las dos corridas
`local` es variación estadística esperable para esa probabilidad, no un
error — el tope existe exactamente para este caso. Las dos corridas
`pi-lan` sí cubrieron las 3 cuotas dentro del tope.

## Desviaciones respecto del diseño de la tesis

Ninguna nueva. Sigue vigente la de la sesión anterior (config=local como
banco de desarrollo, no cota inferior comparable a pi-lan/pi-4g).

## Evidencia

- `tests/test_controller_emulator.py`: 5/5 pasan contra el código
  corregido; 3/5 fallan contra el código anterior (verificado con `git
  stash` antes de comitear el arreglo).
- Las cuatro corridas de la tabla de arriba, con `lazo_resumen.json` /
  `lazo_por_parada.csv` regenerados (incluyen `condicion_llegada`,
  `por_condicion_llegada`).
- `resultados/campana/_figuras_2026-10-29/` (lazo vs desvío, config=local)
  y `resultados/campana/_figuras_2026-10-29_local_vs_pi-lan/` (local vs
  pi-lan combinado): `fig_rtt_cdf`, `fig_tramos`, `fig_comparacion`
  (.pdf/.png, revisadas visualmente), `tabla_latencia.tex` y
  `tabla_condicion.tex` (nueva).
- `resultados/campana/_descartadas/NOTA.md`, secciones 4–6: motivo de cada
  corrida descartada de esta sesión y de la anterior.

### Resultados principales (lazo+desvío combinados, un solo reloj)

| Métrica | local (mediana/p95) | pi-lan (mediana/p95) |
|---|---|---|
| RTT_srv | 47.16 / 73.09 ms | 12.24 / 53.78 ms |
| t_RSU | 18.24 / 26.40 ms | 1.01 / 1.10 ms |
| L (RNF-01) | 18.89 / 26.97 ms | 9.16 / 51.52 ms |

Por condición de llegada (pi-lan, pooled lazo+desvío — ver
`tabla_condicion.tex` para la tabla completa con local incluido):

| Condición | n | t_verde mediana/p95 | T_desp mediana/p95 |
|---|---|---|---|
| verde | 10 | 8.05 / 13.22 ms | -- (no aplica, concesión inmediata) |
| ámbar/todo_rojo | 8 | 2694.64 / 5246.75 ms | 2688.73 / 5233.88 ms |
| rojo | 18 | 10.52 / 63.69 ms | -- (no aplica, concesión inmediata) |

`t_verde` para ámbar/todo_rojo (~2.7 s mediana, hasta ~5.2 s p95) es
exactamente el costo esperado de RF-06 (esperar a que termine el
despeje) — la primera vez que se mide con datos reales, ya que antes del
2026-10-29 el 100 % de las decisiones caía en esa condición pero el
defecto del controlador no dejaba razonar sobre esto por separado de
verde/rojo.

**RNF-01 (L, peor caso p95+cota de reloj) NO CUMPLE en `desvio_pi-lan`**
(p95 medido 25.75 ms + cota 1500 ms = 1525.75 ms > 1000 ms) —
**no por latencia real** (L medido sigue en el orden de decenas de ms,
muy por debajo del umbral): `scripts/pi.sh clock` al FINAL de esa corrida
capturó `chronyc tracking` con `Stratum: 0`, `Leap status: Not
synchronised`, `Reference ID: 00000000`, `Root delay`/`Root dispersion`
en los valores centinela de chrony (1.0 s cada uno) — la Pi perdió
sincronización NTP en algún momento de esa corrida (no se sabe
exactamente cuándo dentro de ella), y la cota conservadora (peor caso
entre inicio y fin) hereda ese 1.5 s. Las demás tres corridas tienen cota
de reloj normal (0–58 ms). **[REVISAR con asesor]**: esto es un evento de
infraestructura (pérdida de sync NTP de la Pi, probablemente por Wi-Fi/
Tailscale), no un hallazgo sobre el canal V2I — pero expone que la
política de "peor caso entre inicio y fin de la corrida" puede quedar
dominada por un evento al final que no afectó realmente los datos
medidos. Antes de la campaña 4G: considerar capturar `chronyc tracking`
periódicamente DURANTE la corrida (no solo inicio/fin) para poder acotar
cuándo ocurrió la pérdida de sync, o al menos repetir la medición de reloj
inmediatamente si `scripts/pi.sh clock` del final sale "Not synchronised".

## Problemas y solución

### 1. Avance de un solo paso en el controlador emulado (banco de pruebas)

Ver "Qué se implementó" punto 1 y la bitácora anterior
(`2026-10-28_campana-centralizada-lazo-desvio.md`) para el diagnóstico
completo. Corregido con reloj continuo + módulo (este documento, sección
"Cómo" punto 1).

### 2. Clasificación por condición leyendo el campo equivocado (encontrado al ejercitar verde/rojo por primera vez)

La primera versión de `_condicion_de_repeticion()` (en el runner) leía
`eventos_servidor.csv` (`M2_rx.fase`) para no depender de `scripts/pi.sh
fetch` con config=pi-lan/pi-4g. Defecto: `agent/rsu_middleware.py::_publicar_m2()`
vuelve a consultar `get_status()` al publicar el M2; si la concesión de
prioridad fue **inmediata** (fase real "verde" o "rojo_general", ambas
fuera de `FASES_NO_INTERRUMPIBLES`), para ese momento ya se llamó
`request_priority()` y el controlador fuerza a reportar "verde" — una
decisión real en "rojo_general" se veía igual que una en "verde" desde el
servidor. Solo el camino en cola (RF-06, fase amarillo/todo_rojo) se
clasificaba bien, porque ese M2 se publica ANTES de pedir prioridad.

Síntoma: la primera corrida `lazo_local` completó las 18 repeticiones
(tope) reportando en vivo `{verde: 13, ambar_todo_rojo: 5, rojo_general:
0}` — parecía una recaída del defecto del controlador. Verificado contra
el evento de decisión real del lado de la RSU
(`eventos_rsu_1.csv::snmp_set_tx.fase`, el mismo campo que ya usaba
`scripts/analisis/lazo_centralizado.py`): la distribución real era
`{verde: 8, ambar_todo_rojo: 5, rojo_general: 5}` — la cuota ya estaba
cubierta desde la repetición 14. El controlador y el middleware se
comportaron bien; el error era solo del clasificador nuevo. Corregido
para leer el evento de decisión del lado RSU (con fetch incremental de
`scripts/pi.sh fetch` para config=pi-lan/pi-4g, no solo al final de la
campaña). Corrida descartada (dato válido pero conteo en vivo/`config.json`
incorrectos) y repetida — ver `_descartadas/NOTA.md` sección 6.

### 3. `t_verde`/anticipación real sin dato para llegadas en verde (encontrado al re-correr con el clasificador ya corregido)

Con la clasificación corregida, las paradas `verde` seguían sin
`t_verde_ms`/`anticipacion_real_s`: `analizar()` busca el inicio de verde
como un evento `ctrl_fase_cambio` con `fase="verde"` logueado para esa
parada, pero `controller_emulator.py::_log_si_cambio_locked` solo loguea
cuando la fase REALMENTE cambia — si la decisión ya fue en verde
(concesión inmediata, sin transición), no hay nada que loguear. Esto es
el primer caso real desde que se corrigió el controlador (antes el 100 %
de las decisiones caía en "amarillo", así que esta rama de código nunca
se había ejercitado con datos reales). No es un defecto del middleware.
Corregido en `analizar()`: si `fase_decision == "verde"` y no hay evento
de transición, se usa el instante de la propia decisión como referencia
de "verde" (t_verde = 0 por construcción, coherente con que ya estaba en
verde).

## Seguimiento (mismo día, el autor fuera de casa — laptop y Pi solo conectadas por Tailscale, NO en la misma LAN)

Tres pedidos de cierre antes de dar la campaña por buena. **Solo
diagnóstico de solo lectura en la Pi** (journalctl, chrony, `ip route`,
`scripts/pi.sh red estado`) — ninguna campaña `pi-*` se volvió a correr, y
no se tocó configuración de red ni se reinició ningún servicio en la Pi
(el autor no tiene forma de recuperarla hasta volver a la misma red).

### 1. Causa de la pérdida de NTP en `desvio_pi-lan`

**No fue una caída de Wi-Fi.** Evidencia (ventana de la corrida,
02:34:38–03:10:21):

- `journalctl -u NetworkManager.service` en esa ventana: **0 eventos**
  (solo renovaciones de lease DHCP normales cada 30 min, mismo IP).
- `journalctl -u wpa_supplicant.service`: solo el "WPA: Group rekeying"
  normal de cada 1 h (protocolo estándar, no una reconexión).
- `journalctl -k` (kernel) filtrado por `wlan0|usb0|link`: **0 líneas**.
- `ip route` al inicio y al fin de la corrida: `wlan0` siempre con
  métrica 600 (ruta por defecto preferida) y `usb0` siempre con métrica
  900 (respaldo, no usado). Contadores de `usb0` subieron solo ~11.4 KB
  RX / ~3.2 KB TX en 36 min — consistente con tráfico de fondo del módem
  (keepalive, etc.), no con el volumen real de una campaña (cientos de
  mensajes MQTT/SNMP). **El enlace fue Wi-Fi todo el tiempo.**

**Causa real: `journalctl -u chrony.service`** muestra "Can't synchronise:
no majority" a las 03:05:24 (dentro de la ventana) — pero visto en un
rango más amplio (00:00–06:00), el mismo patrón "no majority" / "Selected
source" se repite cada ~15–45 min **durante TODA la tarde**, sin relación
con la campaña ni con ningún evento de red. `/etc/chrony/conf.d/rsu-lab.conf`
en la Pi fija exactamente **2** fuentes NTP
(`time.cloudflare.com`, `time.google.com`, elegidas a propósito para
comparar contra la misma referencia que usa la laptop, ver el comentario
en ese archivo) — con solo 2 fuentes, el algoritmo de "mayoría" de chrony
no tiene con qué desempatar si discrepan transitoriamente, así que pierde
sync con cualquier jitter normal de red pública. Esto es **recurrente, no
un incidente aislado** de esta corrida.

Según lo acordado: como el enlace fue Wi-Fi todo el tiempo, la corrida
`desvio_pi-lan` del 2026-10-29 sigue siendo válida como "pi-lan", pero se
repetirá de todas formas (con chrony sincronizado) cuando el autor esté
de vuelta en la misma red — **queda pendiente, no se repitió hoy**.

**Análisis corregido** (sin tocar la Pi): una corrida con pérdida de
sincronización ya no se marca "NO CUMPLE" sino **"no evaluable (reloj sin
sincronizar)"**, conservando sus métricas de un solo reloj (RTT_srv,
t_RSU) y el valor medido de L (solo se suspende el *veredicto* de
RNF-01, no la medición). `scripts/analisis/lazo_centralizado.py`:
`reloj_pi_sincronizado()`/`reloj_pi_sincronizado_de_dirs()` (detectan
`Leap status : Not synchronised` / `Stratum : 0`, el centinela de
chrony) y `rnf01_veredicto_peor_caso` (nuevo campo:
`"CUMPLE"`/`"NO CUMPLE"`/`"no evaluable (reloj sin sincronizar)"`/`"sin
cota de reloj"`). `tabla_latencia.tex` ahora muestra "no sincronizado" en
vez de "1500.0 ms" en la columna de cota. Regenerado
`resultados/campana/_figuras_2026-10-29_local_vs_pi-lan/`.

**Preparado para la próxima campaña `pi-*` (sin correrlo)**:
`scripts/campanas/lazo_centralizado.py` ahora, para config=pi-lan/pi-4g:
(a) pre-vuelo `_verificar_chrony_sincronizado()` — aborta ANTES de
lanzar nada si la Pi ya está desincronizada en ese momento; (b) muestreo
por repetición (`_reloj_pi` + `_chrony_sincronizado`, guardado en
`rep_XX/chronyc_tracking.txt` y en
`config.json::chrony_sincronizado_por_repeticion`) — **marca, no
aborta** a mitad de campaña (perder 18 repeticiones por un hueco de NTP
de minutos sería peor que marcarlo). `reloj_pi_sincronizado_de_dirs()`
ya lee ese campo nuevo además de `reloj_pi_inicio`/`reloj_pi_fin`.

### 2. Anticipación faltante en `desvio`: la cancelación por desvío pisa la detección de cruce

Comprobado con las 36 repeticiones `desvio` ya corridas (18 `local` + 18
`pi-lan`): **3/18 `local` y 0/18 `pi-lan`** terminan con
`ultimo_m3_motivo="cruce"`; el resto, **15/18 y 18/18**, terminan en
`"desvio"` — coincide exactamente con el conteo de anticipación real
faltante (3 y 0 respectivamente).

**Mecanismo, con datos reales** (`servidor/gestor_mision.py::procesar_mp`,
línea ~232): por cada posición MP, el servidor primero calcula la
distancia perpendicular a la ruta planeada; si supera `UMBRAL_DESVIO_M`
(60 m), llama a `_recalcular_por_desvio` (que cancela con
`motivo="desvio"` cualquier parada que ya no esté en la ruta nueva) **y
hace `return` de inmediato** — la detección de cruce
(`mision.seguidor.actualizar(...)`, que es la que puede emitir
`motivo="cruce"`) NUNCA se evalúa para esa posición si el desvío ya
disparó.

El problema es que, en `scripts/campanas/fixtures/trayectoria_desvio_base.csv`,
**el desvío empieza casi exactamente en la posición del RSU** ("C", lat
-12.1074): el último punto sobre la ruta original está ~10–20 s antes del
desvío, y a 36 km/h (10 m/s) con posiciones MP cada 2 s (20 m por
muestra), no hay ninguna muestra intermedia cerca de la línea de parada.
Con los eventos reales de la repetición `20261029-012758_desvio_local/rep_01`:

| Muestra | lat, lon | Distancia a la línea de parada (centro RSU) |
|---|---|---|
| MP seq=15 (última antes del desvío) | -12.1074901, -77.0320657 | **12.3 m, al sur** (todavía aproximándose) |
| MP seq=16 (primera con desvío detectado) | -12.1072886, -77.0310415 | **104.9 m, al norte** (ya pasado) |

Y en una repetición donde SÍ se detectó el cruce primero
(`.../rep_06`, `mis-8983cd50`): el MP que dispara "cruce" está a **1.0 m**
de la línea de parada (prácticamente encima), y la SIGUIENTE muestra (2 s
después, ya con el desvío activo) está a 99 m, al norte. Es decir: el
margen entre "todavía antes" y "el desvío ya se disparó" es de UNA sola
muestra MP (2 s / ~20 m) — el resultado (`cruce` vs `desvio`) depende de
en qué lado de esa muestra caiga el ruido GNSS aplicado a cada
repetición, no de un diseño de trayectoria que deje al vehículo
claramente antes o después del RSU.

**Conclusión: es el caso DESPUÉS, no ANTES.** El vehículo, en términos
prácticos (posición muestreada), ya alcanzó/pasó la línea de parada en
~85–100 % de las repeticiones cuando se detecta el desvío — la
cancelación por desvío está pisando una detección de cruce que, de haber
tenido una muestra más de margen, habría disparado primero. No es que la
trayectoria se aparte mucho antes de llegar al RSU (eso sí sería
"cancelar correctamente una solicitud de un cruce que el vehículo ya no
va a atravesar").

**No se tocó `servidor/gestor_mision.py`** (pedido explícito). Dos
mecanismos posibles, a decidir:

- **(a) Ajustar la trayectoria** (sin tocar servidor/): mover el punto de
  desvío de `trayectoria_desvio_base.csv` BIEN DESPUÉS del RSU (p. ej.
  desde t=50 s en vez de t=30 s, dejando ~15 s / ~150 m de margen tras
  cruzar) para que el cruce se detecte y mida con normalidad, y el desvío
  pase a probar el recálculo de ruta DESPUÉS de que la única RSU del
  escenario ya fue atendida (coherente con el propósito declarado del
  escenario en el docstring del runner: "dispara el recálculo de ruta",
  no "cancela la parada pendiente"). Si en cambio lo que se quiere probar
  es el caso ANTES (desvío antes de llegar, cancelación de una parada no
  alcanzada), habría que mover el punto de desvío bien ANTES del RSU, con
  margen similar. Son dos escenarios de prueba distintos y hoy la
  trayectoria no deja claro cuál de los dos es.
- **(b) Ajustar el orden de evaluación en el servidor** (no aplicado,
  pedido explícito de no tocar `servidor/` sin consultar): evaluar la
  geocerca (cruce) ANTES que el umbral de desvío en `procesar_mp`, o no
  hacer `return` inmediato tras detectar desvío, para que un cruce real
  en la misma muestra no quede nunca sin evaluar. Esto sería más robusto
  frente a cualquier trayectoria futura con el mismo problema de margen,
  no solo la de `desvio` actual.

## Pendiente

- **Repetir `desvio_pi-lan`** (y, si se quiere la misma confiabilidad,
  también valdría la pena repetir `lazo_pi-lan` aunque esa no mostró
  pérdida de sync) cuando el autor esté de vuelta en la misma red que la
  Pi, con chrony sincronizado y el muestreo por repetición ya activo
  (preparado, sección 1 arriba).
- **[REVISAR con asesor]**: decidir si el escenario `desvio` debe probar
  el caso "antes" o "después" del cruce (sección 2) y ajustar
  `trayectoria_desvio_base.csv` en consecuencia — o decidir si además se
  quiere el cambio de orden en el servidor (opción (b)) para que sea
  robusto independientemente de la trayectoria.
- **[REVISAR con asesor]**: si vale la pena agregar una tercera o cuarta
  fuente NTP a `/etc/chrony/conf.d/rsu-lab.conf` en la Pi para que el
  algoritmo de mayoría de chrony sea menos frágil — es un cambio de
  configuración de la Pi, no se tocó hoy por la restricción de red.
- `ambar_todo_rojo` no cubrió la meta de 4 en las dos corridas `local`
  (3/4 y 2/4) — **se reporta así, tal cual, con el tope de 18
  repeticiones alcanzado** (decisión ya tomada, no es un defecto:
  variación estadística esperable para una condición que es ~24 % del
  ciclo). **[REVISAR con asesor]** si vale la pena repetir `local` con
  más repeticiones, dado que `local` sigue sin decidirse si entra a la
  tesis.
- Repetir contra `config=pi-4g` cuando corresponda, con el defecto del
  controlador, el clasificador y el chequeo de chrony ya corregidos/
  preparados desde el inicio.
