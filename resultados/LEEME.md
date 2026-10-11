# Resultados de pruebas (Capítulo 4)

Estructura: `resultados/<escenario>/<AAAA-MM-DD_HHMM>/`
- `datos.csv`     — datos crudos con marcas de tiempo (nunca se editan a mano)
- `config.json`   — parámetros de la corrida + hash del commit usado
- `notas.md`      — condiciones (red, ubicación, incidencias)

El script `scripts/analisis/<escenario>.py` lee las corridas y genera las figuras
directamente en `F:\tesis2\Overleaf\figuras\resultados\`.
