# data/ — grafo vial cacheado para servidor/rutas.py

`grafo_san_miguel_real.graphml` es un grafo vial **real** de OpenStreetMap
(vía Overpass, descargado con `osmnx` 2.1.1, última regeneración el
2026-10-23), no un grafo sintético. Cubre la caja que envuelve las dos
intersecciones de `config/registro_rsu.json` (`OSM-C24` y `OSM-C902`, San
Miguel, Lima, cerca de la PUCP) **y** el escenario de referencia de la
tesis (Cía. de Bomberos San Miguel N.º 83 → Hospital Centro Médico Naval),
más un margen de ~650 m: 5762 nodos, 11401 aristas.

- Se generó con `scripts/datos/regenerar_grafo.py
  --incluir-escenario-referencia` (requiere `osmnx` y acceso a internet; no
  hace falta para *correr* el servidor, solo para regenerar este archivo).
  Las coordenadas de ambos extremos del escenario de referencia se
  geocodificaron con Nominatim (OpenStreetMap) el 2026-10-23 y están
  documentadas en ese script.
- `servidor/rutas.py::cargar_grafo` lo carga con `networkx.read_graphml`
  puro (correr el servidor con este grafo cacheado **no** requiere `osmnx`
  instalado) y lo colapsa de `MultiDiGraph` a `DiGraph` simple quedándose
  con la arista más corta entre cada par de nodos cuando OSMnx trae más de
  una (p. ej. una avenida con separador físico).
- Para pruebas automatizadas (sin red, sin este archivo) se usa en cambio
  `servidor.rutas.construir_grafo_sintetico()`, un grafo pequeño hecho a
  mano con coordenadas inventadas — ver `tests/test_rutas.py`.

Ver `docs/bitacora/2026-10-22_arquitectura-centralizada.md` para el detalle
de la corrida original (caja chica, sin el escenario de referencia).
