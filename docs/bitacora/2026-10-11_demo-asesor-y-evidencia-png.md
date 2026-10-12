# 2026-10-11 — Demo guiada para el asesor y evidencia en PNG

**Objetivo específico:** OE3/OE5 (verificación y comunicación de resultados)
**Requerimientos:** RF-05, RF-06, RF-07, RF-08, RF-09, RF-10, RNF-01, RNF-03, RNF-05 (todos los que ya cubre el banco; sin cambios funcionales de código)
**Sección de la tesis:** Capítulo IV (verificación), preparación de la reunión del 12/10 con el asesor
**Commit:** (ver al final)

## Qué se implementó

Dos herramientas, a pedido explícito del estudiante (`docs/PREPARACION_REUNION_ASESOR.md`, Prompt A), para la reunión con el asesor del 12/10:

1. **`scripts/demo_asesor.sh`**: demo guiada de 8 pasos (0–7) del banco de pruebas contra la Pi real, con encabezado grande por paso (número, título, requerimiento RF/RNF), el comando real ejecutado, una línea de "qué observar", pausa `Enter` entre pasos (u opción `--sin-pausas` para correrla de corrido), y un resumen final OK/FALLO. Cada paso guarda su salida en `evidencia/demo_AAAA-MM-DD/NN_<paso>.txt`.
2. **`scripts/txt_a_png.py`**: convierte cualquier `.txt` de `evidencia/` (incluidos los de `evidencia/demo_*/`) en una imagen PNG con aspecto de terminal (fondo oscuro, fuente monoespaciada, título con el nombre del archivo y su fecha, ancho fijo de 100 columnas con salto de línea automático, resaltado de líneas `$ ...` y de errores). Corrido ahora sobre los 20 `.txt` existentes en `evidencia/` (los 9 de P2/P3/RF-06 más los 8 de la primera corrida completa de la demo, más `02_ciclo-controlador`), generando sus 20 PNG.

## Cómo

- Bash (Git Bash en la laptop, no PowerShell), sin dependencias nuevas más allá de las ya instaladas (`snmpget`/`snmpset`/`snmpwalk` en la Pi, `paho-mqtt` en el venv del proyecto para el paso 7).
- Los pasos 2–6 necesitan lógica Python corta en la Pi (construir los 29 bytes OER, consultar `get_status` del controlador por su protocolo propio, sondear `priorityRequestStatusInPRS`). En vez de incrustarlos como `ssh ... python3 -c "..."` (se probó primero y se abandonó: las comillas y f-strings del código rompen el escapado), cada paso escribe un `.py` a un archivo temporal local, lo copia con `scp` a `/tmp` en la Pi, lo corre con `ssh` y borra la copia remota al salir (`trap`, incluso si el paso falla).
- **RF-06, paso 4**: refleja el comportamiento real desde el commit de hoy (`7017c87`, ver bitácora `2026-10-11_rf06-cola-y-activacion-automatica.md`): la solicitud durante el despeje queda `readyQueued` y se activa sola, no se rechaza. El despeje real del banco (ámbar 3.0s + todo rojo 2.0s = 5s) es más largo que el TTL de RNF-03 (3s), así que el paso acorta `phaseYellowChange`/`phaseRedClear` a 1.0s cada uno vía SNMP (ya son objetos `RW` de NTCIP 1202) justo antes de la prueba y los restaura al salir con un `trap` en el `EXIT` de todo el script — se verificó explícitamente que la Pi queda con los valores originales (30/20, es decir 3.0s/2.0s) incluso simulando un fallo a mitad del paso.
- **Paso 7 (lazo V2I)**: corre `gateway/obu_simulator.py` en la laptop contra el broker mosquitto de la Pi (IP tomada de `ssh -G rsu`, no hardcodeada), espera ~6s, hace `scripts/pi.sh fetch`, combina los tres `eventos_*.csv` (OBU local + RSU y controlador fetched de la Pi) en `resultados/demo_combinado/` (ignorado por git, ver "Cómo" del `.gitignore`) y corre `scripts/analisis/latencia_tramos.py` sobre esa carpeta.
- **`txt_a_png.py`** usa Pillow. **Decisión**: Pillow se instaló en el venv de la laptop (`.venv`) pero **no se agregó a `requirements.txt`**, porque ese archivo son las dependencias que `scripts/pi.sh deploy` instala en la Raspberry Pi (ver su cabecera) y Pillow nunca corre ahí — es una herramienta de conversión de evidencia, solo de la laptop. Agregarla a `requirements.txt` habría forzado una dependencia pesada innecesaria en cada despliegue a la Pi.
- `.gitignore`: se agregaron `resultados/eventos/`, `resultados/rsu/` y `resultados/demo_combinado/` (directorios de trabajo que se regeneran en cada corrida, no corridas curadas como `resultados/prueba_registro/`, ver `resultados/LEEME.md`).

## Desviaciones respecto del diseño de la tesis

Ninguna de código/diseño. Es tooling de verificación y de comunicación de resultados, no un requerimiento nuevo.

## Evidencia

- `evidencia/demo_2026-10-11/00_estado-del-banco.txt` a `07_lazo-v2i-completo.txt` (8 archivos): salida completa de la primera corrida íntegra y exitosa de `scripts/demo_asesor.sh --sin-pausas` contra la Pi real, con sus 8 PNG correspondientes.
- Los 12 `.txt` previos de `evidencia/` (P2, P3, RF-06) ahora tienen también su versión `.png`.

## Problemas y solución

- **Hallazgo real, no solo del script de demo**: `controller/controller_emulator.py` **no tiene un hilo de reloj propio** — `_advance_locked()` (la función que hace avanzar la fase) solo se llama desde dentro de `status()`, es decir, el controlador solo avanza de fase cuando *algo* le pregunta `get_status`. En reposo total (nadie consultando), la fase queda congelada indefinidamente; al primer poll después de un silencio largo, avanza **un solo paso** del ciclo (no recupera el tiempo transcurrido), lo que puede dar una fase visiblemente desincronizada del tiempo real si pasó mucho silencio. Se descubrió al intentar capturar 25s de `journalctl -u rsu-controller -f` sin ningún tráfico SNMP de por medio: el log quedó completamente vacío, porque nada estaba empujando el reloj. **Solución para el paso 2 de la demo**: en vez de solo escuchar el log, el paso sondea `get_status` cada 0.3s durante 25s (igual que haría cualquier gestor SNMP real preguntando el estado) — eso sí hace avanzar el ciclo y se ve en vivo. **No se tocó `controller_emulator.py`**: es un hallazgo a documentar, no un bug a arreglar en el emulador en este hito (agregar un hilo de reloj autónomo es un cambio aparte, más invasivo, y el comportamiento poll-driven no afecta al middleware real, que siempre consulta antes de usar el estado).
- **`ssh ... python3 -c "<script largo>"` no es viable para estos pasos**: el primer intento (escapar comillas con `sed`) se probó y se descartó antes de llegar a ejecutarlo en serio, por el riesgo de romperse silenciosamente con cualquier cambio futuro al contenido del script (f-strings, comillas anidadas, backslashes). Se cambió al patrón `scp` + archivo remoto + `ssh python3 archivo.py` + borrado, ya usado manualmente hoy mismo para la evidencia de RF-06 (ver bitácora anterior) y ahora generalizado en una función (`correr_python_remoto`).
- **`timeout N ssh ... comando_que_no_termina_solo > archivo` pierde todo lo ya recibido**: al matar el `ssh` local con `SIGTERM` vía `timeout`, el archivo de salida quedó vacío (0 bytes) aunque el comando remoto sí corrió — no es exclusivo de `journalctl -f`, es un riesgo general de este patrón. Se evitó por completo en el paso 2 (ver arriba) en vez de intentar mitigarlo.
- **`python3` en Git Bash resuelve al *stub* de Microsoft Store** (`.../WindowsApps/python3`), que falla con "no se encontró Python" en vez de ejecutar nada — mientras que `python` (sin el "3") sí resuelve al intérprete real instalado. Se detectó al fallar el paso 7 silenciosamente. **Solución**: en vez de confiar en `command -v python3`, el script prueba una lista de candidatos (empezando por el propio `.venv` del proyecto, que además ya tiene `paho-mqtt` instalado) y usa el primero cuyo `--version` realmente funciona.
- **`t_V2I_aprox` negativo en el paso 7 (−18.4 ms)**: no es un bug nuevo, es el mismo efecto de deriva de reloj laptop↔Pi ya documentado en `resultados/prueba_registro_sincronizado/notas.md` (P1) — queda como limitación conocida, no se investigó de nuevo aquí.

## Pendiente

- Ejecutar el ensayo completo **con pausas** (como indica `docs/PREPARACION_REUNION_ASESOR.md`, sección "Ensayo esta noche") antes de la reunión real, y tomar las capturas de pantalla adicionales que pide ese documento.
- Evaluar si vale la pena agregar un hilo de reloj autónomo a `controller/controller_emulator.py` en un hito futuro (hallazgo de este commit, no resuelto aquí).
- Continuar con el Prompt B (actualizar la tesis) y el Prompt C (reporte de avance) del mismo documento de preparación.
