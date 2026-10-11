# Unidades systemd de la RSU

Reemplazan las terminales abiertas manualmente (`docs/GUIA_COMANDOS.md`,
paso 1) por dos servicios administrados con `scripts/pi.sh`:

- `rsu-controller.service` → `controller/controller_emulator.py`
- `rsu-agent.service` → `agent/rsu_middleware.py` (requiere `mosquitto` y,
  idealmente, `rsu-controller` ya arriba — ver `After=`/`Wants=` en el
  archivo)

`mosquitto.service` ya existe (paquete del sistema, instalado y habilitado
según `docs/GUIA_COMANDOS.md`); no se crea una unidad nueva para él, solo se
administra con `scripts/pi.sh {start,stop,restart,status,logs} mosquitto`.

## Instalación (una sola vez, en la Pi — necesita contraseña de sudo)

Este paso requiere una contraseña interactiva de `sudo` que el agente de
código no tiene por diseño (no se pide ni se comparte en texto plano).
**Ejecutar a mano, por `ssh rsu`:**

```bash
cd ~/ntcip_middleware
sudo cp deploy/systemd/rsu-controller.service deploy/systemd/rsu-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
```

No se habilitan (`enable`) para arranque automático en el boot: se
administran a demanda con `scripts/pi.sh start|stop|restart <servicio>`,
igual que las terminales manuales que reemplazan. Si en algún momento se
quiere que sobrevivan a un reinicio de la Pi, agregar:

```bash
sudo systemctl enable rsu-controller.service rsu-agent.service
```

## Sudo sin contraseña para estos tres servicios (ya aplicado)

**Estado real en la Pi (2026-10-11):** el estudiante creó
`/etc/sudoers.d/rsu-servicios` con esta regla exacta (confirmado con
`sudo -n -l`):

```
ricardoub ALL=(root) NOPASSWD: /usr/bin/systemctl start rsu-controller.service, \
  /usr/bin/systemctl stop rsu-controller.service, \
  /usr/bin/systemctl restart rsu-controller.service, \
  /usr/bin/systemctl start rsu-agent.service, \
  /usr/bin/systemctl stop rsu-agent.service, \
  /usr/bin/systemctl restart rsu-agent.service, \
  /usr/bin/systemctl restart mosquitto.service
```

Notas sobre esta regla, tal como quedó (no como se había sugerido
originalmente):

- Cubre `start`/`stop`/`restart` de `rsu-controller` y `rsu-agent`, pero
  de `mosquitto` **solo `restart`** (no `start`/`stop` sueltos). Si hace
  falta `scripts/pi.sh start mosquitto` o `stop mosquitto` sin
  contraseña, hay que ampliar la regla.
- **No incluye `journalctl`**: `scripts/pi.sh logs <servicio>` sigue
  pidiendo contraseña (usa `sudo journalctl ... -f`). Para leer el log
  sin seguimiento en vivo y sin contraseña, alcanza con `journalctl -u
  <servicio> -n N --no-pager` **sin** `sudo` — el usuario `ricardoub` ya
  puede leer el journal de estos servicios sin privilegios elevados
  (confirmado en la práctica); solo `-f` (seguimiento) vía
  `scripts/pi.sh logs` requiere la contraseña hoy.
- **La regla general `(ALL : ALL) ALL`** (de un hito anterior, ver
  bitácora `2026-10-11_commit-backlog-y-primer-deploy.md`) **sigue
  presente** además de esta regla acotada — no se retiró. La regla
  acotada es, en la práctica, redundante mientras la general exista,
  pero documentarla aquí deja claro qué haría falta si en algún momento
  se retira la general y se quiere mantener el acceso sin contraseña
  solo para estos tres servicios.

Para crearla desde cero en otra máquina (p. ej. la segunda RSU), el
comando es:

```bash
sudo visudo -f /etc/sudoers.d/rsu-servicios
```

pegando el bloque de arriba. Verificar la ruta real de los binarios antes
(`which systemctl`) — si no coincide exactamente con lo que `visudo`
valida, la regla no aplica y sigue pidiendo contraseña (falla segura, no
silenciosa).

## Verificación

```bash
scripts/pi.sh status controller
scripts/pi.sh status agent
scripts/pi.sh status mosquitto
```

## Nota de dependencias

Al momento de crear estas unidades (2026-10-11), `agent/rsu_middleware.py` y
`controller/controller_emulator.py` todavía no estaban comiteados ni
desplegados en la Pi (solo existía `agent/rsu_snmpv3_agent.py`, la versión de
referencia mínima). Las unidades van a fallar al iniciar hasta que ese
código se comitee, se pushee y se corra `scripts/pi.sh deploy`.
