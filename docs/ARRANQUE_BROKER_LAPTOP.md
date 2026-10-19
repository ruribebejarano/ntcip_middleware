# Arranque desde cero: broker Mosquitto en la laptop

Arquitectura de esta etapa (sin EMQX, sin TLS):

```
Laptop (Windows)                                   Raspberry Pi (rsu-01)
  Mosquitto :1883  <── MQTT por Tailscale ──────  rsu-agent  (RSU_ID=1)
  OBU emulada  ──> 127.0.0.1:1883                     │ TCP local
  Centro de control (SNMPv3) ── Tailscale :1161 ──>   rsu-controller
```

El broker de la laptop hace de broker central (esquema E2+E4). La RSU se
conecta a él como cliente; el Mosquitto de la Pi deja de usarse.

| Equipo | Tailscale |
|---|---|
| Raspberry Pi (RSU) | `rsu-01`, 100.105.28.51 |
| Laptop | `laptopricardoub`, 100.121.77.97 |

## Paso 1 (una vez). Commit y push del código nuevo — Git Bash en la laptop

```bash
cd /e/Tesis/ntcip_middleware
git add agent/ common/ gateway/ config/ scripts/trayectorias/ scripts/campanas/ \
        scripts/analisis/lazo_emulado.py tests/ resultados/trayectorias/ \
        docs/LAZO_EMULADO.md docs/ARRANQUE_BROKER_LAPTOP.md docs/bitacora/2026-10-19_lazo-obu-emulada.md \
        evidencia/2026-10-12_*.png
git commit -m "OE4/OE5: OBU emulada con M1/M2/M3 y lazo completo sin seguridad"
```

(`scripts/pi.sh deploy` hace el push en el paso 4.)

## Paso 2 (una vez). Mosquitto en la laptop — PowerShell como administrador

```powershell
winget install EclipseFoundation.Mosquitto
```

Si winget no lo encuentra: instalador de Windows en https://mosquitto.org/download/.

Configuración (reemplaza el archivo de ejemplo):

```powershell
@"
listener 1883 0.0.0.0
allow_anonymous true
set_tcp_nodelay true
"@ | Set-Content -Encoding ascii "C:\Program Files\mosquitto\mosquitto.conf"

Restart-Service mosquitto
Set-Service mosquitto -StartupType Automatic
Get-Service mosquitto
```

Firewall: abrir el 1883 solo para la red de Tailscale (100.64.0.0/10) y la propia laptop:

```powershell
New-NetFirewallRule -DisplayName "Mosquitto tesis (Tailscale)" -Direction Inbound `
  -Protocol TCP -LocalPort 1883 -RemoteAddress 100.64.0.0/10 -Action Allow
```

Prueba local (dos ventanas de PowerShell):

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -h 127.0.0.1 -t prueba -v
& "C:\Program Files\mosquitto\mosquitto_pub.exe" -h 127.0.0.1 -t prueba -m hola
```

`allow_anonymous true` es solo de laboratorio: sin TLS ni autenticación (P4 pendiente).

## Paso 3 (una vez). SSH a la Pi por Tailscale — laptop

En `C:\Users\<usuario>\.ssh\config`, cambiar el `HostName` del alias `rsu`:

```
Host rsu
    HostName rsu-01
    User ricardoub
    IdentityFile ~/.ssh/id_ed25519_rsu
    IdentitiesOnly yes
```

Si `rsu-01` no resuelve, usar `HostName 100.105.28.51`. Comprobar (Git Bash):

```bash
tailscale status
scripts/check_pi.sh
```

## Paso 4 (una vez). Desplegar y apuntar la RSU al broker de la laptop

Desde Git Bash en la laptop:

```bash
scripts/pi.sh deploy
```

En la Pi (`ssh rsu`), decirle al servicio dónde está el broker (archivo aparte,
no se toca la unidad del repositorio):

```bash
sudo mkdir -p /etc/systemd/system/rsu-agent.service.d
sudo tee /etc/systemd/system/rsu-agent.service.d/broker.conf > /dev/null <<'EOF'
[Service]
Environment=MQTT_BROKER_HOST=100.121.77.97
Environment=RSU_ID=1
EOF
sudo systemctl daemon-reload
```

Opcional, para que la RSU arranque sola tras cada reinicio de la Pi:

```bash
sudo systemctl enable rsu-controller.service rsu-agent.service
```

## Paso 5 (cada vez que se reinicia la Pi). Levantar los servicios

Si no se hizo el `enable` del paso 4, desde Git Bash:

```bash
scripts/pi.sh start controller
scripts/pi.sh start agent
scripts/pi.sh status agent
ssh rsu "journalctl -u rsu-agent -n 20 --no-pager"
```

En el log debe aparecer:
`Conectado al broker MQTT (100.121.77.97:1883), reason_code=Success`.
Si dice `Connection refused` o se reinicia en bucle, revisar que Mosquitto
esté corriendo en la laptop y la regla del firewall.

Relojes (para t_V2I; el RTT M1/M2 no lo necesita). En PowerShell como
administrador:

```powershell
w32tm /resync /force
```

Y en Git Bash: `scripts/pi.sh clock`. Encender la Pi unos 10 minutos antes
de medir para que chrony se estabilice.

## Paso 6. Prueba rápida — laptop

Supervisión SNMPv3 por Tailscale (PowerShell):

```powershell
$RSU = "rsu-01"
.\.venv\Scripts\python.exe centro_control\software_gestion.py walk --host $RSU --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  1.3.6.1.4.1.1206.4.2.1
```

Un recorrido de la OBU emulada contra el broker local:

```powershell
.\.venv\Scripts\python.exe gateway\obu_emulada.py --broker-host 127.0.0.1 `
  --trayectoria resultados\trayectorias\transversal_a_s1.csv
```

Debe mostrar `M1 nueva -> rsu/1 ...`, luego `M2 <- ... estado=recibida` o
`concedida`, y `M3 -> rsu/1 (cruce)`.

## Paso 7. Campaña y análisis

```powershell
.\.venv\Scripts\python.exe scripts\campanas\lazo_emulado.py --broker-host 127.0.0.1 --repeticiones 5
```

Unos 2 minutos por recorrido (3 escenarios × 5 semillas ≈ 30 min). Luego, en Git Bash:

```bash
scripts/pi.sh fetch
.venv/Scripts/python.exe scripts/analisis/lazo_emulado.py \
  --dir resultados/lazo_emulado/<corrida> --dir resultados/rsu/eventos
```

## Paso 8 (opcional). Segunda RSU en la laptop

Las trayectorias `avenida_ab` y `avenida_ba` cruzan dos intersecciones. Sin
una RSU 2, las solicitudes a `rsu/2` quedan sin respuesta (es lo esperado).
Para cerrarlas, en dos ventanas de PowerShell:

```powershell
# ventana 1: controlador de la RSU 2
$env:RSU_ID="2"; $env:RSU_EVENTOS_DIR="resultados\rsu2"
.\.venv\Scripts\python.exe controller\controller_emulator.py --port 9001

# ventana 2: middleware de la RSU 2, contra el mismo broker
$env:RSU_ID="2"; $env:RSU_EVENTOS_DIR="resultados\rsu2"; $env:SNMP_PORT="1162"
$env:CONTROLLER_PORT="9001"; $env:MQTT_BROKER_HOST="127.0.0.1"
.\.venv\Scripts\python.exe agent\rsu_middleware.py
```

En el análisis, agregar `--dir resultados/rsu2`.

## Qué cambia respecto de antes

- `scripts/demo_asesor.sh`, paso 7: publica en el Mosquitto **de la Pi**, al
  que la RSU ya no está conectada. Para la demo del lazo, usar el paso 6 de
  esta guía.
- El Mosquitto de la Pi puede quedar encendido; no se usa. Para apagarlo:
  `ssh rsu "sudo systemctl disable --now mosquitto"`.
- Para volver al broker de la Pi: borrar
  `/etc/systemd/system/rsu-agent.service.d/broker.conf`,
  `sudo systemctl daemon-reload` y reiniciar `agent`.
