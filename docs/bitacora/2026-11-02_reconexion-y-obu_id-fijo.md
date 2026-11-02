# 2026-11-02 — Reconexión de la OBU y `obu_id` fijo por dispositivo

**Objetivo específico:** OE4 (OBU, protocolo OBU↔servidor)  **Requerimientos:** RF-09/RNF-03 (caducidad), RF-10 (renovación), RF-04 (cancelación al cruzar/reemplazar)
**Sección de la tesis:** 3.x (contrato OBU↔servidor, seguridad mTLS) → 4.x (prueba)
**Commits:** `c0f60d9` (reconexión), `239618c` (`obu_id` fijo)

Ítem 2 de `prompt_integracion_app_obu.md`, que pedía primero **demostrar**
si cada hueco hipotético de B2 existía de verdad antes de corregirlo.

## Qué se implementó

**2a — reconexión.** De los cinco puntos del prompt, dos resultaron ser
hipótesis **falsas** (verificadas, no asumidas) y tres eran huecos reales:

1. **Resuscripción tras reconexión (hipótesis falsa).** Se sospechaba que
   HiveMQ MQTT Client, con `cleanStart`/`sessionExpiryInterval` por
   defecto, perdía las suscripciones al caerse la sesión y no las
   recuperaba solo. Decompilando `hivemq-mqtt-client-1.4.1.jar`
   (`MqttClientReconnector`) se encontró `DEFAULT_RESUBSCRIBE_IF_SESSION_EXPIRED
   = true`; un experimento contra el mosquitto real del banco (proxy TCP
   propio para forzar la caída, dos `Mqtt5BlockingClient` en el mismo
   proceso) lo confirmó: tras cortar la conexión, un segundo mensaje
   publicado por un tercero llegó al suscriptor sin que este volviera a
   llamar `subscribeWith()` a mano. No se tocó `MqttObuClient.kt` más que
   un comentario que documenta esto, para que nadie "corrija" algo que no
   está roto.
2. **MP en ráfaga al reconectar (hipótesis falsa).** Se sospechaba que
   HiveMQ encolaba los `publish` hechos mientras no hay conexión y los
   mandaba todos juntos al reconectar. El mismo tipo de experimento
   (publicar con el cliente ya desconectado) mostró que
   `publishWith().send()` lanza `MqttClientStateException` **de
   inmediato** — no encola, no bloquea. El comentario que ya existía en
   `MqttObuClient.kt::publicar()` ya lo decía correctamente.
3. **Descarte de MP desordenado en el servidor (hueco real).**
   `servidor/gestor_mision.py::procesar_mp` recibía `seq` pero solo lo
   registraba en el log — nunca lo usaba para descartar un MP viejo, a
   pesar de que `docs/CONTRATO_OBU.md` ya afirmaba que el servidor
   "deduplica por `seq`". Ahora `Mision.ultimo_mp_seq` guarda el último
   `seq` aceptado y un MP con `seq` menor o igual se descarta (evento
   `MP_descartado`) antes de tocar cualquier estado.
4. **MR no reenviado ante un MI repetido (hueco real).** Si el proceso de
   la app se reinicia (pierde `ultimoMiEnviado`/`ultimaVersionMrAplicada`
   en memoria) y reenvía el MI, el servidor lo trataba como no-op pero no
   le devolvía nada: la app quedaba sin ruta. `armar_mision()` ahora
   reenvía el MR vigente y el último ME en la rama de `MI_repetido`.
5. **MI con destino distinto, ignorado en silencio (hueco real).** Si el
   destino de un MI para un `obu_id` con misión activa difiere en más de
   `TOLERANCIA_MISMO_DESTINO_M` (50 m, `[REVISAR con asesor]`), ya no se
   trata como repetido: se cierra la misión anterior con
   `motivo_fin="reemplazada"` (vía `desarmar_mision`, que cancela — M3 o
   directo — todo lo que estuviera abierto en las RSU) y se arma una
   misión nueva.

**Efecto lateral encontrado al implementar el punto 4:**
`_cuerpo_mr()` mandaba `"version": 1` siempre, incluso tras recalcular la
ruta por desvío (`_recalcular_por_desvio`). Como la app ignora un MR con
`version` ≤ la ya aplicada, un recálculo por desvío **nunca se habría
aplicado** en la app — error preexistente, no introducido por este
cambio, pero expuesto por él. Se agregó `Mision.version`, que sube en
cada recálculo.

**Solicitudes abiertas en la RSU mientras la OBU está caída (punto 5 del
prompt, solo análisis, sin cambio de código):** la renovación de una
solicitud (`_renovar`/`_respaldo_por_ruta`) solo ocurre dentro de
`procesar_mp`, que solo se ejecuta al llegar un MP. Sin OBU (sin MP), el
servidor **no** sigue renovando — contrario a lo que el prompt
consideraba la alternativa "insegura". La RSU tiene su propio hilo
independiente (`agent/rsu_middleware.py::verificar_caducidad_periodica`,
cada 0,5 s) que hace caducar la solicitud a los `T_CAD_SEGUNDOS = 3.0 s`
(`agent/ntcip1211.py`) sin intervención del servidor. Es decir: **se
cumple RF-09** (caduca) y es el comportamiento seguro — el controlador no
queda reteniendo una fase verde indefinidamente para un vehículo que
podría no estar llegando.

**2b — `obu_id` fijo por dispositivo.** Resuelve el `[REVISAR]` que B4
dejó abierto en `TlsConfig.kt`: un certificado de cliente mTLS es de
larga duración con CN fijo, pero `ObuSessionService` generaba un
`obu_id` al azar en cada misión. Ahora `obu_id` es la identidad **del
dispositivo**, no de la sesión/misión (`mision_id`, que asigna el
servidor, sigue siendo la identidad de la misión):

- Con TLS activado, `obu_id = TlsConfig.commonNameCliente()` — leído del
  certificado cargado, única fuente de verdad.
- Sin TLS (broker de desarrollo), `obu_id = Prefs.obuId`, nuevo campo de
  Ajustes ("Identidad del dispositivo"), por defecto `obu-dev-01`.
- `scripts/seguridad/generar_ca.py` y `mosquitto_acl.conf` **ya**
  soportaban un `--id`/CN arbitrario y `use_identity_as_username` + `%u`
  desde B4 — no hizo falta cambiar su lógica, solo los ejemplos y
  comentarios (de `ses-abc123` a `obu-tab-01`).

## Cómo

- Archivos de servidor: `common/events.py` (`EVT_MP_DESCARTADO`),
  `servidor/gestor_mision.py`, `tests/test_gestor_mision.py` (4 pruebas
  nuevas: MP fuera de orden, MI repetido reenvía MR/ME, MI con otro
  destino cierra la misión anterior, desvío sube la versión del MR).
- Archivos de la app (**editados en `master`, no en la rama `app-obu`**,
  según la convención que dejó el ítem 1 de este prompt —
  `app_obu/obu/ObuSessionService.kt`, `obu/Prefs.kt`, `AjustesActivity.kt`,
  `res/layout/activity_ajustes.xml`, `res/values/strings.xml`,
  `seguridad/TlsConfig.kt`, `seguridad/TlsConfigTest.kt`,
  `obu/MqttObuClient.kt` (solo comentario).
- Los dos experimentos de reconexión/publish (puntos 1 y 2 de 2a) se
  armaron como pruebas JVM temporales (un proxy TCP propio +
  `Mqtt5BlockingClient` real contra el mosquitto del banco en
  `127.0.0.1:1883`), **no se comitearon**: eran para observar el
  comportamiento real una sola vez, no para la suite permanente (dependen
  de un broker corriendo).
- `gradlew testDebugUnitTest` (28 pruebas, incluida `TlsConfigTest`) y
  `pytest` (121 pruebas) en verde tras ambos commits.

## Desviaciones respecto del diseño de la tesis

- `TOLERANCIA_MISMO_DESTINO_M = 50 m` es una constante nueva, sin
  calibrar con datos de campo — `[REVISAR con asesor]`.
- La regla "MI con destino distinto reemplaza la misión" no estaba en
  `docs/CONTRATO_OBU.md` antes de hoy; es una decisión de diseño nueva,
  documentada en esa sección.
- `obu_id` = identidad de **dispositivo** (no de sesión) es una decisión
  de diseño de seguridad — `[REVISAR con asesor]`: afecta cómo se
  describe la trazabilidad/pseudonimización en el Capítulo 4 (antes cada
  misión era "anónima" entre sí; ahora todas las misiones del mismo
  dispositivo comparten `obu_id`, aunque sigue sin ser la placa del
  vehículo).

## Evidencia

- Resultado de los experimentos de reconexión (impreso en consola, no
  guardado como archivo): resuscripción automática confirmada;
  `publishWith().send()` lanza `MqttClientStateException` en ~5 ms
  estando desconectado.
- `tests/test_gestor_mision.py`: 16 pruebas en ese archivo (12 antes de
  este ítem + 4 nuevas), 121 en total en `pytest -q`.

## Problemas y solución

- El hallazgo del `version` siempre en 1 (ver arriba) no estaba en el
  alcance original del ítem 2a.3, pero bloqueaba que el reenvío de MR
  fuera correcto en el caso general (una misión que además tuvo un
  desvío) — se corrigió en el mismo commit en lugar de dejarlo
  documentado sin arreglar, porque es un cambio pequeño y directamente
  relacionado.
- Al editar primero en el worktree `ntcip_app` (rama `app-obu`) por
  costumbre de sesiones anteriores, se generaron cambios duplicados
  respecto a la convención fijada por el ítem 1 de este prompt ("el
  trabajo de la app sigue en `master`"). Se corrigió exportando el diff
  con `git diff`/`git apply` al worktree de `master` y descartando los
  cambios del worktree `app-obu` con `git checkout --`, sin perder nada.

## Pendiente

- Probar 2a y 2b con hardware real (tablet + mosquitto con TLS 1.3 +
  mTLS) — ítem 4 de este prompt.
- Llevar al asesor los tres `[REVISAR]`: tolerancia de 50 m, `obu_id` de
  dispositivo (no de sesión), y el umbral de 20 m de B3 (no tocado aquí).
