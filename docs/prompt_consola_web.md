# Prompt para Claude Code: consola web del centro de control (en `E:\Tesis\ntcip_middleware`)

```
Quiero construir la consola web del centro de control del banco de pruebas: una aplicación propia (no Streamlit) que se vea de grado industrial, con colores neutros como las figuras de la tesis, y que sirva para la demo con el asesor y para la sustentación. El panel de Streamlit (centro_control/panel/) se queda como está.

Antes de programar, lee: CLAUDE.md, docs/LAZO_EMULADO.md, docs/DEMO_EN_VIVO.md, docs/bitacora/2026-10-19_lazo-obu-emulada.md, common/events.py, gateway/obu_emulada.py (archivo local resultados/obu_vivo/estado.json), agent/rsu_middleware.py (temas rsu/{id}/solicitudes y veh/{id}/respuestas, eventos), centro_control/software_gestion.py y centro_control/panel/snmp_helpers.py (lectura SNMPv3 de NTCIP 1202/1211), scripts/analisis/lazo_emulado.py y scripts/analisis/graficos_campana.py (métricas y figuras), scripts/demo_lazo.sh y scripts/demo/linea_tiempo.py (pruebas y textos en español). Reutiliza esas funciones; no dupliques lógica de transporte ni de cálculo.

ARQUITECTURA
- Carpeta nueva consola/. Backend en Python (FastAPI + uvicorn) que se arranca con un solo comando: python consola/servidor.py, y abre http://127.0.0.1:8080. Escucha SOLO en 127.0.0.1.
- Frontend: HTML + CSS + JavaScript sin paso de compilación, en consola/static/. Actualización en vivo por Server-Sent Events (o WebSocket). Debe funcionar SIN internet (la demo puede ser sin red): nada de CDN; si usas una librería de gráficos (uPlot o Chart.js), descárgala una vez y guárdala en consola/static/vendor/ con su licencia; fuentes del sistema o IBM Plex guardada localmente.
- Configuración en consola/.env (con consola/.env.example comiteado): broker MQTT (127.0.0.1:1883), host SNMP (rsu-01:1161) y credenciales de laboratorio, alias SSH (rsu), RSU_ID. .env no se comitea.
- Fuentes de datos del backend:
  1. Suscriptor MQTT 5 a rsu/# y veh/#: cada mensaje (M1, M2, M3, legado) con su hora.
  2. Sondeo SNMPv3 con las funciones de snmp_helpers: semáforo cada 0,5 s, priorityRequestTable cada 2 s, tiempos de fase cada 10 s.
  3. Estado local de la OBU (resultados/obu_vivo/estado.json) cada 0,5 s. La posición NO viaja por MQTT (minimización de datos): solo se lee de ese archivo local.
  4. Eventos de la RSU y del controlador: cada 3 s, ssh rsu "tail -n 500 ~/ntcip_middleware/resultados/eventos/eventos_rsu_<id>.csv" y lo mismo para eventos_ctrl_<id>.csv; traducirlos a texto legible con la misma lógica de scripts/demo/linea_tiempo.py (impórtala o extráela a un módulo común).
  5. Estado del banco cada 15 s: tailscale status, ssh rsu systemctl is-active rsu-controller rsu-agent, última línea "Conectado al broker" del journal de rsu-agent, y el desfase de relojes (scripts/pi.sh clock).

PANTALLAS (navegación lateral fija; en pantallas angostas el menú se apila arriba)
1. Monitoreo en vivo:
   - Barra superior con indicadores de estado (punto de color + texto, nunca solo color): broker, RSU-01 (Tailscale directo o por retransmisión), SNMPv3, controlador, desfase de relojes; hora local.
   - Fila de indicadores: solicitudes activas, L de la última solicitud (contra el umbral de 1000 ms de RNF-01), RTT M1/M2 último y p95 de la sesión, PDR de la sesión, fase actual de la RSU.
   - Mapa del corredor dibujado en SVG a partir de config/registro_rsu.json (proyección local de gateway/geometria.py): intersecciones, radio R_i, geocerca R_g, accesos, trayectoria y vehículo, con el acceso asignado resaltado. Sin teselas de mapa (funciona sin internet).
   - Semáforo de la RSU (NTCIP 1202) y la fila activa de priorityRequestTable (NTCIP 1211).
   - Ficha de la OBU: velocidad, distancia, intersección y acceso, solicitud, seq, último estado M2 y RTT.
   - Dos paneles de registro en monoespaciada, con desplazamiento y pausa: "Tráfico MQTT" (hora, tipo M1/M2/M3, tema, resumen) y "Eventos del lazo" (OBU/RSU/controlador en español).
   - Botones para lanzar las pruebas de scripts/demo_lazo.sh desde la interfaz (lazo completo, dos intersecciones, clase no reconocida, caducidad, vehículo detenido): el backend corre gateway/obu_emulada.py como subproceso y transmite su salida al registro. Un botón "Detener" que mate el subproceso.
2. Ensayos y métricas:
   - Selector de corrida (carpetas de resultados/lazo_emulado/), con su config.json visible (commit, fecha, escenarios, parámetros).
   - Indicadores: L (mediana, p95, máx. y cumplimiento de RNF-01), RTT M1/M2, T_desp, PDR y tasa de acierto de acceso.
   - Gráficos interactivos (pasar el mouse muestra el valor), con las MISMAS definiciones que scripts/analisis/graficos_campana.py: (a) CDF del RTT con p50 y p95; (b) cajas por tramo t_V2I, t_RSU, L con los puntos; (c) T_desp según la fase de llegada; (d) RTT a lo largo de cada solicitud.
   - Pestaña "Comparar condiciones": elegir dos o más corridas y ponerles etiqueta (por ejemplo Wi-Fi y 4G). Mostrar: CDF del RTT superpuestas, una por condición, con eje x logarítmico (4G estará en decenas o cientos de ms); cajas de t_V2I, t_RSU y L agrupadas por condición; PDR por condición con intervalo de confianza de Wilson al 95 %; y una tabla con mediana, p95 y diferencia entre condiciones.
   - Tabla por solicitud (de lazo_por_solicitud.csv) con orden por columna.
   - Botones "Exportar figuras (PDF)" y "Tabla LaTeX" que llaman a scripts/analisis/graficos_campana.py y dejan los archivos en la carpeta de la corrida; mostrar dónde quedaron.
3. Registro de comandos (auditoría):
   - Toda acción que la consola ejecuta o envía queda registrada con hora, origen → destino, canal (MQTT, SNMPv3, TCP RSU→controlador, SSH, proceso local), comando o carga útil completa, y resultado: lecturas y escrituras SNMP, mensajes publicados, comandos SSH, subprocesos lanzados. Además se incorporan las órdenes de la RSU al controlador leídas de sus eventos (request_priority, activar_cola_rf06, clear_priority_m3, rechazada, caducidad).
   - Persistir en resultados/consola/registro_comandos.jsonl (agregar a .gitignore), una línea por entrada, y permitir descargarlo.
   - Filtros por canal, búsqueda por id de solicitud, tema u OID, y un panel de detalle con la carga útil y la respuesta formateadas.

ESTILO (neutro, como las figuras de la tesis)
- Tema claro: fondo #f5f5f4, paneles #ffffff, bordes #d6d3d1, texto #1c1917, texto secundario #57534e, acento único #334155 (pizarra). Estados: correcto #15803d, advertencia #a16207, error #b91c1c, siempre con texto o ícono además del color. Tipos de mensaje en tonos sobrios: M1 #334155, M2 #15803d, M3 #9a3412.
- Tipografía: sans para la interfaz y monoespaciada para valores, horas, temas y registros. Esquinas de 6 px, bordes de 1 px, sin degradados ni sombras grandes ni emojis. Densidad alta de información, alineación en grilla.
- Gráficos con la misma paleta neutra de las figuras de graficos_campana.py.
- Accesibilidad: botones y enlaces reales, contraste 4,5:1, objetivos de clic de 44 px, aria-label en botones de solo ícono.

CALIDAD
- No cambies el comportamiento de agent/, controller/ ni gateway/ salvo que sea imprescindible; si lo es, dímelo antes.
- Si la Pi no responde o el broker está caído, la consola sigue funcionando y lo muestra en los indicadores (no se cae).
- Pruebas en tests/ para: traducción de eventos a texto, cálculo de métricas expuestas por la API y escritura del registro de comandos.
- Documenta en docs/CONSOLA.md: cómo instalar dependencias (agrega fastapi y uvicorn a centro_control/requirements.txt), cómo arrancar, qué muestra cada pantalla y de dónde sale cada dato.
- Antes de terminar, arranca la consola contra el banco real y verifica cada pantalla; corrige lo que falle. Luego bitácora (docs/bitacora/AAAA-MM-DD_consola-web.md) y commit.
```
