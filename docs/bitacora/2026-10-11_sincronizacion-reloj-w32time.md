# 2026-10-11 — Sincronización de reloj (W32Time) y comparación antes/después

**Objetivo específico:** Infraestructura transversal; sustenta la medición de `t_V2I` en `scripts/analisis/latencia_tramos.py` (RNF-01, `ssec:latencia`).
**Requerimientos:** Ninguno directo (ver nota de `2026-10-11_flujo-laptop-pi.md`).
**Sección de la tesis:** `ssec:instrumentacion` (Capítulo IV).
**Commit:** sin cambios de código en este hito (solo resultados y bitácora); ver `resultados/prueba_registro_sincronizado/`.

## Qué se hizo

1. Se configuró W32Time en la laptop (`time.cloudflare.com` /
   `time.google.com`, arranque automático) — comandos ejecutados por el
   estudiante en PowerShell elevado (el agente de código no tiene ni
   pide credenciales de administrador).
2. Se repitió la prueba de registro de eventos de P1
   (`resultados/prueba_registro/`) en una carpeta nueva,
   `resultados/prueba_registro_sincronizado/`, con W32Time ya activo,
   para comparar antes/después.
3. Al encontrar que la convergencia era mucho más lenta de lo esperado
   (ver "Problemas y solución"), se midió el offset de reloj **en el
   momento exacto** de la segunda corrida y se usó para corregir
   analíticamente el resultado, en vez de esperar la convergencia
   completa.

## Comparación antes / después

| | `prueba_registro/` | `prueba_registro_sincronizado/` |
|---|---|---|
| W32Time en la laptop | detenido | activo, en proceso de *slew* |
| `t_V2I` crudo | −2.75 ms (imposible) | +157.60 ms (imposible) |
| `t_RSU` / `t_NTCIP` (solo Pi, no cruzan máquina) | 0.19 / 0.74 ms | 0.19 / 0.55 ms |
| Offset laptop↔Pi medido en el momento | no medido | **+156.95 ms** |
| `t_V2I` corregido con el offset medido | no se puede corregir (offset desconocido) | **≈0.65 ms** (plausible) |

Detalle completo del cálculo en `resultados/prueba_registro_sincronizado/notas.md`.

## Desviaciones respecto del diseño de la tesis

Ninguna sobre el diseño del sistema. Hallazgo operativo importante para
el Capítulo IV: **activar W32Time no corrige el reloj al instante.**
Windows corrige gradualmente ("slew"), no de un salto, incluso cuando se
fuerza `w32tm /resync /force` o se reinicia el servicio
(`Stop-Service`/`Start-Service`) — se probaron ambas cosas y la tasa de
corrección observada fue la misma en los dos casos, ≈4 ms/min. Para un
desfase acumulado de ~194 ms (producto de varias horas sin sincronizar
durante esta sesión), la convergencia completa habría tomado del orden
de 40–50 minutos adicionales, que no se esperaron.

## Evidencia

- `resultados/prueba_registro_sincronizado/` (`config.json`, `notas.md`,
  `eventos_obu.csv`, `eventos_rsu_1.csv`, `eventos_ctrl_1.csv`,
  `latencia_tramos.csv`): la segunda corrida completa, con el offset
  medido y la corrección documentada.
- `evidencia/2026-10-11_laptop_w32time-sincronizado.png` (ya comiteada
  en el hito de P2): configuración y primer `/resync /force` exitoso.

## Problemas y solución

- **La convergencia del reloj fue mucho más lenta de lo esperado** tras
  configurar W32Time: offset medido en +194 ms, +187 ms, +171 ms,
  +158 ms, +156 ms a lo largo de ~16 minutos (≈4 ms/min). Se probó
  forzar un `/resync /force` adicional y, después, un ciclo completo
  `Stop-Service`/`Start-Service` + `/resync /force`, con la hipótesis de
  que un "primer sync" tras reiniciar el servicio podría aplicar un
  salto (*step*) en vez de una corrección gradual — no fue el caso: la
  tasa de corrección se mantuvo igual antes y después de ambos
  intentos. No se profundizó más en la causa exacta (política interna
  de slew/step de W32Time, posiblemente ligada al tamaño del offset o a
  configuración de `MaxPosPhaseCorrection`), por no ser el objetivo de
  este hito.
- **Solución adoptada**: en vez de esperar la convergencia completa, se
  midió el offset vigente en el momento exacto de la corrida
  (`scripts/pi.sh clock`, ya disponible desde el hito de
  `2026-10-11_flujo-laptop-pi.md`) y se usó para corregir
  analíticamente `t_V2I` y `L_aprox`. El resultado corregido (~0.65 ms)
  es plausible para un salto MQTT en LAN, lo que valida el método.

## Pendiente

- Si se quiere confirmar que el offset realmente llega a converger a
  ~0 con tiempo suficiente, repetir `scripts/pi.sh clock` más tarde
  (sin que sea bloqueante para seguir con P3).
- Evaluar, para las campañas reales de latencia (P6 en adelante), si
  conviene dejar W32Time corriendo con antelación suficiente (varias
  horas) antes de la campaña, o si conviene que
  `scripts/analisis/latencia_tramos.py` reciba el offset medido como
  parámetro y lo aplique automáticamente — no implementado todavía.
- Continuar con **P3** (`docs/PLAN_IMPLEMENTACION.md`): NTCIP 1211 real
  (`priorityRequestTable`), reemplazando `solicitudPrioridadTest`.
