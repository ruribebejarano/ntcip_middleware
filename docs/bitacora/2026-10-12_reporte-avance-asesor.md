# 2026-10-12 — Reporte de avance para la reunión con el asesor

**Objetivo específico:** transversal (documentación para la reunión de asesoría, no código de los OE)
**Requerimientos:** ninguno directo
**Sección de la tesis:** —
**Commit:** (ver mensaje de este commit)

## Qué se implementó

`redaccion/Reporte_avance_2026-10-12.docx`: reporte de una página (2
páginas reales, dentro del máximo pedido) para la reunión de asesoría del
2026-10-12, generado con `python-docx` replicando la estructura exacta de
`E:\Tesis\redaccion\Formato Reporte de Reuniones R03 20190577.docx`
(encabezado, tabla de 5 filas "a ser llenado por el alumno/a ser llenado
por el asesor", tabla de firmas).

Contenido: avance por objetivo específico (OE1–OE5, la numeración vigente
de `main.tex`/`CLAUDE.md`, no la de `docs/PLAN_IMPLEMENTACION.md`, que usa
una numeración anterior a la fusión de OE — ver nota en `CLAUDE.md`), con
porcentajes calculados como hitos del plan completados / hitos planeados
por OE (no una estimación subjetiva); lo implementado y verificado desde
P0 hasta P3 (incluida la revisión de RF-06 de hoy); los 4 hallazgos
pedidos (objeto inexistente en `main.tex`, deriva de reloj, bug de
`pysnmp` con `ACCESS` write-only, codificación OER de 29 bytes); las 6
decisiones pedidas; y los próximos pasos con fechas hasta el 20 de
noviembre, tomados directamente de `docs/PLAN_IMPLEMENTACION.md`.

## Cómo

- `python-docx` 1.2.0 (instalado para esta tarea; no estaba en el entorno
  antes). El documento se arma por código, no por edición manual de XML,
  replicando tamaños de página (A4), márgenes y fuente (Arial) medidos
  del `.docx` de la plantilla con el propio `python-docx`.
- Verificado renderizando con Word (automatización COM vía PowerShell,
  `SaveAs` a PDF) y confirmando con `ComputeStatistics(2)` que el
  documento mide exactamente 2 páginas; se revisaron ambas páginas
  convertidas a imagen (`pdftoppm`) antes de darlo por bueno.

## Desviaciones respecto del diseño de la tesis

Ninguna de código. Dos correcciones hechas al contenido pedido en
`docs/PREPARACION_REUNION_ASESOR.md` (Prompt C), para no inventar datos:

- **Decisión 1 (TLSTM vs. USM):** el texto del prompt daba por hecho que
  "pysnmp no soporta TLSTM". Esa verificación experimental todavía no se
  hizo — está programada recién para P4 (ver `docs/PLAN_IMPLEMENTACION.md`
  y `docs/CRONOGRAMA.md`, gate G1). El reporte presenta esto como
  pendiente de verificar, no como un hecho ya confirmado.
- **Decisiones 2 y 6 (retirar NTCIP 1209; retiro del enlace I2I):** ambas
  ya están confirmadas y hechas, no pendientes. `main.tex` ya declara
  explícitamente 1209 fuera de alcance (`ssec:alcance`,
  `ssec:mw_1202_1209`, lista de trabajo futuro); el repo de la tesis tiene
  5 commits (`7f56bc0`, `acbe312`, `662f2f3`, `fff0a1e`, `5e4c79e`) que
  retiraron por completo el enlace I2I, la coordinación de ola verde y
  toda mención a Wi-SUN/watchdog, a pedido explícito del autor. El reporte
  las presenta como confirmación, no como decisión abierta — tal como pedía
  el propio Prompt C para el caso de I2I.
- **Decisión 3 (OBU: Python vs. app Android):** se verificó contra
  `main.tex` (`ssec:app`) que el diseño vigente sigue especificando una
  app nativa en Kotlin para Android (justificada por el acceso Bluetooth
  SPP que exige RF-01), mientras que el prototipo actual
  (`gateway/obu_simulator.py`) es un script Python que solo simula el
  envío de M1. El reporte presenta esta discrepancia explícitamente para
  que el asesor decida, en vez de asumir que ya se resolvió a favor de uno
  u otro.
- **Decisión 4 (EMQX vs. local):** se confirmó contra el código
  (`agent/rsu_middleware.py`, `MQTT_BROKER_HOST = "127.0.0.1"`) que P0–P3
  se verificaron contra mosquitto local en la propia RSU, no contra el
  despliegue EMQX Cloud Serverless provisionado el 2026-10-04
  (`docs/bitacora/2026-10-04_broker-emqx-serverless.md`). El reporte deja
  claro que ambos existen pero el prototipo probado hasta ahora usa el
  local.

## Evidencia

No aplica (el propio `.docx` es el entregable).

## Problemas y solución

- Ninguna herramienta de conversión docx→PDF/Markdown estaba disponible en
  el entorno (`pandoc`, LibreOffice/`soffice`, el paquete `docx` de npm):
  se resolvió instalando `python-docx` (no estaba) y usando Microsoft Word
  vía automatización COM (ya instalado en la laptop) para la verificación
  de páginas y el renderizado de control.

## Pendiente

- Completar a mano, antes de la reunión: el número de reunión (se dejó
  como `___ (completar)`, no se inventó) y si la reunión es presencial o
  por Zoom.
- El asesor debe tomar las 4 decisiones realmente abiertas del reporte (1,
  3, 4, 5); las decisiones 2 y 6 son solo confirmación.
