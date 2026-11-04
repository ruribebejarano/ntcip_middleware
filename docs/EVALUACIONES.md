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

## Cambiar o agregar rutas

Edita `scripts/evaluacion/rutas.json`. Cada entrada es una ruta:

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

Para revisar la ruta sin correr nada:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 preparar -Ruta mi_ruta
```

Muestra la longitud y las RSU elegidas. Las RSU se ubican solo donde OpenStreetMap
marca un semáforo sobre la ruta, así que puede haber menos que `max_rsu`. También se
omiten las que quedan muy cerca del origen en línea recta: una misión que empieza
dentro del radio de una RSU la da por cruzada casi de inmediato. Por lo mismo, con la
tablet conviene iniciar la misión lejos de la primera RSU.

Si el script dice que la ruta queda fuera del grafo vial, ejecuta el comando
`regenerar_grafo.py` que imprime. Necesita `osmnx` e internet, y el servidor debe
reiniciarse para usar el grafo nuevo. La app también tiene que incluir esa zona.

## Resultados

Cada evaluación queda en `resultados/evaluacion/<fecha>_<ruta>_<modo>/`, con:

- `resumen.txt`: misiones, paradas, `L`, RTT, anticipación, frecuencia de MP, huecos
  y fuente de velocidad.
- `paradas.csv`: una fila por parada.
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
- **El error del ETA** no se calcula, porque el servidor no registra el ETA en sus
  eventos.
- Con `-Factor` distinto de 1, o con `-SinTls`, los resultados no son comparables con
  la campaña de [RESULTADOS_CAMPANA.md](RESULTADOS_CAMPANA.md).

## Si algo se queda corriendo

```powershell
powershell -ExecutionPolicy Bypass -File scripts\evaluacion\evaluar.ps1 detener
```
