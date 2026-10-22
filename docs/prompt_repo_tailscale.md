# Prompt para Claude Code: acceso a la RSU por Tailscale (repositorio ntcip_middleware)

Instalé Tailscale en la Raspberry Pi y en la laptop, con la misma cuenta personal. Datos:

| Equipo | Nombre en Tailscale | IP de Tailscale | Sistema |
|---|---|---|---|
| Raspberry Pi 5 (RSU) | rsu-01 | 100.105.28.51 | Linux 6.18.39+rpt-rpi-2712, Tailscale 1.104.1 |
| Laptop (centro de control y OBU) | laptopricardoub | 100.121.77.97 | Windows 11 25H2, Tailscale 1.104.1 |

`tailscaled` está habilitado para iniciar con el sistema en la Pi. La laptop **ya no está en la red de casa**, así que la IP local 192.168.18.175 no es alcanzable desde aquí.

Evidencia ya guardada en `evidencia/`:
- `2026-10-12_tailscale_consola-maquinas.png`: consola de Tailscale con ambas máquinas conectadas.
- `2026-10-12_rsu_tailscale-status.png`: `tailscale up`, `tailscale status`, `tailscale ip -4` y `systemctl is-enabled tailscaled` en la Pi.

## Tareas

1. Actualiza el alias `rsu` en `~/.ssh/config` para que use `HostName rsu-01`, o `100.105.28.51` si el nombre no resuelve. Comprueba con `scripts/check_pi.sh` que funciona desde fuera de casa.
2. Revisa en qué dirección escucha el agente SNMPv3 (`agent/rsu_middleware.py`) y en qué escucha mosquitto. Si están ligados a la IP de la red local, haz que también respondan por la interfaz de Tailscale (`tailscale0`). **No los expongas a ninguna otra interfaz sin preguntarme.** Si hace falta reiniciar servicios, usa `scripts/pi.sh` (ya tienes sudo sin contraseña para eso).
3. Desde la laptop, por Tailscale, ejecuta un `snmpwalk` del subárbol NTCIP 1202 contra la RSU y guarda la salida en `evidencia/2026-10-12_snmpwalk-por-tailscale.txt` (y su versión PNG con `scripts/txt_a_png.py`). Agrega a ese archivo un encabezado que indique que la laptop está fuera de la red local de la RSU. Es la evidencia de que el centro de control supervisa la RSU a través de un túnel iniciado desde la RSU.
4. Comprueba también que `scripts/pi.sh status` y el panel del centro de control funcionen por Tailscale. Si el panel tiene la IP local fija, cámbiala a una configuración (`.env`) que acepte `rsu-01`.
5. Actualiza `docs/CONEXION_RASPBERRY.md`: Tailscale pasa a ser el acceso principal; la IP local queda como alternativa cuando se está en casa; Raspberry Pi Connect se usa solo para mantenimiento. Indica que Tailscale se usa con una cuenta personal, porque el dominio institucional alcanzó el límite de usuarios del plan gratuito.
6. Crea la entrada de bitácora `docs/bitacora/2026-10-12_acceso-remoto-tailscale.md`, con la plantilla, y haz commit.

Al terminar, dime si el `snmpwalk` por Tailscale funcionó, para que actualice la tesis.
