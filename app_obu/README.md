# OBU NTCIP -- app Android (Etapa 1)

App Android nativa (Kotlin) que implementa el lado OBU de
`docs/CONTRATO_OBU.md`: equivalente real de `gateway/obu_emulada.py`, con
GNSS real en vez de un CSV y una pantalla única con mapa, en vez de una
consola.

**Etapa 1 (esta):** MQTT 5 + QoS 1, mapa osmdroid con ruta, indicador de
próximo semáforo, publicación de posición a 1 Hz desde un foreground
service, registro de eventos compatible con `scripts/analisis/`, ajustes
sin nada hardcodeado.

**Etapa 3 (TLS 1.3 + mTLS, B4, 2026-11-01):** implementada y conectada al
cliente MQTT (ver la sección "TLS 1.3 + mTLS (Etapa 3)" más abajo), pero
**sin probar contra un broker real ni en la tablet** (no hay hardware
disponible en esta sesión). El mismatch entre un CN de certificado fijo y
el `obu_id` que antes era aleatorio por misión se resolvió el 2026-11-02
(item 2b de `prompt_integracion_app_obu.md`): `obu_id` pasa a ser la
identidad fija del dispositivo -- ver esa sección para el detalle y
`[REVISAR con asesor]` (sigue siendo una decisión de diseño de seguridad
a confirmar con el asesor). Una fuente de velocidad más precisa (por
ejemplo, un lector OBD-II del vehículo) queda como trabajo futuro.

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

Pantalla de Ajustes (ícono de llave, arriba a la derecha del mapa -- solo
visible cuando no hay misión activa, ver §6 del contrato). **Se guarda sola
al salir** (atrás o "Listo"); los archivos, al elegirlos. En el orden de la
pantalla:

- **Conexión con el servidor**
  - **Host del broker MQTT**, con hosts predefinidos: **Tailscale**
    `100.121.77.97` (la laptop en el tailnet; valor por defecto), **Emulador**
    `10.0.2.2` y **Manual**.
  - **Puerto**: 8883 con TLS; 1883 es el broker de desarrollo sin cifrar
    (solo ensayos, §1 del contrato). Al activar o desactivar TLS el puerto
    cambia solo entre 1883 y 8883 si no se había puesto otro.
  - **Conexión segura (TLS 1.3 + mTLS)**: interruptor y los tres archivos
    (CA, Certificado, Llave). Se verifican al elegirlos: "✓ obu-tab-01,
    válido hasta el …" o qué falta o está mal.
  - **Probar conexión**: conecta un momento al broker (Client ID
    `obu-<id>-prueba`, sin publicar nada) y dice si respondió, rechazó el
    puerto o rechazó el certificado.
- **Misión**: Clase NTCIP 1211 (por defecto 1, la única reconocida hoy por
  `agent/ntcip1211.py::CLASES_EMERGENCIA_RECONOCIDAS`), `obu_id` (solo sin
  TLS; con TLS se muestra el CN del certificado) y vibrar al conceder el verde.
- **Demo (sin GPS)**: Ruta emulada y trayectoria propia. "Elegir archivo…"
  **solo acepta `.csv`** (en la tablet llegó a quedar la llave TLS cargada
  como trayectoria); un archivo que no es CSV se descarta solo.
- **Registro y batería**: exportar CSV de eventos y revisar la
  optimización de batería.

## Pantalla principal

Horizontal (la tablet): **mapa a la izquierda, panel a la derecha**. En
vertical el panel pasa debajo del mapa. Girar la tablet no reinicia nada
(`configChanges` en el manifiesto).

**Mapa.** Sigue al vehículo (punto azul) hasta que el usuario lo toca o
arrastra; entonces deja de seguirlo y aparece el botón **Centrar** para
volver. El alfiler es el destino. Las **cruces rojas** son hospitales y
clínicas con emergencia de OSM y los **puntos grises**, las RSU de la zona
PUCP (ver "Zona PUCP"). Las fuentes emulan posiciones a ~5 Hz (el MP sigue a
1 Hz), así que el vehículo se desplaza de forma continua.

### Sin misión

Arriba, lo que hace falta para salir; abajo, el modo de prueba:

- **Conexión con el servidor**: al abrir la app (y al volver de Ajustes) se
  prueba el broker y se muestra "✓ Conectado a host:puerto con TLS, como
  obu-tab-01" o el motivo del error. Tocar la línea vuelve a probar. Antes,
  un puerto o certificado equivocado solo se notaba como un "Conectando con
  el servidor…" eterno ya iniciada la misión.
- **Estado del GNSS** (solo con GPS real), **destino** y hospitales.
- **El destino se recuerda** (GPS real y Ruta libre): al abrir la app o al
  terminar una misión queda puesto, y repetir la prueba es un solo toque.
- Sobre el botón, **qué falta para iniciar** ("elegir el destino", "esperar
  «GNSS listo»"...), en vez de un botón gris sin explicación.
- Si la misión no puede arrancar (por ejemplo, TLS activado con un archivo
  que falta o no sirve), un aviso dice por qué, con un botón a Ajustes. La
  app ya no se cierra (antes: `ForegroundServiceDidNotStartInTimeException`,
  porque el servicio salía antes de `startForeground()`).

**Modo de prueba:**

- **Ruta emulada / GPS real** (misma preferencia que en Ajustes).
- Con **Ruta emulada**, chips de escenario:
  - **Ruta libre** (por defecto): eliges **origen y destino en el mapa**
    (pulsación larga → "Destino aquí" / "Origen aquí"; origen por defecto:
    PUCP, Av. Universitaria). Al iniciar, el servidor calcula la ruta real
    sobre el grafo de OSM (`servidor/rutas.py`) y el vehículo emulado
    **recorre esa ruta** (la del MR) a 40 km/h; si el servidor recalcula,
    sigue por la nueva desde donde iba. No hace falta ninguna trayectoria
    grabada. Al terminar, origen y destino quedan puestos para repetir.
  - **PUCP (grabada)** / **Mariano Cornejo (grabada)**: las trayectorias
    CSV de `pruebas/` (`app/src/main/assets/escenarios/escenarios.json`).
    Elegir una carga su trayectoria y su destino. **Ojo:** la segunda es la
    del antiguo escenario "Hospital del Niño", pero su destino
    (-12.0664649, -77.0626982, Av. Mariano Cornejo) **no** es el Instituto
    Nacional de Salud del Niño: según OSM, ese está en Av. Brasil (Breña),
    -12.06500, -77.04644. Para ir al INSN real, usar Ruta libre.
  - El vehículo queda **quieto** en el origen hasta "Iniciar emergencia".
  - Con una trayectoria grabada activa, **elegir otro destino** (mapa,
    hospital o lista) **pasa solo a Ruta libre**: una grabada solo va a su
    propio destino, y seguirla hacia otro hospital hacía que el vehículo se
    fuera "por otros lados" mientras el servidor recalculaba la ruta.
  - **Velocidad de demo ×1 / ×2 / ×4**: acelera solo el reloj (las
    velocidades del MP no se escalan). Con ×2/×4 el CSV de eventos lleva un
    evento `demo` (`{"factor": 4}`) al inicio y `demo_factor` en cada
    `MP_tx`: **esas corridas no se usan en mediciones**. Durante la misión se
    ve la pastilla "DEMO ×4".
- Con **GPS real**: estado del GNSS -- gris "Buscando señal GNSS…", naranja
  "Precisión 45 m — esperando ≤ 30 m", verde "GNSS listo · ±6 m".
  **"Iniciar emergencia" solo se habilita en verde.** Debajo:
  - satélites a la vista y usados en el fix (muchos vistos y 0 usados = bajo
    techo o sin cielo despejado);
  - un **círculo gris** con la ubicación aproximada por red (Wi-Fi/antenas),
    solo como referencia mientras no hay fix: nunca es origen del MI ni va
    en un MP;
  - un aviso si la posición está **fuera de la zona de rutas del servidor**
    (la caja del grafo: lat −12.110 a −12.053, lon −77.095 a −77.026).
- **Destino**: pulsación larga sobre el mapa, tocar una cruz roja, o
  **Hospitales y clínicas cercanos…** (lista ordenada por distancia).

### Por qué el GPS real "no detecta" la ubicación (prueba del 2026-10-31)

En la tablet el proveedor `gps` **nunca había tenido un fix**: estaba bajo
techo y, sin datos móviles, no tiene A-GPS. Solo había ubicación aproximada
por red (en casa, ~lon −76.95, **fuera del grafo**). Para una prueba con GPS
real:

1. Salir al aire libre con la app abierta en "GPS real" y esperar el verde
   (la primera vez puede tardar varios minutos; el hotspot del celular
   encendido ayuda a la siguiente).
2. Hacerla **dentro de la zona del grafo** (alrededor de la PUCP). Desde
   casa, el servidor enlazaría el origen al nodo más cercano del borde del
   grafo, a kilómetros: habría que regenerarlo con
   `scripts/datos/regenerar_grafo.py` incluyendo la zona (ver "Escenario
   casa").

Para agregar el escenario **Casa**: copiar `pruebas/trayectoria_casa.csv` a
`app/src/main/assets/escenarios/` y sumar su entrada (id, nombre,
trayectoria, destino) a `escenarios.json`; recompilar.

### Con misión

- Pastillas **EMULADA** (morado) o **GPS ±7 m** (verde; naranja si la
  precisión pasa de 30 m; rojo "GPS · sin fix"), y **DEMO ×N** si aplica.
- **Tarjeta grande del próximo semáforo**, con color e ícono: gris
  PENDIENTE, azul SOLICITANDO, naranja CAMBIANDO A VERDE (concedida, pero
  el controlador reporta todavía amarillo/todo rojo: la calle transversal se
  está despejando), verde VERDE CONCEDIDO (solo con fase `verde`), ámbar
  ESPERANDO DESPEJE (`en_cola`), naranja EN ESPERA (otra unidad, conflicto),
  y su ETA. La vibración salta con el verde real, no con la concesión.
  Mientras no llega el MR: "Conectando con el servidor…" (sin conexión) o
  "Esperando la ruta del servidor…".
- Debajo, en letra pequeña, **cómo se logró el verde**: "Extensión de verde
  · X s", "Esperó despeje · X s" o "Verde adelantado · X s", a partir de los
  campos `accion`, `t_hasta_verde_ms`, `anticipacion_s` (y `fase_al_recibir`)
  que el servidor agregará al ME. Mientras no existan, solo "Estado: … ·
  fase …". Los valores de `accion` se reconocen por palabra clave
  (`exten…`, `…despeje…`/`…cola…`, `adelant…`/`anticip…`); si el servidor usa
  otros nombres, ajustar `VistaMision.textoDetalle`.
- **Tira de chips** con todas las RSU de la ruta en orden, y un **marcador
  por RSU en el mapa** del mismo color. Una parada cancelada con el vehículo
  ya pasado el cruce se muestra como **✓ cruzada** (el ME no distingue
  "cancelada por cruce" de "cancelada por desvío": se decide por la
  posición sobre la ruta, con el mismo margen de 20 m que el servidor).
- **Vibración corta** al pasar a verde (una vez por intersección;
  desactivable en Ajustes).
- **Pantalla siempre encendida** mientras dura la misión.
- **"Terminar emergencia" pide confirmación.**
- **Fin automático**: al terminar la trayectoria emulada la app espera 2 s
  (últimos MP en el punto final), envía MF `motivo="destino"` (como
  `obu_emulada.py`) y vuelve al inicio con el escenario listo para repetir.
  También termina si el servidor envía `mision_activa=false` en el ME.
- Sin conexión con el broker, la ruta emulada **no arranca** hasta conectar
  (el MI sale apenas el broker responde; el vehículo no avanza sin servidor)
  y se muestra "Sin conexión con el servidor" desde el principio.

## Zona PUCP: 23 RSU y hospitales cercanos

`pruebas/generar_zona_pucp.py` arma, a partir de OSM:

- `pruebas/hospitales_zona_pucp.json`: 14 hospitales y clínicas **con
  emergencia** dentro del grafo (Overpass: `amenity`/`healthcare` =
  `hospital`|`clinic`; clínicas solo con `emergency=yes`). © colaboradores
  de OpenStreetMap, ODbL.
- `pruebas/registro_rsu_zona_pucp.json`: **23 RSU (rsu_id 11–33)** en
  cruces con `highway=traffic_signals` del propio grafo:
  - **11–20, por rutas**: cruces por los que pasan las rutas del servidor
    desde la PUCP a esos hospitales. Elección greedy: primero los que dan
    semáforo a rutas que aún no tienen ninguno, luego los más transitados;
    separación ≥ 250 m entre RSU y ≥ 350 m de la base. 12 de los 14 destinos
    quedan con al menos una RSU (los otros: el Centro Médico PUCP, a 400 m, y
    el Geriátrico San José, cuya ruta no cruza semáforos de OSM).
  - **21–33, por radio**: toda intersección semaforizada a menos de 1,5 km
    del campus (`--radio-m`), para que cualquier ruta que salga de la PUCP o
    pase cerca encuentre semáforos (Av. Universitaria, La Marina, Riva
    Agüero, Venezuela, Parque de las Leyendas, Mariano Cornejo...). Las
    señales de OSM se agrupan por cruce (≤ 40 m) y cada cruce se representa
    con el nodo del grafo más cercano con `street_count ≥ 3`.
  - Al regenerar, las RSU por rutas del registro existente **conservan su
    rsu_id**; con `--radio-m 2000` serían 30 RSU (cada RSU son 2 procesos,
    ~90 MB: 23 RSU + servidor + consola ≈ 2,2 GB).
- Ambos se copian a `app/src/main/assets/zona/` **solo para dibujarlos** en
  el mapa; el registro que vale es el que carga el servidor.

Levantar todo con ese registro (desde `E:\Tesis\ntcip_middleware`, rama
master):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\lanzar_rsus.ps1 -Registro E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_zona_pucp.json -ConServidor -ConConsola
```

Verificado con `GestorMision` (40 km/h desde la PUCP): al INSN pasa por las
RSU 17 → 11 → 18; al Rebagliati, 17 → 11 → 18 → 20; al Hospital PNP Luis
N. Sáenz, 19 → 14; al Centro Médico Naval, 15.

## Probar en la tablet real

Galaxy Tab S6 Lite (SM-P610, Android 13, solo Wi-Fi). Pasos una sola vez
por equipo, salvo donde se indica.

1. **Instalar el APK** (ver "Instalar en la tablet (USB)"): con la tablet
   por USB y la depuración USB activada,
   ```bash
   adb install -r app_obu/app/build/outputs/apk/debug/app-debug.apk
   ```
   Sin `adb`: copiar `app-debug.apk` a `Download/` de la tablet y abrirlo
   desde la app "Mis archivos" (pide permitir "instalar apps desconocidas"
   para Mis archivos -- solo esa vez).
2. **Permisos** (la app los pide al abrirse; si se negaron: Ajustes de
   Android > Aplicaciones > OBU NTCIP > Permisos):
   - Ubicación: **"Permitir solo mientras se usa la app"** y **"Usar
     ubicación precisa"** activado (sin ubicación precisa el GPS entrega
     precisiones de cientos de metros y nunca pasa a "listo"). No hace
     falta "Permitir todo el tiempo" (ver más abajo, foreground service).
   - Notificaciones: permitir (el foreground service de la misión la
     necesita).
   - Batería: "Sin restricciones" (ver "Batería en Samsung/One UI").
   - Ubicación del sistema activada (panel rápido). Opcional pero ayuda a
     la primera fijación: Ajustes > Ubicación > Servicios de ubicación >
     "Precisión de ubicación de Google" -- sin datos móviles la tablet no
     tiene A-GPS, así que conviene abrir la app en "GPS real" unos minutos
     antes, cerca de una ventana o ya en la calle, hasta ver el verde.
3. **Host del broker** (Ajustes de la app > Host del broker MQTT, puerto
   1883). Dos opciones:
   - **Red de casa (LAN)**: la IP de la laptop en el Wi-Fi de casa
     (`ipconfig` en PowerShell, "Adaptador de LAN inalámbrica Wi-Fi" >
     "Dirección IPv4", p. ej. `192.168.1.34`). Solo sirve mientras la
     tablet esté en ese mismo Wi-Fi -- **no para la caminata**: en cuanto
     sale del alcance del router pierde la conexión.
   - **Tailscale** (la que sirve para caminar): la tablet sale a internet
     por el hotspot del celular y llega a la laptop por Tailscale. Instalar
     Tailscale en la tablet (Play Store), iniciar sesión con la misma
     cuenta que la laptop, y usar la IP `100.x` de la laptop
     (`tailscale ip -4`, hoy `100.121.77.97`). La laptop puede quedarse en
     casa conectada al Wi-Fi.
   `demo_casa.ps1` imprime ambas IP al arrancar.
4. **Mosquitto escuchando fuera de la laptop**: `mosquitto.conf` debe
   tener `listener 1883 0.0.0.0` y `allow_anonymous true` (ver
   `docs/ARRANQUE_BROKER_LAPTOP.md`, Paso 2; con solo `listener 1883` sin
   dirección, o sin listener, Mosquitto 2.x escucha únicamente en
   `127.0.0.1`). Reiniciar el servicio después de editarlo:
   ```powershell
   Restart-Service mosquitto
   ```
5. **Regla de firewall para el 1883** (PowerShell como administrador). Para
   Tailscale ya existe la de `docs/ARRANQUE_BROKER_LAPTOP.md`
   (`-RemoteAddress 100.64.0.0/10`). Para la LAN de casa, limitada a la
   subred local y al perfil privado:
   ```powershell
   New-NetFirewallRule -DisplayName "Mosquitto tesis (LAN casa)" -Direction Inbound `
     -Protocol TCP -LocalPort 1883 -RemoteAddress LocalSubnet -Profile Private -Action Allow
   ```
   (el Wi-Fi de casa debe estar marcado como red **Privada** en Windows; si
   está como Pública la regla no aplica). Comprobar desde la laptop:
   ```powershell
   Get-NetTCPConnection -LocalPort 1883 -State Listen
   ```
   debe mostrar `0.0.0.0`. Desde la tablet, la app deja de mostrar "Sin
   conexión con el servidor" al iniciar una misión.
6. **Copiar una trayectoria propia a la tablet por USB** (solo si no es uno de los escenarios incluidos en la app):
   - Con `adb`:
     ```bash
     adb push app_obu/pruebas/trayectoria_casa.csv /sdcard/Download/
     ```
   - Sin `adb`: conectar por USB, en la tablet elegir "Transferir
     archivos" en la notificación de USB, y en el Explorador de Windows
     copiar el `.csv` a `Galaxy Tab S6 Lite > Tablet > Download`.
   Luego en la app: Ajustes > Avanzado > **Elegir archivo…** > Descargas > el archivo (o, mejor, agregarlo como escenario incluido: ver "Pantalla principal").
   La app guarda el permiso de lectura del archivo; no hace falta volver a
   elegirlo tras reiniciar.

Prueba rápida antes de salir: "Ruta emulada" con `trayectoria_casa.csv`
contra el broker por la misma IP que se usará afuera -- si eso funciona,
lo único que cambia en la calle es la fuente de posición.

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

Mientras está activo: el indicador "EMULADA" durante la misión (ver "Pantalla principal"),
y los MP van con `"fuente_velocidad": "simulada"` -- valor documentado en
el enum de `docs/CONTRATO_OBU.md` §3 (`"gps"|"respaldo"|"simulada"`); ver
`app_obu/PROPUESTA_FIN_MISION.md`, §4.

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
del error del reloj (ver `docs/ARRANQUE_BROKER_LAPTOP.md`), en la
tablet no hay una herramienta equivalente.

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

## Escenario PUCP

Segundo escenario de prueba en mesa, cerca de la PUCP (San Miguel), con el
grafo real `data/grafo_san_miguel_real.graphml` (cubre desde Santa Marina
hasta más allá de la avenida La Marina, incluida esta zona):

- **Origen:** `-12.071468, -77.078353` (Av. Universitaria).
- **Destino:** `-12.0754746, -77.0755802` (Av. Abraham Lincoln).
- **Ruta real** calculada por `servidor/rutas.py::calcular_ruta` (la misma
  función que usa el servidor, Dijkstra sobre `length`): 871.5 m, 12 nodos,
  Av. Universitaria (0–96 m) → tramo sin nombre en el grafo (96–170 m) →
  Av. Simón Bolívar (170–355 m) → Av. Abraham Lincoln (355–872 m).
- **RSU única del escenario (`rsu_id=3`):** `OSM-PUCP-04`, la intersección
  real Av. Simón Bolívar / Av. Abraham Lincoln (nodo `316803089` del grafo,
  a 354.5 m de recorrido), con sus 4 accesos calculados desde la geometría
  real del grafo (rumbo entre ese nodo y cada vecino), no supuestos
  perpendiculares. Ver `app_obu/pruebas/registro_rsu_pucp.json`.
  - Ningún nodo `highway=traffic_signals` de OSM cae sobre esta ruta real
    (se revisó el grafo completo, no solo sus 12 nodos). Por eso la
    intersección se tomó cruzando la ruta con
    `osm/salida_osm/candidatas_pucp.csv` (salida de
    `osm/osm_lima_rsu.py::agrupar_intersecciones`, centroides de nodos
    `highway=traffic_signals` de una descarga Overpass **propia** de ese
    script, en una fecha distinta y separada de
    `data/grafo_san_miguel_real.graphml`): de las 40 filas, solo
    `RSU-PUCP-03` (21 m de la polilínea, a 109 m de recorrido) y
    `RSU-PUCP-04` (4.6 m de la polilínea, a 354.5 m de recorrido) quedan
    sobre esta ruta real.
  - **`OSM-PUCP-04` NO está etiquetada `highway=traffic_signals` en el
    grafo vial que de verdad enruta.** El nodo `316803089` de
    `data/grafo_san_miguel_real.graphml` (el más cercano al centroide de
    `RSU-PUCP-04`, <5 m) solo trae los atributos `y`, `x`, `street_count`
    -- sin `highway=traffic_signals`. `RSU-PUCP-04` es una **intersección
    candidata** del estudio OSM de `osm/` (semaforizada en SU propia
    descarga Overpass, de otra fecha), que este escenario asume como RSU
    para el banco de pruebas; no es una confirmación de semáforo dentro
    del grafo que calcula la ruta. [DATO: confirmar en campo si esa
    intersección tiene semáforo real antes de citarla como tal en la
    tesis.]
  - **`RSU-PUCP-03` se descartó**: queda a solo ~119 m en línea recta del
    origen (<150 m), sin holgura para que el servidor envíe el M1 con la
    anticipación de RF-03/RF8 antes de que la OBU la cruce.
  - **`RSU-PUCP-10` NO se usó**: aunque está cerca del destino en línea
    recta (~220 m), queda a 138 m de la polilínea de la ruta real que
    calcula `networkx` (por fuera de `RADIO_DETECCION_RSU_M=40 m` de
    `cruzar_con_registro`) — con este origen/destino exactos, la ruta no
    pasa por ella y el servidor nunca la habría incluido en la MR.
- **Nunca usar `rsu_id=1`**: es el agente real de la Raspberry Pi
  (`rsu-agent.service`), que puede seguir conectado al mismo broker
  Mosquitto de la laptop por la campaña de otra sesión (ver
  `docs/ARRANQUE_BROKER_LAPTOP.md`).
- **Tampoco usar `rsu_id=2` aquí**: es el que ya usa
  `app_obu/pruebas/registro_rsu_mesa.json` para la "Prueba en mesa" de la
  sección anterior. `agent/rsu_middleware.py` arma su client_id MQTT como
  `rsu-middleware-{RSU_ID}` (`agent/rsu_middleware.py`, variable
  `client_id`): si DOS procesos corren con el **mismo** `RSU_ID` contra el
  **mismo** broker, usan el mismo client_id y Mosquitto expulsa a uno cada
  vez que el otro se conecta -- un bucle de conexión/desconexión visto de
  verdad el 2026-10-28, no importa qué puertos SNMP/control use cada uno
  (esos son locales a cada proceso, nunca chocan entre sí). Por eso
  `app_obu/pruebas/registro_rsu_pucp.json` usa **`rsu_id=3`**, para poder
  correr este escenario **sin tener que detener** la "Prueba en mesa" si
  ya está corriendo. Si en cambio se prefiere reutilizar `rsu_id=2` (por
  ejemplo, para no editar el registro), hay que **detener antes**
  `controller\controller_emulator.py` y `agent\rsu_middleware.py` de la
  "Prueba en mesa" -- nunca correr dos RSU con el mismo `RSU_ID` a la vez.
  El registro completo (`config/registro_rsu.json`) tampoco se usa en
  ninguna de las dos pruebas, por la misma razón del `rsu_id=1`.
- **Trayectorias generadas** (a partir de la geometría real de la ruta, a
  30 km/h constante, 1 Hz): `app_obu/pruebas/trayectoria_pucp.csv` (mismo
  formato que `scripts/trayectorias/generar.py`, columnas
  `t_s,lat,lon,rumbo_deg,velocidad_kmh`; usable por `gateway/obu_emulada.py`
  y por el modo simulado de la app) y `app_obu/pruebas/trayectoria_pucp.gpx`
  (equivalente, con `<time>` cada 1 s, para el emulador de Android).

**Verificado sin la app**, con exactamente los comandos de abajo
(controlador + RSU 3 emulada + servidor con `registro_rsu_pucp.json` +
`gateway/obu_emulada.py` con `trayectoria_pucp.csv`), 2026-10-29: el
servidor envía el primer M1 a `rsu/3/solicitudes` a los ~26 s de misión
(`t_servicio=8.0`, ETA informado por el controlador: **17 s de
anticipación** antes de que la OBU llegue a la RSU hacia el t≈43 s), la RSU
responde M2 `estado="concedida"` (fase forzada a verde tras el despeje
`amarillo`→`todo_rojo`, RF-06), y al cruzar la intersección (t≈43 s) la
propia OBU emite M3 `motivo="cruce"`, que la RSU usa para liberar la
prioridad (`[middleware] M3 de '...' (cruce) -> liberando prioridad`). La
misión termina sola con `MF motivo="destino"` al llegar al final de la
trayectoria (t≈105 s). `ME` en la consola de `gateway/obu_emulada.py`
muestra la misma secuencia: `pendiente` → `solicitada` → `concedida` (con
renovaciones de M1 cada segundo mientras dura) → `None` (ya cruzada, tras
el M3).

### Levantar el escenario completo (PowerShell, desde `E:\Tesis\ntcip_middleware`)

El código de `servidor/`, `controller/`, `agent/`, `gateway/` y `data/` es
idéntico entre la rama `master` (worktree `E:\Tesis\ntcip_middleware`, donde
sigue la campaña de medición con la Pi real) y esta rama `app-obu` (worktree
`E:\Tesis\ntcip_app`, donde viven los archivos de este escenario) -- por eso
los comandos de abajo corren desde `ntcip_middleware`, pero apuntan al
registro y a la trayectoria con su **ruta absoluta** dentro de
`ntcip_app\app_obu\pruebas\`.

**Puede correr al mismo tiempo que la "Prueba en mesa"** de la sección
anterior porque usa `RSU_ID=3` (ella usa `RSU_ID=2`) -- client_id MQTT
distinto (`rsu-middleware-3` vs `rsu-middleware-2`) y puertos SNMP/control
locales distintos, sin pisarse. **Lo que nunca se debe hacer** es correr dos
`agent\rsu_middleware.py` con el **mismo** `RSU_ID` contra el mismo broker a
la vez: ambos arman el mismo client_id MQTT y Mosquitto expulsa a uno cada
vez que el otro se conecta, en bucle (visto de verdad el 2026-10-28). Si en
vez de `RSU_ID=3` se prefiere reutilizar `RSU_ID=2` en los comandos de
abajo (por ejemplo, para no tener dos RSU emuladas abiertas), hay que
**detener antes** `controller\controller_emulator.py` y
`agent\rsu_middleware.py` de la "Prueba en mesa".

1. **Mosquitto** ya corriendo en la laptop (Paso 2 de
   `docs/ARRANQUE_BROKER_LAPTOP.md`; `Get-Service mosquitto` debe decir
   `Running`).
2. **Controlador emulado de la RSU 3** (ventana de PowerShell 1):
   ```powershell
   Set-Location "E:\Tesis\ntcip_middleware"
   $env:RSU_ID = "3"; $env:RSU_EVENTOS_DIR = "resultados\rsu_pucp"
   .\.venv\Scripts\python.exe controller\controller_emulator.py --port 9102
   ```
3. **Middleware de la RSU 3** (ventana de PowerShell 2, mismo broker):
   ```powershell
   Set-Location "E:\Tesis\ntcip_middleware"
   $env:RSU_ID = "3"; $env:RSU_EVENTOS_DIR = "resultados\rsu_pucp"
   $env:SNMP_PORT = "1172"; $env:CONTROLLER_PORT = "9102"
   $env:MQTT_BROKER_HOST = "127.0.0.1"
   .\.venv\Scripts\python.exe agent\rsu_middleware.py
   ```
   (Si al correr esto el puerto SNMP `1172` o el de control `9102` ya
   estuvieran ocupados por algún proceso suelto de una sesión anterior,
   usar cualquier otro par de puertos libres -- eso no tiene relación con
   el problema de `RSU_ID` repetido de arriba, son solo los puertos
   locales de ESTE proceso.)
4. **Servidor central**, con el registro del escenario PUCP (ventana de
   PowerShell 3):
   ```powershell
   Set-Location "E:\Tesis\ntcip_middleware"
   $env:REGISTRO_RSU_PATH = "E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_pucp.json"
   Remove-Item Env:\RSU_ID, Env:\SNMP_PORT, Env:\CONTROLLER_PORT -ErrorAction SilentlyContinue
   .\.venv\Scripts\python.exe servidor\main.py
   ```
   (sin `GRAFO_SINTETICO`: usa `data\grafo_san_miguel_real.graphml`, que ya
   cubre la zona de la PUCP.)
5. **OBU** -- cualquiera de las dos:
   - **OBU emulada** (ventana de PowerShell 4, sin la app):
     ```powershell
     Set-Location "E:\Tesis\ntcip_middleware"
     .\.venv\Scripts\python.exe gateway\obu_emulada.py --broker-host 127.0.0.1 `
       --trayectoria "E:\Tesis\ntcip_app\app_obu\pruebas\trayectoria_pucp.csv"
     ```
   - **App Android**, en Ajustes: mismo host/puerto/clase que la sección
     anterior, activar "Modo simulado" y en "Trayectoria" tocar **"Elegir
     archivo"** (no la integrada) para seleccionar
     `trayectoria_pucp.csv` -- previamente copiada al dispositivo/emulador,
     por ejemplo:
     ```powershell
     adb push "E:\Tesis\ntcip_app\app_obu\pruebas\trayectoria_pucp.csv" /sdcard/Download/
     ```
     y elegirla desde el picker del sistema (Descargas). En la pantalla
     principal, tocar como destino cualquier punto sobre Av. Abraham
     Lincoln más allá de la intersección con Av. Simón Bolívar (por
     ejemplo, cerca de `-12.0755, -77.0756`, el extremo final de
     `trayectoria_pucp.csv`) y "Iniciar emergencia".
     **Verificación:** la ruta (MR) y el próximo semáforo (ME) deben
     mostrar siempre `rsu_id="3"`, nunca `"1"` ni `"2"`.
6. Para el emulador de Android por GPS simulado en vez del modo simulado de
   la app: Extended controls → Location → Routes → "Load GPX/KML" →
   `app_obu\pruebas\trayectoria_pucp.gpx` → Play (reproduce respetando los
   `<time>` de cada punto, 1 s entre muestras); en ese caso NO activar
   "Modo simulado" en Ajustes (la app toma la posición del GPS del
   emulador, que ya sigue esta ruta).

## Escenario Hospital del Niño

Tercer escenario de prueba en mesa, para la demo al asesor: ambulancia desde
Av. La Marina hacia el Hospital del Niño (Instituto Nacional de Salud del
Niño, Breña), con el mismo grafo real `data/grafo_san_miguel_real.graphml`.

- **Origen:** `-12.074664, -77.082933` (Av. La Marina).
- **Destino:** `-12.0664649, -77.0626982` (Hospital del Niño). El nodo del
  grafo más cercano queda a 134 m del punto exacto (el hospital está
  retirado de Av. Mariano Cornejo) -- normal, no es un error de la ruta.
- **Ruta real** (`servidor/rutas.py::calcular_ruta`): **2928.1 m**, 39
  nodos: Río Morona (0 m) → Putumayo (84 m) → Calle Napo (245 m) →
  Prolongación Av. Mariscal José de la Mar (303 m) → Calle Napo (328 m) →
  Prolongación Av. Mariscal José de la Mar (341 m) → **Av. Universitaria**
  (547 m) → **Av. Mariano Cornejo** (1304 m, hasta el destino).
- **3 RSU (`rsu_id` 4, 5, 6), SOLO de `osm/salida_osm/candidatas_pucp.csv`**
  (por instrucción explícita: nada de Overpass ni de otras zonas). De las
  40 filas de ese CSV, 6 caen dentro de `RADIO_DETECCION_RSU_M=40 m` de la
  ruta real Y a más de 150 m del origen -- se eligieron las 3 mejor
  espaciadas y con más nodos de respaldo en el CSV:
  - `rsu_id=4`, `OSM-PUCP-07` (acum=547 m): Prolongación Av. Mariscal José
    de la Mar / Av. Universitaria / Av. Manuel Cipriano Dulanto. El nodo
    más cercano de la ruta (`589642633`) **sí** trae `highway=traffic_signals`
    en este grafo.
  - `rsu_id=5`, `OSM-PUCP-03` (acum=1099 m): Av. Universitaria / Av. Simón
    Bolívar (la misma intersección real de `registro_rsu_pucp.json`, aquí
    con otro `rsu_id` porque el escenario es distinto).
  - `rsu_id=6`, `OSM-PUCP-08` (acum=1748 m): Av. Mariano Cornejo / Av.
    Santa Gertrudis.
  - **Descartadas:** `RSU-PUCP-06` (misma esquina que `RSU-PUCP-07`, a solo
    41 m -- duplicado, menos nodos de respaldo en el CSV);
    `RSU-PUCP-02` (205.7 m de `RSU-PUCP-03`, redundante); `RSU-PUCP-38`
    (acum=2414 m, de sobra calificada pero se dejó fuera por el límite de
    3 RSU).
  - **Cobertura real:** las 3 RSU cubren hasta acum≈1748 m de los 2928.1 m
    totales (~60 %) -- `candidatas_pucp.csv` es un estudio acotado a la
    zona de la PUCP y no llega hasta Breña; no se inventó ninguna
    intersección en el tramo final de Av. Mariano Cornejo hacia el
    hospital. Ver `app_obu/pruebas/registro_rsu_hospital_nino.json`, bloque
    `origen`, para el detalle completo de la selección.
  - Accesos y rumbos calculados **desde la geometría real** del grafo
    (igual que en `registro_rsu_pucp.json`), no supuestos perpendiculares.
- **Nunca usar `rsu_id=1`** (Raspberry Pi real) **ni `2`/`3`** (los usan
  `registro_rsu_mesa.json` y `registro_rsu_pucp.json` -- mismo `RSU_ID`
  contra el mismo broker = mismo client_id MQTT = Mosquitto expulsa a uno
  en bucle, ver sección "Escenario PUCP" arriba).
- **Trayectorias** (geometría real de la ruta, ~35 km/h, 1 Hz):
  `app_obu/pruebas/trayectoria_hospital_nino.csv` (303 muestras, 302 s) y
  `app_obu/pruebas/trayectoria_hospital_nino.gpx` equivalente con `<time>`.

**Verificado sin la app** (`demo_hospital_nino.ps1` + `gateway/obu_emulada.py`
con `trayectoria_hospital_nino.csv`, factor 6 para la verificación, la
trayectoria entregada es factor 1), 2026-10-29: el servidor manda MR con
las 3 paradas en orden `['4','5','6']`; a cada una le llega su M1 por
`rsu/4`, `rsu/5`, `rsu/6/solicitudes` (eventos separados en
`resultados/hospital_nino/rsu{4,5,6}/`, sin mezclarse), se concede M2
`estado="concedida"` y se libera al cruzar -- `OSM-PUCP-03` y `OSM-PUCP-08`
con M3 `motivo="cruce"` de la propia OBU, `OSM-PUCP-07` por caducidad
(RF-09) al alejarse. `ME` muestra la secuencia esperada por cada RSU:
`pendiente` → `solicitada` → `concedida` → (renovaciones) → la siguiente
RSU, hasta `None` tras la RSU 6. La misión termina con `MF motivo="destino"`.

### Demo con `demo_hospital_nino.ps1` (PowerShell, desde `E:\Tesis\ntcip_middleware`)

```powershell
powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\demo_hospital_nino.ps1
```

Comprueba que Mosquitto esté corriendo y que los puertos de este escenario
(SNMP 1174-1176, control 9104-9106) estén libres, y abre **6 ventanas**
(controlador + middleware de cada una de las 3 RSU, puertos y
`RSU_EVENTOS_DIR` propios) más una séptima con el servidor central
apuntando a `registro_rsu_hospital_nino.json` (ruta absoluta). Guarda los
PID en `resultados\hospital_nino\pids.json`; si se vuelve a correr sin
detener antes, lo avisa y no abre nada nuevo.

Para detener todo (controlador+middleware de las 3 RSU y el servidor):

```powershell
powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\detener_hospital_nino.ps1
```

**OBU -- con la app Android:**

1. En Ajustes: host del broker (**Tailscale** en la tablet, **Emulador** en
   el emulador), puerto 1883, clase `1`.
2. En la pantalla principal: **Ruta emulada** > escenario **Hospital del
   Niño** (ya incluido en la app: carga la trayectoria y el destino, sin
   copiar archivos ni tocar el mapa) > velocidad ×1 (×2/×4 solo para mostrar,
   quedan marcadas como demo) > "Iniciar emergencia".
3. **Verificación:** la tira de semáforos debe mostrar RSU 4 → 5 → 6 en ese
   orden, nunca 1, 2 ni 3. Al llegar al final la misión termina sola.
4. Para el emulador de Android por GPS simulado en vez de la ruta emulada de
   la app: Extended controls → Location → Routes → "Load GPX/KML" →
   `app_obu\pruebas\trayectoria_hospital_nino.gpx` → Play; en ese caso NO
   activar "Modo simulado" en Ajustes.

**Plan B -- sin la app, con la OBU emulada** (si la tablet/el emulador no
están disponibles o fallan a último momento):

```powershell
Set-Location "E:\Tesis\ntcip_middleware"
.\.venv\Scripts\python.exe gateway\obu_emulada.py --broker-host 127.0.0.1 `
  --trayectoria "E:\Tesis\ntcip_app\app_obu\pruebas\trayectoria_hospital_nino.csv"
```

Reproduce la misma misión en consola (MI, MR con las 3 RSU, ME por cada
una) sin necesitar la tablet ni el emulador -- la demo al asesor puede
mostrarse igual, viendo la consola del servidor y de esta OBU emulada en
paralelo. Con `--factor 4` o `--factor 6` se acorta a ~75 s/~50 s en vez de
los 302 s reales, útil si el tiempo de la reunión es corto.

## Escenario casa (caminando con GPS real)

Una sola RSU emulada (**rsu_id 7**) en una intersección semaforizada real
de OSM sobre la ruta entre la casa y un destino a pie. Todo sale de
`pruebas/generar_escenario_casa.py`:

```bash
python app_obu/pruebas/generar_escenario_casa.py --origen=LAT,LON --destino=LAT,LON
```

(con `=` para que el signo menos de las coordenadas no se lea como opción).
El script:

1. verifica que `data/grafo_san_miguel_real.graphml` cubra ambos puntos (si
   no, imprime el `scripts/datos/regenerar_grafo.py --norte/--sur/--este/
   --oeste` con una caja que une la actual y los puntos nuevos, para no
   romper los otros escenarios, y termina con código 2);
2. calcula la ruta con `servidor/rutas.py::calcular_ruta` -- la misma que
   enviará el servidor en el MR. **Es una ruta de red vial `drive`**
   (respeta sentidos únicos): hay que caminar por esa ruta (la línea del MR
   en el mapa de la app), no por un atajo peatonal; a más de 60 m de ella
   el servidor recalcula por desvío;
3. lista los nodos de la ruta con `highway=traffic_signals` en el grafo (o
   a ≤ 25 m de uno) y `street_count ≥ 3`, a ≥ 200 m del origen, **simula
   `GestorMision` con cada uno** a 5 km/h y elige el primero en el que el
   M1 sale por geocerca (ver abajo por qué importa);
4. escribe `pruebas/registro_rsu_casa.json` (accesos y rumbos desde la
   geometría real) y `pruebas/trayectoria_casa.csv` (5 km/h, 1 Hz, para el
   ensayo en "Ruta emulada").

Levantar RSU 7 + servidor (desde `E:\Tesis\ntcip_middleware`, como el del
Hospital del Niño): `pruebas/demo_casa.ps1`; detener con
`pruebas/detener_casa.ps1`. El script avisa si Mosquitto solo escucha en
`127.0.0.1` o si falta la regla de firewall, e imprime las IP para la app.

En la tablet: "GPS real", esperar el verde, tocar el destino, "Iniciar
emergencia", caminar por la ruta.

### Velocidad a pie: cuándo sale el M1

Medido con la simulación del propio generador (parámetros actuales del
servidor, sin calibrar):

- **El M1 sale por la geocerca R_g = 150 m**, no por ETA: a 5 km/h eso es
  ~108 s antes de llegar al cruce, y se renueva a 1 Hz (≈ 108 M1 con
  `seq` creciente) hasta cruzar. El primer M1 lleva `t_servicio = 8`
  (`ANTICIPACION_MINIMA_S`), no el ETA real (~108 s): la vía de geocerca de
  `gestor_mision.py::_aplicar_decision_geocerca` no usa el ETA. Con un
  vehículo a 40 km/h, 150 m son ~13 s y la diferencia no importa; a pie la
  prioridad se pediría casi dos minutos antes.
- **El disparo por ETA** (`eta ≤ ANTICIPACION_MINIMA_S = 8 s`) a 5 km/h
  solo actuaría a ~11 m del cruce -- la geocerca siempre llega antes.
- **`VELOCIDAD_RESPALDO_KMH = 30`**: si el MP trae `velocidad_kmh ≤ 1`
  (parado en la esquina, o Android sin `speed`, que la app envía como 0),
  el servidor asume 30 km/h, y el ETA mostrado cae (p. ej. 60 m → 7 s en
  vez de 43 s). A pie es frecuente: el ETA de la tarjeta puede saltar
  mientras uno espera. No adelanta el M1 en la práctica porque la geocerca
  ya lo emitió antes.
- **Origen demasiado cerca del semáforo**: si el origen queda a menos de
  R_i + margen = 350 m en línea recta del semáforo y la ruta da vueltas,
  `SeguidorAcceso` puede asignarlo con otro acceso, darlo por "cruzado" y
  excluirlo hasta salir de 350 m -- entonces el M1 sale solo por ETA a
  ~11 m y **sin renovaciones** (la RSU lo caduca a los 3 s, RF-09). Por eso
  el generador simula cada candidata y prefiere las que disparan por
  geocerca; si ninguna lo hace, lo avisa.
- El rumbo GPS caminando es ruidoso: con `psi_tol = 30°` y 3 muestras
  seguidas fuera, una vereda con curvas o cruzar la calle en diagonal
  puede cancelar la solicitud por `rumbo_divergente`. Caminar recto por la
  vereda del lado de la ruta.

## Estructura

- `obu/velocidad/FuentePosicion.kt`: interfaz de posición+velocidad+rumbo
  con dos implementaciones hoy (`FuenteGnss`, `FuenteSimulada`), dejada
  como punto de extensión para otras fuentes de velocidad.

## TLS 1.3 + mTLS (Etapa 3)

`obu/seguridad/TlsConfig.kt` parsea los tres PEM (CA, certificado del
cliente, llave) y construye un `KeyManagerFactory`/`TrustManagerFactory`
puros de `javax.net.ssl` (sin BouncyCastle); `obu/MqttObuClient.kt` los
conecta al builder de HiveMQ MQTT Client con `.sslConfig(...)` cuando
`tls != null`. Cubierto por `TlsConfigTest.kt` (parseo, sin broker real).

### Emitir los certificados

```
python scripts/seguridad/generar_ca.py init                          # una sola vez
python scripts/seguridad/generar_ca.py emitir --tipo obu --id obu-tab-01
```

`<obu_id>` (`obu-tab-01` arriba) es la identidad **fija de ese
dispositivo** (item 2b, 2026-11-02) -- no un id de sesión ni de misión; un
certificado por tablet, emitido una vez. Esto genera `deploy/pki/ca/ca.crt`,
`deploy/pki/obu/<obu_id>/obu-<obu_id>.crt` y `.../obu-<obu_id>.key`
(PKCS#8, `openssl genpkey`, no `genrsa` -- la app no entiende PKCS#1).
`deploy/pki/` está en `.gitignore`: **nunca commitear estos archivos**,
cada despliegue genera los suyos.

### Cargar el certificado de cliente en la tablet

No hay una forma de "instalar" el certificado en el almacén de Android:
la app lee los tres archivos directamente, vía selector del sistema
(SAF), igual que el CSV de una trayectoria propia (ver "Modo simulado").

1. Copiar `ca.crt`, `obu-<obu_id>.crt` y `obu-<obu_id>.key` a la tablet
   (por USB, o subirlos a una carpeta de Drive/almacenamiento propio del
   dispositivo -- **nunca** a un servicio en la nube fuera del control del
   proyecto, son credenciales).
2. En Ajustes de la app, sección "Conexión segura (TLS 1.3 + mTLS)": botones "CA",
   "Certificado" y "Llave" abren el selector de archivos del sistema, uno
   por archivo.
3. Activar el interruptor "Usar TLS/mTLS con el broker" (se guarda solo; debe aparecer "✓ obu-tab-01, válido hasta…"). El
   campo "Identidad del dispositivo (obu_id)" de Ajustes **se ignora**
   mientras TLS esté activado: la app usa el Common Name del certificado
   de cliente que acabas de cargar (ver la sección siguiente) -- no hace
   falta que coincida con lo que esté escrito ahí.
4. Cambiar el puerto a **8883** (Ajustes, campo "Puerto"): el puerto 1883
   es el broker de desarrollo sin TLS, no acepta mTLS.

### Cambiar entre TLS y modo sin TLS

El interruptor de Ajustes es el único control: apagado (por defecto) usa
el broker de desarrollo plano en el puerto configurado (1883 hoy), sin
tocar ningún certificado. Si el interruptor está encendido pero falta
alguno de los tres archivos, o no se puede leer, la app **no arranca la
misión sin cifrar** (se detiene con el evento `error_tls_config` en el
registro) -- nunca cae de vuelta a texto plano en silencio.

### Resuelto -- CN del certificado vs. `obu_id` (identidad fija por dispositivo)

`docs/CONTRATO_OBU.md` §1 exige que el Common Name del certificado sea
**exactamente** el `obu_id`, porque la ACL del broker
(`scripts/seguridad/mosquitto_acl.conf`) lo usa como `%u`. Hasta el
2026-11-01, `ObuSessionService.iniciarMision()` generaba un `obu_id` **al
azar en cada misión** (`"ses-" + Random.nextBytes(3)...`), lo que chocaba
con un certificado de cliente, de larga duración y CN fijo por diseño.

**Solución (item 2b de `prompt_integracion_app_obu.md`, 2026-11-02):**
`obu_id` pasa a ser la identidad **fija del dispositivo**, no de la
sesión/misión -- la identidad *de la misión* sigue siendo `mision_id`,
que asigna el servidor.

- **Con TLS activado:** `obu_id` = `TlsConfig.commonNameCliente()`, el CN
  leído directamente del certificado de cliente cargado. El certificado
  es la única fuente de verdad -- así nunca puede quedar desincronizado
  del `obu_id` que de verdad se usa. El campo "Identidad del dispositivo
  (obu_id)" de Ajustes se ignora en este caso.
- **Sin TLS (broker de desarrollo):** `obu_id` = el valor fijo de Ajustes
  (`Prefs.obuId`, por defecto `obu-dev-01`), porque no hay certificado del
  que leerlo.
- La idempotencia del MI repetido (`servidor/gestor_mision.py::armar_mision`)
  **mejora** con esto: antes un reinicio de proceso generaba un `obu_id`
  nuevo y el servidor no podía reconocer la misión anterior; ahora el
  `obu_id` es estable entre reinicios, así que el servidor sí la reconoce
  y reenvía el MR/ME vigentes (ver `docs/CONTRATO_OBU.md` §3, "MI
  repetido").
- `[REVISAR con asesor]`: identidad de **dispositivo** (no de sesión) es
  una decisión de diseño de seguridad -- confirmar que es lo que se
  quiere documentar en el Capítulo 4 (coherente con la revocación por OBU
  de `scripts/seguridad/generar_ca.py revocar`).
- Las campañas de `gateway/obu_emulada.py` (OE5) no usan TLS hoy y pueden
  seguir con identidades de prueba fijas por repetición (`--obu-id`, ver
  `scripts/campanas/lazo_centralizado.py`) -- no afectadas por este
  cambio.

## Capturas/fotos para la tesis (una vez que la prueba en mesa funcione)

1. Pantalla de Ajustes con host/puerto/clase/obu_id configurados.
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
