# 2026-10-30 — Renovación y cruce por avance sobre la ruta (servidor central)

**Objetivo específico:** OE4 (verificación de geocerca en el servidor) / OE1 (servidor como decisor)  **Requerimientos:** RF8 (anticipación), RNF-02 (renovación a 1 Hz), RNF-03 (caducidad), RF-04 (cancelación al cruzar)
**Sección de la tesis:** 3.x (servidor central: ssec:emision / ruta) → 4.x (prueba)
**Commit:** el de este archivo (`OE4: renovar y cerrar por avance en ruta ...`)

## Qué se implementó

Corrige el defecto descrito en `2026-10-30_consola-multi-rsu.md` ("Pendiente"):
una solicitud emitida por anticipación de ETA en una intersección que la
geocerca no seguía nunca se renovaba, y la RSU la daba por caducada
(RNF-03, 3 s) **antes** de que llegara el vehículo. En el escenario
hospital_nino a velocidad real ocurría con el vehículo a 40 m de la RSU 4.

Ahora, en `servidor/gestor_mision.py::procesar_mp`, un paso 3 (respaldo
por ruta, `_respaldo_por_ruta`) actúa después de la geocerca:

- toda parada en solicitada / en cola / concedida que la geocerca no
  renovó en ese MP se renueva igual (M1 con seq+1);
- se cierra con M3 `cruce` cuando el avance sobre la ruta supera la
  distancia de llegada de la parada + `MARGEN_CRUCE_M` (20 m, constante
  que ya existía en el módulo pero no se usaba).

Además, `_recalcular_por_desvio` actualiza la `ParadaRsu` de las paradas
que siguen en la ruta nueva, porque su `distancia_llegada_m` se mide sobre
esa ruta (el avance vuelve a 0 al recalcular).

## Cómo

- Archivos: `servidor/gestor_mision.py`, `tests/test_gestor_mision.py`
  (2 pruebas nuevas: un rodeo sintético que reproduce el defecto si se
  desactiva el respaldo, y su corrección: seq consecutivos sin huecos + M3
  `cruce`).
- No se tocó `gateway/geometria.py` (la semántica de "cruce" de la
  geocerca, ssec:emision, queda igual) ni `agent/`.

## Desviaciones respecto del diseño de la tesis

- **A documentar en el Cap. 3:** la renovación de una solicitud vigente
  deja de depender solo de la geocerca. El servidor la mantiene viva por
  avance sobre la ruta, y la cierra por cruce con el mismo criterio. La
  geocerca sigue siendo la verificación final del acceso: si dispara antes
  (cruce al pasar el centro), manda ella.
- **Cambio de comportamiento observable:** las renovaciones llevan ahora en
  `t_servicio` el ETA recalculado en cada MP (decreciente). Antes quedaba
  congelado en el último ETA que tuvo la parada mientras estaba
  "pendiente".
- `MARGEN_CRUCE_M = 20 m` sigue siendo provisional (marcado [REVISAR con
  asesor]): con GNSS real, un margen muy corto podría cerrar antes de
  tiempo si la proyección sobre la ruta salta.

## Evidencia

- Reproducción offline (`GestorMision` con reloj simulado y
  `trayectoria_hospital_nino.csv`): RSU 4 pasa de 1 M1 a 10 (t=49…58) +
  M3 `cruce` en t=59 (el vehículo pasa el centro en t=56). RSU 5 y 6 sin
  cambios en sus tiempos de M1/M3.
- En vivo, `--factor 1`, 3 RSU + servidor con `scripts/demo/lanzar_rsus.ps1`
  contra un broker aparte (1884), `resultados/demo/2026-10-30T111219/`
  (no versionado):

  | RSU | M1 recibidos | hueco máx. | caducidad | M3 | 1.er M1 a | M3 a |
  |---|---|---|---|---|---|---|
  | 4 | 10 | 1,00 s | 0 | cruce | 69 m | 23 m después |
  | 5 | 16 | 1,00 s | 0 | cruce | 149 m | 8 m después |
  | 6 | 14 | 1,00 s | 0 | cruce | 149 m | 18 m después |

  Antes del cambio (`resultados/demo/2026-10-30T024239/`): RSU 4, 1 M1 y
  caducidad con el vehículo a 40 m.
- `pytest -q tests`: 114 pruebas pasan.

**Capturas que debe tomar el estudiante:** la línea de tiempo de la consola
("Misión (varias RSU)") de una corrida a `--factor 1` donde se vea la RSU 4
concedida hasta el M3 `cruce`, sin `caducidad`.

## Problemas y solución

- El M1 por ETA del paso 1 y la renovación del paso 3 podían salir en el
  mismo MP: el seq de cada parada se toma **antes** del paso 1 y el paso 3
  solo renueva lo que no se emitió ni renovó en ese mismo MP.
- Observado de paso (sin corregir): si se corre `lanzar_rsus.ps1` con su
  salida conectada a una tubería (`| Select-String`, `| Out-String`), la
  llamada no termina hasta que mueren los procesos lanzados (heredan el
  handle de la tubería por `Start-Process -Redirect*`). Desde una terminal
  normal termina enseguida.

## Pendiente

- Calibrar `MARGEN_CRUCE_M` con GNSS real (OE5).
- La exclusión de la geocerca tras un giro lejano (cruce "falso" de
  `SeguidorAcceso`) sigue existiendo; ya no deja la solicitud sin
  renovar. Decidir con el asesor si ssec:emision debe exigir cercanía al
  centro para llamarlo "cruce".
