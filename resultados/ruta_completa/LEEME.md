# LEEME: cómo se generó cada archivo de `resultados/ruta_completa/`

Todo se corre con el Python del entorno virtual del repo, desde la raíz del repo, en la laptop
(condición local). Los comandos están en el orden en que se ejecutaron.

## 1. Registro de RSU e intersecciones

```
python scripts/datos/registro_ruta.py --origen=-12.074664,-77.082933 --destino=-12.0649978,-77.0464372 \
  --semaforos <semaforos_nodos.geojson de OSM> \
  --salida scripts/campanas/fixtures/registro_ruta_hospital_nino.json \
  --csv resultados/ruta_completa/intersecciones_ruta.csv
```

Genera `intersecciones_ruta.csv` y el registro de 13 RSU (ids 101–113).

## 2. Trayectorias base y validación sin red

```
python scripts/campanas/preparar_ruta_completa.py
```

Escribe en `scripts/campanas/fixtures/ruta_completa/` las trayectorias A, B (una por semilla) y C,
y `validacion_sin_red.json`.

## 3. Campaña

Primero se arranca el broker TLS 1.3 + mTLS en 8883:

```
mosquitto -c deploy/pki/mosquitto_laptop_tls.conf
```

Su log queda en `_broker/`. Luego, cada escenario:

```
python scripts/campanas/ruta_completa.py --escenario A --semillas 101 102 103 104 105 --tls deploy/pki
python scripts/campanas/ruta_completa.py --escenario B --semillas 201 202 203 204 205 --tls deploy/pki
python scripts/campanas/ruta_completa.py --escenario C --semillas 301 --tls deploy/pki
```

Cada uno crea `<timestamp>_<escenario>/`, con `config.json` y una carpeta `rep_XX/` por
repetición: eventos CSV de cada nodo, logs, trayectorias, desfases de los controladores y
memoria. `_campana_*.log` es la salida de consola. `_prueba/` es una repetición de prueba que no
cuenta como dato.

## 4. Análisis

```
python scripts/analisis/ruta_completa.py --dir resultados/ruta_completa/20261107-123645_A \
  --dir resultados/ruta_completa/20261107-132149_B --dir resultados/ruta_completa/20261107-141431_C \
  --salida resultados/ruta_completa/analisis
```

Genera `analisis/por_parada.csv`, `por_repeticion.json` y `resumen.json`.

## 4b. Estimación sin red con la geocerca corregida (no es medición)

```
python scripts/analisis/estimacion_geocerca_corregida.py   --salida resultados/ruta_completa/analisis/estimacion_geocerca_corregida.json
```

## 5. Figuras

```
python scripts/analisis/figuras_ruta_completa.py --analisis resultados/ruta_completa/analisis \
  --rep-a resultados/ruta_completa/20261107-123645_A/rep_01 \
  --rep-b resultados/ruta_completa/20261107-132149_B/rep_01 \
  --salida resultados/ruta_completa/figuras
```

## Otros

- **`RESUMEN.md`:** cifras clave, con el archivo del que sale cada una, y hallazgos.
- **`borrador_seccion_tesis.tex`:** propuesta de texto para reemplazar la subsección de
  priorización sucesiva. No se editó `main.tex`.
- **`PLAN.md`, `AVANCE.md`, `simulacion_previa.py`:** planificación y estimación previas.

## 6. Reproducción animada (registros medidos, sin cálculos nuevos)

```
python scripts/analisis/reproduccion_ruta.py   --rep resultados/ruta_completa/20261107-123645_A/rep_01   --rep resultados/ruta_completa/20261107-132149_B/rep_01   --rep resultados/ruta_completa/20261107-141431_C/rep_01   --analisis resultados/ruta_completa/analisis   --salida resultados/ruta_completa/reproduccion/reproduccion_ruta.html
```

- Genera una página HTML autocontenida: se abre con doble clic, sin servidor.
- Los tramos de verde por prioridad salen de las órdenes SNMP de la RSU al controlador. El
  controlador solo registra cambios de fase visibles.
- El plan normal se reconstruye desde `ctrl_inicio`.
