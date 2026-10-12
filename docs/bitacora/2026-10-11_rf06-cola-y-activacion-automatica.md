# 2026-10-11 — RF-06: cola (readyQueued) y activación automática en vez de rechazo

**Objetivo específico:** OE3 (middleware NTCIP)
**Requerimientos:** RF-06, RF-09, RNF-03
**Sección de la tesis:** `ssec:mw_1211`, `ssec:mw_limites`, `ssec:mw_impl`
**Commit:** `7017c87`

## Qué se implementó

Hasta P3, una solicitud de prioridad que llegaba mientras el controlador
estaba en `amarillo` o `todo_rojo` (intervalo de seguridad en curso,
restricción R-02) se **rechazaba** (`SolicitudRechazada`, motivo
`limite_operacional`). A pedido del asesor/estudiante, ese comportamiento
cambia: ahora la solicitud **se encola** (`readyQueued`, estado real de
`priorityRequestStatusInPRS` de la norma) y se **activa sola, sin
intervención externa**, en cuanto termina el despeje (el controlador pasa
a `verde` o `rojo_general`) — siempre que para ese momento la solicitud
siga vigente según el TTL de RF-09/RNF-03 (3 s). RF-05 (clase de vehículo
no reconocida) no cambia: sigue siendo un rechazo duro.

## Cómo

- **`agent/ntcip1211.py`** (lógica NTCIP pura, sin red):
  - `PriorityRequestServer.aceptar_solicitud()`: ya no levanta
    `SolicitudRechazada` por límite operacional. Si la fase es insegura,
    deja la fila en `READY_QUEUED` en vez de `ACTIVE_PROCESSING`.
  - Nuevo método `intentar_activar_cola(fase_actual)`: si la fila 1 está
    `READY_QUEUED` y la fase ya es segura, la pasa a `ACTIVE_PROCESSING` y
    renueva el TTL desde ese instante. Devuelve `None` si no hay nada que
    activar (sigue en despeje, o la fila no está en cola).
  - `verificar_caducidad()`: antes solo caducaba filas `ACTIVE_PROCESSING`;
    ahora también caduca filas `READY_QUEUED` que lleven más de
    `T_CAD_SEGUNDOS` sin que termine el despeje — el TTL es "vigencia de la
    solicitud", no solo "vigencia ya forzando el controlador".
  - `refrescar()`: ahora también refresca una fila `READY_QUEUED` (antes
    solo `ACTIVE_PROCESSING`), para que actualizaciones M1 repetidas de la
    misma solicitud mientras espera en cola no caduquen de forma espuria.
- **`agent/rsu_middleware.py`**:
  - `procesar_solicitud_prioridad()`: si la fila queda `READY_QUEUED`, YA
    NO reenvía `request_priority` al controlador — solo loguea y espera.
    El reenvío (`_reenviar_request_priority`, función nueva, compartida)
    se posterga hasta que el watchdog confirme la activación.
  - `verificar_caducidad_periodica()` (el watchdog, antes solo veía RF-09):
    ahora, en cada ciclo de 0.5 s, si no caducó y hay una fila en cola,
    consulta la fase actual del controlador (`get_status`) e intenta
    `PRS.intentar_activar_cola()`; si activa, recién ahí reenvía
    `request_priority`.
  - `PrgPriorityRequestAbsoluteInstance.setValue()`: sin cambios de código
    (ya no hace falta: `SolicitudRechazada` ya no se levanta por RF-06, así
    que el `SET` SNMP se acepta normalmente aunque la fila quede en cola;
    solo RF-05 o el controlador inalcanzable siguen devolviendo
    `wrongValue`). Se actualizó el comentario para reflejarlo.
  - Nuevo `_ULTIMO_ID_EVENTO` (protegido por `PRS_LOCK`): `agent/ntcip1211.py`
    es lógica NTCIP pura y no conoce el id de evento (string) de
    `common/events.py` — solo el `priorityRequestID` numérico 1..255. Sin
    esto, la activación tardía del watchdog habría logueado con un id de
    evento distinto al de la solicitud original, rompiendo el cruce en
    `scripts/analisis/latencia_tramos.py`.
- **`tests/test_ntcip1211.py`**: los dos tests que esperaban
  `SolicitudRechazada` durante `amarillo`/`todo_rojo` se reescribieron para
  verificar `READY_QUEUED`; se agregaron dos tests nuevos:
  `test_se_activa_al_terminar_el_despeje_dentro_del_ttl` (encola en
  `amarillo`, no activa mientras sigue en `todo_rojo`, activa al llegar a
  `verde`) y `test_caduca_en_cola_si_el_despeje_tarda_mas_que_el_ttl`
  (encolada más del TTL sin que termine el despeje → `closedTimeToLiveError`,
  y ya no se puede activar después). 17 tests en total, todos pasan.
- Probado en dos niveles, igual que P3:
  1. 17 tests unitarios (`tests/test_ntcip1211.py`).
  2. Integración local (controller/controller_emulator.py real en el
     puerto 19000, `agent.rsu_middleware` real con `CONTROLLER_PORT`
     apuntado ahí): confirma encolado en `amarillo`, activación automática
     al llegar a `rojo_general` dentro del TTL, y que RF-05 sigue
     rechazando duro.
  3. **SNMP real contra la Pi** (`192.168.18.175:1161`), con
     `phaseYellowChange`/`phaseRedClear` acortados temporalmente (vía SNMP,
     objetos RW ya existentes de NTCIP 1202) para que el despeje real del
     banco (normalmente 5 s: 3 s amarillo + 2 s todo rojo) quedara por
     debajo del TTL de 3 s y así poder demostrar también la activación
     automática en vivo, no solo el encolado. Se restauraron los valores
     originales al terminar.

## Desviaciones respecto del diseño de la tesis

`ssec:mw_limites` describía RF-06 como un rechazo. Con este cambio, la
restricción operacional (R-02, no interrumpir un intervalo de seguridad en
curso) sigue cumpliéndose igual — nunca se fuerza una transición durante
`amarillo`/`todo_rojo` — pero la solicitud ya no se pierde: queda vigente
y se sirve en cuanto es seguro hacerlo, dentro del TTL de RF-09. Falta
actualizar `ssec:mw_limites` (y la futura `ssec:mw_1211`, todavía
placeholder) para describir el nuevo comportamiento de cola en vez del
rechazo.

## Evidencia

- `evidencia/2026-10-11_tests_rf06-cola.txt`: los 17 tests unitarios,
  incluidos los 4 de `TestRF06LimitesOperacionales`.
- `evidencia/2026-10-11_agente_snmpset-aceptado-priorityrequesttable.txt`:
  caso base sin cambios — SET con fase ya segura (`rojo_general`) se
  activa de inmediato (`activeProcessing`), sin pasar por la cola.
- `evidencia/2026-10-11_agente_cola-amarillo-rf06.txt`: SET aceptado
  durante `amarillo` real del banco, y `snmpwalk` de `priorityRequestTable`
  mostrando la fila 1 en `readyQueued` (valor `2`) mientras el despeje
  sigue en curso.
- `evidencia/2026-10-11_agente_clase-rechazada-rf05.txt`: RF-05 (clase no
  reconocida) sigue devolviendo `wrongValue` de inmediato, sin crear fila
  ni en cola ni activa — confirma que este commit no lo afectó.
- `evidencia/2026-10-11_watchdog_rf06-timeline.txt`: línea de tiempo real
  (poll SNMP + `journalctl`) de la misma solicitud: encolada en `amarillo`
  (19:51:34) → activada sola al empezar `rojo_general` (19:51:36, dentro
  del TTL) → fuerza verde → caduca por RF-09 tres segundos después de
  activarse (19:51:39, nadie la refrescó) → el controlador libera.

## Problemas y solución

- **El despeje real del banco (5 s) es más largo que el TTL (3 s)**: con
  los tiempos de fase por defecto de la Pi (`phaseYellowChange=3.0s`,
  `phaseRedClear=2.0s`), una solicitud que llega al *inicio* de `amarillo`
  normalmente caducaría en cola antes de que termine el despeje — no es un
  bug, es el comportamiento esperado (la restricción R-02 no se puede
  violar solo porque alguien pidió prioridad, y el TTL de 3s es anterior a
  este cambio, no se modificó). Para poder demostrar también la activación
  automática con datos reales del banco (no solo con la integración local
  de tiempos arbitrarios), se acortaron temporalmente esos dos objetos NTCIP
  1202 (ya `RW` desde P2) a 1.0s cada uno vía SNMP, y se restauraron al
  terminar. Documentado explícitamente en cada archivo de evidencia donde
  aplica, para que no se confunda con un cambio permanente de la
  configuración del banco.
- **Pérdida del id de evento (string) al activar desde el watchdog**: la
  fila de `agent/ntcip1211.py` solo guarda el `priorityRequestID` numérico
  (1..255), no el id de `common/events.py` usado para cruzar eventos entre
  máquinas. Sin guardar aparte el último id de evento visto
  (`_ULTIMO_ID_EVENTO` en `agent/rsu_middleware.py`), la activación tardía
  se habría logueado con un id distinto al de la solicitud original,
  rompiendo `scripts/analisis/latencia_tramos.py` para este caso. Se
  decidió no mezclar esa noción en `agent/ntcip1211.py` (que es lógica
  NTCIP pura, sin saber nada de `common/events.py`) y resolverlo en la capa
  de `rsu_middleware.py`, que ya es quien conoce ambos mundos.

## Pendiente

- Actualizar `ssec:mw_limites` en `main.tex` para describir el encolado y
  la activación automática en vez del rechazo (sigue describiendo el
  comportamiento de P3).
- Redactar `ssec:mw_1211` (sigue como placeholder "PEGAR AQUÍ").
- Pendientes heredados de P3, sin cambios: confirmar el borrador NTCIP 1211
  contra la versión publicada (correo a NEMA sin respuesta), confirmar el
  mapeo de clases contra D.S. N.º 016-2009-MTC, agregar las columnas 11-14
  de `priorityRequestTable` si hacen falta.
- Continuar con **P4** (`docs/PLAN_IMPLEMENTACION.md`): CA propia, mTLS en
  Mosquitto, y decisión TLSTM frente a USM.
