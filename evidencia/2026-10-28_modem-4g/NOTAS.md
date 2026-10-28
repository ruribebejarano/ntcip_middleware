# Evidencia — puesta en marcha del módem 4G SIM7670G en la RSU

**Fecha:** 2026-10-28, 17:54–18:39 (hora de Lima). **Equipo:** Raspberry Pi
`rsu-01` (hostname `ricardoub`, LAN `192.168.18.176`, Tailscale
`100.105.28.51`) + SIMCOM SIM7670G-MNGV (firmware V1.9.05) por USB.
**Operador:** Claro Perú (716-10), chip prepago, APN `claro.pe`.
Procedimiento completo y modos de red: `docs/MODEM_4G.md`.

## Archivos

| Archivo | Contenido |
|---|---|
| `00_diagnostico_caida_tailscale.txt` | Caída de Tailscale: `usb0` era ruta por defecto (métrica 100) y el 4G no reenviaba tráfico; `ping -I usb0` 100 % pérdida; logs de `tailscaled` ("context deadline exceeded", "UDP is blocked") |
| `01_dialmode_creset.png` | Corrección: `AT$MYCONFIG?` → `"usbnetmode",0` (RNDIS, ya estaba bien); `AT+DIALMODE?` → `ERROR` (no se puede consultar en este firmware); `AT+DIALMODE=0` → `OK`; `AT+CRESET` (el puerto desaparece al reiniciarse) |
| `02_ati_estado_enlace_IMEI_SIN_DIFUMINAR.png` | `ATI`, `AT+CPIN?`, `AT+CSQ`, `AT+CEREG?`, `AT+COPS?`, `AT+CPSI?`, `AT+CGDCONT?`, `AT+CGPADDR=1` tras el reinicio. **Contiene el IMEI: difuminar antes de usar en la tesis** |
| `03_cping_modem.png` | `AT+CPING="8.8.8.8",1,4` desde el módem |
| `04_interfaz_rutas.png` | `ip -br addr show usb0`, `ip route`, `ip -6 route` en modo normal |
| `05_ping_curl_4g.png` | Ping a 8.8.8.8 forzado por `usb0` (ruta temporal) y `curl --interface usb0 -4/-6 https://ifconfig.me` |
| `06_tailscale_consumo.png` | `tailscale status` y `ip -s link show usb0` (consumo) |

## Valores registrados

**Enlace celular** (`02`, tras el reinicio):
- `+CSQ: 24,0` (señal buena, escala 0–31); `+CEREG: 0,1` (registrado, red propia).
- `+CPSI: LTE,Online,716-10,0x3779,77623141,134,EUTRAN-BAND2,675,4,4,-12,-97,-85,5`
  → LTE banda 2, RSRQ −12 dB, RSRP −97 dBm, RSSI −85 dBm, SNR 5 dB.
- IP del operador: `10.127.43.28` (antes del reinicio era `10.108.9.245`: **cambia en cada sesión**) + IPv6 global.

**RTT desde el módem** (`03`, `AT+CPING`, 4 paquetes, después de `DIALMODE=0`):
4/4 recibidos, mín 39 ms, máx 135 ms, prom. 70 ms. (Antes de `DIALMODE=0`:
4/4, 27–275 ms, prom. ~100 ms.) Con 10 paquetes el comando respondió `ERROR`;
con 4 funciona.

**RTT desde la Pi por el 4G** (`05`, `ping -c 10 8.8.8.8` con ruta temporal por `usb0`):
10/10, 0 % pérdida, mín/prom/máx/mdev = 31,0 / 53,5 / 121,7 / 25,9 ms. El
primer paquete (122 ms) es más lento, consistente con la radio saliendo de
reposo. **Esta es la medición representativa del camino que usará la RSU.**

**Direccionamiento** (`05`):
- IPv4 pública vista desde internet: `179.6.137.254` (NAT del operador; la
  RSU tiene `10.127.43.28` del operador y `192.168.0.100` del NAT del módem).
- IPv6: `curl -6` falla en 6 ms. **Esperado**: en modo normal `usb0` no tiene
  ruta IPv6 por defecto (`ipv6.never-default yes`). La IPv6 global se verificó
  antes del ajuste: `curl --interface usb0 https://ifconfig.me` →
  `2800:4b0:440c:3f68:2089:84ff:fe6a:96ab`.

**Modo de red al momento de la captura** (`04`, `06`): modo normal. IPv4 por
defecto `wlan0` (600), respaldo `usb0` (900); IPv6 sin ruta por defecto por
`usb0`; Tailscale directo por la LAN (`direct 192.168.18.220`).

**Consumo del 4G** desde el reinicio del módem (`06`): RX 45 299 B, TX 66 146 B
(solo pruebas manuales). 2 errores de recepción, insignificantes.

## Pendiente / [REVISAR]

- Las capturas son del modo normal; las del modo campaña (`tailscale ping`
  mostrando camino no-LAN) se toman al ejecutar la campaña 4G.
- Foto del montaje (Pi + módem + antena): pendiente.
- Que la IPv6 global sea alcanzable desde fuera (firewall del operador) no se probó.
- Medición única, en un solo lugar y horario: es referencia, no resultado de la campaña.
