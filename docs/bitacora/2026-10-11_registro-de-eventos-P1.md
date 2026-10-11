# 2026-10-11 — Registro de eventos del lazo de priorización (P1, RF-10)

**Objetivo específico:** OE3 (instrumentación del middleware); sustenta directamente la "Instrumentación y registro de eventos" (`ssec:instrumentacion`, Capítulo IV) y la caracterización del canal V2I (`sec:car_v2i`).
**Requerimientos:** RF-10 ("Registrar cada evento del lazo de priorización con su marca de tiempo, para su evaluación posterior" — la numeración vigente en `main.tex`; `docs/PLAN_IMPLEMENTACION.md` lo llama RF-13, de antes de la fusión de OE5/OE6, ver nota de desalineación en `CLAUDE.md`).
**Sección de la tesis:** `ssec:mw_impl` (implementación del middleware); `ssec:instrumentacion` (Capítulo IV).
**Commit:** `455621d`

## Qué se implementó

- `common/events.py`: módulo compartido de registro de eventos en CSV
  (`ts_ns`, `nodo`, `tipo_evento`, `id_solicitud`, `extra_json`), con un
  `EventLogger` por nodo (archivo propio `eventos_<nodo>.csv`, nunca
  compartido entre procesos) y un lector `iter_eventos()` para el
  análisis posterior.
- Integrado en los tres procesos reales del banco de pruebas:
  - `gateway/obu_simulator.py`: genera `id_solicitud` (antes no existía
    en el simulador, aunque ya estaba en el diseño de M1 según
    `tab:mensajes`) y registra `M1_tx`.
  - `agent/rsu_middleware.py`: registra `M1_rx` y `snmp_set_tx` (este
    último representa, hasta que se implemente NTCIP 1211 real —
    `docs/PLAN_IMPLEMENTACION.md` P2/P3 —, el momento en que la RSU
    traduce la solicitud y la "escribe" hacia el controlador; se
    registra igual desde el camino V2I que desde el SET manual de
    `centro_control/software_gestion.py`, con un `id_solicitud`
    sintético para este segundo caso, ya que no viene de ninguna OBU).
  - `controller/controller_emulator.py`: registra `ctrl_fase_cambio`
    solo cuando la fase visible realmente cambia (deduplicado contra
    polls repetidos de `get_status`).
- `scripts/analisis/latencia_tramos.py`: cruza los eventos por
  `id_solicitud` y aproxima `t_V2I`, `t_RSU`, `t_NTCIP` y `L` según la
  ecuación de `ssec:latencia`. Documenta explícitamente, en su propio
  docstring, que es una cota inferior de `L` (no mide `t_adq` ni separa
  `t_OBU`) mientras el agente no implemente NTCIP real y la OBU no
  adquiera telemetría real.
- De paso, corrigió el bug de re-suscripción MQTT encontrado en el
  smoke test anterior (ver bitácora
  `2026-10-11_arranque-servicios-y-smoke-test.md`): `client.subscribe()`
  se movió al callback `on_connect`.

## Cómo

- Python 3.13 (laptop y Pi); sin dependencias nuevas (solo `csv`/`json`/
  `threading` de la biblioteca estándar).
- Prueba corrida en vivo contra la Pi (commit `455621d` desplegado,
  servicios reiniciados), no en un entorno aislado: ver
  `resultados/prueba_registro/notas.md` para el procedimiento exacto y
  `resultados/prueba_registro/config.json` para los parámetros.

## Desviaciones respecto del diseño de la tesis

Ninguna sobre el diseño del sistema. Una aclaración de alcance: los
tipos de evento `M2_tx`, `M2_rx`, `M3_tx` y `caducidad` quedaron
**definidos como constantes** en `common/events.py` pero **no se
registran todavía**, porque el código actual no implementa esas partes
del protocolo (el middleware no publica ninguna respuesta M2 hacia la
OBU; `obu_simulator.py` no implementa cancelación M3 ni manejo de
caducidad del lado de la OBU). No se fabricó ningún evento para code
paths que no existen. `M4_tx`/`M4_rx` (I2I) ni siquiera se dejaron como
constantes activas por la misma razón, más el hecho de que I2I no es un
objetivo específico vigente de la tesis (ver `CLAUDE.md`).

## Evidencia

`resultados/prueba_registro/`:
- `eventos_obu.csv`, `eventos_rsu_1.csv`, `eventos_ctrl_1.csv` — los tres
  archivos de eventos de la corrida.
- `latencia_tramos.csv` — salida de `scripts/analisis/latencia_tramos.py`.
- `config.json`, `notas.md` — parámetros y bitácora detallada de la
  corrida.

No se tomó captura de pantalla para este hito (toda la evidencia es la
salida de los propios scripts, ya en texto/CSV).

## Problemas y solución

- **`t_V2I_aprox_ms` dio negativo (−2.75 ms)** en la única solicitud de
  la corrida — físicamente imposible (M1_rx no puede ocurrir antes que
  M1_tx). Diagnóstico: `t_V2I` es el único de los tres tramos que resta
  una marca de tiempo de la laptop (`M1_tx`) de una marca de tiempo de
  la Pi (`M1_rx`); los otros dos tramos (`t_RSU`, `t_NTCIP`), calculados
  enteramente con marcas de tiempo de la Pi, salieron positivos y del
  orden de magnitud esperado (0.19 ms y 0.74 ms). Causa raíz: la
  sincronización de reloj de la laptop contra NTP (W32Time) sigue
  pendiente de aplicarse (bloqueada en la tarea anterior por falta de
  PowerShell elevado) — sin eso, cualquier tramo que cruce de una
  máquina a otra queda contaminado por el desfase de reloj, no solo por
  la latencia real de red. **No se "corrigió" nada en el código**: el
  cruce de eventos por `id_solicitud` funciona correctamente (se
  verificó que las cuatro filas correspondientes se alinearon bien);
  el problema es exclusivamente de sincronización de reloj entre
  máquinas, ya diagnosticado y con su solución ya entregada al
  estudiante en la tarea anterior.

## Pendiente

- Aplicar el fix de W32Time en la laptop (comandos ya entregados,
  requieren PowerShell como Administrador) y **repetir esta prueba**
  para confirmar que `t_V2I_aprox_ms` da un valor positivo razonable.
- Implementar el lado de respuesta del protocolo (M2 publicado por la
  RSU hacia la OBU) para poder registrar `M2_tx`/`M2_rx` y medir RTT,
  si se quiere esa métrica antes de llegar a P2/P3.
- Seguir con **P2** (`docs/PLAN_IMPLEMENTACION.md`): objetos reales de
  NTCIP 1202 y controlador emulado con ciclo de fases real.
