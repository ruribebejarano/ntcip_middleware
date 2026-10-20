# 2026-10-20 — Consola web del centro de control (FastAPI, reemplaza nada)

**Objetivo específico:** herramienta de apoyo a OE5 (demo y lectura del banco de pruebas); no implementa un OE nuevo  **Requerimientos:** RF-03, RF-04, RF-07, RF-08, RF-09, RF-10, RF-11, RNF-01, RNF-02
**Sección de la tesis:** 4.4–4.5 (presentación del lazo y de las métricas; esta consola es herramienta de apoyo, no un resultado que se cite por sí mismo)
**Commit:** (ver el commit de este cambio)

## Qué se implementó
Consola web propia (FastAPI + JavaScript sin paso de compilación, sin
CDN) para supervisar el banco en vivo y revisar campañas de medición, de
grado más presentable que `centro_control/panel/` (Streamlit, que se
mantiene tal cual, sin tocar). Tres pantallas: Monitoreo en vivo (mapa del
corredor en SVG, semáforo NTCIP 1202, `priorityRequestTable` NTCIP 1211,
ficha de la OBU, tráfico MQTT y eventos del lazo traducidos a español,
botones para lanzar las pruebas del lazo), Ensayos y métricas (lee
`resultados/lazo_emulado/`, grafica con las mismas fórmulas de
`scripts/analisis/*.py`, exporta figuras/tabla LaTeX, compara condiciones
con intervalo de Wilson del PDR) y Registro de comandos (auditoría de
cada SNMP GET/WALK, mensaje MQTT, comando SSH y subproceso que la consola
ejecuta, persistida en JSONL).

## Cómo
- `consola/servidor.py` arranca `uvicorn` en `127.0.0.1:8080` (fastapi
  0.153.0, uvicorn 0.54.0, agregados a `centro_control/requirements.txt`).
- `consola/backend/`: hilos en segundo plano para MQTT (`mqtt_cliente.py`,
  reusa el mismo patrón que `centro_control/panel/pages/1_Lazo_V2I_en_vivo.py`),
  SNMPv3 (`snmp_poller.py`, reusa `centro_control/software_gestion.py` y
  `centro_control/panel/ntcip_objetos.py`), estado local de la OBU
  (`obu_local.py`), eventos de la RSU/controlador por SSH (`eventos_remotos.py`,
  reusa la traducción de `scripts/demo/linea_tiempo.py`), estado del
  banco (`estado_banco.py`, reusa `scripts/pi.sh clock`), pruebas del
  lazo como subproceso (`pruebas.py`, lanza `gateway/obu_emulada.py`
  igual que `scripts/demo_lazo.sh`), métricas (`analisis.py`, reusa
  `scripts/analisis/lazo_emulado.py` y `graficos_campana.py`) y el
  registro de auditoría (`registro_comandos.py`).
- Se extrajo `common/traduccion_eventos.py` desde
  `scripts/demo/linea_tiempo.py` (que ahora lo importa) para que la
  consola use la MISMA traducción de eventos a español sin duplicarla.
- Difusión en vivo por Server-Sent Events (`/sse`, `consola/backend/bus.py`).
- Gráficos (CDF del RTT, cajas por tramo, espera del despeje, serie de
  RTT) en SVG nativo (`consola/static/js/graficos.js`), sin ninguna
  librería de terceros: decisión de diseño, no una limitación — evita
  cualquier dependencia de red o de licencia vendorizada.
- Pruebas: `tests/test_traduccion_eventos.py`,
  `tests/test_consola_analisis.py`, `tests/test_consola_registro_comandos.py`
  (62 pruebas en total, todas pasando).
- Documentación: `docs/CONSOLA.md`.

## Desviaciones respecto del diseño de la tesis
Ninguna: es una herramienta de apoyo (visualización/orquestación), no
toca la lógica de V2I/NTCIP ni los requerimientos. Dos hallazgos a
registrar, ninguno inventado, ambos verificados en el banco local:

1. **Hallazgo de plataforma (corregido aquí):** `pysnmp.hlapi` crea su
   propio event loop de asyncio en cada GET/WALK. Sondeando con 3 hilos
   en paralelo (semáforo/tabla/tiempos) contra el `ProactorEventLoop` por
   defecto de Windows, el proceso se corrompe en minutos
   (`RuntimeError: Cannot run the event loop while another loop is
   running`, después `OSError: [WinError 87]` en el self-pipe de
   asyncio, tumbando uvicorn). Se resolvió sondeando SNMP en un solo
   hilo y forzando `asyncio.WindowsSelectorEventLoopPolicy()` antes de
   arrancar uvicorn (`consola/servidor.py`). Verificado sin errores
   durante sesiones de varios minutos contra el agente local. Documentado
   en `docs/CONSOLA.md`; no debería afectar a Linux (sin
   `ProactorEventLoop`), pero conviene re-probar si se porta.
2. **Hallazgo pre-existente, NO corregido aquí (fuera de alcance de este
   cambio):** `scripts/analisis/graficos_campana.py::fig_tramos()` falla
   con `ValueError` de matplotlib (`List of boxplot statistics and
   positions values must have same length`) cuando una corrida no tiene
   NINGÚN dato de `t_V2I`, `t_RSU` ni `L` (p. ej. al exportar figuras de
   una corrida cuyos eventos de la RSU todavía no se trajeron con
   `scripts/pi.sh fetch`). Reproducido también desde la línea de
   comandos, sin la consola de por medio. La consola solo invoca el
   script tal cual y propaga el error (se ve en el botón "Exportar
   figuras"); no se modificó `graficos_campana.py` porque es código de
   medición del Capítulo IV, fuera del alcance de esta tarea — queda
   pendiente decidir el arreglo (p. ej. omitir `fig_tramos`/`fig_panel`
   cuando las tres series están vacías) con el asesor o en un cambio
   aparte.

## Evidencia
Probado contra el banco local emulado (controlador + RSU + consola en la
laptop, broker Mosquitto local, sin la Raspberry Pi — estaba offline en
Tailscale durante esta sesión): lazo completo OBU → M1 → RSU → verde →
M2 concedida → M3 → cancelada, visible en vivo en la pantalla de
Monitoreo (mapa, semáforo, tráfico MQTT) y registrado en el log de
comandos. También probado con la RSU real offline: los indicadores
muestran el error (SNMP timeout, SSH "Connection timed out") sin que la
consola deje de responder, como pide el requisito de robustez. No se
guardó evidencia en `evidencia/` porque esta sesión fue de verificación
de la herramienta, no una medición para el Capítulo IV.

## Problemas y solución
Ver el hallazgo de pysnmp/asyncio arriba. Aparte, al probar manualmente
con varias instancias de `controller_emulator.py`/`rsu_middleware.py`/
`consola/servidor.py` lanzadas repetidas veces se observó que cada
lanzamiento en este entorno (Git Bash + `.venv` en Windows) deja **dos**
procesos `python.exe` vivos con la misma línea de comandos; no se
investigó la causa (no es un problema introducido por este cambio, se
reproduce igual con `centro_control/panel/`) — solo se documenta por si
se repite y confunde una futura sesión de depuración.

## Pendiente
- Decidir con el asesor el arreglo de `graficos_campana.py::fig_tramos()`
  para corridas sin datos de tramo (hallazgo 2 de arriba).
- Probar la consola contra la Raspberry Pi real cuando vuelva a estar en
  línea (en esta sesión estaba offline en Tailscale).
- La fila de métricas en vivo de "Monitoreo" (L, RTT, PDR de sesión) es
  una aproximación calculada en el navegador para tener un vistazo
  rápido; las cifras con rigor estadístico siempre están en "Ensayos y
  métricas" (mismas fórmulas que `scripts/analisis/lazo_emulado.py`). Si
  se necesita que esa fila también sea rigurosa, habría que moverle el
  cálculo al backend.
