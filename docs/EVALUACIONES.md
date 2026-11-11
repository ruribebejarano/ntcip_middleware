# Evaluaciones con OBU emulada y con GNSS real

`scripts/evaluacion/evaluar.ps1` levanta las RSU y el servidor, corre la prueba,
detiene todo y deja un resumen. Las RSU y los controladores son emulados en la
laptop; ningún semáforo real interviene. Los comandos se ejecutan en PowerShell,
desde la raíz del repositorio.

## Antes de empezar

Con mTLS, que es la opción por defecto, el broker TLS debe estar abierto en otra
terminal:

```powershell
& "C:\Program Files (x86)\Mosquitto\mosquitto.exe" -c deploy\pki\mosquitto_laptop_tls.conf -v
```

Con `-SinTls` se usa en cambio el servicio de Mosquitto en el puerto 1883, sin
cifrar. Sirve solo para ensayos.

## Evaluar con la OBU emulada

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 emulada -Ruta pucp_mariano_cornejo
```

| Opción | Por defecto | Qué cambia |
|---|---|---|
| `-Repeticiones N` | 3 | Número de misiones |
| `-SigmaPos M` | 5 | Ruido GNSS simulado, en metros |
| `-Factor F` | 1 | Velocidad de reproducción; distinto de 1 no sirve para medir |
| `-SinTls` | apagado | Usa el broker de desarrollo |

Entre repeticiones hay una pausa aleatoria, para que la solicitud llegue en otra
fase del semáforo.

## Evaluar con la tablet y GNSS real

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 gnss -Ruta pucp_mariano_cornejo
```

El script levanta las RSU y el servidor, muestra los datos para la app y espera.

1. **Certificado (solo la primera vez):** el script emite el de `obu-tab-01` y
   muestra sus tres archivos. Cópialos a la tablet y cárgalos en Ajustes (ver
   `app_obu/README.md`, "Cargar el certificado de cliente en la tablet"). Con otra
   tablet, usa `-ObuId <id>`.
2. **Conexión:** tablet con datos (hotspot) y Tailscale. En Ajustes, usa el host y
   el puerto que muestra el script.
3. **GNSS:** elige **GPS real** y espera "GNSS listo" en verde, al aire libre. La
   tablet no tiene datos propios, así que conviene conectarla al hotspot con
   anticipación: la primera fijación puede tardar.
4. **Misión:** ve al origen, elige en el mapa el destino que muestra el script y
   pulsa **Iniciar emergencia**. Sigue la ruta de la app: a más de 60 m de ella, el
   servidor la recalcula. Puedes hacer varias misiones.
5. **Cierre:** pulsa Enter en la terminal cuando termines. Si exportaste el CSV de
   la tablet, guárdalo en la carpeta `tablet\` que indica el script.

El origen real es donde está la tablet al iniciar. La ruta debe seguir la red vial
de vehículos, también si la pruebas caminando.

### Dejar la prueba sola, sin estar en la laptop

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 gnss -Ruta ruta_casa_nogales -ConBroker -FinTrasInactividadMin 30 -DuracionMaxMin 240 -Suspender
```

| Opción | Qué hace |
|---|---|
| `-ConBroker` | Abre el broker TLS oculto si no está abierto, y lo cierra al final. Basta una sola ventana |
| `-FinTrasInactividadMin N` | Termina solo cuando todas las misiones iniciadas ya terminaron y el servidor lleva N minutos sin recibir nada. Si una misión quedó abierta, espera el doble. No termina antes de la primera misión |
| `-DuracionMaxMin N` | Tope de duración total, pase lo que pase |
| `-Suspender` | Al terminar, guardar el resumen y cerrar todo, suspende la laptop (con 30 s para cancelar con Ctrl+C) |

Enter sigue terminando la prueba en cualquier momento. Mientras corre, el script
mantiene la laptop despierta sin cambiar la configuración de energía de Windows; al
terminar, vuelve a su comportamiento normal. **Cerrar la tapa puede suspenderla
igual**: déjala abierta o cambia en Windows qué hace la tapa con corriente.

Elige N mayor que el tiempo que tardas entre una misión y la siguiente (volver al
origen): entre misiones el servidor no recibe nada. El motivo del cierre queda en
`fin.txt`, junto al resumen.

## Cambiar o agregar rutas

Todo se ajusta en `scripts/evaluacion/rutas.json`, sin tocar código. Cada entrada es
una ruta:

```json
"mi_ruta": {
  "descripcion": "Texto libre",
  "origen": [-12.074664, -77.082933],
  "destino": [-12.0664649, -77.0626982],
  "velocidad_emulada_kmh": 35,
  "max_rsu": 3,
  "separacion_min_m": 300,
  "min_desde_origen_m": 200,
  "primer_rsu_id": 50
}
```

| Campo | Qué hace |
|---|---|
| `origen`, `destino` | `[latitud, longitud]`. En Google Maps u OpenStreetMap, clic derecho sobre el punto para copiarlas |
| `velocidad_emulada_kmh` | Velocidad de la OBU emulada; no afecta a la tablet |
| `max_rsu` | Máximo de RSU emuladas sobre la ruta |
| `separacion_min_m` | Distancia mínima entre RSU, por la ruta |
| `min_desde_origen_m` | Distancia mínima entre el origen y la primera RSU |
| `primer_rsu_id` | Identificador de la primera RSU; las demás siguen en orden. Evita el 1, que usa la Raspberry Pi |
| `rsu_manual` | Opcional. Lista de puntos `[latitud, longitud]` donde poner las RSU a mano (ver abajo) |
| `grafo` | Opcional. Grafo vial propio de la ruta, relativo a la raíz del repo (por ejemplo `data/grafo_mi_ruta.graphml`). Sin él se usa el grafo compartido (ver abajo) |

### Cómo se decide la ruta

La ruta es siempre el camino más corto por distancia sobre el grafo vial, entre el
nodo más cercano al origen y el más cercano al destino: es la misma que calcula el
servidor. No admite puntos intermedios. Para que pase por otras calles, mueve el
origen o el destino, o divide el recorrido en dos rutas. Con la tablet, el origen
real es donde está la tablet al iniciar la misión, y el destino es el que eliges
en el mapa de la app.

### RSU automáticas o a mano

- **Automáticas** (sin `rsu_manual`): se ubican donde OpenStreetMap marca un
  semáforo sobre la ruta, respetando `max_rsu`, `separacion_min_m` y
  `min_desde_origen_m`. Puede haber menos que `max_rsu`.
- **A mano** (con `rsu_manual`): cada punto se asocia al nodo de la ruta más
  cercano. Un punto a más de 40 m de la ruta, o que cae en el mismo nodo que otro,
  se omite con un aviso. En este modo se ignoran `max_rsu` y `separacion_min_m`.
  Los identificadores siguen el orden de la ruta, no el de la lista.

```json
"rsu_manual": [
  [-12.07481, -77.079598],
  [-12.075324, -77.077597]
]
```

Para tomar un punto: clic derecho en la intersección, en Google Maps u
OpenStreetMap, y copiar las coordenadas. La ruta `hospital_nino_brena` es un
ejemplo con 13 RSU a mano.

En los dos modos se omiten las RSU que quedan muy cerca del origen en línea recta:
una misión que empieza dentro del radio de una RSU la da por cruzada casi de
inmediato. Por lo mismo, con la tablet conviene iniciar la misión lejos de la
primera RSU.

### Revisar antes de salir

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 preparar -Ruta mi_ruta
```

Muestra la longitud de la ruta y cada RSU con su distancia desde el origen. Si una
RSU sale con «AVISO: el servidor no la detecta en la ruta», no recibirá
solicitudes: muévela a la intersección por la que pasa la ruta. El registro y la
trayectoria quedan en `resultados/evaluacion/rutas/`.

### Rutas fuera de la zona del grafo

El grafo compartido (`data/grafo_san_miguel_real.graphml`) cubre San Miguel,
Pueblo Libre, Jesús María y Lince, y es el de las campañas ya medidas. Para una
zona alejada, no lo agrandes: dale a la ruta su propio grafo.

1. Agrega a la ruta en `rutas.json` el campo `"grafo": "data/grafo_<ruta>.graphml"`.
2. Ejecuta `preparar`: si el archivo no existe, imprime el comando
   `regenerar_grafo.py ... --salida data/grafo_<ruta>.graphml`, con una caja que
   cubre el origen, el destino y las RSU a mano. Necesita `osmnx` e internet.
3. Vuelve a ejecutar `preparar`.

`evaluar.ps1 emulada` y `evaluar.ps1 gnss` le pasan ese grafo al servidor
(variable `GRAFO_PATH`). Las demás rutas siguen usando el compartido. La app
muestra el aviso «fuera de la zona de rutas del servidor» fuera de la caja del
grafo compartido; en una ruta con grafo propio ese aviso no aplica.

Ampliar el grafo compartido (el comando que sugiere `preparar` para una ruta sin
`grafo`) vuelve a descargar OpenStreetMap para toda la caja: las rutas de las
campañas anteriores podrían cambiar.

## Protocolo de la prueba con la tablet

Nada de esto toca un semáforo real: las RSU y los controladores corren en la laptop.
Quien maneja no opera la tablet.

**Antes de salir**

1. `evaluar.ps1 preparar -Ruta <ruta>` y revisar las RSU.
2. Laptop enchufada, con internet estable, suspensión desactivada y Tailscale activo.
   Broker TLS abierto (ver «Antes de empezar»).
3. Tablet cargada, con el certificado `obu-tab-01` ya cargado y Tailscale instalado.
   Celular con datos para el hotspot, también cargado.
4. Hacer una misión corta de prueba en casa con la OBU emulada
   (`evaluar.ps1 emulada -Ruta <ruta> -Repeticiones 1`).

**En el punto de partida**

1. En la laptop: `evaluar.ps1 gnss -Ruta <ruta>`. Anotar el host y el puerto.
2. Tablet en el hotspot, Tailscale encendido, «GPS real» y esperar «GNSS listo».
3. Verificar en la app que conecta al broker antes de iniciar.

**Misiones, en este orden**

| # | Misión | Para qué |
|---|---|---|
| 1 | Recorrido normal, siguiendo la ruta | Caso base: cruces, anticipación y error del ETA sin detención |
| 2 | Recorrido normal, otra vez | Segunda muestra del caso base |
| 3 | Detenerse más de 5 s antes de una RSU (por ejemplo, en la cola de un semáforo) | Error del ETA con detención y suspensión de la solicitud |
| 4 | Salir más de 60 m de la ruta y volver por otra calle | Recálculo por desvío |
| 5 | Apagar el hotspot 20–30 s a mitad de ruta y volver a encenderlo | Reconexión de la app: huecos de MP y caducidades |

Anotar en papel la hora y lo que pasó en cada misión (dónde se detuvo, dónde se
desvió, cuándo se cortó la red): sirve para leer el resumen. Al terminar, pulsar
Enter en la laptop y guardar el CSV de la tablet en la carpeta `tablet\`.

## Resultados

Cada evaluación queda en `resultados/evaluacion/<fecha>_<ruta>_<modo>/`, con:

- `resumen.txt`: misiones, paradas, `L`, RTT, anticipación, frecuencia de MP, huecos,
  fuente de velocidad, MP sin velocidad y error del ETA.
- `paradas.csv`: una fila por parada, con el error del ETA de esa parada.
- Eventos y logs de cada proceso. En el modo emulado, cada misión está en `obu\rep_NN\`.

Para volver a resumir una carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 resumen -Dir resultados\evaluacion\<carpeta>
```

## Cómo leer los resultados

- **`L`** es válida aquí porque el servidor y las RSU emuladas comparten el reloj de
  la laptop, pero no atraviesa un enlace hacia una RSU física.
- **Con la tablet**, los tiempos de `t_OBU→srv` cruzan el reloj de dos equipos y el
  resumen no los usa.
- **El error del ETA** compara el ETA que estimó el servidor a unos 8 s de la RSU
  (evento `eta_estimado`, uno por MP) con el tiempo que de verdad tardó el recorrido
  en pasar por el centro de la RSU. Positivo significa que el vehículo llegó más
  tarde de lo estimado. Se separa en pasos con y sin detención. Usa solo el reloj
  del servidor. Las corridas hechas antes de que existiera `eta_estimado` no lo
  tienen.
- Con `-Factor` distinto de 1, o con `-SinTls`, los resultados no son comparables con
  la campaña de [RESULTADOS_CAMPANA.md](RESULTADOS_CAMPANA.md).

## Si algo se queda corriendo

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 detener
```
