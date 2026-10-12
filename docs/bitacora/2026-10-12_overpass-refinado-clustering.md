# 2026-10-12 — Refinamiento de la comparación OSM/Overpass vs. inventario MML

**Objetivo específico:** ninguno (continúa la verificación de un dato citado en el Capítulo I)
**Requerimientos:** N/A
**Sección de la tesis:** introducción / "Fragmentación tecnológica..." (cita `\cite{MML_GMU_Controlador2025}`, la cifra de 1,646 intersecciones semaforizadas)
**Commit:** `<se completa al hacer commit>`

## Qué se implementó

Nada de código permanente (un par de scripts Python de un solo uso en
`%TEMP%`, no en el repositorio). Se refinó la comparación de
`2026-10-11_overpass-traffic-signals-lima.md`, que usaba un bbox
rectangular aproximado y un conteo simple de nodos:

1. Se reemplazó el bbox por el límite administrativo real de Lima
   Metropolitana (relación OSM 1944670, vía Nominatim), que excluye el
   Callao.
2. Se separaron los nodos `highway=traffic_signals` peatonales (en vías
   exclusivamente peatonales/ciclovía, o con `crossing=traffic_signals`
   sin vía vehicular) de los vehiculares, usando las vías `highway=*` que
   contienen cada nodo.
3. Se agruparon los nodos vehiculares a menos de 40 m entre sí como una
   misma intersección (componentes conexas sobre un grafo de pares a
   <40 m, `scipy.spatial.cKDTree`).

## Resultado

- Límite real (sin bbox): 3,502 nodos `highway=traffic_signals` (vs. 3,758
  del bbox -- el sobre-conteo del bbox solo explicaba un 6.8% de la
  diferencia original).
- Vehiculares: 3,370 (96.2%) · Peatonales: 132 (3.8%).
- Agrupados a <40 m: **1,411 intersecciones**, de las cuales 943 (66.8%)
  tienen 2+ nodos (uno por acceso) y 468 (33.2%) un solo nodo.
- **OSM (1,411) vs. MML (1,646): razón 0.857 -- OSM reporta ~14.3% MENOS
  que el inventario oficial**, no ~2.28x más como sugería la comparación
  anterior sin refinar. Lectura invertida: en vez de "OSM exagera por mal
  etiquetado", el resultado refinado sugiere que OSM tiene cobertura
  incompleta de la red semafórica real de Lima -- consistente con, y
  reforzando, el argumento de fragmentación/falta de un inventario único
  y confiable que ya cita `main.tex`.

## Cómo

- Nominatim para resolver "Provincia de Lima" a la relación OSM 1944670.
- Dos consultas Overpass QL contra `overpass-api.de`: una para los nodos
  (`out body;`, 652,508 bytes), otra para las vías `highway=*` que
  contienen esos nodos (`way(bn.signals)[highway]; out body;`, 2,102,346
  bytes) -- necesaria para la clasificación vehicular/peatonal.
- **Cambio de método de descarga respecto de la vez anterior**: la
  herramienta de *fetch* del agente (usada el 2026-10-11 para la consulta
  simple de conteo) no es viable para 2+ MB de JSON -- resume el contenido
  con un modelo, no garantiza reproducir miles de coordenadas exactas sin
  error. Se usó en su lugar `urllib.request` de Python directo, con
  reintentos (los intentos grandes normalmente fallan la primera vez con
  504 "servidor ocupado" y pasan en el segundo o tercer intento). El
  `curl`/PowerShell local sigue devolviendo 406 de forma intermitente
  (mismo problema de red/TLS de esta máquina que en la entrada anterior);
  `urllib.request` sí logró pasar.
- Clasificación vehicular/peatonal: conjunto de valores `highway` de las
  vías padre de cada nodo, clasificado contra una lista fija de clases
  "drivable" vs. "solo peatonal" (ver el archivo de evidencia para la
  lista completa).
- Agrupamiento: proyección equirectangular local (válida a esta escala),
  `cKDTree.query_pairs(r=40)` + Union-Find para las componentes conexas.

## Desviaciones respecto del diseño de la tesis

Ninguna -- verificación de un dato de contexto, no toca diseño ni
implementación.

## Evidencia

- `evidencia/2026-10-12_overpass_traffic_signals-lima-refinado.txt`:
  metodología completa (las dos consultas Overpass QL exactas, la
  clasificación, el agrupamiento, el caveat de *chaining* del
  agrupamiento, y la comparación final).
- `evidencia/2026-10-12_overpass_clusters-interseccion-detalle.csv`:
  detalle de los 1,411 clusters (id, número de nodos, ids de OSM de cada
  nodo miembro, centroide lat/lon) -- reproducible y verificable nodo por
  nodo en OSM si se quiere auditar algún caso.

## Problemas y solución

- **El agrupamiento por enlace simple ("chaining") puede fusionar de
  más**: un cluster de componentes conexas con radio fijo puede terminar
  con un diámetro mayor que el radio de enlace si hay una cadena continua
  de nodos próximos entre sí (p. ej. una avenida con semáforos muy
  seguidos). Se verificó el diámetro máximo (Haversine, par más alejado)
  de los 943 clusters multi-nodo: solo 7 (0.7%) superan 80 m, solo 2
  (0.2%) superan 100 m -- el efecto es real pero marginal (<1% de los
  clusters), documentado explícitamente en la evidencia en vez de
  ignorarlo u ocultarlo detrás de una cifra única.
- **Descarga de >2 MB de JSON no es viable vía la herramienta de fetch del
  agente**: a diferencia de la consulta simple de conteo del 2026-10-11
  (unas pocas líneas de JSON, reproducibles fielmente por un modelo), un
  volumen de miles de coordenadas no se puede confiar a un resumen —
  cualquier error de transcripción de un dígito en una coordenada
  corrompería silenciosamente el agrupamiento espacial. Se resolvió
  bajando los bytes crudos con `urllib.request` de Python en su lugar.

## Pendiente

- Decidir si esta comparación refinada (y no la del 2026-10-11, ya
  superada) se incorpora al texto de la tesis.
- Si se incorpora, considerar verificar visualmente en un mapa los 7
  clusters con diámetro >80 m, para confirmar si son intersecciones
  complejas reales o fusiones erróneas de dos cruces cercanos -- no hecho
  en esta sesión.
- Las 943 intersecciones con 2+ nodos por acceso podrían ser una fuente
  de datos real para la línea de detención por acceso del registro de RSU
  (`ssec:registro`), en vez de solo el centroide de la intersección -- no
  explorado todavía, solo señalado como posibilidad.
