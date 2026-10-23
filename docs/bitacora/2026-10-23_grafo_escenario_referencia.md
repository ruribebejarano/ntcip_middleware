# 2026-10-23 — Grafo real ampliado al escenario de referencia y corrección de cargar_grafo

**Objetivo específico:** OE1 (arquitectura, cálculo de ruta)
**Requerimientos:** RF-13 (cálculo de ruta óptima)
**Sección de la tesis:** `ssec:ruta_servidor`
**Commit:** (pendiente de commit)

## Qué se implementó

Se geocodificaron con Nominatim los dos extremos del escenario de
referencia de la tesis (Cía. de Bomberos San Miguel N.º 83 y Hospital
Centro Médico Naval), algo que en la corrida del 2026-10-22 no se había
logrado. Con esas coordenadas se regeneró `data/grafo_san_miguel_real.graphml`
con una caja que ahora cubre la ruta real completa (antes solo cubría las
dos intersecciones de `config/registro_rsu.json`). De paso, al probar
`calcular_ruta()` contra este grafo más grande apareció y se corrigió un
error preexistente en `servidor/rutas.py::cargar_grafo`.

## Cómo

- **Geocodificación:** Nominatim (`nominatim.openstreetmap.org/search`,
  `countrycodes=pe`), con un `User-Agent` identificable. El intento anterior
  había fallado por cómo estaba escrita la consulta (incluía "N.º" con el
  carácter de grado), no porque Nominatim no tuviera el dato:
  - Compañía de Bomberos San Miguel Nº 83: -12.0856611, -77.0758653
  - Hospital Centro Médico Naval: -12.0587319, -77.0891002
- **`scripts/datos/regenerar_grafo.py`:** se le agregó la bandera
  `--incluir-escenario-referencia` (amplía la caja con las dos coordenadas
  anteriores) y `--norte/--sur/--este/--oeste` para una caja manual —el
  docstring original ya prometía esto último, pero el código no lo tenía
  implementado. Corrida con `--incluir-escenario-referencia`: caja de
  ~6.3 km × 7.5 km, 5762 nodos, 11401 aristas, 216 s contra Overpass
  (`overpass-api.de`).
- **Corrección en `servidor/rutas.py::cargar_grafo`:** el grafo que exporta
  OSMnx es un `MultiDiGraph` (permite más de una arista entre el mismo par
  de nodos — en este grafo había 20 pares así, típicamente avenidas con
  separador físico). `calcular_ruta()` acumula `G[prev][nid]["length"]`
  esperando un `DiGraph` simple; contra un `MultiDiGraph` esa posición es
  un diccionario de aristas paralelas (indexado por un entero, no por
  "length"), así que fallaba con `KeyError`. Se corrigió haciendo que
  `cargar_grafo` colapse el grafo a `DiGraph` simple, quedándose con la
  arista de menor longitud entre cada par de nodos cuando hay más de una.

## Desviaciones respecto del diseño de la tesis

Ninguna. Es una corrección de implementación (la tesis ya describe
`calcular_ruta()` como un camino más corto sobre un grafo vial, sin asumir
aristas paralelas).

## Evidencia

Sin archivo de evidencia dedicado: la corrida de `regenerar_grafo.py` y la
verificación manual de `calcular_ruta()` (bomberos→hospital: 6260.4 m;
`OSM-C24`→`OSM-C902`: 572.1 m, ambas sin error) quedaron en el historial de
esta sesión, no en `evidencia/`.

## Problemas y solución

- **Nominatim no encontraba los dos nombres** en el intento del
  2026-10-22 → la consulta incluía el carácter "N.º" mal codificado; con
  una consulta más simple ("Compañía de Bomberos San Miguel", "Centro
  Médico Naval") sí resolvió ambos.
- **`calcular_ruta()` fallaba con `KeyError('length')`** contra el grafo
  real (nunca antes ejercitado con datos reales, solo con los grafos
  sintéticos de las pruebas) → causa y corrección descritas arriba en
  "Cómo".

## Pendiente

- Confirmar con el asesor si el escenario de referencia (bomberos →
  hospital) debe usarse como campaña de prueba real, ahora que el grafo ya
  lo cubre.
- El resto de lo marcado como pendiente en
  `docs/bitacora/2026-10-22_arquitectura-centralizada.md` (Raspberry Pi
  real, TLS/mTLS reales, consola de monitoreo, scripts de análisis) sigue
  abierto; no se tocó en esta sesión.
