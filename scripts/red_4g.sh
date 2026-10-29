#!/usr/bin/env bash
#
# Modo de red de la RSU (módem 4G SIM7670G + Wi-Fi). Se ejecuta EN la
# Raspberry Pi -- la laptop lo invoca por SSH con "scripts/pi.sh red
# <subcomando> [host]" (ver docs/MODEM_4G.md, sección 4).
#
# Uso:
#   scripts/red_4g.sh modo-normal   [--perfil <perfil>]
#   scripts/red_4g.sh modo-campana  [--perfil <perfil>] [--sin-wifi]
#   scripts/red_4g.sh estado        [--perfil <perfil>] [--puerto-at <puerto>]
#   scripts/red_4g.sh evidencia     [--destino <dir>]
#
# --perfil:    nombre del perfil de NetworkManager asociado a usb0 (el
#              módem 4G). Default: "netplan-eth0" (nombre heredado de
#              netplan, ver docs/MODEM_4G.md sección 1 -- no es una interfaz
#              Ethernet real).
# --puerto-at: puerto serie de comandos AT del módem. Default: /dev/ttyACM2.
#
# modo-normal:   Wi-Fi para todo (ruta por defecto), 4G de respaldo
#                (ipv4.route-metric 900) y SIN ruta IPv6 por defecto por el
#                4G (ipv6.never-default yes), para no gastar saldo con
#                tráfico IPv6 fuera de las pruebas.
# modo-campana:  4G como ruta principal (ipv4.route-metric 50). NO apaga el
#                Wi-Fi por sí solo: con --sin-wifi, primero verifica que
#                Tailscale esté conectado (si no, aborta sin tocar el Wi-Fi)
#                y avisa que el acceso quedará solo por Tailscale.
# estado:        modo detectado, rutas IPv4/IPv6, Tailscale, contadores de
#                usb0 y (si se puede) señal del módem por el puerto AT, sin
#                dejar ModemManager tomado el puerto al terminar.
# evidencia:     guarda en ~/evidencia_4g/red_<fecha>.txt el mismo bloque de
#                comandos usado en la puesta en marcha del 2026-10-28 (ver
#                evidencia/2026-10-28_modem-4g/red_2026-10-28_1838.txt).

set -euo pipefail

PERFIL_DEFAULT="netplan-eth0"
PUERTO_AT_DEFAULT="/dev/ttyACM2"
DESTINO_DEFAULT="$HOME/evidencia_4g"

usage() {
  sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

modo_normal() {
  local perfil="$1"
  echo "==> modo normal: '$perfil' metrica 900 (respaldo), sin ruta IPv6 por defecto, Wi-Fi encendido"
  sudo nmcli connection modify "$perfil" ipv4.route-metric 900 ipv6.never-default yes
  sudo nmcli radio wifi on
  sudo nmcli connection up "$perfil"
}

modo_campana() {
  local perfil="$1" sin_wifi="$2"
  echo "==> modo campaña: '$perfil' metrica 50 (ruta principal por 4G)"
  sudo nmcli connection modify "$perfil" ipv4.route-metric 50
  sudo nmcli connection up "$perfil"
  if [ "$sin_wifi" = "1" ]; then
    echo "==> verificando Tailscale antes de apagar el Wi-Fi..."
    if ! tailscale ip -4 >/dev/null 2>&1; then
      echo "ERROR: Tailscale no está conectado (falló 'tailscale ip -4')." >&2
      echo "       NO se apaga el Wi-Fi: se perdería el acceso a esta RSU." >&2
      exit 1
    fi
    echo "AVISO: a partir de aquí el acceso a esta RSU será SOLO por Tailscale ($(tailscale ip -4))."
    sudo nmcli radio wifi off
  else
    echo "Wi-Fi sin cambios (usar --sin-wifi para apagarlo, tras verificar Tailscale)."
  fi
}

consultar_at() {
  # Consulta best-effort por el puerto AT, sin dejar ModemManager tomado el
  # puerto al salir: si estaba activo, se detiene antes de abrir el puerto y
  # se reinicia al terminar (incluso si la consulta falla).
  #
  # NOTA: se restaura ModemManager explícitamente en CADA punto de salida
  # (no con `trap ... RETURN`): ese trap dispara despues de que bash ya
  # destruyo el scope de las variables `local` de esta funcion, asi que
  # referenciar $mm_activo ahi da "unbound variable" bajo `set -u` --
  # pasó de verdad en la campaña pi-lan del 2026-10-28.
  local puerto="$1"; shift
  if [ ! -e "$puerto" ]; then
    echo "(puerto $puerto no existe)"
    return 0
  fi
  local mm_activo=0
  if systemctl is-active --quiet ModemManager 2>/dev/null; then
    mm_activo=1
    sudo systemctl stop ModemManager
    sleep 0.3
  fi
  if ! stty -F "$puerto" 115200 raw -echo 2>/dev/null; then
    echo "(no se pudo configurar $puerto)"
    [ "$mm_activo" = "1" ] && sudo systemctl start ModemManager
    return 0
  fi
  ( for c in "$@"; do printf '%s\r' "$c" > "$puerto"; sleep 0.3; done ) &
  timeout 2 cat "$puerto" 2>/dev/null || true
  wait 2>/dev/null || true
  if [ "$mm_activo" = "1" ]; then
    sudo systemctl start ModemManager
  fi
}

estado() {
  local perfil="$1" puerto_at="$2"
  echo "=== Modo detectado ==="
  local wifi_txt="apagado"
  nmcli radio wifi 2>/dev/null | grep -qi "^enabled" && wifi_txt="encendido"
  local metrica_usb0
  metrica_usb0="$(ip route show dev usb0 default 2>/dev/null | grep -oP 'metric \K[0-9]+' | head -1)"
  [ -z "$metrica_usb0" ] && metrica_usb0="sin ruta por defecto"
  echo "Wi-Fi: $wifi_txt | perfil 4G: $perfil | metrica ruta por defecto de usb0: $metrica_usb0"
  echo
  echo "=== ip route ==="
  ip route
  echo
  echo "=== ip -6 route (default) ==="
  ip -6 route | grep default || echo "(sin ruta IPv6 por defecto)"
  echo
  echo "=== tailscale status ==="
  tailscale status || echo "(tailscale no respondió)"
  echo
  echo "=== contadores usb0 ==="
  ip -s link show usb0 || echo "(usb0 no existe)"
  echo
  echo "=== módem ($puerto_at) ==="
  consultar_at "$puerto_at" "AT+CSQ" "AT+CPSI?"
}

evidencia() {
  local destino_dir="$1"
  mkdir -p "$destino_dir"
  local archivo="$destino_dir/red_$(date +%Y-%m-%d_%H%M).txt"
  {
    date
    echo
    ip -br addr show usb0
    echo
    ip route
    echo
    ip -6 route
    echo
    ping -c 10 8.8.8.8 || true
    echo
    curl -s ifconfig.me; echo
    echo
    tailscale status || true
    echo
    ip -s link show usb0
  } > "$archivo"
  echo "Guardado: $archivo"
}

cmd="${1:-}"
[ -z "$cmd" ] && usage
shift

perfil="$PERFIL_DEFAULT"
puerto_at="$PUERTO_AT_DEFAULT"
sin_wifi=0
destino="$DESTINO_DEFAULT"

while [ $# -gt 0 ]; do
  case "$1" in
    --perfil) perfil="$2"; shift 2 ;;
    --puerto-at) puerto_at="$2"; shift 2 ;;
    --sin-wifi) sin_wifi=1; shift ;;
    --destino) destino="$2"; shift 2 ;;
    *) echo "Argumento desconocido: $1" >&2; exit 1 ;;
  esac
done

case "$cmd" in
  modo-normal)  modo_normal "$perfil" ;;
  modo-campana) modo_campana "$perfil" "$sin_wifi" ;;
  estado)       estado "$perfil" "$puerto_at" ;;
  evidencia)    evidencia "$destino" ;;
  *) usage ;;
esac
