# 2026-10-11 — Arranque de servicios, corrección de reloj y primera prueba de humo del lazo

**Objetivo específico:** OE3 (middleware NTCIP, verificado funcionalmente por primera vez end-to-end); infraestructura transversal (reloj, servicios).
**Requerimientos:** RF-05 a RF-09 (parcial: la ruta OBU→RSU→controlador respondió; faltan los casos de rechazo/caducidad, ver Pendiente); sustento de RNF-01 (sincronización de reloj entre OBU y RSU).
**Sección de la tesis:** `sec:banco_impl`, `ssec:mw_impl`; antecedente directo de `sec:verificacion_ntcip` (Capítulo IV) una vez que esto se repita con objetos NTCIP reales (ver `docs/PLAN_IMPLEMENTACION.md`, P2/P3).
**Commit:** `b947bc7` (fix de `PYTHONUNBUFFERED`); sin commit de código aplicativo en este hito (ver "Problemas y solución" — el bug encontrado no se corrigió).

## Qué se implementó

- Las unidades `rsu-controller.service` y `rsu-agent.service` quedaron
  **instaladas, corriendo y con logs legibles** (ver "Problemas y
  solución" para el fix de buffering que hizo falta).
- `chrony` en la Pi quedó sincronizando **exclusivamente** contra
  `time.cloudflare.com` y `time.google.com` (se deshabilitó el pool por
  defecto de Debian que se superponía).
- `mosquitto` quedó escuchando en `0.0.0.0:1883` (antes solo en
  `localhost`), con `allow_anonymous true`, exactamente como ya
  documentaba `docs/GUIA_COMANDOS.md` — necesario para que la OBU
  simulada (en la laptop) pueda publicar.
- Primera prueba de humo del lazo completo, de punta a punta: OBU
  simulada (laptop) → broker MQTT (Pi) → middleware/agente (Pi) →
  controlador emulado (Pi) → verificado de vuelta por SNMP GET desde la
  laptop. Ver "Cómo" para el detalle.

## Cómo

- `gateway/obu_simulator.py --broker-host 192.168.18.175 --vehiculo-id
  ambulancia-smoke-test --eta-seg 8`, corrido desde la laptop con el
  `.venv` ya existente (`paho-mqtt==2.1.0`).
- Verificación de recepción: `sudo journalctl -u rsu-agent.service` y
  `-u rsu-controller.service` en la Pi.
- Verificación de cierre del lazo: `centro_control/software_gestion.py
  get --host 192.168.18.175 --port 1161 --v3-user rsuLabUser --auth-key
  labAuthPass123 --priv-key labPrivPass123 1.3.6.1.4.1.99999.1.1.0` →
  devolvió `3` (verde), confirmando que la fase forzada por la solicitud
  V2I es legible por SNMP.
- Offset de reloj medido con `scripts/pi.sh clock` (ver también la
  entrada de bitácora anterior): Pi vs. `time.cloudflare.com` ≈ −5 ms;
  laptop vs. `time.cloudflare.com` ≈ +33 ms (con el servicio Windows Time
  **detenido** en la laptop). Desfase combinado estimado: **~38 ms**.

## Desviaciones respecto del diseño de la tesis

Ninguna sobre el diseño del sistema. Desviaciones operativas:

- El `sudo` sin contraseña que se configuró en la Pi (para que
  `scripts/pi.sh start/stop/restart/logs` no pidan contraseña) quedó
  como `(ALL : ALL) ALL` — acceso total, no acotado a los comandos
  `systemctl`/`journalctl` de las tres unidades que proponía
  `deploy/systemd/README.md`. Funciona, pero es más permisivo de lo
  recomendado; queda a criterio del estudiante acotarlo más adelante.
- La sincronización de reloj persistente de la laptop (Windows Time
  contra `time.cloudflare.com`/`time.google.com`, arranque automático)
  **no se aplicó todavía**: requiere PowerShell elevado (Administrador),
  que el agente de código no tiene. Comandos exactos entregados al
  estudiante; pendiente de que los corra y se vuelva a medir el offset.

## Evidencia

Sugerido para `evidencia/` (ninguna capturada todavía en este hito; se
verificó todo por SSH/journalctl, no por captura de pantalla):

- `2026-10-11_pi_status-tres-servicios.png` — salida de `scripts/pi.sh
  status agent`, `status controller` y `status mosquitto` mostrando los
  tres `active (running)`.
- `2026-10-11_pi_chrony-tracking.png` — `chronyc tracking` en la Pi,
  mostrando `Reference ID: time.cloudflare.com`.
- `2026-10-11_smoke-test_obu-publica.png` — consola de la laptop con la
  salida de `gateway/obu_simulator.py` ("Solicitud de prioridad
  publicada...").
- `2026-10-11_smoke-test_journalctl-agente-controlador.png` (o `.log`
  con `journalctl ... > archivo.log`) — las líneas "Solicitud V2I
  recibida..." (agente) y "Prioridad solicitada... fase forzada a
  verde..." (controlador), una junto a la otra o en dos capturas.
- `2026-10-11_smoke-test_snmp-get-fase-verde.png` — salida del `GET`
  SNMP devolviendo `3` (verde).
- (Opcional, una vez corregido el fix de W32Time) `2026-10-11_laptop_
  w32tm-query-status.png` — `w32tm /query /status` mostrando el nuevo
  origen de sincronización.

## Problemas y solución

- **`journalctl` no mostraba ninguna línea de `print()` de los scripts**
  (solo los mensajes de systemd) → causa: Python usa buffering por
  bloques cuando `stdout` no es una terminal (como ocurre bajo systemd
  con `StandardOutput=journal`), así que los `print()` se quedaban en el
  buffer en vez de llegar al journal. Solución: agregar
  `Environment=PYTHONUNBUFFERED=1` a ambas unidades (commit `b947bc7`),
  reinstalar (`cp` a `/etc/systemd/system/` + `daemon-reload`) y
  reiniciar ambos servicios. Confirmado: los logs aparecen de inmediato
  después del fix.
- **La primera corrida de la prueba de humo no tuvo ninguna reacción**
  (ni el agente ni el controlador loguearon nada) → causa real, **bug
  de aplicación sin corregir todavía**: `agent/rsu_middleware.py`,
  función `start_mqtt_listener()` (línea 158), llama a
  `client.subscribe(MQTT_TOPIC, qos=1)` **una sola vez, justo después del
  `connect()` inicial**, en vez de dentro del callback `_on_mqtt_connect`
  (línea 127, que hoy solo imprime un mensaje). Cuando la conexión se
  reconecta — en este caso, porque se reinició `mosquitto` para abrir el
  listener a `0.0.0.0` — el cliente MQTT se reconecta automáticamente
  (`loop_start()` ya lo maneja) pero **sin volver a suscribirse**, así
  que el middleware queda conectado al broker pero sordo al tópico de
  solicitudes, sin ningún error visible. Diagnosticado reiniciando
  `rsu-agent.service` (fuerza una conexión inicial fresca, con su
  `subscribe()` de arranque) y repitiendo la prueba: con eso sí
  funcionó de punta a punta. **No se corrigió el código en este hito**
  (fuera del alcance de esta tarea, que era verificar el despliegue, no
  tocar la lógica del middleware); queda como primer pendiente de P1 o
  de un hito dedicado: mover `client.subscribe(MQTT_TOPIC, qos=1)` al
  cuerpo de `_on_mqtt_connect`, para que cualquier reconexión (no solo
  la primera) vuelva a suscribirse.

## Pendiente

- **Corregir el bug de re-suscripción** en
  `agent/rsu_middleware.py::start_mqtt_listener` (ver arriba) — afecta
  la confiabilidad de cualquier campaña de pruebas más larga, no solo
  reinicios manuales del broker.
- Aplicar la configuración persistente de Windows Time en la laptop
  (comandos entregados, requieren PowerShell como Administrador) y
  volver a medir el offset con `scripts/pi.sh clock`.
- Decidir si se acota el `sudo` sin contraseña de la Pi a los comandos
  específicos que necesita `scripts/pi.sh`, en vez de `ALL:ALL`.
- Capturar la evidencia listada arriba y citarla en esta entrada (o en
  una de seguimiento) antes de usar este hito como respaldo en el
  Capítulo III/IV.
- Continuar con **P1** (`docs/PLAN_IMPLEMENTACION.md`): registro de
  eventos con marcas de tiempo (RF-10).
