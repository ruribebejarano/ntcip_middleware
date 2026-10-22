# data/ — grafo vial cacheado para servidor/rutas.py

`grafo_san_miguel_real.graphml` es un grafo vial **real** de OpenStreetMap
(vía Overpass, descargado con `osmnx` 2.1.1 el 2026-10-22), no un grafo
sintético. Cubre la caja que envuelve las dos intersecciones de
`config/registro_rsu.json` (`OSM-C24` y `OSM-C902`, San Miguel, Lima, cerca
de la PUCP) más un margen de ~650 m: 415 nodos, 725 aristas.

- Se generó con `scripts/datos/regenerar_grafo.py` (requiere `osmnx` y
  acceso a internet; no hace falta para *correr* el servidor, solo para
  regenerar este archivo).
- `servidor/rutas.py` lo carga con `networkx.read_graphml` puro — correr el
  servidor con este grafo cacheado **no** requiere `osmnx` instalado.
- Para pruebas automatizadas (sin red, sin este archivo) se usa en cambio
  `servidor.rutas.construir_grafo_sintetico()`, un grafo pequeño hecho a
  mano con coordenadas inventadas — ver `tests/test_rutas.py`.

[DATO: medir en campo] esta caja no fue verificada contra las coordenadas
reales de la Cía. de Bomberos San Miguel N.º 83 ni del Hospital Centro
Médico Naval (el escenario de referencia de la tesis): no se pudieron
geocodificar esos dos nombres con Nominatim en este entorno. Si el autor
confirma esas coordenadas y caen fuera de esta caja, hay que volver a
correr `scripts/datos/regenerar_grafo.py` con una caja más grande (parámetro
`--margen-deg`, o editar las coordenadas de referencia en el script).

Ver `docs/bitacora/2026-10-22_arquitectura-centralizada.md` para el detalle
completo de esta corrida (parámetros exactos, tiempo, y el intento de
geocodificación que falló).
