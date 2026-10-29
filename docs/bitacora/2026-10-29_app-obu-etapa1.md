# 2026-10-29 — App Android de la OBU, Etapa 1 (mapa, ruta, MQTT, GNSS real)

**Objetivo específico:** OE4 (app Android mínima con mapa y ruta, sustituye a `gateway/obu_emulada.py` para la validación final)
**Requerimientos:** RF-02 (adquisición de posición real) implementado; RF-01 (lector OBD-II) explícitamente NO implementado, queda para la Etapa 2
**Sección de la tesis:** 3.4 Diseño de la OBU
**Commit:** este commit ("OE4: app Android OBU, etapa 1")
**Worktree:** `E:\Tesis\ntcip_app`, rama `app-obu` (worktree separado del principal, `E:\Tesis\ntcip_middleware`, que en paralelo trabaja la campaña de medición y la Raspberry Pi)

## Qué se implementó

Proyecto Android nativo en Kotlin (`app_obu/`), cliente real de
`docs/CONTRATO_OBU.md` -- equivalente de `gateway/obu_emulada.py` pero con
GNSS real (`LocationManager.GPS_PROVIDER`, sin Google Play Services) en
vez de un CSV, y una pantalla única con mapa (osmdroid) en vez de una
consola. Dispositivo de prueba: Samsung Galaxy Tab S6 Lite (SM-P610),
Android 13, One UI 5.1.1, solo Wi-Fi (sin datos propios: en vehículo usa
hotspot de un celular + Tailscale hacia el broker de la laptop).

- Mapa con posición actual, elegir destino al tocar, ruta (MR) dibujada
  (reemplaza a la anterior, no acumula), indicador grande de próximo
  semáforo (ME, con los estados en español natural del contrato,
  incluido `en_espera` → "en espera por otra unidad").
- MQTT 5 (HiveMQ MQTT Client), QoS 1, `client_id="obu-{obu_id}"`,
  `obu_id` pseudónimo de sesión (como `gateway/obu_emulada.py`).
- Publicación de MP a 1 Hz desde un foreground service (tipo `location`),
  solo con misión activa y solo si hay un fix GNSS vigente (no inventa
  posición); fuente de velocidad/rumbo detrás de una interfaz
  (`FuentePosicion`) con dos implementaciones: GNSS real y una trayectoria
  CSV pregrabada ("modo simulado", para pruebas en mesa sin GNSS,
  desactivado por defecto, con aviso fijo en pantalla mientras está
  activo).
- Registro de eventos compatible con `common/events.py` (mismo esquema de
  columnas y de nombre de archivo) sin tocar ese archivo; exportable
  desde Ajustes (comparte el CSV vía `FileProvider`).
- Consulta SNTP propia (UDP, sin tocar el reloj del sistema) contra
  `time.cloudflare.com` al iniciar y terminar cada misión, para acotar
  (de forma aproximada, no como `chronyc`) el error del reloj de la
  tablet frente al de la laptop/Pi.
- Aviso de restricción de batería (Samsung/One UI, aparte del límite de
  Android "puro" que ya resuelve el foreground service).
- Ajustes sin nada hardcodeado: host/puerto del broker, clase NTCIP 1211,
  modo simulado y la trayectoria que usa.
- `app_obu/pruebas/registro_rsu_mesa.json`: copia de
  `config/registro_rsu.json` solo con la RSU 2, para poder probar en mesa
  sin arriesgar que el servidor le mande un M1 real al agente de la Pi
  (RSU 1), que sigue conectado al mismo broker por la campaña de la otra
  sesión.
- `app_obu/PROPUESTA_FIN_MISION.md`: propuesta (no aplicada en este
  worktree, le corresponde a quien trabaje en `servidor/` y en
  `docs/CONTRATO_OBU.md`) de una señal explícita de fin de misión en el
  ME (`mision_activa`, `motivo_fin`), porque hoy no existe ninguna y "todas
  las paradas canceladas" es ambiguo entre "la misión terminó" y "el
  vehículo ya pasó la última RSU y sigue hacia el destino".

## Cómo

- **Decisión de alcance explícita del asesor/autor** (instrucción
  recibida antes de escribir código): sin watchdog por ausencia de ME
  (4G corta segundos sin que eso signifique fin de misión -- el
  indicador solo muestra "sin conexión con el servidor" y sigue
  publicando MP), sin detección local de llegada a destino (la app solo
  envía MF `motivo="boton"`, nunca `"destino"` -- eso le toca al
  servidor), sin `ACCESS_BACKGROUND_LOCATION` (un foreground service de
  tipo `location` iniciado por el usuario ya cuenta como primer plano
  para la ubicación, según la guía oficial de Android).
- **Toolchain más nuevo de lo esperado.** Este entorno (laptop con
  Android Studio y SDK ya instalados) tiene Gradle/AGP/Kotlin/androidx
  mucho más recientes que los que se conocían al diseñar el plan: AGP 9.0
  cambió el modelo de integración de Kotlin (Kotlin "built-in" en AGP,
  sin el plugin `org.jetbrains.kotlin.android`) y las versiones estables
  actuales de androidx (`core-ktx`, `activity-ktx`) ya exigen
  `compileSdk` 36/37. Se resolvió así, sin bajar la calidad del proyecto:
  - `android.builtInKotlin=false` + `android.newDsl=false` en
    `gradle.properties`: sigue aplicando el plugin clásico de Kotlin
    (camino de "opt out" documentado explícitamente en las notas de
    versión de AGP 9.0), en vez de migrar a un DSL nuevo y en evolución
    justo al escribir la Etapa 1.
  - `compileSdk = 37` (el máximo que exigían las dependencias), sin tocar
    `targetSdk = 34` ni `minSdk = 29` -- son independientes, confirmado
    contra el propio mensaje de error de Gradle.
  - `Mqtt5BlockingClient`/HiveMQ 1.4.1 arrastra varios jars de Netty con
    el mismo `META-INF/INDEX.LIST`: excluido explícitamente en
    `packaging.resources` del módulo `app`.
- **Gradle wrapper generado contra un Gradle real** (9.8.2, descargado de
  `services.gradle.org`), no escrito a mano: no había `gradle`/`java` en
  el `PATH` de este entorno, pero sí el JDK embebido de Android Studio
  (`Android Studio/jbr`), usado solo para correr `gradle wrapper` una vez.
- **`assembleDebug` y `testDebugUnitTest` corridos de verdad** desde Git
  Bash (`JAVA_HOME` apuntando al JBR de Android Studio), no solo
  revisados a ojo -- ver "Evidencia".
- Fin de misión por lo que SÍ puede detectar la app hoy: botón (MF
  `motivo="boton"`) y, cuando `servidor/gestor_mision.py` implemente la
  propuesta de `PROPUESTA_FIN_MISION.md`, `mision_activa=false` en el ME
  (ya interpretado en `ObuSessionService.onMensajeEstado()`, aunque el
  servidor actual todavía no lo envía).
- Dedup: MR por `version` (ignora una versión igual o anterior a la
  aplicada); ME por `ts_ms` (ignora uno que no sea estrictamente mayor al
  último aplicado -- comparar el payload completo no sirve porque
  `ts_ms` cambia siempre).

## Desviaciones respecto del contrato (`docs/CONTRATO_OBU.md`)

- `fuente_velocidad="simulada"` en el modo de trayectoria pregrabada: no
  está en el enum documentado (`"obd2"|"gps"|"respaldo"`). Es informativo
  y el servidor no lo valida, pero el contrato debería extender el enum
  -- propuesta de una línea en `PROPUESTA_FIN_MISION.md`, §4.
- `mision_activa`/`motivo_fin` en ME: campos que la app ya sabe
  interpretar pero que `servidor/gestor_mision.py` no envía todavía (ver
  arriba). Mientras no se implementen, la app depende enteramente del
  botón para terminar una misión desde la UI.

## Evidencia

- `app_obu/app/build/outputs/apk/debug/app-debug.apk` (22.8 MB),
  generado con `./gradlew assembleDebug` desde este worktree -- build
  limpio, sin warnings propios del proyecto (solo el aviso esperado de
  AGP por seguir con el plugin clásico de Kotlin).
- `./gradlew testDebugUnitTest`: 3/3 pruebas verdes
  (`MensajesTest`, traducción de estados a español natural del
  contrato) -- `app_obu/app/build/test-results/testDebugUnitTest/`.
- Falta (no se puede hacer desde este entorno): instalar en la Tab S6
  Lite por `adb` y correr la prueba en mesa de `app_obu/README.md` contra
  `servidor/main.py` + una RSU emulada con `RSU_ID=2`. Son los pasos y
  las capturas que pide `app_obu/README.md`, sección final.

## Pendiente

- **Prueba en mesa real** (servidor + RSU emulada + tablet por USB/adb),
  con las capturas listadas en `app_obu/README.md`.
- **`PROPUESTA_FIN_MISION.md`**: implementarla en `servidor/` (otro
  worktree) para que la app pueda terminar una misión por "destino" o
  "tiempo_maximo" sin depender solo del botón.
- **Etapa 2** (lector OBD-II ELM327 por Bluetooth clásico, PID 0x0D):
  estructura dejada lista en `FuentePosicion`/`FuenteGnss`, sin
  implementar.
- **Etapa 3** (TLS 1.3 + mTLS): gancho dejado listo en
  `seguridad/TlsConfig.kt` y en `MqttObuClient`, siempre `null` hoy.
- **Validar en campo** la lectura de "foreground service alcanza sin
  `ACCESS_BACKGROUND_LOCATION`" contra Android 13 / One UI 5.1.1 real,
  no solo contra la documentación oficial.
