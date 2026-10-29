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

## Pendiente

- **[REVISAR con asesor]**: política de cota de reloj ante pérdida de
  sync NTP de la Pi durante una corrida (ver "Evidencia", `desvio_pi-lan`,
  RNF-01 NO CUMPLE por la cota, no por latencia real). Capturar
  `chronyc tracking` más seguido antes de la campaña 4G.
- `ambar_todo_rojo` no cubrió la meta de 4 en las dos corridas `local`
  (3/4 y 2/4) — se aceptó por el tope de 18, pero si se quiere la cuota
  completa en `local` también, repetir esas dos con más repeticiones o un
  `--tope-repeticiones` mayor. **[REVISAR con asesor]** si vale la pena
  dado que `local` sigue sin decidirse si entra a la tesis.
- `desvio` sigue prácticamente sin anticipación real medible: `local`
  3/18 paradas, `pi-lan` **0/18** — contraste muy marcado con `lazo`
  (18/18 en ambos config). Mismo patrón ya documentado el 2026-10-22/
  2026-10-28 ("desvio sin anticipación real medible"), ahora con cifras
  más precisas gracias al desglose por condición, pero la causa sigue sin
  investigarse a fondo.
- Repetir contra `config=pi-4g` cuando corresponda, con el defecto del
  controlador y el clasificador ya corregidos desde el inicio.
