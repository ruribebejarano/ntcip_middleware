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

## Sudo sin contraseña para estos tres servicios (opcional, recomendado)

Sin esto, cada `scripts/pi.sh start|stop|restart|logs ...` va a pedir la
contraseña de `ricardoub` de forma interactiva (`ssh -t`). Para evitarlo,
**a mano, por `ssh rsu`**, crear una regla de sudoers acotada exactamente a
estos comandos (nunca dar `sudo` sin contraseña de forma general):

```bash
sudo visudo -f /etc/sudoers.d/rsu-pi-scripts
```

Contenido:

```
ricardoub ALL=(root) NOPASSWD: /usr/bin/systemctl start rsu-controller.service, \
  /usr/bin/systemctl stop rsu-controller.service, \
  /usr/bin/systemctl restart rsu-controller.service, \
  /usr/bin/systemctl start rsu-agent.service, \
  /usr/bin/systemctl stop rsu-agent.service, \
  /usr/bin/systemctl restart rsu-agent.service, \
  /usr/bin/systemctl start mosquitto.service, \
  /usr/bin/systemctl stop mosquitto.service, \
  /usr/bin/systemctl restart mosquitto.service, \
  /usr/bin/journalctl -u rsu-controller.service -n 50 -f, \
  /usr/bin/journalctl -u rsu-agent.service -n 50 -f, \
  /usr/bin/journalctl -u mosquitto.service -n 50 -f
```

Verificar la ruta real de los binarios antes de pegar (`which systemctl`,
`which journalctl`) — si no coincide exactamente con lo que `visudo` valida,
la regla no aplica y sigue pidiendo contraseña (falla segura, no silenciosa).

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
