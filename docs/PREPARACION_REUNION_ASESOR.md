# Preparación de la reunión con el asesor (lunes 12 de octubre)

Tres entregables para mañana:
1. **Demo en vivo** del banco de pruebas, guiada paso a paso con un solo script.
2. **main.pdf actualizado** con la implementación de P0–P3 y sus evidencias como figuras.
3. **Reporte de avance** de una página, con hallazgos y decisiones pendientes.

Orden para esta noche: Prompt A → Prompt B → Prompt C → ensayo completo de la demo (ver el final).

---

## Prompt A: script de demo y evidencias como imagen (en `E:\Tesis\ntcip_middleware`)

```
Crea scripts/demo_asesor.sh: una demo guiada del banco de pruebas para mostrarla en vivo a mi asesor. Requisitos:
- Cada paso muestra un encabezado grande con el número, el título y el requerimiento que verifica (RF/RNF con los IDs actuales de main.tex), ejecuta el comando real contra la Pi, explica en una línea qué observar en la salida y espera "Enter para continuar". Usa colores legibles en Git Bash.
- Cada paso guarda además su salida en evidencia/demo_AAAA-MM-DD/NN_<paso>.txt.
- Pasos:
  0. Estado del banco: scripts/check_pi.sh, scripts/pi.sh status (agent, controller, mosquitto) y scripts/pi.sh clock (desfase laptop-Pi).
  1. snmpwalk del subárbol NTCIP 1202 (objetos reales y sus valores).
  2. Ciclo del controlador: unos 25 s de log mostrando verde, ámbar, todo rojo y rojo con sus tiempos.
  3. Solicitud NTCIP 1211 aceptada en verde: snmpset de prgPriorityRequestAbsolute (29 bytes, mostrando el hex con los campos) y snmpwalk de priorityRequestTable.
  4. Solicitud durante ámbar o todo rojo: queda en readyQueued y se activa al terminar el despeje (o rechazada, según el estado actual del código; el texto del paso debe coincidir con lo implementado).
  5. Clase de vehículo no reconocida: rechazada (RF-05).
  6. Caducidad: solicitud sin actualizar, liberada a los 3 s (RF-09, RNF-03), con la línea de tiempo de journalctl.
  7. Lazo V2I: la OBU simulada envía M1 por MQTT, la RSU la traduce a NTCIP 1211, el controlador pasa a verde, y latencia_tramos.py muestra los tramos de esa solicitud.
- Al final imprime un resumen: paso, requerimiento y resultado (OK/FALLO).
- Opción --sin-pausas para ejecutarlo de corrido.

Después crea scripts/txt_a_png.py, que convierta cada .txt de evidencia/ (incluidos los de demo_*/) en una imagen PNG con aspecto de terminal: fondo oscuro, fuente monoespaciada, un título con el nombre del archivo y la fecha, ancho fijo y salto de línea automático. Así cada evidencia en texto tiene también su versión en imagen para la tesis y las diapositivas. Conviértelos todos ahora.

Prueba el script completo una vez contra la Pi con --sin-pausas y corrige lo que falle. Bitácora y commit.
```

## Prompt B: actualizar la tesis (en `F:\tesis2\Overleaf`)

```
/add-dir E:\Tesis\ntcip_middleware
Lee todas las entradas de E:\Tesis\ntcip_middleware\docs\bitacora\ (excepto _plantilla.md) y redacta con ellas las subsecciones de implementación del Capítulo III (ssec:obu_impl, ssec:rsu_impl, ssec:mw_impl, ssec:seg_impl y el banco de pruebas), en el estilo del documento.
- Inserta como figuras las evidencias relevantes, usando las versiones PNG de E:\Tesis\ntcip_middleware\evidencia\ (cópialas a figuras/implementacion/), con pies que digan qué demuestra cada una. Incluye la figura del mapa de bytes de prgPriorityRequestAbsolute si ya existe.
- Agrega una tabla de entorno de software (sistema operativo, Python, pysnmp con su commit fijado, paho-mqtt, Mosquitto, chrony) y una tabla de los objetos NTCIP 1202 y 1211 implementados (OID, acceso, unidad).
- Registra como desviaciones respecto del diseño: el broker en EMQX us-east-1, USM en lugar de TLSTM (si ya se decidió), la MIB 1211 tomada del borrador v02A-SE03 y los bugs encontrados (pysnmp writeonly, deriva de reloj de 194 ms).
- En el Capítulo IV, sección 4.2 (middleware NTCIP), llena la tabla de casos de prueba con los resultados ya verificados (P2 y P3). Lo demás queda como está.
- No inventes datos: todo debe salir de la bitácora o de las evidencias. Compila main.pdf, revisa que no haya referencias rotas y haz commit.
```

## Prompt C: reporte de avance (en `E:\Tesis\ntcip_middleware`)

```
Usa el formato E:\Tesis\redaccion\Formato Reporte de Reuniones R03 20190577.docx (lee su estructura y respétala) para generar redaccion/Reporte_avance_2026-10-12.docx con: avance por objetivo específico (con % honesto), lo implementado y verificado desde la última reunión (P0–P3), hallazgos (phaseStatusCurrentGroup inexistente, deriva de reloj, bug de pysnmp, codificación OER de 29 bytes), y estas decisiones que necesito que el asesor tome:
1) TLSTM frente a USM: pysnmp no soporta TLSTM.
2) Retirar NTCIP 1209 del OE3.
3) OBU como programa en Python usando el enlace celular del teléfono, en lugar de una aplicación móvil.
4) Broker en EMQX Cloud (us-east-1) frente a uno local, y su efecto en la latencia.
5) MIB de NTCIP 1211 tomada del borrador 2017, mientras se obtiene la versión publicada.
6) Retiro del enlace I2I (si ya está acordado, preséntalo como confirmación).
Agrega los próximos pasos con fechas hasta el 20 de noviembre. Máximo 2 páginas. No inventes porcentajes ni resultados: toma todo de la bitácora y del plan.
```

---

## Ensayo esta noche (15 minutos)

1. Pi encendida y `./scripts/check_pi.sh` OK.
2. En PowerShell como administrador: `w32tm /resync /force`.
3. `bash scripts/demo_asesor.sh` completo, con pausas, como si fuera la reunión.
4. Toma capturas con **Win + Shift + S** de los pasos 1, 3, 4, 5 y 6 y guárdalas en `evidencia/demo_AAAA-MM-DD/`.
5. Si algún paso falla, pásale el error a Claude Code esta noche, no mañana.

## Mañana antes de la reunión (10 minutos)
- Enciende la Pi 10 minutos antes, para que chrony se estabilice.
- `w32tm /resync /force` y `scripts/check_pi.sh`.
- Ten abiertos: la terminal con la demo, main.pdf en el capítulo III y el reporte de avance.
- **Plan B si falla la red:** las evidencias en PNG y main.pdf muestran lo mismo sin depender de la Pi.
