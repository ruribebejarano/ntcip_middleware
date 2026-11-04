#!/usr/bin/env bash
#
# Se ejecuta en la Pi, sin SSH abierto: registra los contadores de una interfaz cada
# 10 s, fase por fase, para que la medición no incluya tráfico de control.
# Lo copia y lanza scripts/consumo/experimento.py.
#
# Uso: registrar_en_pi.sh <t0_epoch> <interfaz> <dir> <limite_mb> <detener_agente 0|1> <margen_s> <fase:seg> ...
# Fase "fondo" y "obu": agente detenido si detener_agente=1. Fase "obu": la Pi corre la OBU emulada.

set -u

T0="$1"; IFACE="$2"; DIR="$3"; LIMITE_MB="$4"; DETENER="$5"; MARGEN="$6"; shift 6
CSV="$DIR/contadores.csv"
STATS="/sys/class/net/$IFACE/statistics"
REPO="$HOME/ntcip_middleware"

agente() {
  [ "$DETENER" = "1" ] || return 0
  sudo -n systemctl "$1" rsu-agent.service
}

OBU_PID=""
terminar() {
  [ -n "$OBU_PID" ] && pkill -P "$OBU_PID" 2>/dev/null
  agente start
}
trap terminar EXIT
trap 'echo "interrumpido" >> "$DIR/estado.txt"; exit 1' INT TERM

correr_obu() {
  # $1 = fin de la fase (epoch); no empieza una misión que no alcance a terminar.
  local fin="$1" tray filas
  sleep "$MARGEN"
  for tray in "$DIR"/tray_*.csv; do
    filas="$(wc -l < "$tray")"
    [ $(( $(date +%s) + filas + 15 )) -lt "$fin" ] || break
    ( cd "$REPO" && RSU_EVENTOS_DIR="$DIR/obu" PYTHONUNBUFFERED=1 "$HOME/rsu-env/bin/python" gateway/obu_emulada.py \
        --broker-host "$(cat "$DIR/broker_host.txt")" --broker-port 8883 --obu-id obu-pi-consumo \
        --trayectoria "$tray" --tls-ca "$DIR/ca.crt" --tls-cert "$DIR/obu.crt" --tls-key "$DIR/obu.key" ) >> "$DIR/obu.log" 2>&1
    sleep $(( RANDOM % 25 ))
  done
}

leer() { echo "$(cat "$STATS/rx_bytes") $(cat "$STATS/tx_bytes")"; }

echo "ts,fase,rx_bytes,tx_bytes" > "$CSV"
mkdir -p "$DIR/obu"
while [ "$(date +%s)" -lt "$T0" ]; do sleep 1; done

read -r RX0 TX0 <<<"$(leer)"
INICIO=$T0
for plan in "$@"; do
  FASE="${plan%%:*}"; SEG="${plan##*:}"
  FIN=$(( INICIO + SEG ))
  case "$FASE" in
    fondo|obu) agente stop ;;
    *) agente start ;;
  esac
  if [ "$FASE" = "obu" ]; then
    correr_obu "$FIN" &
    OBU_PID=$!
  fi
  while [ "$(date +%s)" -lt "$FIN" ]; do
    read -r RX TX <<<"$(leer)"
    echo "$(date +%s.%N),$FASE,$RX,$TX" >> "$CSV"
    if [ $(( (RX - RX0 + TX - TX0) / 1000000 )) -ge "$LIMITE_MB" ]; then
      echo "abortado: se alcanzo el limite de $LIMITE_MB MB" >> "$DIR/estado.txt"
      exit 2
    fi
    sleep 10
  done
  read -r RX TX <<<"$(leer)"
  echo "$(date +%s.%N),$FASE,$RX,$TX" >> "$CSV"
  if [ -n "$OBU_PID" ]; then
    wait "$OBU_PID"
    OBU_PID=""
  fi
  INICIO=$FIN
done
echo "completo" >> "$DIR/estado.txt"
