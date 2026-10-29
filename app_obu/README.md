# OBU NTCIP -- app Android (Etapa 1)

App Android nativa (Kotlin) que implementa el lado OBU de
`docs/CONTRATO_OBU.md`: equivalente real de `gateway/obu_emulada.py`, con
GNSS real en vez de un CSV y una pantalla única con mapa, en vez de una
consola.

**Etapa 1 (esta):** MQTT 5 + QoS 1, mapa osmdroid con ruta, indicador de
próximo semáforo, publicación de posición a 1 Hz desde un foreground
service, registro de eventos compatible con `scripts/analisis/`, ajustes
sin nada hardcodeado.

**No implementado todavía** (estructura dejada lista, ver abajo):
Etapa 2 (lector OBD-II ELM327 por Bluetooth, velocidad PID 0x0D con GPS de
respaldo) y Etapa 3 (TLS 1.3 + mTLS).

## Requisitos

- Android Studio (cualquier versión reciente; no es obligatorio para
  compilar, ver "Compilar" abajo) o, como mínimo, un JDK 17+ y el Android
  SDK con `compileSdk`/`platforms;android-34` y `build-tools` instalados
  y la licencia (`sdkmanager --licenses`) aceptada.
- Un dispositivo o emulador con Android 10 (API 29) o superior. Probado
  en una Samsung Galaxy Tab S6 Lite (SM-P610), Android 13, One UI 5.1.1.

Versiones fijadas en este proyecto (`app_obu/build.gradle.kts`,
`app_obu/app/build.gradle.kts`, `app_obu/gradle/wrapper/`): Gradle 9.8.2,
Android Gradle Plugin 9.5.0, Kotlin 2.4.21, compileSdk/targetSdk 34,
minSdk 29. Son las versiones estables más recientes al momento de escribir
esto (octubre 2026) -- si al compilar más adelante Gradle sugiere
versiones más nuevas, no hay necesidad de pelear con eso: con que
compileSdk/targetSdk/minSdk se mantengan en los valores de arriba, el
proyecto sigue cumpliendo lo acordado.

## Compilar

Desde la raíz de este módulo (`app_obu/`), con Git Bash:

```bash
cd app_obu
./gradlew assembleDebug
```

El wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`)
ya está generado y versionado -- no hace falta tener Gradle instalado
aparte, pero sí un JDK 17+ en `JAVA_HOME` o en el `PATH` (Android Studio
trae uno propio en `Android Studio/jbr/`; en Windows, por ejemplo:
`$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"`).

`local.properties` (con `sdk.dir`) **no está versionado** (ver
`app_obu/.gitignore`) porque la ruta del SDK es de cada máquina -- Android
Studio lo recrea solo al abrir el proyecto; para la línea de comandos,
crear `app_obu/local.properties` con una línea `sdk.dir=<ruta del SDK>`.

El primer `assembleDebug` descarga `platforms;android-34` y las
dependencias de Maven si hiciera falta (requiere red e Internet; las
licencias del SDK ya deben estar aceptadas, `sdkmanager --licenses`). El
APK de depuración queda en `app_obu/app/build/outputs/apk/debug/`.

Desde Android Studio: `File > Open...` sobre la carpeta `app_obu/` (no
sobre la raíz del repositorio) y dejar que sincronice.

## Instalar en la tablet (USB)

1. En la tablet: Ajustes > Acerca del teléfono > tocar 7 veces "Número de
   compilación" para activar Opciones de desarrollador; luego Ajustes >
   Opciones de desarrollador > activar "Depuración USB".
2. Conectar la tablet a la laptop por USB y aceptar el diálogo de
   confianza que aparece en la tablet.
3. Verificar que `adb` la reconoce:
   ```bash
   adb devices
   ```
4. Instalar:
   ```bash
   adb install -r app_obu/app/build/outputs/apk/debug/app-debug.apk
   ```
   (o `./gradlew installDebug` desde `app_obu/`, que hace lo mismo).

## Ajustes de la app (nada hardcodeado)

Pantalla de Ajustes (ícono de engranaje, arriba a la derecha -- solo
visible cuando no hay misión activa, ver §6 del contrato):

- **Host / puerto del broker MQTT.** Para el entorno de desarrollo de
  esta sesión: host `100.121.77.97` (IP de Tailscale de la laptop),
  puerto `1883`, **sin TLS** -- permitido por §1 del contrato solo para
  desarrollo; nunca el broker de producción sin cifrar.
- **Clase NTCIP 1211** (por defecto 1 -- la única reconocida hoy por
  `agent/ntcip1211.py::CLASES_EMERGENCIA_RECONOCIDAS`).
- **Modo simulado** y la trayectoria CSV que usa (ver abajo).

## Por qué no se pide `ACCESS_BACKGROUND_LOCATION`

El manifiesto solo declara `ACCESS_FINE_LOCATION` +
`FOREGROUND_SERVICE_LOCATION`. Según la guía oficial de Android sobre
acceso a ubicación en segundo plano, un *foreground service* cuenta como
"la app está en primer plano" a efectos de ubicación mientras esté
corriendo -- `ACCESS_BACKGROUND_LOCATION` es para cuando la app accede a
la ubicación SIN un foreground service activo y sin UI visible, que no es
el caso aquí: `ObuSessionService` (tipo `location`) lo arranca la propia
acción del usuario ("Iniciar emergencia") y se mantiene con notificación
persistente mientras la misión está activa. Si en las pruebas contra
Android 13 real se encuentra que las actualizaciones de ubicación SÍ se
cortan con la pantalla apagada, es una señal de que esta lectura de la
política no aplica en la práctica para este dispositivo/One UI -- avisar
antes de agregar el permiso, no agregarlo preventivamente.

## Batería en Samsung/One UI

Aparte del límite de Android "puro" (resuelto con el foreground service),
One UI tiene su propia gestión de batería que puede matar procesos en
segundo plano igual. La app detecta esto
(`PowerManager.isIgnoringBatteryOptimizations`) y, si la restricción está
activa, muestra un diálogo para abrir el ajuste del sistema
(`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`; si ese intent falla en
algún One UI, cae a la pantalla de detalle de la app). Si de todas formas
la app se corta en una prueba real, el camino manual en esta tablet
(Android 13, One UI 5.1.1) es:

> Ajustes > Aplicaciones > OBU NTCIP > Batería > **Sin restricciones**

(y, si existe en esta versión de One UI, también revisar Ajustes >
Cuidado de batería y dispositivo > Batería > Límites de uso en segundo
plano, para que la app no quede en "Apps en reposo profundo"/"Apps
inactivas").

## Criterio de "fix GNSS válido"

`FuenteGnss.kt` (lógica pura y probada por unidad en
`EvaluadorFixGnss.kt`/`EvaluadorFixGnssTest.kt`) decide si un fix GNSS es
publicable por su **calidad** -- proveedor GPS, precisión horizontal
(`Location.accuracy`) dentro de 30 m por defecto, y antigüedad de la
lectura menor a 5 s -- y NO por si trae velocidad o rumbo. Con el
vehículo detenido en una cola o en un semáforo en rojo, Android
normalmente deja de reportar `speed`/`bearing` aunque el fix siga siendo
bueno; descartar esas muestras habría congelado la misión en el servidor
justo en el peor momento. Sin velocidad se envía `0.0`; sin rumbo se
hereda el último rumbo real conocido de la misión (importante: el
servidor usa `rumbo_deg` para decidir si la OBU sigue encarando el acceso
ya asignado, ver `gateway/geometria.py::SeguidorAcceso` -- un rumbo
inventado ahí podría cancelar la solicitud de prioridad por
`MOTIVO_RUMBO` solo por estar detenido, no desviado). Si nunca hubo un
rumbo real todavía (arranque de la misión sin haberse movido), se manda
0.0° como mejor esfuerzo -- de bajo riesgo en la práctica, porque para que
importe el vehículo ya tendría que estar dentro del radio de detección de
una RSU sin haberse movido nunca desde que se armó la misión. El registro
de eventos (`MP_tx`) guarda `precision_m` y `rumbo_medido` (si el rumbo de
esa muestra fue medido o heredado) para poder auditar esto después; esos
dos campos NO van en el MP que recibe el servidor, solo en el CSV de
eventos de la app.

## Modo simulado (pruebas en mesa sin GNSS)

Desactivado por defecto. Desde Ajustes: activar "Modo simulado" y, si se
quiere, elegir otro archivo CSV (mismo formato que
`scripts/trayectorias/generar.py`, columnas `t_s,lat,lon,rumbo_deg,
velocidad_kmh` por nombre de cabecera) -- por defecto usa
`avenida_ab_s1.csv`, incluido como asset
(`app/src/main/assets/trayectorias/`), copiado de
`resultados/trayectorias/avenida_ab_s1.csv`.

Con el modo activo, la posición (en la pantalla principal y como origen
del MI) viene de la trayectoria, no del GPS -- no depende de
`ACCESS_FINE_LOCATION` estar concedido para que el botón "Iniciar
emergencia" se habilite. (`POST_NOTIFICATIONS` y el propio permiso de
ubicación sí siguen haciendo falta para arrancar el foreground service,
que siempre es de tipo `location` aunque la posición sea simulada --
exigencia de Android al declarar ese tipo, no de esta app.)

Mientras está activo: un aviso en rojo fijo en pantalla ("MODO SIMULADO —
sin GPS real"), y los MP van con `"fuente_velocidad": "simulada"` -- un
valor que **no** está en el enum de `docs/CONTRATO_OBU.md` §3
(`"obd2"|"gps"|"respaldo"`); ver `app_obu/PROPUESTA_FIN_MISION.md`, §4,
para la extensión de contrato sugerida (no aplicada, es solo una
propuesta).

La reproducción siempre es a factor 1 (tiempo real), a diferencia de
`--factor` en `gateway/obu_emulada.py`.

## Reloj y eventos

`ObuSessionService` registra eventos en
`filesDir/eventos/eventos_<obu_id>.csv` (almacenamiento interno de la
app -- no visible en el explorador de archivos del sistema, pero
exportable desde Ajustes > "Exportar CSV de eventos", que abre el panel
de compartir de Android vía `FileProvider`). Mismo esquema de columnas que
`common/events.py` (`ts_ns,nodo,tipo_evento,id_solicitud,extra_json`) y
mismo nombre de archivo (`eventos_<nodo>.csv`, con `nodo = obu_id`), para
que `scripts/analisis/*.py` lo lea sin tocar código.

Eventos con los mismos nombres que `gateway/obu_emulada.py`: `MI_tx`,
`MP_tx`, `MF_tx`, `MR_rx`, `ME_rx`. Dos eventos propios de esta app, sin
equivalente en `common/events.py` (no se tocó ese archivo -- está fuera
de `app_obu/`, ver instrucciones de esta sesión; si se quiere que
`common/events.py` los documente también, pedirlo aparte):

- `conexion_mqtt` -- extra: `estado=conectado|desconectado` (callbacks de
  conexión/desconexión de HiveMQ MQTT Client).
- `reloj_sntp` -- ver abajo.
- `bateria_restringida` -- extra: `ignorando_optimizacion` (bool).

**`ts_ns` tiene resolución de milisegundos, no de nanosegundos.** Para
que el CSV sea legible sin cambios por `scripts/analisis/*.py`
(`common/events.py::iter_eventos` espera una columna `ts_ns`), se escribe
`System.currentTimeMillis() * 1_000_000`: mismo esquema, pero la
resolución real es de ms.

**Sincronización del reloj de la tablet.** La app NO implementa un
cliente NTP que corrija el reloj del sistema -- depende de que Android
tenga activado "Fecha y hora automáticas" (Ajustes > Fecha y hora), que en
esta tablet (sin datos propios, solo Wi-Fi/hotspot) sincroniza por SNTP de
forma oportunista cuando hay red, sin una cadencia garantizada. A
diferencia de la laptop/Pi, donde `chronyc tracking` da una cota medida
del error del reloj (ver `docs/ARRANQUE_BROKER_LAPTOP.md` y la campaña
pi-lan en `docs/bitacora/`), en la tablet no hay una herramienta
equivalente.

Para acotar esto de todas formas, la app hace su propia consulta SNTP
(UDP, puerto 123, sin tocar el reloj del sistema -- ver
`obu/SntpCliente.kt`) contra `time.cloudflare.com` al iniciar y al
terminar cada misión, y registra el resultado como evento `reloj_sntp`
(`offset_ms`, `rtt_ms`). **Esto no es lo mismo que `chronyc tracking`**:
es una medición puntual (dos por misión), no una disciplina continua, y
depende de que la consulta UDP llegue y vuelva en el margen de 2 s que
usa `SntpCliente` -- si falla (sin red en ese instante, por ejemplo), no
se bloquea el MI/MF, simplemente no queda ese evento. Para cualquier
métrica de latencia que cruce el reloj de la tablet con el de otra
máquina (OBU→servidor, por ejemplo), usar `offset_ms` de `reloj_sntp` como
corrección aproximada y reportar la medición como indicativa, no dentro
de un margen de error tan ajustado como el de la campaña pi-lan.

## Fin de misión: qué puede y qué no puede detectar la app

Por diseño (y por instrucción explícita para esta etapa), la app **nunca**
decide por su cuenta que la misión terminó, salvo que el usuario pulse
"Terminar emergencia" (envía MF `motivo="boton"`). No hay un watchdog por
ausencia de ME (las redes 4G cortan segundos sin que eso signifique que la
misión acabó) ni detección local de llegada a destino (la app solo manda
MF con motivo `"boton"`, nunca `"destino"` -- eso le toca al servidor).

Si no llega ningún ME en más de 5 s, el indicador muestra "Sin conexión
con el servidor" **sin dejar de publicar MP** (la misión sigue activa
localmente). La app queda preparada para interpretar una señal explícita
de fin de misión del servidor (`mision_activa=false`, `motivo_fin=...` en
el ME) que **todavía no existe** en `servidor/gestor_mision.py` -- ver
`app_obu/PROPUESTA_FIN_MISION.md` para la propuesta de ese cambio (no
implementada aquí, le corresponde al worktree principal). Mientras ese
cambio no esté implementado, la única forma de terminar una misión desde
la app es el botón; `TIEMPO_MAXIMO_MISION_S` (30 min) sigue existiendo en
el servidor como límite de seguridad, pero la app no lo refleja todavía
en pantalla.

## Prueba en mesa

El agente de la Raspberry Pi real (`rsu-agent.service`, `RSU_ID=1`) puede
seguir conectado al mismo broker Mosquitto de la laptop mientras se hace
esta prueba (otra sesión lo usa para la campaña de medición, ver
`docs/ARRANQUE_BROKER_LAPTOP.md`). **No usar el registro de RSU completo
para esta prueba**: si la ruta calculada llegara a incluir la RSU 1
(`OSM-C24`), el servidor le mandaría un M1 real al agente de la Pi, sin
que la otra sesión lo note. Por eso `app_obu/pruebas/registro_rsu_mesa.json`
es una copia de `config/registro_rsu.json` **solo con la RSU 2**
(`OSM-C902`) -- con esa RSU 1 fuera del archivo,
`servidor/rutas.py::cruzar_con_registro` nunca puede incluirla en una ruta,
sin importar la trayectoria.

1. **Laptop -- Mosquitto** ya corriendo (Paso 2 de
   `docs/ARRANQUE_BROKER_LAPTOP.md`).
2. **Laptop -- RSU emulada con `RSU_ID=2`** (Paso 8 de ese mismo
   documento, NO el Paso 6 que asume que la RSU 1 de la Pi ya está
   arriba): dos ventanas de PowerShell, una para
   `controller\controller_emulator.py --port 9001` y otra para
   `agent\rsu_middleware.py` con `RSU_ID=2`, `SNMP_PORT=1162`,
   `CONTROLLER_PORT=9001`, apuntando al broker local.
3. **Laptop -- servidor central**, con el registro recortado:
   ```powershell
   $env:REGISTRO_RSU_PATH = "app_obu\pruebas\registro_rsu_mesa.json"
   .\.venv\Scripts\python.exe servidor\main.py
   ```
   (sin `GRAFO_SINTETICO`: usa el grafo real cacheado en
   `data/grafo_san_miguel_real.graphml`, igual que el Paso 6 de
   `docs/ARRANQUE_BROKER_LAPTOP.md`).
4. **Tablet -- Ajustes**: host `100.121.77.97`, puerto `1883`, clase `1`.
   Para una primera prueba sin salir a la calle, activar "Modo simulado"
   (usa `avenida_ab_s1.csv` por defecto, que cruza geográficamente las dos
   RSU del registro completo -- con el registro recortado del paso 3,
   solo debería aparecer la RSU 2 en la ruta).
5. En la tablet: tocar el mapa como destino un punto sobre la misma
   avenida de `avenida_ab_s1.csv`, más allá de la RSU 2 (OSM-C902, centro
   en `-12.0997, -77.0323`) -- por ejemplo **`-12.0976, -77.0327`**
   (el extremo final de esa trayectoria, unos 250 m al norte de la RSU
   2). El origen lo pone la propia app (primer punto de la trayectoria
   simulada, `-12.1088, -77.0305`); con ese origen y ese destino, la ruta
   que calcule `servidor/rutas.py` sobre el grafo real debería seguir
   aproximadamente la misma calle que recorre `avenida_ab_s1.csv` y pasar
   por la RSU 2 en el camino. Si el destino se elige antes de la RSU 2 (o
   en otra calle), la ruta puede no cruzarla y la prueba no sirve para
   verificar el paso 6. Tras elegir destino, "Iniciar emergencia".
   **Verificación:** la ruta (MR) y el próximo semáforo (ME) que aparecen
   en la app deben mostrar siempre `rsu_id="2"`, nunca `"1"`. Si aparece
   `"1"`, detener la prueba y revisar `REGISTRO_RSU_PATH` (no se habrá
   aplicado el registro recortado).
6. En la consola de `servidor/main.py` deben verse los MI/MP recibidos y
   los M1/M2 contra `rsu/2/solicitudes`. "Terminar emergencia" en la
   tablet debe mandar el MF y la app debe volver a la pantalla inicial.

## Estructura (etapas 2 y 3, dejadas listas pero sin implementar)

- `obu/velocidad/FuentePosicion.kt`: interfaz de posición+velocidad+rumbo
  con dos implementaciones hoy (`FuenteGnss`, `FuenteSimulada`). La Etapa
  2 (lector OBD-II ELM327 por Bluetooth clásico, PID 0x0D a 1 Hz, GPS de
  respaldo) reemplazaría solo `velocidadKmh` dentro de `FuenteGnss`, no
  necesitaría una tercera implementación completa.
- `obu/seguridad/TlsConfig.kt`: parámetro opcional de
  `obu/MqttObuClient.kt`, siempre `null` hoy. La Etapa 3 (TLS 1.3 + mTLS,
  certificados de `scripts/seguridad/generar_ca.py`) completaría ese data
  class y lo conectaría al builder de HiveMQ MQTT Client.

## Capturas/fotos para la tesis (una vez que la prueba en mesa funcione)

1. Pantalla de Ajustes con host/puerto/clase configurados.
2. Pantalla principal antes de iniciar misión (mapa centrado, sin ruta).
3. Justo tras "Iniciar emergencia": destino marcado + polilínea del MR.
4. Indicador de próximo semáforo en "concedida", con ETA.
5. (Si se logra) indicador en "en espera por otra unidad".
6. Notificación persistente del servicio con la pantalla apagada o la app
   en segundo plano.
7. Consola de `servidor/main.py` mostrando MI/MP recibidos en paralelo.
8. Pantalla tras "Terminar emergencia" (vuelta al inicio).
9. CSV de eventos exportado/compartido, como evidencia del registro.
10. Diálogo de "optimización de batería" si aparece en la tablet.
