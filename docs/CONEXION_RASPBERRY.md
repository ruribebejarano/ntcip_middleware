# Conexión con la Raspberry Pi (RSU del banco de pruebas)

Este documento describe cómo dejar la laptop "conectada" con la Raspberry Pi,
siguiendo el flujo de trabajo ya definido en `CLAUDE.md`: **se desarrolla y se
comitea en la laptop; en la Pi solo se hace `git pull`** (salvo depuración de
algo que solo se reproduce en el hardware real).

## Qué se configuró

- **Clave SSH dedicada**: `~/.ssh/id_ed25519_rsu` (par pública/privada, generado
  sin passphrase para facilitar los scripts de este repo). Vive en la laptop,
  fuera del repo — nunca se comitea.
- **Alias SSH `rsu`** en `~/.ssh/config` de la laptop:
  ```
  Host rsu
      HostName 192.168.18.175
      User ricardoub
      IdentityFile ~/.ssh/id_ed25519_rsu
      IdentitiesOnly yes
  ```
  Con esto, `ssh rsu` reemplaza tener que recordar la IP y el usuario.
- **`scripts/check_pi.sh`**: verifica que la Pi responda por SSH y el estado
  del repo/entorno virtual en ella. No modifica nada.
- **`scripts/deploy_to_pi.sh`**: hace `git pull --ff-only` en la Pi. No
  reinicia el agente (eso se hace a mano, ver `docs/agent.md`). Reemplazado
  en el uso diario por `scripts/pi.sh deploy` (ver abajo), que además
  reinstala `requirements.txt` si cambió.
- **`scripts/pi.sh`**: `deploy`, `start`/`stop`/`restart`/`status`/`logs
  <servicio>` (`agent`/`controller`/`mosquitto`) y `fetch` (copia
  `resultados/` de la Pi a la laptop) y `clock` (offset de reloj de ambas
  máquinas). Ver el encabezado del script para el detalle de cada
  subcomando.
- **Unidades systemd** en `deploy/systemd/` (`rsu-controller.service`,
  `rsu-agent.service`): reemplazan las terminales manuales de
  `docs/GUIA_COMANDOS.md` por servicios administrados con `scripts/pi.sh`.
  `mosquitto.service` ya existía como servicio del sistema.

## Puesta en marcha (una sola vez, con la Pi encendida y en la misma red)

1. Confirmar la IP actual de la Pi (`hostname -I` en la propia Pi, o revisar el
   router). Si cambió, actualizar `HostName` en `~/.ssh/config` de la laptop
   (ver nota de IP más abajo).
2. Confirmar el usuario real de la Pi. El alias asume `ricardoub`; si la
   cuenta configurada es otra, actualizar `User`.
3. Copiar la clave pública a la Pi (pedirá la contraseña esa única vez):
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519_rsu.pub rsu
   ```
4. Si la Pi cambia de IP y ya tenía una entrada en `~/.ssh/known_hosts` con
   otra IP, agregar la clave de host para la IP nueva antes de conectar
   (si la huella no coincide con la ya conocida, **no continuar** — podría
   no ser la misma Pi):
   ```bash
   ssh-keyscan -t ed25519 <IP_NUEVA> | ssh-keygen -lf -   # comparar huella
   ssh-keyscan -t ed25519 <IP_NUEVA> >> ~/.ssh/known_hosts  # si coincide
   ```
5. Verificar:
   ```bash
   ./scripts/check_pi.sh
   ```

## Puesta en marcha de `scripts/pi.sh` (una sola vez, necesita contraseña de sudo)

El agente de código despliega archivos y puede correr comandos por SSH, pero
**no tiene ni pide la contraseña de `sudo` de la Pi** — eso se hace a mano,
una sola vez, por `ssh rsu`:

1. **Unidades systemd** (`rsu-controller`, `rsu-agent`): instalación y
   sudoers sin contraseña opcional — ver `deploy/systemd/README.md`.
2. **Reloj (chrony)**, necesario para medir latencia por tramo entre la OBU
   (laptop) y la RSU (Pi) con marcas de tiempo de ambas máquinas:
   ```bash
   sudo apt update && sudo apt install -y chrony
   sudo cp ~/ntcip_middleware/scripts/chrony/rsu-lab.conf /etc/chrony/conf.d/rsu-lab.conf
   sudo systemctl restart chrony
   chronyc tracking
   ```
3. Verificar todo junto desde la laptop:
   ```bash
   scripts/pi.sh status controller
   scripts/pi.sh status agent
   scripts/pi.sh status mosquitto
   scripts/pi.sh clock
   ```

Para verificar el reloj de la laptop (Windows) contra la misma referencia
que usa `scripts/chrony/rsu-lab.conf`, sin cambiar la configuración de hora
del sistema (solo lectura):
```powershell
w32tm /stripchart /computer:time.cloudflare.com /samples:1 /dataonly
```
Si se quiere que Windows se sincronice de forma persistente contra esa misma
referencia (cambio de configuración del sistema, no solo lectura),
**confirmar antes de aplicar**:
```powershell
w32tm /config /manualpeerlist:"time.cloudflare.com time.google.com" /syncfromflags:manual /update
```

## Uso del día a día

```bash
scripts/pi.sh deploy              # push (laptop) + pull (Pi) + pip install si hizo falta
scripts/pi.sh status agent        # o: controller | mosquitto
scripts/pi.sh restart agent
scripts/pi.sh logs agent          # journalctl -f, Ctrl+C para salir
scripts/pi.sh fetch               # trae resultados/ de la Pi a la laptop
scripts/pi.sh clock               # offset de reloj de la Pi y de la laptop
./scripts/check_pi.sh             # diagnosticar si algo no conecta
```

## Advertencias (no violar sin confirmar con el usuario)

- **No editar `hostapd`, `dnsmasq`, interfaces de red ni `snmpd.conf` de la Pi
  sin preguntar primero.** Ver `CLAUDE.md` — una sesión SSH perdida por un
  cambio de red mal aplicado cuesta un viaje físico al equipo.
- La IP `192.168.18.175` es la última observada (actualizada el 2026-10-11;
  antes era `192.168.18.163`); **no está confirmado que sea una IP fija**
  (reserva DHCP). Si el banco de pruebas requiere una IP estable para que
  este alias no se rompa cada vez que la Pi se reinicia, eso implica
  configurar una reserva DHCP en el router o una IP estática en la Pi —
  cambio de red que también debe confirmarse antes de aplicarse.
- Hay **dos RSU** en el banco de pruebas (ver `CLAUDE.md`). Este documento y
  los scripts cubren una sola por ahora; si la segunda ya tiene IP asignada,
  se puede replicar el mismo patrón con un segundo alias (p. ej. `rsu2`) y un
  segundo argumento de host en los scripts.
