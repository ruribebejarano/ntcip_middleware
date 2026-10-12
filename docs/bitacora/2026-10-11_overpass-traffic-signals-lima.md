# 2026-10-11 — Contraste OSM/Overpass vs. inventario MML de intersecciones semaforizadas

**Objetivo específico:** ninguno (verificación de un dato citado en el Capítulo I de la tesis, no parte de P0–P9)
**Requerimientos:** N/A
**Sección de la tesis:** introducción / "Fragmentación tecnológica..." (cita `\cite{MML_GMU_Controlador2025}`, la cifra de 1,646 intersecciones semaforizadas)
**Commit:** `<pendiente de completar>`

## Qué se implementó

Nada de código. Se consultó la Overpass API (OpenStreetMap) para contar
cuántos nodos `highway=traffic_signals` existen en un bbox aproximado de
Lima Metropolitana, como contraste externo del dato de 1,646
intersecciones semaforizadas que `main.tex` cita del inventario de la
Municipalidad Metropolitana de Lima (MML). No se implementó nada más, por
pedido explícito.

## Cómo

- Consulta Overpass QL: `node["highway"="traffic_signals"](-12.30,-77.20,-11.75,-76.80); out count;`
- El `curl` local a `overpass-api.de` devolvió sistemáticamente HTTP 406
  (Apache), incluso para un `GET /api/status` sin parámetros — parece un
  problema de la red/inspección TLS de esta máquina (en un intento sí pasó
  la conexión y Overpass respondió con un 504 "server probably too busy",
  confirmando que el servidor funciona normalmente). La consulta se
  resolvió entonces a través de la herramienta de *fetch* del agente, dos
  veces, con resultado idéntico ambas veces.
- Resultado: **3,758 nodos** `highway=traffic_signals` en el bbox, frente
  a las **1,646 intersecciones semaforizadas** del inventario de la MML
  (`\cite{MML_GMU_Controlador2025}`) — OSM reporta ~2.28× la cifra oficial.

## Desviaciones respecto del diseño de la tesis

Ninguna — esta tarea no toca el diseño ni la implementación, solo verifica
un dato de contexto ya citado.

## Evidencia

- `evidencia/2026-10-11_overpass_traffic_signals-lima.txt`: la consulta
  completa, el JSON de respuesta tal como lo devolvió la API, y la
  comparación con la cifra de la MML.

## Problemas y solución

- **`curl` local bloqueado (406) contra `overpass-api.de`**: no se pudo
  diagnosticar la causa raíz en esta sesión (probablemente inspección
  TLS/proxy de la red de esta máquina, dado que un intento sí llegó al
  servidor y produjo un 504 genuino de Overpass, no otro 406). Se resolvió
  usando la herramienta de *fetch* del agente como ruta alterna, sin
  necesidad de workaround adicional. Si se vuelve a necesitar esta
  consulta desde esta laptop, vale la pena investigar si hay un proxy
  corporativo o un antivirus con inspección SSL interfiriendo.

## Pendiente

- Decidir si esta comparación se incorpora a la tesis (p. ej. como
  evidencia adicional de la dificultad de obtener un inventario fiable y
  único de semáforos en Lima, en la sección de fragmentación tecnológica)
  y, si se incorpora, investigar cuál de las hipótesis de la evidencia
  (convención de etiquetado de OSM por aproximación/cruce peatonal, bbox
  más amplio que el límite administrativo de la MML, calidad de OSM,
  cobertura jurisdiccional distinta) explica mejor la diferencia de
  ~2.28× antes de afirmar una causa en el texto — no investigado en esta
  sesión, por pedido explícito de no implementar nada más todavía.
