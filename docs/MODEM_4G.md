# Módem 4G SIM7670G en la RSU (Raspberry Pi)

**Fecha de puesta en marcha:** 2026-10-28. **Operador:** Claro Perú (MCC/MNC
716-10), chip prepago, APN `claro.pe`. **Conexión física:** módem SIM7670G
por USB a la Raspberry Pi (`rsu-01`), antena LTE principal conectada.

Este documento reemplaza, para la Fase 4 de la campaña (RSU por 4G), al PDF
`F:\tesis2\Overleaf\Comandos módulo 4G SIM7670G y MQTT.pdf`, que no se usó
en esta puesta en marcha. [REVISAR] cruzar con ese PDF si difiere.

---

## 1. Cómo se presenta el módem en Linux

| Elemento | Valor observado | Nota |
|---|---|---|
| Interfaz de red | `usb0` (driver `rndis_host`) | Modo RNDIS: el módem hace NAT y da a la Pi `192.168.0.100/24`, gateway `192.168.0.1` |
| Puertos serie | `/dev/ttyACM0`–`ttyACM3` (driver `cdc_acm`) | **No** aparecen como `ttyUSB*` (no hace falta el driver `option`) |
| Puerto de comandos AT | `/dev/ttyACM2` | Verificado con `AT` → `OK` |
| Módulo | SIMCOM SIM7670G-MNGV, firmware V1.9.05 | Salida de `ATI` |
| Identificación USB | `QualComm_QualComm_Compo` | Normal en esta familia de módulos |
| Perfil de NetworkManager | `netplan-eth0` (asociado a `usb0`) | El nombre viene de netplan; lo usa el módem, no el puerto Ethernet |

Abrir el puerto AT:

```bash
sudo systemctl stop ModemManager 2>/dev/null   # evita que tome el puerto
sudo minicom -D /dev/ttyACM2 -b 115200          # salir: Ctrl+A, X ; eco local: Ctrl+A, E
```

## 2. Estado del enlace celular (2026-10-28)

| Comando | Respuesta | Lectura |
|---|---|---|
| `AT+CPIN?` | `READY` | Chip reconocido, sin PIN |
| `AT+CSQ` | `23,0` | Señal buena (escala 0–31) |
| `AT+CEREG?` | `0,1` | Registrado en red propia |
| `AT+COPS?` | `0,2,"71610",7` | Claro Perú, LTE |
| `AT+CPSI?` | `LTE,Online,716-10,…,EUTRAN-BAND2,…,-14,-98,-84,6` | Banda 2; RSRQ −14 dB, RSRP −98 dBm, RSSI −84 dBm, SNR 6 dB |
| `AT+CGDCONT?` | `1,"IPV4V6","claro.pe",…` | APN correcto, doble pila |
| `AT+CGPADDR=1` | `10.108.9.245` + IPv6 (tras el reinicio: `10.127.43.28`) | IPv4 privada del operador (CGNAT) e IPv6 global; **cambia en cada sesión** |
| `AT+CPING="8.8.8.8",1,4` | 4/4, 27–275 ms (prom. ~100 ms) | Primera medición de RTT desde el propio módem, antes de `DIALMODE=0`. Después del cambio también funciona: 4/4, 39–135 ms (prom. 70 ms). Con 10 paquetes responde `ERROR`; usar 4 |

**Direccionamiento (relevante para la redacción):** en IPv4 la RSU está detrás
del NAT del operador (`10.108.9.245`, privada) y del NAT del propio módem
(`192.168.0.100`): no es alcanzable desde fuera y solo puede iniciar
conexiones salientes (MQTT, Tailscale). En IPv6, en cambio, la Pi recibe una
dirección **global** (`2800:4b0:…`, verificada con `curl ifconfig.me`); que
sea alcanzable desde fuera depende del firewall del operador y **no se probó**.
El argumento "la RSU no es alcanzable por CGNAT" debe limitarse a IPv4.

## 3. Problema encontrado y solución

**Síntoma:** el módem tenía sesión de datos (IP del operador, `AT+CPING`
exitoso) y la Pi alcanzaba al módem (`ping 192.168.0.1` OK), pero ningún
tráfico de la Pi salía a internet por `usb0` (100 % de pérdida a 8.8.8.8,
incluso con ruta explícita, descartando el filtro de ruta inversa).

**Causa:** el módem estaba en modo de marcado manual: la sesión de datos era
solo del módem y no se compartía hacia la interfaz RNDIS.

**Solución** (queda guardada en el módem, sobrevive a reinicios):

```
AT$MYCONFIG?                    -> "usbnetmode",0 (RNDIS; ya estaba bien)
AT+DIALMODE=0                   -> OK  (marcado automático; AT+DIALMODE? da ERROR en este firmware)
AT$MYCONFIG="usbnetmode",0      -> OK
AT+CRESET                       -> el módem se reinicia (~30 s; minicom pierde el puerto)
```

Referencia: Waveshare, *A7600X RNDIS Dial-up Networking*.

**Efecto colateral que hubo que corregir:** NetworkManager asignó a `usb0`
métrica 100, menor que la del Wi-Fi (600). Mientras el 4G no reenviaba
tráfico, toda la salida a internet de la Pi iba a `usb0` y Tailscale se
desconectó (la Pi seguía accesible por SSH en la LAN, `192.168.18.176`).

Además, la memoria de SMS del chip estaba llena (20/20), lo que impide
recibir avisos del operador (recargas, paquetes). Se vació con `AT+CMGD=0,4`.

## 4. Modos de red de la RSU

Automatizado en `scripts/red_4g.sh` (corre EN la Pi) y `scripts/pi.sh red
<subcomando> [host]` (lo invoca por SSH desde la laptop). El perfil de
NetworkManager (`netplan-eth0` por defecto) y el puerto AT (`/dev/ttyACM2`
por defecto) son parámetros (`--perfil`, `--puerto-at`), no están fijos en
el script.

```bash
scripts/pi.sh red modo-normal   [host]                # Wi-Fi para todo, 4G de respaldo
scripts/pi.sh red modo-campana  [host]                 # 4G como ruta principal, Wi-Fi SIN apagar
scripts/pi.sh red modo-campana  [host] --sin-wifi      # además apaga el Wi-Fi (verifica Tailscale antes)
scripts/pi.sh red estado        [host]                 # modo, rutas, tailscale, contadores usb0, señal
scripts/pi.sh red evidencia     [host]                 # guarda el bloque de ~/evidencia_4g/red_<fecha>.txt
```

### Modo normal (por defecto): Wi-Fi para todo, 4G de respaldo

| | IPv4 | IPv6 |
|---|---|---|
| `wlan0` | ruta por defecto, métrica 600 | — (la red local no da IPv6) |
| `usb0` (4G) | ruta por defecto, métrica 900 (respaldo) | **sin** ruta por defecto (`never-default`) |

`red_4g.sh modo-normal` aplica `ipv4.route-metric 900` +
`ipv6.never-default yes` al perfil del módem y enciende el Wi-Fi. Sin
`ipv6.never-default`, todo el tráfico IPv6 de la Pi (actualizaciones, parte
de Tailscale) sale por el 4G aunque el Wi-Fi tenga prioridad en IPv4:
consume saldo sin que se note y mezcla caminos en las mediciones.

### Modo campaña 4G: un solo camino, por el 4G

1. **Antes**, en modo normal: `scripts/pi.sh deploy` y cualquier `apt`/`pip`/`git pull` (no gastar megas).
2. Confirmar que se entra a la Pi por su IP de Tailscale (`100.105.28.51`) desde la laptop.
3. `scripts/pi.sh red modo-campana [host]`: `ipv4.route-metric 50` en el
   perfil del módem (4G pasa a ser la ruta principal). **No apaga el
   Wi-Fi por sí solo** — con `--sin-wifi`, primero verifica que Tailscale
   esté conectado (`tailscale ip -4`) y aborta sin tocarlo si no lo está;
   si lo está, avisa que el acceso quedará solo por Tailscale y recién
   entonces apaga el Wi-Fi.
4. Verificar que el camino ya no es la LAN: `scripts/pi.sh tailscale-ping [host]`
   (= `tailscale ping --c 1 laptopricardoub` desde la Pi) debe decir
   `via DERP(...)` o `via <IP pública>`, **no** `via 192.168.18.x` (`scripts/pi.sh red estado`
   incluye `tailscale status`). En modo normal/`pi-lan` es al revés: debe salir
   `via 192.168.18.x` (camino directo por la LAN) — así lo usa
   `scripts/campanas/lazo_centralizado.py` para confirmar `config=pi-lan` antes de medir.
5. Al terminar, volver al modo normal: `scripts/pi.sh red modo-normal [host]`.

Si se pierde todo acceso (Wi-Fi apagado y 4G caído): `nmcli radio wifi off`
persiste tras reiniciar, así que hay que conectar la Pi al router por cable
Ethernet (o monitor y teclado) y ejecutar `sudo nmcli radio wifi on`
(o `scripts/red_4g.sh modo-normal` ya en la propia Pi).

## 5. Saldo y consumo

- El chip funciona con **paquetes de megas que vencen** (historial de SMS:
  paquete de 500 MB expirado el 13/10). Tener saldo no garantiza datos: para
  la campaña, activar un paquete (app Mi Claro).
- `AT+CUSD=1,"*777#",15` respondió `ERROR`; probar antes `AT+CSCS="GSM"`.
- Leer SMS: `AT+CMGF=1`, `AT+CPMS="SM","SM","SM"`, `AT+CMGL="ALL"`. Los
  mensajes llegan en UTF-16 hexadecimal y el módem los muestra recortados.
- Consumo acumulado desde el último reinicio del módem: `ip -s link show usb0`
  (bytes RX/TX; se reinicia con el módem). Registrar antes y después de cada
  corrida de la campaña.

## 6. Evidencia a capturar

Primera captura (modo normal, 2026-10-28): `evidencia/2026-10-28_modem-4g/` (ver su `NOTAS.md`).
Resultado de referencia: ping desde la Pi por el 4G a 8.8.8.8, 10/10, 31–122 ms, prom. 53 ms;
IPv4 pública vista desde internet `179.6.137.254`. Para cada campaña, como mínimo:

1. Foto del montaje: Pi + SIM7670G + antena.
2. Captura de minicom con `AT+CPIN?`, `AT+CSQ`, `AT+CEREG?`, `AT+COPS?`, `AT+CPSI?`, `AT+CGDCONT?`, `AT+CGPADDR=1`.
3. `AT+CPING="8.8.8.8",1,4` desde el módem (con 10 paquetes da `ERROR`). Referencia; la medición válida es el ping desde la Pi (punto 5).
4. Captura de `ip -br addr show usb0`, `ip route`, `ip -6 route` (o
   directamente `scripts/pi.sh red estado [host]`).
5. Captura de ping y `curl --interface usb0 https://ifconfig.me` por el 4G.
6. Captura de `tailscale status` y `tailscale ping` en modo campaña (camino no LAN).
7. `ip -s link show usb0` antes y después de cada corrida (`scripts/pi.sh red estado`
   o `scripts/pi.sh red evidencia [host]`, que guarda el bloque completo en
   `~/evidencia_4g/red_<fecha>.txt` en la propia Pi).
