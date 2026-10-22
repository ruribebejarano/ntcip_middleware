# 2026-10-22 — Modo semiautomático y ruta calculada por el servidor (decisión de diseño)

**Objetivo específico:** OE1 (arquitectura), OE4 (OBU)  **Requerimientos:** RF-03, RF-04, RF-09, RF-11 (afectados por esta decisión; ver "Desviaciones")
**Sección de la tesis:** 3.2 (arquitectura), `ssec:app`, `ssec:zonas`, `ssec:emision` (diseño) → trabajo futuro
**Commit:** *(no aplica — no hay código todavía, ver más abajo)*

## Qué se implementó

Nada todavía: esta entrada registra una **decisión de diseño**, tomada sobre
`E:\Tesis\prompt_modo_semiautomatico_ruta.md`, previa a cualquier cambio de
código.

## Qué se decidió

1. **Modo de solicitud semiautomático.** El operador arma la misión una sola
   vez desde la app ("Iniciar emergencia" + destino); a partir de ahí, cada
   intersección de la ruta se solicita automáticamente, sin acción del
   conductor. La misión se desarma sola al llegar al destino o al vencer un
   tiempo máximo [DATO: por definir], o con el botón "Terminar emergencia".
2. **Ruta calculada por el servidor central.** Al armar la misión, el
   servidor calcula la ruta óptima desde la posición de la OBU hasta el
   destino (OSMnx + NetworkX sobre la red vial de OSM, en el banco de
   pruebas), la cruza con `config/registro_rsu.json` y obtiene la lista
   ordenada de RSU/accesos que el vehículo atraviesa. La geocerca que ya
   implementa `gateway/geometria.py` se conserva, pero cambia de rol: deja
   de decidir a qué RSU dirigir la solicitud y pasa a ser la **verificación
   final** de que la posición real de la OBU corresponde al acceso que el
   servidor ya designó por ruta.
3. **Interfaces.** La app Android (interfaz mínima: botón iniciar/terminar +
   destino, indicador del próximo semáforo, mapa con la ruta del servidor) y
   la consola de monitoreo (mapa de la misión: ruta, RSU por estado,
   posición en vivo, anticipación real vs. requerida) quedan como
   requerimientos nuevos, sin implementación todavía.

## Alternativas descartadas

- **Modo manual** (pedir prioridad en cada cruce desde la app): obliga al
  conductor a manipular el celular en plena emergencia; el presupuesto
  t = d / v (RF8 de `E:\Tesis\redaccion\capitulo3_borrador.md`) no admite esa
  demora en los cruces con `t_vecino_s < 5 s`.
- **Modo automático total** (solicitar siempre que el vehículo se mueve):
  pediría prioridad sin una emergencia activa (retorno a base, traslados no
  urgentes), alteraría el tránsito sin necesidad y se presta a abuso.

## Desviación importante respecto del diseño vigente de la tesis — pendiente de resolver con el asesor

**Esta decisión contradice una sección ya redactada y evidenciada de
`main.tex`** (fuera de este repo, en `F:\tesis2\Overleaf`): la sección de
selección del esquema de direccionamiento OBU→RSU (`ssec:sel_direccionamiento`)
comparó seis esquemas (E1–E6) con una matriz de criterios ponderados y
**adoptó explícitamente E2+E4 — registro descargado en la OBU, selección
local del acceso, sin consulta a un servicio central en el momento de la
solicitud** — por encima de E3 (el centro de control decide), que puntuó más
bajo en latencia, tolerancia a fallas y minimización de datos de posición
(Ley N.º 29733). La idea de "servidor central decide qué RSU y cuándo" de
esta entrada es, en lo esencial, el esquema E3 que esa sección ya evaluó y
descartó.

No se corrigió `main.tex` en este paso (son los Capítulos I–III, congelados
por `CLAUDE.md` del repositorio de la tesis, que exige mostrar antes/después
y esperar aprobación del autor antes de tocarlos). Queda como decisión
pendiente con el asesor: o bien (a) la arquitectura centralizada por 4G y el
modo semiautomático se adoptan formalmente, lo que obliga a reabrir y
rehacer `ssec:sel_direccionamiento` con una justificación nueva de por qué
ahora conviene E3 pese a lo que la matriz original mostró, o (b) esta línea
de trabajo queda como una exploración/propuesta de mejora fuera del cuerpo
principal de la tesis (p. ej. trabajo futuro), y el prototipo sigue
construido sobre E2+E4 tal como está escrito y ya evidenciado.

## Evidencia

No aplica (decisión de diseño, sin corrida ni medición).

## Problemas y solución

No aplica todavía.

## Pendiente

- Resolver con el asesor la desviación de la sección anterior antes de tocar
  código o `main.tex`.
- Si se confirma la adopción: script de ruta con OSMnx → lista ordenada de
  RSU; gestión de misión en el servidor; mapa de misión en la consola; app
  Android mínima con mapa y ruta (ver `docs/CRONOGRAMA.md`, sección añadida
  el 2026-10-22).
- Adaptar `gateway/obu_emulada.py` (decide localmente y publica M1 directo a
  `rsu/{RSU_ID}/solicitudes`), `agent/rsu_middleware.py` (reportar estado al
  servidor, no solo a la OBU) y `consola/` (mapa de misión) — inventario
  detallado en la respuesta del asistente a
  `E:\Tesis\prompt_modo_semiautomatico_ruta.md`, punto 2.

> Nota 2026-10-22: superado por la arquitectura centralizada, ver `2026-10-22_arquitectura-centralizada.md`.
