# Prueba de registro de eventos (P1, RF-10)

Corrida de validación del módulo `common/events.py` integrado en
`gateway/obu_simulator.py`, `agent/rsu_middleware.py` y
`controller/controller_emulator.py`. No es una campaña de latencia real
(un solo ensayo), solo verifica que el registro y el cruce por
`id_solicitud` funcionan de punta a punta.

## Cómo se corrió

- `rsu-agent.service` y `rsu-controller.service` reiniciados en la Pi
  (`192.168.18.175`) con el código del commit `455621d`.
- Desde la laptop: `gateway/obu_simulator.py --broker-host 192.168.18.175
  --vehiculo-id ambulancia-p1 --eta-seg 10 --obu-id obu`, con
  `RSU_EVENTOS_DIR=resultados/prueba_registro` para que el evento del lado
  de la OBU cayera directamente aquí.
- `eventos_rsu_1.csv` y `eventos_ctrl_1.csv` se generaron en
  `~/ntcip_middleware/resultados/eventos/` en la Pi (ruta por defecto de
  los servicios) y se copiaron a mano a esta carpeta con `scp` (no se usó
  `scripts/pi.sh fetch` porque ese fetch trae `resultados/` completo a
  `resultados/rsu/`, no a esta carpeta puntual).
- `scripts/analisis/latencia_tramos.py --dir resultados/prueba_registro`
  generó `latencia_tramos.csv`.

## Resultado

Una sola solicitud (`ambulancia-p1-cdd9f1ab`), con los 4 eventos
completos. Los cuatro eventos aparecieron en el orden correcto y se
cruzaron correctamente por `id_solicitud` (el cruce en sí funciona).

Los **valores de latencia no son utilizables como medición real**:
`t_V2I_aprox_ms = -2.75` (negativo, imposible físicamente). Causa:
`t_V2I` es el único tramo que resta una marca de tiempo de la laptop
(`M1_tx`, en `gateway/obu_simulator.py`) de una marca de tiempo de la Pi
(`M1_rx`, en `agent/rsu_middleware.py`) — y la sincronización de reloj
entre ambas máquinas (ver bitácora `2026-10-11_arranque-servicios-y-
smoke-test.md`) todavía no se aplicó del lado de la laptop (W32Time
seguía detenido en el momento de esta corrida). Consistente con esto,
`t_RSU_aprox_ms` (0.19) y `t_NTCIP_aprox_ms` (0.74) — ambos calculados
con dos marcas de tiempo de la **misma** máquina (la Pi) — sí son
positivos y del orden de magnitud esperado para un salto TCP local.

Esto confirma, con un ejemplo concreto, que la sincronización de reloj no
es un detalle secundario: sin ella, cualquier campaña de latencia V2I
(sección 4.3 de `docs/PLAN_IMPLEMENTACION.md`) va a reportar valores sin
sentido para el tramo que cruza máquinas. No se repitió la corrida
después de aplicar el fix de W32Time porque ese fix sigue pendiente del
lado del estudiante (requiere PowerShell como Administrador); repetir
esta prueba después de aplicarlo queda como siguiente paso.
