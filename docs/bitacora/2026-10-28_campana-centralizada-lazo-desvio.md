# 2026-10-28 — Campaña lazo/desvío: local y RSU real (pi-lan, Wi-Fi); choque de client_id y exclusión de "conflicto"

**Objetivo específico:** OE5 (campaña de medición del lazo, `config=local` y `config=pi-lan`)
**Requerimientos:** RNF-01 (latencia L), RF8 (anticipación real)
**Sección de la tesis:** 4.3–4.5 (campaña y resultados) / 3.9, 4.8 (limitaciones y trabajo futuro)
**Commit:** `2ea29d0` (fase local); `7bc1134`, `89801da`, `6a4c76b`, `e16258c`, `8593964`, `f68e87c` (fase pi-lan)

## Qué se implementó

Dos cosas separadas, no confundirlas:

1. **Diagnóstico y corrección de una campaña contaminada.** Las cinco
   corridas locales de hoy (tres de una sesión anterior, dos de esta)
   tenían entre 47 y 59 líneas `"Conectado al broker MQTT"` por
   repetición en `agent.log`, cuando debería haber exactamente **una**.
   Causa real: `rsu-agent.service` en la Pi, activo sin interrupción
   desde el 2026-10-11, con
   `/etc/systemd/system/rsu-agent.service.d/broker.conf` apuntando al
   broker Mosquitto de **esta laptop** (`MQTT_BROKER_HOST=100.121.77.97`,
   su IP Tailscale) con `RSU_ID=1` — el mismo `client_id`
   (`rsu-middleware-1`, `agent/rsu_middleware.py:845`) que usa cada
   agente local que lanza `scripts/campanas/lazo_centralizado.py` contra
   `127.0.0.1:1883` (el mismo broker físico). Mosquitto expulsa a quien
   tenía ese `client_id` cuando el otro se conecta: los dos agentes se
   expulsaban uno al otro en bucle, y las solicitudes que llegaban
   mientras el agente local estaba "afuera" del broker se perdían sin
   dejar ningún rastro en sus eventos (`sin_respuesta`). **No fue falta
   de memoria** — se verificó en el log antes de atribuir una causa, como
   se pidió.
2. **Exclusión del escenario `conflicto` de la campaña y del Capítulo 4**
   (decisión del autor, no un hallazgo técnico): es un caso demasiado
   específico para el alcance de esta tesis. El código
   (`servidor/conflictos.py`, el soporte en el runner y en el análisis)
   se conserva sin cambios y sigue verificado con
   `tests/test_conflictos.py`; solo se saca de la campaña de medición.

## Cómo

- **Diagnóstico** (sin cambiar código primero, como se pidió):
  - Procesos vivos en la laptop (`Get-CimInstance Win32_Process -Filter
    "name='python.exe'"`): ninguno huérfano en el momento de revisar (los
    pares que parecían duplicados eran el *launcher stub* de
    `.venv\Scripts\python.exe` en Windows —254 KB, relanza el intérprete
    real de `C:\Program Files\Python313\` como hijo— no dos campañas
    corriendo a la vez).
  - `scripts/pi.sh status agent rsu`: **activo**, reconectando cada ~2 s
    en vivo (`journalctl`, 19:39:14 → 19:39:33...), con el
    `broker.conf` ya descrito.
  - Log de Mosquitto: no existe. `mosquitto.conf` (ruta real
    `C:\Program Files (x86)\Mosquitto\mosquitto.conf`, no
    `C:\Program Files\mosquitto\` como dice `docs/ARRANQUE_BROKER_LAPTOP.md`
    — desviación menor, **[REVISAR]** corregir esa ruta en la doc) no
    tiene `log_dest`: no hay forma de citar literalmente
    "already connected"/"closing old connection". La reconexión cada 2 s
    capturada en la Pi es la evidencia directa.
  - Conteo exacto por repetición (`grep -c "Conectado al broker"
    rep_NN/agent.log`) en las cuatro corridas con agente local: entre 47 y
    59 por repetición, confirmando el choque en las cinco corridas de hoy
    (incluida `20261028-184751_conflicto_local`, aunque esa además está
    fuera de alcance por el punto 2).
- **Corrección aplicada:**
  - `scripts/pi.sh stop agent rsu` (2026-10-28 19:42) — detiene el agente
    de la Pi mientras se corren campañas `config=local`.
  - `scripts/campanas/lazo_centralizado.py`:
    `_verificar_sin_interferencia_local()` (nueva, se corre una vez al
    inicio si `config=local`): aborta si `CONTROLLER_PORT`/`SNMP_PORT` ya
    están ocupados (proceso huérfano) o si `rsu-agent.service` sigue
    activo en el host dado (mismo client_id); si no se puede verificar
    (Pi apagada/inalcanzable), avisa y continúa — no bloquea una prueba
    local solo porque la Pi no responde.
  - `_contar_conexiones_broker()` / `_verificar_una_sola_conexion()`
    (nuevas, se corren después de cada repetición): cuentan
    `"Conectado al broker"` en `agent.log`/`servidor.log` de esa
    repetición; abortan si hay más de una.
  - `tests/test_campana_runner.py` (nuevo): prueba el conteo y el
    chequeo en aislado con logs sintéticos (no se puede reproducir el
    choque real sin dos procesos de verdad).
- **Verificación de la corrección:** corrida de prueba (2 repeticiones,
  escenario `lazo`) después de detener el agente de la Pi: `agent.log`
  de ambas repeticiones con **1** conexión, no 47-59.
- **Exclusión de `conflicto`:** `docs/CRONOGRAMA.md` (decisión de alcance
  #2, tabla de avance OE4, S9), `docs/MEDICION_LATENCIA.md` (§8.3, nuevo
  banner en §8.6), y banners en los docstrings de
  `scripts/campanas/lazo_centralizado.py` y
  `scripts/analisis/lazo_centralizado.py::analizar_conflicto()`. Ningún
  código se borró.

## Redacción propuesta para la tesis (limitaciones / trabajo futuro)

**[REVISAR con asesor]**, texto exacto pedido por el estudiante, para
insertar en limitaciones/trabajo futuro (`main.tex`, sección a definir
por el estudiante — no se tocó `main.tex` en esta sesión):

> El servidor central incluye una lógica de arbitraje entre misiones
> simultáneas que solicitan accesos incompatibles de una misma
> intersección (`servidor/conflictos.py`), verificada mediante pruebas
> unitarias; su evaluación experimental queda fuera del alcance de este
> trabajo.

## Desviaciones respecto del diseño de la tesis

- La exclusión de `conflicto` de la campaña (punto 2 arriba) es una
  desviación de alcance explícita, no un hallazgo técnico — ya
  documentada en `docs/CRONOGRAMA.md`.
- `docs/ARRANQUE_BROKER_LAPTOP.md` tiene la ruta de instalación de
  Mosquitto equivocada (`C:\Program Files\mosquitto\`, debería ser
  `C:\Program Files (x86)\Mosquitto\`). **[REVISAR]** corregir esa ruta;
  no se tocó en esta sesión (fuera del pedido explícito).
- Mosquitto corre sin `log_dest`: no queda registro persistente de
  eventos del broker (conexiones, expulsiones). **[REVISAR con asesor]**
  si vale la pena agregarlo antes de la campaña con hardware real
  (ayudaría a diagnosticar justo este tipo de problema sin depender de
  los logs del lado del cliente).

## Evidencia

- `resultados/campana/_descartadas/` con `NOTA.md`: las cinco corridas
  contaminadas y/o fuera de alcance, con el motivo de cada una.
- Corrida limpia, con el agente de la Pi detenido y los chequeos nuevos
  activos: `resultados/campana/20261028-195302_lazo_local/` y
  `resultados/campana/20261028-201105_desvio_local/` (10 repeticiones
  c/u). Confirmado `grep -c "Conectado al broker" rep_NN/agent.log` = 1
  en las 20 repeticiones (antes: 47-59).
- Resultado: **0 `sin_respuesta` en las dos corridas** (10/10 concedidas
  cada una) — el choque de client_id era, en efecto, toda la causa; no
  hizo falta investigar ninguna otra causa en los logs porque no quedó
  ningún caso sin explicar.
- `resultados/campana/_figuras_2026-10-28/`: `fig_rtt_cdf`, `fig_tramos`,
  `fig_comparacion` (.pdf/.png) y `tabla_latencia.tex`, comparando `lazo`
  vs. `desvio` (`scripts/analisis/graficos_campana_centralizada.py`).
  Resumen (un solo reloj, `config=local`):

  | Métrica | lazo (mediana / p95 ms) | desvío (mediana / p95 ms) |
  |---|---|---|
  | RTT_srv | 18.80 / 35.14 | 17.23 / 41.06 |
  | t_RSU | 3.65 / 18.20 | 3.07 / 24.13 |
  | L (RNF-01) | 4.86 / 18.76 | 3.67 / 24.64 |

  RNF-01 (`L` p95 ≤ 1000 ms) **CUMPLE** en ambos escenarios, con amplio
  margen (p95 real ~20-25 ms). `desvio` no tiene anticipación real
  medible (`n=0`): mismo comportamiento que la corrida de referencia del
  2026-10-22, no es una regresión de esta sesión — pendiente de entender
  por qué (**[REVISAR]**, no investigado a fondo en esta sesión).

## Problemas y solución

Ver "Cómo" arriba (es el mismo contenido: síntoma, causa, corrección).

## Fase 3 — `config=pi-lan`: RSU real por Wi-Fi vía Tailscale

**PARADA 1 confirmada: opción A** (broker en la laptop + Pi por Wi-Fi vía
Tailscale, sin cambios de red en la Pi). La opción B (Ethernet con perfil
propio, distinto de `netplan-eth0`) queda como posible extensión futura,
no implementada.

### Qué se hizo

1. `scripts/pi.sh deploy rsu` (`fa14ebe → 7bc1134`, 2 semanas de commits
   atrasados en la Pi — el agente real corría con código viejo todo este
   tiempo) → `restart controller`/`restart agent` → `status` de ambos:
   activos.
2. Verificación previa (ya automática en el runner, además de la manual
   pedida): sin agente/controlador huérfano en la laptop; `rsu-agent`/
   `rsu-controller` activos en la Pi; `scripts/pi.sh tailscale-ping rsu`
   → `direct 192.168.18.220` (camino LAN, no DERP); `scripts/pi.sh red
   estado` → `wlan0` como ruta por defecto (modo normal, no 4G).
3. Campaña `--config pi-lan`, `lazo` y `desvio`, 10 repeticiones c/u.

### Dos bugs nuevos, encontrados y corregidos en el camino (ninguno es memoria ni client_id)

1. **`_pi_sh()` resolvía al bash de WSL, no al de Git Bash.**
   `subprocess.run(["bash", ...])` sin ruta explícita podía resolver a
   `C:\Windows\System32\bash.exe` (el lanzador de WSL) según el PATH que
   ve el proceso de Python — no el de una terminal interactiva. WSL no
   tiene el mismo `~/.ssh/config` ni resuelve rutas Windows igual: toda
   verificación contra la Pi (`_verificar_pi_activa`, `_estado_red_pi`,
   etc.) caía en silencio en la rama de "no se pudo verificar" desde
   siempre, sin que nadie lo notara porque `config=local` nunca necesitó
   que esas verificaciones funcionaran de verdad. Corregido: ruta
   explícita a Git Bash + `encoding="utf-8"` (otro problema aparte:
   `systemctl status` imprime "●"/"○" y el locale de Windows no los
   decodifica).
2. **Primera corrida real: 100 % `sin_respuesta` ("m1_tx_sin_m1_rx").**
   Investigado en los eventos (no asumido): el servidor (laptop) se
   conectó, con éxito, al Mosquitto **propio de la Pi**
   (`--broker-host 100.105.28.51`, siguiendo lo que decía el docstring
   del runner), mientras el agente real de la Pi está conectado, desde
   `docs/ARRANQUE_BROKER_LAPTOP.md`, al Mosquitto **de la laptop**
   (`deploy/systemd/rsu-agent.service.d/broker.conf`:
   `MQTT_BROKER_HOST=100.121.77.97`). Dos brokers Mosquitto
   independientes y activos (el de la Pi sigue instalado y corriendo,
   sin uso real) — el M1 se publicaba en uno y nadie lo escuchaba del
   otro lado. El docstring del runner describía un diseño ("broker en
   cada RSU") que nunca se desplegó así; se corrigió para describir la
   realidad desplegada (broker en la laptop, en los tres `config`), con
   nota `[REVISAR con asesor]` si se prefiere cambiar el despliegue en
   vez de la documentación. Con `--broker-host 127.0.0.1`: **0
   `sin_respuesta`** en las dos corridas rehechas.
3. **(Menor) `offset_confiable()` confundía el margen de error de
   `chronyc` con el offset real.** La regex agarraba el primer número
   seguido de "ms" — en la práctica, casi siempre el margen `+/- 50ms`,
   no el offset real (`-8608us`, otra unidad). Marcaba "no confiable"
   corridas con sincronización excelente. Corregido para anclar al valor
   justo antes del corchete de `chronyc sources -v`, con su unidad real.

### Resultado final (corridas limpias, re-hechas con los tres bugs corregidos)

- `resultados/campana/20261028-212725_lazo_pi-lan/` y
  `resultados/campana/20261028-214736_desvio_pi-lan/`: **1** conexión al
  broker por repetición (20/20), **0 `sin_respuesta`** (20/20
  concedidas).
- `lazo` (pi-lan): offset de reloj confiable en toda la corrida. RTT_srv
  mediana 9.44 ms (p95 15.66); `t_RSU` mediana 1.08 ms (p95 1.37); `L`
  (RNF-01) mediana 10.41 ms (p95 10.81, **CUMPLE** vs. 1000 ms);
  anticipación real mediana 10.56 s (RF8 = 8.0 s). **[ACLARACIÓN
  2026-10-28, revisión de figuras]**: este `L` p95 = 10,81 ms es SOLO del
  escenario `lazo` (n=10). `tabla_latencia.tex` y `fig_tramos` de
  `_figuras_2026-10-28_local_vs_pi-lan/` reportan `lazo`+`desvio`
  combinados (n=20, pedido así para esa figura comparativa) y dan `L`
  pi-lan p95 = 15,77 ms, no 10,81 ms — es el mismo dato con distinto
  agrupamiento, no una discrepancia. No confundir los dos números al
  citar en el Capítulo 4; usar 15,77 ms si se cita la figura/tabla
  combinada, 10,81 ms si se cita el escenario `lazo` aislado.
- `desvio` (pi-lan): offset de reloj confiable al inicio, **no
  confiable al final** (deriva real de ~12 ms sobre el umbral de 10 ms,
  no un bug — el propio chronyc lo reportó así) → `L`/anticipación real
  excluidas para esa corrida por la política ya documentada (sección
  8.4); `RTT_srv`/`t_RSU` (un reloj, válidas siempre) mediana 10.33/1.04
  ms.
- Comparación `local` vs. `pi-lan` (ambos escenarios combinados, 20
  paradas c/u):

  | Métrica (un reloj) | local (mediana/p95 ms) | pi-lan (mediana/p95 ms) |
  |---|---|---|
  | RTT_srv | 18.80 / 35.22 | 9.78 / 19.25 |
  | t_RSU | 3.65 / 18.20 | 1.06 / 1.14 |

  `pi-lan` salió **más rápido** que `local`, al revés de lo intuitivo —
  hipótesis más probable: en `config=local` los CUATRO procesos
  (servidor, controlador, agente, OBU) compiten por CPU en la MISMA
  laptop, mientras que en `pi-lan` el controlador/agente corren en la Pi
  (su propio CPU) y la laptop solo corre servidor+OBU. **[REVISAR]**: no
  se investigó a fondo, dejar como observación, no como conclusión
  cerrada.
- Figuras y tabla: `resultados/campana/_figuras_2026-10-28_local_vs_pi-lan/`.
- `rsu-agent.service` se dejó **activo** al terminar (estado normal de
  servicio).

### Limitación explícita del enlace (pedida, no inferida)

`config.json` de cada corrida `pi-lan` ahora registra
`enlace_rsu_descripcion` ("Wi-Fi (wlan0 de la Pi) alcanzado por
Tailscale -- 'pi-lan' es el nombre genérico del código, NO una conexión
Ethernet cableada"), `enlace_rsu_ip` (`192.168.18.176`, parseada de
`ip route`), `enlace_laptop` (detectado: `Wi-Fi (interfaz 'Wi-Fi')` —
**la laptop también estaba por Wi-Fi hoy**, ningún tramo de esta
medición es cableado) y `limitacion_enlace`
**[REVISAR con asesor]** con ese texto completo.

## Fase 4 — Revisión del análisis: cota de reloj, encuadre local/pi-lan, anticipación real

Tres correcciones al análisis, pedidas tras revisar la Fase 3, **sin
volver a correr ninguna campaña** (solo se reanalizaron los datos ya
recolectados, y se corrió UNA repetición adicional, descartada, solo
para medir uso de CPU).

### 1. `offset_confiable()` confundía el margen de error con el offset

**Correcto, confirmado con `chronyc tracking` real** (ver más abajo): el
campo `+/- zzzz` de `chronyc sources -v` que se usaba como "el offset" en
la versión del 2026-10-28 anterior a esta revisión es, según el propio
texto de ayuda de `chronyc` (`sources -v`, encabezado `zzzz = estimated
error`), la **cota de error declarada** de esa medición puntual — no un
margen cosmético a ignorar, y tampoco el offset en sí (ese es `xxxx`/
`yyyy`, antes del `+/-`).

Salida real de `chronyc tracking` en la Pi, pedida para esta revisión
(fuera de la ventana de la campaña, como caracterización del orden de
magnitud típico — las corridas `pi-lan` ya hechas no tienen este campo
capturado, solo `sources -v`):

```
Reference ID    : D8EF2300 (time1.google.com)
Stratum         : 2
System time     : 0.000363231 seconds slow of NTP time
Last offset     : +0.000125032 seconds
RMS offset      : 0.001115581 seconds
Root delay      : 0.038743746 seconds
Root dispersion : 0.004902852 seconds
Leap status     : Normal
```

Campo leído para la cota: **`Root dispersion + Root delay / 2`** (la
fórmula estándar de NTP para la distancia de sincronización) ≈ 4,9 ms +
19,4 ms ≈ **24,3 ms** — del mismo orden que el `+/- 50ms` de `sources -v`
que ya se venía usando, confirmando que NO era un error ignorar ese
campo; el error estaba en comparar esa cota contra un umbral fijo de
10 ms para decidir si **excluir por completo** la métrica, en vez de
reportarla con la cota adjunta.

**Corregido:**
- `scripts/pi.sh clock` ahora captura `chronyc tracking` además de
  `sources -v` (de aquí en adelante; las corridas ya hechas solo tienen
  `sources -v`).
- `scripts/analisis/lazo_centralizado.py`: `cota_reloj_pi_ms()` reemplaza
  a `offset_confiable()`; `analizar()` ya NO excluye `t_OBU_srv`,
  `t_srv_RSU`, `L`, `t_verde`, anticipación real por un umbral — se
  calculan siempre que haya datos, y `cota_reloj_pi_ms` (más
  `l_p95_peor_caso_ms` / `rnf01_cumple_p95_peor_caso`) se agregan al
  resumen. `tabla_latencia.tex`/`fig_tramos` (en
  `graficos_campana_centralizada.py`) ahora muestran la cota junto a
  cada métrica de dos relojes.
- RNF-01 se reporta como **peor caso**: `L_p95_medido + cota_reloj_pi_ms`
  contra el umbral de 1000 ms. Ejemplo (`pi-lan`, `lazo`): L p95 medido
  10,81 ms + cota 52 ms = 62,81 ms ≪ 1000 ms → **CUMPLE** con amplio
  margen incluso así.
- **[REVISAR con asesor] se mantiene**: la laptop sincroniza por W32Time,
  sin un campo equivalente a "Root dispersion" — la cota reportada es
  SOLO del lado de la Pi.
- Ver `docs/MEDICION_LATENCIA.md` sección 8.4 (reescrita) para el detalle
  completo y la justificación.

### 2. Encuadre `local` vs. `pi-lan`

Confirmado con los propios datos (sección 8.7 nueva de
`docs/MEDICION_LATENCIA.md`): `pi-lan` salió más rápido que `local` en
RTT_srv/t_RSU, señal de que `local` no puede leerse como "el lazo sin el
costo de la red" — probablemente es contención de CPU entre los cuatro
procesos del lazo corriendo a la vez en la misma laptop.

Evidencia de respaldo, barata (una repetición adicional de `lazo` en
`config=local`, muestreando `Win32_Processor.LoadPercentage` cada 1 s
durante toda la repetición; **descartada del dataset oficial, solo
diagnóstica**): promedio 9,6 %, **máximo 42 %** del sistema completo (4
núcleos / 8 procesadores lógicos, Intel i5-9300HF) — consistente con
picos de contención, pero **no concluyente**: es un promedio de TODO el
sistema, no por proceso ni por núcleo, así que no aísla cuánto de ese
pico es de los 4 procesos del lazo. Se registra como evidencia parcial,
no como prueba.

Propuesta de redacción (Capítulo IV, **[REVISAR con asesor]**, no
aplicada a `main.tex`): `pi-lan` como configuración de **referencia**
del canal V2I; `local` solo como **banco de desarrollo**, fuera de la
figura principal de latencia, y si se muestra, siempre con esta
limitación explícita — nunca como cota inferior/superior comparable a
`pi-lan`/`pi-4g`.

### 3. Anticipación real (RF8) para `pi-lan`

Ya aparece en `tabla_latencia.tex` y en `fig_tramos` (nota al pie con la
cota) tras quitar la exclusión por umbral del punto 1 — n=10 (viene
íntegramente del escenario `lazo`; `desvio` sigue dando n=0 tanto en
`local` como en `pi-lan`, mismo comportamiento ya conocido de la
corrida de referencia del 2026-10-22, sin relación con la cota de reloj).
Mediana 10,56 s / p95 10,97 s, cota 58 ms — RF8 exige ≥ 8,0 s, se cumple
con margen.

### Evidencia (Fase 4)

- `resultados/campana/_figuras_2026-10-28_local_vs_pi-lan/` regenerada
  con la nueva metodología (tabla con columna "Cota reloj (Pi)" y
  anticipación real para `pi-lan`).
- Los cuatro `lazo_resumen.json` ya comiteados (`20261028-195302_lazo_local`,
  `20261028-201105_desvio_local`, `20261028-212725_lazo_pi-lan`,
  `20261028-214736_desvio_pi-lan`) se regeneraron con los campos nuevos.

## Fase 5 — Revisión de figuras: desglose por tramo, cota real por corrida, overlap de texto

Tres correcciones a `scripts/analisis/graficos_campana_centralizada.py`
pedidas tras revisar visualmente los PNG de la Fase 4 (sin volver a correr
ninguna campaña, solo regenerar figuras desde los datos ya analizados):

1. **`L` pi-lan vacía en una versión anterior de la tabla**: era el
   síntoma de un estado previo a la Fase 4 (commit `f68e87c`, antes de
   quitar la exclusión por umbral de reloj); el estado actual (commit
   `65c7aed` en adelante) ya trae `L` pi-lan con `n=20` y su cota — ver la
   aclaración agregada arriba, en el bloque de `lazo` (pi-lan). No hubo
   que corregir código para esto, solo reconciliar la cifra de la
   narrativa (10,81 ms, solo `lazo`) con la de la tabla/figura combinada
   (15,77 ms, `lazo`+`desvio`).
2. **`fig_tramos` ahora desglosa por tramo real de la arquitectura
   centralizada** (antes solo mostraba `t_RSU` y `L`): `t_srv` (cola en
   el servidor antes de M1, un reloj), `t_srv→RSU` (red servidor→RSU, dos
   relojes), `t_RSU` (procesamiento en la RSU, un reloj), `t_retorno`
   (RSU→servidor hasta M2_rx, derivado = RTT_srv − L, dos relojes). Los
   tramos de dos relojes se marcan con trama rayada y "†" SOLO cuando la
   corrida de esa etiqueta de verdad cruza máquinas (`cota_reloj_pi_ms` ≠
   0): en `config=local` los cuatro procesos comparten el reloj del
   sistema operativo, así que no se marcan — evita un falso positivo de
   incertidumbre que la primera versión de este cambio sí tenía (probado
   contra `_figuras_2026-10-28`, donde ambas etiquetas son `local`, antes
   y después del ajuste). `L` en sí ya no se grafica en `fig_tramos`:
   sigue en `tabla_latencia.tex` con su cota.
3. **`fig_comparacion` tenía la nota (`--nota`) incrustada en el PNG
   superpuesta con las etiquetas del eje x.** Se quitó esa nota (y la de
   `fig_tramos`) del PNG; ambas quedan en un `notas_figuras.txt` nuevo,
   junto a las figuras, con el texto listo para copiar al `\caption` de
   LaTeX (que es donde corresponde, no incrustado en la imagen).

### Evidencia (Fase 5)

- `resultados/campana/_figuras_2026-10-28/` y
  `resultados/campana/_figuras_2026-10-28_local_vs_pi-lan/` regeneradas
  con el script corregido; `tabla_latencia.tex` de ambas sin cambios de
  contenido (mismos números, mismo formato de tabla). PNG revisados
  visualmente: sin texto superpuesto, desglose por tramo legible, marcado
  de cruce de reloj correcto por corrida.
- `notas_figuras.txt` nuevo en ambas carpetas de salida.

## Pendiente

- Corregir la ruta de instalación de Mosquitto en
  `docs/ARRANQUE_BROKER_LAPTOP.md` (`C:\Program Files\mosquitto\` →
  `C:\Program Files (x86)\Mosquitto\`).
- Evaluar agregar `log_dest` a `mosquitto.conf` antes de la campaña con
  hardware real.
- **[REVISAR con asesor]**: decidir si el diseño final quiere un broker
  por RSU (como asumía el docstring viejo del runner) o centralizado en
  la laptop (lo que de verdad hay desplegado hoy, siguiendo
  `docs/ARRANQUE_BROKER_LAPTOP.md`). Si se opta por centralizado, el
  Mosquitto de la Pi (activo, sin uso) podría desactivarse.
- **[REVISAR con asesor]**: decidir si `local` entra o no a la tesis, y
  con qué encuadre (sección 8.7 de `docs/MEDICION_LATENCIA.md`) — la
  hipótesis de contención de CPU tiene evidencia parcial, no una
  medición por proceso/núcleo que la confirme de forma concluyente.
- `desvio` sigue sin anticipación real medible (`n=0`) tanto en `local`
  como en `pi-lan` — mismo comportamiento que la corrida de referencia
  del 2026-10-22, pendiente de entender por qué.
- Repetir contra `config=pi-4g` (módem 4G) cuando corresponda, con los
  mismos chequeos ya automatizados y `chronyc tracking` ya capturándose
  desde el inicio (no solo `sources -v`).
- Opción B de la PARADA 1 (Ethernet con perfil propio, distinto de
  `netplan-eth0`), si hay tiempo.
