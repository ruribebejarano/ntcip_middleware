#!/usr/bin/env bash
#
# Cambia el broker MQTT al que se conecta el agente de la RSU (se ejecuta EN
# la Raspberry Pi, pide la contraseña de sudo):
#
#   bash scripts/pi_broker.sh nube      broker de Oracle Cloud (campaña 4G)
#   bash scripts/pi_broker.sh laptop    broker de la laptop por Tailscale
#   bash scripts/pi_broker.sh estado    broker configurado y última conexión
#
# Reescribe solo MQTT_BROKER_HOST en el drop-in
# /etc/systemd/system/rsu-agent.service.d/broker.conf (RSU_ID y el drop-in
# tls.conf no cambian), recarga systemd y reinicia rsu-agent. Las dos
# direcciones están en el SAN del certificado del broker (generar_ca.py).

set -euo pipefail

DROPIN="/etc/systemd/system/rsu-agent.service.d/broker.conf"
HOST_NUBE="129.151.104.124"    # máquina virtual de Oracle Cloud, Chile Central
HOST_LAPTOP="100.121.77.97"    # laptop por Tailscale

estado() {
  echo "Broker configurado: $(grep -oP 'MQTT_BROKER_HOST=\K\S+' "$DROPIN" || echo '(sin definir)')"
  journalctl -u rsu-agent.service --no-pager -n 200 -o cat 2>/dev/null \
    | grep -E "Conectado al broker|Desconectado del broker|keepalive" | tail -3 || true
}

cambiar() {
  local host="$1"
  [ -f "$DROPIN" ] || { echo "ERROR: no existe $DROPIN" >&2; exit 1; }
  echo "==> MQTT_BROKER_HOST=$host en $DROPIN"
  sudo sed -i "s/^Environment=MQTT_BROKER_HOST=.*/Environment=MQTT_BROKER_HOST=$host/" "$DROPIN"
  sudo systemctl daemon-reload
  sudo systemctl restart rsu-agent.service
  echo "==> esperando la conexión del agente..."
  sleep 8
  estado
}

case "${1:-}" in
  nube)   cambiar "$HOST_NUBE" ;;
  laptop) cambiar "$HOST_LAPTOP" ;;
  estado) estado ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
