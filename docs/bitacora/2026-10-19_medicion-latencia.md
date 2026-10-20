# 2026-10-19 — Documentar y corregir la medición de latencia del lazo

**Objetivo específico:** OE5  **Requerimientos:** RF-10, RNF-01
**Sección de la tesis:** `ssec:metricas` → `ssec:instrumentacion` (Capítulo IV)
**Commit:** (ver HEAD tras este commit)

## Qué se implementó
`docs/MEDICION_LATENCIA.md`: documento único de referencia sobre cómo se mide
la latencia del lazo (diagrama del lazo con los puntos de registro, tabla de
métricas con fórmula/reloj/confiabilidad, relación con `L = t_adq + t_OBU +
t_V2I + t_RSU + t_NTCIP <= 1 s` de `main.tex`, sincronización de relojes y
ajustes que afectan la medición). `scripts/analisis/lazo_emulado.py` ahora
separa explícitamente `L` (hasta la decisión de la RSU) de la espera del
despeje (`T_desp`), que antes quedaban mezcladas en `t_hasta_verde_ms`.

## Cómo
- `common/events.py`: dos tipos de evento nuevos, `EVT_MUESTRA` (`"muestra"`)
  y `EVT_BROKER_RX` (`"broker_rx"`).
- `gateway/obu_emulada.py`: registra `muestra` en cada fila de la trayectoria,
  antes de la decisión de geometría (para medir `t_OBU`).
- `scripts/testigo_broker.py` (nuevo): cliente MQTT que corre en la máquina
  del broker, se suscribe a `rsu/#`/`veh/#` y registra `broker_rx`, para
  estimar `t_up`/`t_down` (cota superior, declarado así en el docstring).
- `scripts/analisis/lazo_emulado.py`:
  - `L_ms` = primer `snmp_set_tx` con `accion` en {`request_priority`,
    `en_cola_despeje`} − `M1_tx(seq 1)`. Antes no existía como campo propio:
    `t_V2I_ms` y `t_RSU_ms` ya lo componían por separado, pero nada lo
    reportaba junto ni lo comparaba contra el umbral de RNF-01.
  - `T_desp_ms` (antes `espera_despeje_ms`, mismo cálculo, solo renombrado
    para que quede claro que es la contraparte de `L` en `T_act = L + T_desp
    + T_m`, no parte de `L`).
  - `t_hasta_verde_ms` → `t_hasta_verde_con_despeje_ms` (mismo cálculo,
    renombrado: incluye `T_desp` cuando la hubo, no es `L`).
  - `rtt_mitad_ms` (RTT/2 por solicitud): estimación del tramo de ida sin
    depender de sincronizar relojes.
  - `t_OBU_ms`, `t_up_ms`, `t_down_ms`: nuevos, `None` si faltan los eventos
    `muestra`/`broker_rx` correspondientes.
  - El resumen global agrega `rnf01_cumple_p95` (bool) y el reporte en
    consola compara el p95 de `L` contra los 1000 ms de RNF-01.
- `tests/test_lazo_emulado_analisis.py` (nuevo, 9 pruebas): eventos
  sintéticos para solicitud aceptada en verde, encolada en ámbar, rechazada
  (RF-05, sin `L`), `L` que no cumple RNF-01, `t_OBU` con y sin evento
  `muestra`, `t_up`/`t_down` con y sin testigo, y `rtt_mitad_ms`.

## Desviaciones respecto del diseño de la tesis
Ninguna: esto es instrumentación y análisis, no cambia el diseño del lazo.

## Evidencia
No aplica (sin captura de pantalla): el cambio es de documentación y de
scripts de análisis, verificado con pruebas automatizadas (ver "Cómo", 38
pruebas en total tras este cambio, `pytest tests/ -q`).

## Problemas y solución
- No hay ninguna corrida en `resultados/lazo_emulado/`: se revisó todo
  `resultados/` y los únicos `eventos_*.csv` existentes son de la campaña
  legada (`gateway/obu_simulator.py`, sin `seq` en `M1_tx`) o transcripciones
  del recorrido manual de `docs/bitacora/2026-10-19_lazo-obu-emulada.md`
  (tampoco guardadas con `--repeticiones` vía
  `scripts/campanas/lazo_emulado.py`). No se generó una corrida nueva en esta
  sesión: no hay Mosquitto instalado en este entorno, y un *broker* MQTT
  sustituto sin soporte de MQTT 5 (Response Topic/Correlation Data) no
  reproduciría fielmente el mecanismo de M2 ni el cálculo de RTT —
  corresponde correrlo contra un *broker* real (ver sección 7 de
  `docs/MEDICION_LATENCIA.md`).
- El guion de prueba inicial (`tests/test_lazo_emulado_analisis.py`) usaba
  `tipo` como nombre de parámetro posicional y como `kwarg` de un evento a la
  vez (`TypeError: multiple values for argument 'tipo'`); se renombró el
  parámetro posicional a `tipo_evento`.

## Pendiente
- Correr `scripts/campanas/lazo_emulado.py --factor 1` contra un *broker*
  real (Mosquitto, con `set_tcp_nodelay true`) y analizarla, para tener una
  corrida real con la que completar `ssec:instrumentacion`/`ssec:metricas`
  del Capítulo IV con cifras genuinas.
- Correr `scripts/testigo_broker.py` en esa misma campaña para obtener
  `t_up`/`t_down` por primera vez.
- `t_adq` (OBD-II/GNSS real) sigue sin instrumentar: depende de
  `gateway/obd_reader.py`, que no existe todavía (plan documentado en
  `docs/MEDICION_LATENCIA.md`, sección 6.4).
