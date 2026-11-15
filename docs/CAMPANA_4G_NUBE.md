# Campaña 4G con el broker y el servidor en Oracle Cloud

Repite la condición 4G de la campaña centralizada en **tres sesiones**
(mañana, tarde y noche; en días distintos si es posible), con el broker
MQTT, el servidor central y la OBU emulada juntos en una máquina virtual
con IP pública, y la RSU física llegando a ella por la red celular, sin la
red superpuesta en el camino del lazo. Es la condición que la tesis
declara pendiente en sus limitaciones ("Cobertura celular del banco").

## Infraestructura (ya montada)

| Pieza | Valor |
|---|---|
| Máquina | Oracle Cloud, Chile Central (Santiago), `VM.Standard.E2.1.Micro` (Always Free), Ubuntu 24.04, 1 GB + 1 GB de swap |
| IP pública | `129.151.104.124` (efímera: se conserva al reiniciar, cambia si la instancia se detiene o se termina) |
| Acceso | `ssh -i ~/.ssh/oci_ntcip ubuntu@129.151.104.124` |
| Broker | Mosquitto 2.0.18, servicio `mosquitto-ntcip` (`deploy/mosquitto_nube_tls.conf`), TLS 1.3 + mTLS en 8883 |
| Certificados | `deploy/pki/` de la máquina: CA pública, CRL, `servidor-central` (SAN con la IP pública) y las OBU `obu-lazo-r01..r18`, `obu-desvio-r01..r18`. La llave de la CA queda solo en la laptop |
| Administración de la Pi | Tailscale (`broker-nube`) + llave SSH propia de la máquina, alias `rsu` |

Si la IP pública cambia, hay que volver a emitir el certificado del broker
con la IP nueva en el SAN (`generar_ca.py emitir --tipo servidor --san ...`),
copiarlo a la máquina, reiniciar `mosquitto-ntcip` y actualizar
`HOST_NUBE` en `scripts/pi_broker.sh`.

La CRL de la CA vence el **2026-12-03**: después de esa fecha el broker
rechaza las conexiones hasta renovarla.

## Antes de cada sesión

1. **Saldo del chip** del módem: revisar en Mi Claro. Anotar el saldo.
2. **Pi en modo campaña** (el 4G pasa a ser la ruta principal; el Wi-Fi
   queda encendido solo para administrar por Tailscale). En la Pi:
   ```bash
   bash ~/ntcip_middleware/scripts/red_4g.sh modo-campana
   ```
   Comprobar que la ruta por defecto es `usb0`:
   ```bash
   ip route | grep default
   ```
3. **Pi apuntando al broker de Oracle.** En la Pi (pide la contraseña de sudo):
   ```bash
   bash ~/ntcip_middleware/scripts/pi_broker.sh nube
   ```
   Debe terminar con `Conectado al broker MQTT (129.151.104.124:8883)`.
4. **Máquina actualizada.** Desde la laptop:
   ```bash
   ssh -i ~/.ssh/oci_ntcip ubuntu@129.151.104.124 'cd ~/ntcip_middleware && git pull --ff-only && systemctl is-active mosquitto-ntcip && timedatectl | grep synchronized'
   ```

## Sesión

Entrar a la máquina y abrir una sesión de `tmux`, para que la campaña siga
aunque se corte el SSH:

```bash
ssh -i ~/.ssh/oci_ntcip ubuntu@129.151.104.124
tmux new -s campana
cd ~/ntcip_middleware
```

Correr los dos escenarios. `--broker-host 127.0.0.1` porque el servidor y la
OBU están en la misma máquina que el broker (el SAN del certificado incluye
`127.0.0.1`):

```bash
.venv/bin/python scripts/campanas/lazo_centralizado.py --escenario lazo --config pi-4g --factor 1 --broker-host 127.0.0.1 --broker-port 8883 --tls deploy/pki
.venv/bin/python scripts/campanas/lazo_centralizado.py --escenario desvio --config pi-4g --factor 1 --broker-host 127.0.0.1 --broker-port 8883 --tls deploy/pki
```

Si se corta el SSH, volver a entrar y `tmux attach -t campana`.

Anotar para cada sesión: fecha, hora de inicio y fin, lugar de la Pi,
operador, y las carpetas de salida que imprime el script.

## Después de cada sesión

1. **Traer los resultados a la laptop** (Git Bash, raíz del repo):
   ```bash
   scp -i ~/.ssh/oci_ntcip -r 'ubuntu@129.151.104.124:ntcip_middleware/resultados/campana/*_pi-4g' resultados/campana/
   ```
2. **Pi de vuelta al broker de la laptop y a modo normal.** En la Pi:
   ```bash
   bash ~/ntcip_middleware/scripts/pi_broker.sh laptop
   bash ~/ntcip_middleware/scripts/red_4g.sh modo-normal
   ```
3. Anotar el saldo final del chip.

## Notas

- El agente de la RSU usa la reconexión ajustada (`keepalive` 10 s,
  reintentos de 1 a 2 s); la campaña del 2026-11-03 corrió con la
  configuración por defecto. No cambia la latencia del lazo, pero conviene
  dejarlo dicho al comparar.
- La latencia medida incluye el trayecto Lima–Santiago, que es justamente
  lo que la tesis pide medir para un broker en la nube.
