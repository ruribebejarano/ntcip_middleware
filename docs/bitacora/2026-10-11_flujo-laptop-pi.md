# 2026-10-11 — Flujo de despliegue laptop ↔ Raspberry Pi

**Objetivo específico:** Infraestructura transversal (no corresponde a un OE específico de `main.tex`)
**Requerimientos:** Ninguno directo; sustenta la medición de latencia por tramo (RNF-01, ecuación de `ssec:latencia`), que necesita el reloj de la OBU (laptop) y de la RSU (Pi) sincronizados.
**Sección de la tesis:** No aplica a una sección de diseño; es infraestructura del banco de pruebas, antecedente de `sec:banco_impl` (Capítulo III) y de la "Instrumentación y registro de eventos" (`ssec:instrumentacion`, Capítulo IV).
**Commit:** *(pendiente — ver el commit "infra: flujo laptop-Pi" inmediatamente posterior a esta entrada)*

## Qué se implementó

- `scripts/pi.sh`: herramienta única para `deploy` (push laptop + pull Pi +
  reinstalo de `requirements.txt` si cambió), `start`/`stop`/`restart`/
  `status`/`logs <servicio>` (`agent`/`controller`/`mosquitto`), `fetch`
  (copia `resultados/` de la Pi a la laptop) y `clock` (offset de reloj de
  ambas máquinas).
- Unidades systemd `deploy/systemd/rsu-controller.service` y
  `rsu-agent.service`, para reemplazar las terminales manuales de
  `docs/GUIA_COMANDOS.md`.
- Configuración de `chrony` preparada en `scripts/chrony/rsu-lab.conf`
  (referencias NTP explícitas: `time.cloudflare.com`, `time.google.com`),
  para que la Pi y la laptop midan su offset contra la misma referencia.
- `.claude/settings.json` con permisos para `ssh rsu`, `ssh rsu2`,
  `scripts/pi.sh` y `scripts/check_pi.sh` (no se comitea, está en
  `.gitignore` junto con `CLAUDE.md`).
- Alias SSH `rsu` (`~/.ssh/config` de la laptop, fuera del repo) actualizado
  a la IP vigente de la Pi.

## Cómo

- Bash (scripts POSIX, probados con `bash -n` y ejecución real contra la
  Pi); `systemd` (unidades `[Unit]/[Service]/[Install]` estándar,
  `Type=simple`, `Restart=on-failure`); `chrony` (no instalado aún en la
  Pi — ver "Pendiente").
- La Pi está en Debian 13 (trixie), Python 3.13.5, con el entorno virtual
  `~/rsu-env` ya creado y con `paho-mqtt`/`pysnmp` instalados y
  verificados (`python3 -c "import paho.mqtt.client, pysnmp"` → OK).
- `mosquitto.service` ya existía como servicio del sistema (`enabled`,
  `active`); no se creó una unidad nueva para él.

## Desviaciones respecto del diseño de la tesis

Ninguna sobre el diseño del sistema en sí. Dos notas operativas:

1. La IP de la Pi cambió de `192.168.18.163` a `192.168.18.175`
   (reasignación DHCP tras reconectarla a la red); se actualizó el alias
   SSH y `docs/CONEXION_RASPBERRY.md`. Sigue sin confirmarse si la IP es
   estable — ver "Pendiente".
2. Las unidades systemd creadas (`rsu-controller`, `rsu-agent`) **no se
   instalaron en la Pi**: requieren la contraseña de `sudo`, que el agente
   de código no tiene ni pide por diseño. Los comandos exactos para
   instalarlas a mano quedan en `deploy/systemd/README.md`. Tampoco se
   instaló `chrony` por la misma razón (ver `docs/CONEXION_RASPBERRY.md`).

## Evidencia

Ninguna en `evidencia/` (este hito es infraestructura de desarrollo, no una
prueba del lazo de priorización). Verificación de humo incluida más abajo.

```
$ scripts/pi.sh status mosquitto
● mosquitto.service - Mosquitto MQTT Broker
     Active: active (running) since Thu 2026-10-08 02:25:08 -05; 3 days ago
     ...
```

## Problemas y solución

- **SSH a `rsu` con timeout** → la Pi estaba apagada/desconectada de la red
  (confirmado: laptop en el subnet correcto, 192.168.18.220, pero sin
  entrada ARP para `.163` y sin respuesta a `ping`). Solución: el usuario
  reconectó la Pi, que recibió la IP `.175` por DHCP.
- **`Host key verification failed` al conectar a la IP nueva** → no había
  entrada en `~/.ssh/known_hosts` para `.175`. Antes de confiar en la clave
  nueva, se comparó su huella (`ssh-keygen -lf` sobre la salida de
  `ssh-keyscan`) contra la que ya se conocía para `.163`
  (`SHA256:cYOc+UQuWXLO1qvWQPhBvI/4LS86RccrUOVrxS9qABs`): coincide
  exactamente, confirmando que es la misma Raspberry Pi y no un dispositivo
  distinto respondiendo en esa IP. Se agregó la clave con
  `ssh-keyscan -t ed25519 192.168.18.175 >> ~/.ssh/known_hosts`.

## Pendiente

- Instalar a mano (con `sudo`, una sola vez) las unidades systemd y
  `chrony` — comandos exactos en `deploy/systemd/README.md` y
  `docs/CONEXION_RASPBERRY.md`.
- Comitear y pushear el código ya escrito en la laptop pero todavía sin
  commit: `agent/rsu_middleware.py`, `controller/controller_emulator.py`,
  `gateway/obu_simulator.py`, `centro_control/` y cambios relacionados en
  `requirements.txt`/`agent/rsu_snmpv3_agent.py`/`docs/agent.md`. Las
  unidades systemd van a fallar al iniciar hasta entonces, porque la Pi
  solo tiene hoy `agent/rsu_snmpv3_agent.py` (la versión mínima de
  referencia).
- Decidir si la IP de la Pi debe fijarse (reserva DHCP en el router o IP
  estática en la Pi) para que el alias SSH no se rompa en cada reinicio —
  es un cambio de red y debe confirmarse antes de aplicarse (regla de
  `CLAUDE.md`).
- Configurar un segundo alias `rsu2` cuando la segunda RSU del banco de
  pruebas tenga IP asignada.
