# 2026-11-02 — Matriz de pruebas de seguridad del broker (S3)

**Objetivo específico:** OE5 (evidencia de la sección 4.6)  **Requerimientos:** RNF-05
**Sección de la tesis:** 4.6 (pruebas de seguridad)
**Commit:** `b9bdf7b`

Ítem S3 de `prompt_seguridad.md`: matriz T01-T16 contra un Mosquitto y un
agente SNMPv3 reales (locales, sin Pi ni tablet). **16/16 en verde.**

## Qué se implementó

`tests/test_seguridad_broker.py` (marcador `seguridad`, se salta todo el
módulo si no hay mosquitto instalado). Cada caso levanta su propio banco
(`scripts/seguridad/banco_local.py`) y lo baja al terminar, para que el
log de cada uno quede aislado como evidencia.

- **T01-T05, T12** (rechazo de handshake TLS/mTLS): sin certificado, CA
  ajena, cliente que fuerza TLS 1.2, certificado vencido, certificado
  revocado, SAN que no coincide con el host. Los cinco primeros
  confirmaron algo que no era obvio de antemano: con este paho (2.1.0),
  un rechazo de handshake **no lanza una excepción sincrónica** desde
  `connect()` — el handshake real ocurre dentro de `loop_start()`, y el
  rechazo se ve como `on_disconnect` con "Unspecified error". Hubo que
  rediseñar el helper de conexión de la prueba (`_conectar()`) para mirar
  `on_connect` **y** `on_disconnect`, no solo capturar una excepción.
- **T06-T09** (ACL entre identidades): confirmado que una OBU no puede
  publicar en el tema de solicitudes de una RSU, ni en el de posición de
  otra OBU, ni suscribirse a la ruta de otra OBU; una RSU no puede
  suscribirse a las solicitudes de otra RSU.
- **T10**: demuestra **y documenta** la limitación conocida de
  `mosquitto_acl.conf` (la regla `pattern write servidor/central/respuestas`,
  sin `%c`/`%u`, deja pasar un M2 falso de cualquier cliente autenticado)
  y que `servidor/gestor_mision.py::procesar_m2` lo ignora (id_solicitud
  fuera de seguimiento). Ambas partes en la misma prueba, porque el
  argumento de la tesis necesita las dos.
- **T11**: flujo legítimo de punta a punta (MI→MR, M1→M2) con TLS 1.3 +
  mTLS real. Reusa `scripts/campanas/lazo_centralizado.py` (`_lanzar_servidor`,
  `_lanzar_local`, `_correr_obus`) en vez de reimplementar el lanzamiento
  de servidor/RSU/OBU.
- **T13**: no reimplementado — referenciado a
  `test_gestor_mision.py::test_mp_fuera_de_orden_se_descarta`, ya cubierto
  por el ítem 2a.2 de `prompt_integracion_app_obu.md`.
- **T14-T16** (SNMPv3, agente local sin la Pi): `noAuthNoPriv`, protocolo
  de autenticación equivocado y clave equivocada, los tres rechazados.

## Hallazgos (no asumidos, verificados)

1. **La "Estado de partida" de `prompt_seguridad.md` describía mal el
   estado real de SNMPv3.** Decía "SNMPv3 con USM authPriv (SHA-256 +
   AES-128); un gestor con SHA-1 es rechazado (R10)". El código real
   (`agent/rsu_middleware.py::config.usmHMACSHAAuthProtocol`, y su propio
   mensaje de arranque "auth SHA-1 / priv AES-128") usa **SHA-1**, no
   SHA-256 — la subida que proponía `docs/PLAN_10H_2026-10-19.md` nunca
   se implementó (su bitácora, `docs/bitacora/2026-10-19_decision-g1-usm-sha256.md`,
   no existe). T15 usa MD5 como protocolo "equivocado" en vez de SHA-1,
   que es el real. **No se corrigió el código** — es una decisión de
   diseño de seguridad pendiente, no algo que decidir sin el asesor.
2. **Bug real en `scripts/campanas/lazo_centralizado.py`, anterior a esta
   sesión.** `_lanzar_local()` nunca pasaba `MQTT_BROKER_HOST`/`MQTT_BROKER_PORT`
   al entorno del agente — dependía en silencio de `os.environ`, y todas
   las campañas `local` hechas hasta ahora coincidían con el puerto por
   defecto (1883). Al correr T11 contra el banco (puerto arbitrario), la
   RSU intentaba TLS contra el Mosquitto de *desarrollo* (sin TLS, en
   1883) y fallaba con `ssl.SSLEOFError` en vez de un error claro de
   configuración. Corregido: `_lanzar_local()` ahora recibe y usa
   `broker_host`/`broker_port`.

## Cómo

- `scripts/seguridad/correr_matriz.py`: corre la matriz completa (incluye
  el T13 referenciado) y escribe `evidencia/2026-11-02_seguridad/`:
  `resultados.csv`, un `.txt` por caso con el log del broker (no `.log`:
  el `.gitignore` del proyecto ignora `*.log` en todo el repo — ningún
  `.log` se había comiteado nunca, confirmado con `git ls-files`) y
  `tabla_seguridad.tex`.
- `mosquitto_tls.conf`/`mosquitto_acl.conf`: se quita el aviso "NO
  PROBADO CONTRA UN MOSQUITTO REAL" (ya lo está, con esta matriz) y se
  activa `crlfile` (T05 lo requería).
- `pytest -q`: 142 pruebas (127 normales + 15 de seguridad).

## Desviaciones respecto del diseño de la tesis

Ninguna de diseño — los hallazgos de SNMPv3 (arriba) son sobre el estado
de la implementación, no sobre el diseño de la tesis en sí.

## Evidencia

- `evidencia/2026-11-02_seguridad/resultados.csv`, `tabla_seguridad.tex`,
  `T01.txt`…`T12.txt` (logs del broker por caso).
- `pytest tests/test_seguridad_broker.py -v`: 15/15; con el T13
  referenciado, 16/16.

## Problemas y solución

- **`log_dest stdout` perdía el log al matar el broker con `taskkill /F`**
  (encontrado en S2, documentado ahí).
- **PermissionError al re-levantar el banco entre casos** (archivo de
  log todavía bloqueado por el proceso recién matado): `bajar()` ahora
  espera, con reintentos, a poder borrar el log antes de devolver el
  control.
- **Choque de nombre de módulo**: `scripts/analisis/lazo_centralizado.py`
  y `scripts/campanas/lazo_centralizado.py` se llaman igual;
  `tests/test_lazo_centralizado.py` ya cachea `sys.modules["lazo_centralizado"]`
  con el de análisis. T11 importaba por `sys.path` + nombre (colisión,
  `AttributeError: no attribute 'FIXTURES'` al correr la suite completa,
  no al correr el archivo solo) — corregido importando por ruta
  (`importlib.util.spec_from_file_location`), el mismo patrón que ya usa
  `tests/test_campana_runner.py` para el mismo choque.

## Pendiente

- S4 (costo de TLS en la latencia, opcional) y S5 (redacción) — ver el
  resto de `prompt_seguridad.md`.
- Probar la matriz contra el Mosquitto de la Raspberry Pi real y el
  handshake mTLS de la app en la tablet — ambos fuera de esta sesión
  (sin Pi ni tablet).
- `[REVISAR con asesor]`: subir SNMPv3 de SHA-1 a SHA-256 (o documentar
  SHA-1 como la decisión final), y la limitación de T10 (o
  `dynamic-security` como trabajo futuro).
