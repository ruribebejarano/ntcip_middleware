# 2026-11-01 — Retirar OBD-II del alcance y cerrar los pendientes B1-B6

**Objetivo específico:** OE4 (OBU), OE1 (arquitectura/cronograma), OE5 (campañas y Capítulo 4)
**Requerimientos:** RF-01/RF5 (adquisición de velocidad), RF-09/RNF-03 (caducidad de solicitudes), RF-10 (renovación), RF8 (anticipación), RNF-01 (latencia del lazo)
**Sección de la tesis:** 3.x (OBU, servidor, TLS/mTLS) → 4.x (campañas, resultados)
**Commits:** `48fae29`, `548ba27`, `b7365f9`, `f066e28`, `96beeec`, `d15da55`, `0e930f3` (en `master`), más `6196c39` y `002e911` en la rama/worktree `app-obu`.

Esta sesión no dejó su propia bitácora al cerrar; se reconstruye aquí a
partir de los mensajes y diffs de esos commits, siguiendo
`prompt_quitar_OBD2_y_pendientes.md`.

## Qué se implementó

**Parte A — retirar el lector OBD-II del alcance** (`48fae29`). La OBU pasa
a ser solo la app del operador en Android, con posición, rumbo y velocidad
del receptor GNSS del propio dispositivo (sin ELM327/Bluetooth SPP). Se
actualizaron comentarios y documentación (`README.md`, `docs/CONTRATO_OBU.md`,
`docs/CRONOGRAMA.md`, `docs/LAZO_EMULADO.md`, `docs/MEDICION_LATENCIA.md`,
`docs/PLAN_IMPLEMENTACION.md`, `gateway/obu_emulada.py`,
`gateway/obu_simulator.py`, `scripts/analisis/latencia_tramos.py`,
`servidor/gestor_mision.py`) sin tocar lógica; el lector queda como trabajo
futuro. La redacción (`redaccion/`, fuera de git) se actualizó por separado
con respaldo previo.

**Parte B, ítem por ítem:**

- **B1** (`548ba27`): `docs/CRONOGRAMA.md` al día tras el reporte R11
  (30/10) — mTLS contra un broker real y la Raspberry Pi física ya no
  estaban pendientes; se reubicó lo que sí sigue pendiente (campaña
  `pi-4g`, TLS en la app, Ethernet de la RPi) en S8-S10.
- **B2** (`b7365f9` en `master` + `6196c39` en `app-obu`): el servidor
  vuelve idempotente un MI para una misión ya armada del mismo `obu_id`
  (`armar_mision()` devuelve la misión existente y registra
  `MI_repetido`, sin mirar destino ni reenviar el MR — ver los huecos que
  deja esto, corregidos en el ítem 2 del prompt siguiente); la app guarda
  el último MI enviado y lo reenvía al reconectar MQTT, con los MP
  reanudándose solos.
- **B3** (`f066e28`): fin de misión por destino o tiempo máximo, según
  `app_obu/PROPUESTA_FIN_MISION.md`. `Mision.motivo_fin` nuevo, asignado en
  `desarmar_mision()` y expuesto en el ME junto con `mision_activa`;
  `procesar_mp()` cierra por destino contra `UMBRAL_LLEGADA_DESTINO_M` (= 20
  m, el valor más conservador disponible, `[REVISAR con asesor]`) antes de
  evaluar la geocerca.
- **B4** (`96beeec` en `master` + `002e911` en `app-obu`): `generar_ca.py`
  emite llaves PKCS#8 (antes PKCS#1) para que la app las parsee con
  `javax.crypto` puro; en la app, `TlsConfig` parsea los tres PEM (CA,
  certificado de cliente, llave) y `MqttObuClient` los conecta al builder de
  HiveMQ con `sslConfig()`. Sin probar contra un broker real ni en la
  tablet (no había hardware en esa sesión). Quedó documentado un problema
  de diseño abierto en `app_obu/README.md`: el certificado de cliente
  exige un CN fijo, pero el `obu_id` de la app es aleatorio por misión —
  resuelto recién en el ítem 2b de `prompt_integracion_app_obu.md`.
- **B5** (`d15da55`): no hizo falta código nuevo — la configuración
  `pi-4g`, el prevuelo de `chrony` y las figuras comparativas por etiqueta
  ya estaban implementados; solo se corrigió un docstring desactualizado
  de `scripts/campanas/lazo_centralizado.py` (`--repeticiones` ya no existe
  desde las cuotas adaptativas del 29/10).
- **B6** (`0e930f3`): `scripts/analisis/resumen_capitulo4.py`, que cuenta
  por corrida las solicitudes M1 iniciales, sus renovaciones (RF-10) y
  caducidades (RNF-03/RF-09), y genera `tabla_renovacion.tex`. Corrido
  contra las cuatro corridas válidas del 29/10
  (`resultados/campana/_figuras_2026-10-29_local_vs_pi-lan/`): cero
  caducidades en 72 repeticiones a velocidad real. El resto de B6 (los
  borradores `redaccion/capitulo4_resultados_campana.tex` y
  `redaccion/capitulo4_limitaciones_trabajo_futuro.tex`) se escribió en
  paralelo, fuera de git (no tiene commit propio).

## Cómo

- Repositorio principal `ntcip_middleware` en `master`; `app_obu/` se editó
  en el worktree `ntcip_app` (rama `app-obu`) y se trajo a `master` el
  2026-11-02 con `prompt_integracion_app_obu.md` (ítem 1, commits
  `20892b3` y `65efa7e`).
- `pytest` en `ntcip_middleware` y `gradlew testDebugUnitTest` en
  `ntcip_app/app_obu` en verde al cierre de cada parte (según las reglas
  del prompt); no se conservó la salida exacta de esas corridas en esta
  reconstrucción.

## Desviaciones respecto del diseño de la tesis

- El cierre de B2 fue parcial: la idempotencia del MI no mira el destino
  ni reenvía el MR/último ME, y no cubre la resuscripción tras una caída
  de sesión MQTT ni el descarte de MP viejos. Señalado explícitamente como
  pendiente al abrir `prompt_integracion_app_obu.md`.
- `UMBRAL_LLEGADA_DESTINO_M = 20 m` (B3) sigue provisional, `[REVISAR con
  asesor]`.
- B4 deja sin resolver el choque entre `obu_id` aleatorio por misión y el
  CN fijo del certificado mTLS — se marcó `[REVISAR]` en
  `app_obu/README.md` en vez de decidirlo en el código.

## Evidencia

- Reporte de cierre de la sesión (2026-11-01, 23:05) referenciado por
  `prompt_integracion_app_obu.md`; no se encontró un archivo de evidencia
  separado para esta sesión además de lo ya citado en cada commit.
- `resultados/campana/_figuras_2026-10-29_local_vs_pi-lan/tabla_renovacion.tex`
  y `resumen_renovacion.json` (B6).

## Problemas y solución

- Esta sesión no dejó bitácora al cerrar; se reconstruyó el 2026-11-02 a
  partir de `git log 48fae29^..0e930f3` y los commits de `app-obu`
  (`6196c39`, `002e911`) referenciados por el prompt siguiente, sin acceso
  a los razonamientos intermedios que no quedaron en los mensajes de
  commit.

## Pendiente

- Completar B2 (resuscripción tras reconexión, descarte de MP viejos, MR
  reenviado ante MI repetido, cierre de la misión anterior si el destino
  cambia) y fijar `obu_id` = CN del certificado — ambos abordados en
  `prompt_integracion_app_obu.md`, ítem 2.
- Ejecutar la campaña `pi-4g` real (B5 preparó el terreno, no la corrida).
- Decidir con el asesor los `[REVISAR]` abiertos: margen de 20 m, y el
  tratamiento del `obu_id`/CN en B4.
