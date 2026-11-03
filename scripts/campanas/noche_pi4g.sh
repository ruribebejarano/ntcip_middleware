#!/usr/bin/env bash
#
# Campaña pi-4g desatendida (lazo + desvío) con TLS 1.3 + mTLS, pensada
# para dejarla corriendo de noche. Se ejecuta en la LAPTOP, desde Git Bash,
# en la raíz del repo. NO cambia el modo de red de la Pi ni instala nada:
# eso requiere sudo con contraseña y se hace antes, a mano (ver
# deploy/systemd/rsu-agent-tls.conf y scripts/pi.sh red modo-campana).
#
# Uso:
#   scripts/campanas/noche_pi4g.sh [--solo-verificar] [--tope N] [--limite-mb M] [--host rsu]
#
#   --solo-verificar  corre solo las comprobaciones previas y sale.
#   --tope N          --tope-repeticiones de cada corrida (default 18).
#   --limite-mb M     si tras la corrida de lazo el consumo de usb0 ya supera
#                     M/2 MB, no se corre la de desvío (protege el saldo).
#
# Qué hace, en orden:
#   1. Comprobaciones: broker TLS de la laptop escuchando en 8883, Pi
#      alcanzable, servicios activos, agente configurado para 8883, ruta por
#      defecto de la Pi por usb0 (4G), camino Tailscale que no sea la LAN.
#   2. Espera a que chrony esté sincronizado en la Pi (hasta 60 min).
#   3. Contadores de usb0 al inicio (consumo total de la noche).
#   4. Corrida lazo, consumo; corrida desvío (salvo --limite-mb), consumo.
#      Si una corrida aborta al empezar (p. ej. chrony), espera y la
#      reintenta una vez.
#   5. Evidencia de red en la Pi, contadores de usb0 al final, análisis de
#      cada corrida y resumen de consumo.
# Todo queda en resultados/campana/_noche/<fecha>.log.

set -uo pipefail

HOST="rsu"
TOPE=18
LIMITE_MB=""
SOLO_VERIFICAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --tope) TOPE="$2"; shift 2 ;;
    --limite-mb) LIMITE_MB="$2"; shift 2 ;;
    --solo-verificar) SOLO_VERIFICAR=1; shift ;;
    *) echo "Argumento desconocido: $1" >&2; exit 1 ;;
  esac
done

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"
PKI="deploy/pki"
BROKER_HOST="laptopricardoub"
BROKER_PORT=8883

mkdir -p resultados/campana/_noche
LOG="resultados/campana/_noche/$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

paso() { echo; echo "=== [$(date +%H:%M:%S)] $* ==="; }
falla() { echo "*** FALLA: $*"; exit 1; }

bytes_usb0() {
  # rx+tx de usb0 en la Pi, sin sudo (sysfs).
  ssh -o ConnectTimeout=15 "$HOST" \
    "echo \$((\$(cat /sys/class/net/usb0/statistics/rx_bytes) + \$(cat /sys/class/net/usb0/statistics/tx_bytes)))" 2>/dev/null
}

mb() { awk -v b="$1" 'BEGIN { printf "%.2f", b / 1000000 }'; }

chrony_ok() {
  local t
  t="$(ssh -o ConnectTimeout=15 "$HOST" "chronyc tracking" 2>/dev/null)" || return 1
  ! grep -qE "Leap status\s*:\s*Not synchronised|Stratum\s*:\s*0\b" <<<"$t"
}

# ---------------------------------------------------------------------------
paso "1. Comprobaciones previas (host $HOST)"

netstat -an 2>/dev/null | grep -qE "[:.]${BROKER_PORT}[[:space:]].*LISTEN" \
  || falla "no hay nada escuchando en el puerto ${BROKER_PORT} de la laptop. Arrancar en PowerShell:
  & \"C:\\Program Files (x86)\\Mosquitto\\mosquitto.exe\" -c deploy\\pki\\mosquitto_laptop_tls.conf -v"
echo "OK broker TLS escuchando en ${BROKER_PORT}"

ssh -o ConnectTimeout=15 -o BatchMode=yes "$HOST" true || falla "no se llega a la Pi por SSH ($HOST)"
echo "OK SSH a $HOST"

activos="$(ssh "$HOST" "systemctl is-active rsu-agent rsu-controller" | tr '\n' ' ')"
[ "$activos" = "active active " ] || falla "servicios de la Pi no activos: $activos (scripts/pi.sh start controller / start agent)"
echo "OK rsu-agent y rsu-controller activos"

entorno="$(ssh "$HOST" "systemctl show rsu-agent -p Environment")"
grep -q "MQTT_BROKER_PORT=8883" <<<"$entorno" \
  || falla "el agente de la Pi no está configurado para TLS (falta deploy/systemd/rsu-agent-tls.conf en rsu-agent.service.d). Entorno: $entorno"
grep -q "RSU_TLS_CERT=" <<<"$entorno" || falla "el agente no tiene RSU_TLS_CERT. Entorno: $entorno"
echo "OK agente con MQTT_BROKER_PORT=8883 y certificado"

ruta="$(ssh "$HOST" "ip route show default" | sort -t' ' -k1,1 | awk '{for(i=1;i<=NF;i++){if($i=="dev")d=$(i+1);if($i=="metric")m=$(i+1)}; print m, d}' | sort -n | head -1)"
grep -q "usb0" <<<"$ruta" || falla "la ruta por defecto de la Pi no es usb0 (métrica, interfaz: $ruta). Pasar a 4G: scripts/pi.sh red modo-campana $HOST"
echo "OK ruta por defecto de la Pi por usb0 ($ruta)"

camino="$(ssh "$HOST" "tailscale ping --c 1 $BROKER_HOST" 2>&1 | tail -1)"
echo "Camino Tailscale Pi -> laptop: $camino"
grep -q "via 192\.168\." <<<"$camino" && falla "Tailscale sigue yendo por la LAN ($camino): no sería una medición 4G"

base0="$(bytes_usb0)"
[ -n "$base0" ] || falla "no se pudieron leer los contadores de usb0 en la Pi"
echo "OK contadores de usb0 legibles ($(mb "$base0") MB acumulados desde que se levantó la interfaz)"

if [ "$SOLO_VERIFICAR" = "1" ]; then
  paso "Solo verificación: todo listo"
  exit 0
fi

# ---------------------------------------------------------------------------
paso "2. Esperando sincronización NTP de la Pi (máx. 60 min)"
for i in $(seq 1 60); do
  chrony_ok && { echo "OK chrony sincronizado"; break; }
  [ "$i" = "60" ] && falla "chrony no se sincronizó en 60 min"
  echo "chrony sin sincronizar, reintento en 60 s ($i/60)"
  sleep 60
done

inicio_noche="$(bytes_usb0)"

correr() {
  # $1 = escenario. Imprime la carpeta de la corrida en la última línea.
  local escenario="$1" intento salida dir
  for intento in 1 2; do
    paso "Corrida $escenario (intento $intento)"
    "$PY" scripts/campanas/lazo_centralizado.py --escenario "$escenario" \
      --config pi-4g --broker-host "$BROKER_HOST" --broker-port "$BROKER_PORT" \
      --tls "$PKI" --host-rsu "$HOST" --factor 1 --tope-repeticiones "$TOPE"
    dir="$(ls -dt resultados/campana/*_"${escenario}"_pi-4g 2>/dev/null | head -1)"
    if [ -n "$dir" ] && [ -f "$dir/config.json" ] && grep -q '"fecha_fin"' "$dir/config.json"; then
      CORRIDAS+=("$dir")
      "$PY" scripts/analisis/consumo_datos.py --dir "$dir"
      return 0
    fi
    echo "La corrida $escenario no terminó; espero 15 min a chrony y reintento."
    for _ in $(seq 1 15); do chrony_ok && break; sleep 60; done
  done
  echo "*** La corrida $escenario falló dos veces; se sigue con lo que haya."
  return 1
}

CORRIDAS=()
paso "3. Corridas (tope $TOPE repeticiones cada una)"
correr lazo

seguir=1
if [ -n "$LIMITE_MB" ]; then
  usado="$(( $(bytes_usb0) - inicio_noche ))"
  if awk -v u="$usado" -v l="$LIMITE_MB" 'BEGIN { exit !(u / 1000000 > l / 2) }'; then
    echo "Consumo tras lazo: $(mb "$usado") MB > mitad del límite ($LIMITE_MB MB): NO se corre desvío."
    seguir=0
  fi
fi
[ "$seguir" = "1" ] && correr desvio

# ---------------------------------------------------------------------------
paso "4. Evidencia y cierre"
ssh "$HOST" "cd ~/ntcip_middleware && bash scripts/red_4g.sh evidencia" || echo "(no se pudo guardar la evidencia de red)"
fin_noche="$(bytes_usb0)"

for d in "${CORRIDAS[@]}"; do
  "$PY" scripts/analisis/lazo_centralizado.py --dir "$d" > "$d/analisis.txt" 2>&1 \
    && echo "Análisis: $d/analisis.txt" || echo "(falló el análisis de $d, ver $d/analisis.txt)"
done

paso "Resumen"
echo "Corridas completas: ${#CORRIDAS[@]} -> ${CORRIDAS[*]:-ninguna}"
[ ${#CORRIDAS[@]} -gt 0 ] && "$PY" scripts/analisis/consumo_datos.py $(printf -- '--dir %s ' "${CORRIDAS[@]}")
if [ -n "$inicio_noche" ] && [ -n "$fin_noche" ] && [ "$fin_noche" -ge "$inicio_noche" ]; then
  echo "Consumo total de usb0 en la noche (incluye esperas y cierre): $(mb $((fin_noche - inicio_noche))) MB"
else
  echo "Consumo total de la noche: no calculable (contador reiniciado o Pi inalcanzable al final)"
fi
echo "La Pi queda en modo 4G: al volver, 'scripts/pi.sh red modo-normal $HOST'."
echo "Log: $LOG"
