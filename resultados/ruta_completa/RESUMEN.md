# Resumen: ruta completa Av. La Marina → Hospital del Niño (Breña)

Campaña del 2026-11-07, condición local (laptop, broker TLS 1.3 + mTLS en 8883), 13 RSU y 13
controladores emulados, ruta de 5301,5 m. Corridas:

- A: `20261107-123645_A` (semillas 101–105)
- B: `20261107-132149_B` (semillas 201–205, perfil **sintético**)
- C: `20261107-141431_C` (semilla 301, desvío)

Las 11 repeticiones terminaron sin problemas registrados en su `config.json`: memoria libre mínima
de 1899 MB, arranque de 3,4–4,5 s, duración de 540 s en A, 606–659 s en B y 568 s en C.

## Cifras clave

Todas salen de `analisis/resumen.json`, salvo que se indique otra cosa.

| Cifra | A | B (sintético) | C |
|---|---|---|---|
| Solicitudes concedidas | 65/65 | 65/65 | 12/12 |
| Caducidades | 0 | 0 | 0 |
| Anticipación real, mediana | 13,0 s | 15,0 s | 12,0 s (*) |
| Anticipación real, mínima | 5,0 s | 6,4 s | 7,0 s (*) |
| Llegadas con anticipación < 8 s | 4/63 | 4/64 | 1/11 (*) |
| RTT servidor–RSU, mediana / 95 % bajo | 37,3 / 63,9 ms | 31,1 / 70,1 ms | 34,0 / 105,7 ms |
| L (M1 en RSU → verde), mediana | 4,5 ms | 3,2 ms | 3,1 ms |
| Verde sin prioridad, método de la tesis / exacto | 38,1 % / 39,7 % | 40,6 % / 40,6 % | (**) |
| Demora evitada por misión, tesis / exacta | 57,7 / 51,3 s | 51,9 / 52,5 s | (**) |
| Máximo de solicitudes simultáneas | 1 | 1 | 2 (4 s) |

(*) Sin contar la RSU 108, que el vehículo no cruza (ver más abajo). Calculado a mano desde
`analisis/por_parada.csv`, con las filas `ruta_C` y `rsu_id != 108`.

(**) El contrafactual de C incluye la RSU 108, cuyo "cruce" no es real; no se reporta.

En C hubo 2 recálculos (a 6,0 s y 7,0 s de la salida; de 13 → 6 → 4 paradas) y 6,1 ms del MP
al recálculo (`resumen.json` → `ruta_C.desvio`).

## Figuras (`figuras/`, PDF + PNG)

- `fig_ruta_mapa`: ruta y las 13 RSU.
- `fig_ruta_espacio_tiempo_A`, `fig_ruta_espacio_tiempo_B`: A rep_01 y B rep_01.
- `fig_ruta_anticipacion`: anticipación por RSU, A y B; propuesta para la tesis.
- `fig_ruta_con_sin_prioridad`.

## Resultados no esperados

1. **Anticipación menor a 8 s en 9 de 138 llegadas.** Contradice la tesis vigente: la tabla de
   cumplimiento y las conclusiones dicen "mínimo 9,21 s, sin ningún caso por debajo".
   - En A (RSU 101 y 104, las 5 repeticiones) la solicitud siempre la abrió el respaldo por ETA
     (`t_servicio` de 6,6–7,8 s), no la geocerca. El ETA se evalúa a 1 Hz y dispara con ETA ≤ 8 s,
     así que llega por debajo.
   - **Causa (verificada sobre la trayectoria A sin ruido):** el seguidor de la geocerca
     (`gateway/geometria.py`, `SeguidorAcceso`) declara "cruce" en cuanto la intersección deja de
     estar "por delante" (cono de ±45°), aunque el vehículo todavía esté lejos. Al declarar
     "cruce", además la excluye hasta que el vehículo se aleje más de 350 m.
     - RSU 101: la ruta la tiene por delante a 299–199 m (s = 140–240 m) y luego gira al sur.
       Queda excluida y el vehículo nunca se aleja 350 m, así que la geocerca no la vuelve a
       asignar.
     - RSU 104: hay una "S" (rumbo 130° → 39° → 129°) en los últimos 200 m. A 155 m queda de
       lado (47° > 45°) y se excluye. Solo se libera a 61 m, porque otra RSU ocupa el único hueco
       de exclusión.
     - Lo mismo explica el motivo "cruce" de la RSU 108 al desviarse en C.
     - Prueba fuera del repo: declarar "cruce" solo si el vehículo ya estuvo dentro de R_g (150 m)
       y, si no, perder la asignación sin excluir. Con eso, las 13 RSU de A abren por geocerca; la
       101 a 137 m de recorrido y la 104 a 192 m. No se aplicó: cambia el criterio de emisión y
       cancelación de la tesis.
   - En B, 3 casos los abrió la geocerca a 150 m (`t_servicio` = 8) con el vehículo rápido y la
     fase en ámbar o todo rojo.
2. **Verde con el vehículo detenido.** En B, 11 solicitudes mantuvieron prioridad con el vehículo
   detenido, 123 s en total y hasta 20 s en una sola.
   - La suspensión por detención (`T_DETENIDO_MAX_S` = 5 s) solo actúa sobre solicitudes que
     sostiene el ETA. Dentro de la geocerca, la renovación sigue.
   - En 4 de las 5 detenciones dirigidas sí hubo suspensión; quedaron 5–7 s de verde.
3. **RSU 108 en C.** El servidor la solicita al entrar a la geocerca (413,3 s) y la cancela 1 s
   después con motivo "cruce", al girar.
   - El controlador recibió 1 s de prioridad para un vehículo que no pasó.
   - El motivo "cruce" es engañoso: el vehículo no cruzó.
4. **Doble recálculo en C.** Se recalculó a 6 s de la salida y otra vez 1 s después: el primer
   recálculo partió de un nodo que todavía estaba en la ruta original.
5. **Dos solicitudes simultáneas en C.** Las RSU 110 y 111, a 141 m, coincidieron durante 4 s
   tras reingresar a la ruta; la 110 se había abierto por ETA.
6. **Error del ETA en B.** Mediana de +0,8 s, pero el 95 % de los errores absolutos queda bajo
   20,6 s: el ETA usa la velocidad del momento y no anticipa las detenciones del perfil.

## Estimación sin red para las RSU 101 y 104 (no es medición)

Decisión del autor (2026-11-07): no se repite la campaña con la geocerca corregida.

En lugar de rellenar las mediciones afectadas, `scripts/analisis/estimacion_geocerca_corregida.py`
pasa las mismas trayectorias, con el mismo ruido, por la geocerca tal cual y por la corregida. El
resultado está en `analisis/estimacion_geocerca_corregida.json`.

- Solo cambian las RSU 101 y 104; las otras 11 quedan igual.
- Tiempo desde la apertura por geocerca hasta llegar al centro, en A:
  - 101: 14 s (hoy la geocerca no la abre).
  - 104: 20 s (hoy 8 s o nada).
- En B los valores son de 16 a 40 s, porque incluyen las detenciones del perfil.
- Es tiempo hasta el centro, no anticipación real: falta la transición del controlador, que solo
  se mide con la red. Las tablas medidas no se modificaron.

## Lo que no se pudo medir

- **Controlador real y 4G.** Todo corrió en la condición local, con controladores emulados de
  ciclo fijo idéntico (8/3/2/8 s).
- **Más de una misión a la vez.** No se probó el arbitraje entre misiones.
- **C con estadística.** C tiene una sola repetición.
- **Velocidad real en ruta.** No hay trayectoria GNSS real de esta ruta; A es reproducida y B es
  sintética.

## Propuesta para la presentación

"En una ruta real de 5,3 km hacia el Hospital del Niño, con 13 semáforos y una RSU en cada uno,
el servidor pidió y obtuvo verde en las 13 intersecciones de cada misión, sin una sola solicitud
perdida. Sin prioridad, la ambulancia habría llegado en verde a solo 4 de cada 10 cruces; con
prioridad ahorra cerca de un minuto por viaje. Mostrar `fig_ruta_espacio_tiempo_A`."
