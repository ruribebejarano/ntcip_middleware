#!/usr/bin/env bash
#
# Segunda parte de la campaña nocturna: repite la referencia local a 1 Hz
# cuando termina noche_pi4g.sh. Se ejecuta en la LAPTOP, desde Git Bash.
#
#   lazo y desvío con TLS 1.3 + mTLS (8883), lazo sin TLS (1883, servicio de
#   Windows): este último par da el costo de TLS a 1 Hz.
#
# Detiene rsu-agent en la Pi mientras corre (mismo client_id que el agente
# local, ver _verificar_sin_agente_local_huerfano en lazo_centralizado.py) y
# lo vuelve a iniciar al terminar. No cambia el modo de red de la Pi.
#
# Uso:
#   scripts/campanas/noche_local.sh --esperar-log <log de noche_pi4g> [--tope N]

set -uo pipefail

LOG_4G=""
TOPE=18
HOST="rsu"
while [ $# -gt 0 ]; do
  case "$1" in
    --esperar-log) LOG_4G="$2"; shift 2 ;;
    --tope) TOPE="$2"; shift 2 ;;
    *) echo "Argumento desconocido: $1" >&2; exit 1 ;;
  esac
done

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

mkdir -p resultados/campana/_noche
LOG="resultados/campana/_noche/local_$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

paso() { echo; echo "=== [$(date +%H:%M:%S)] $* ==="; }

if [ -n "$LOG_4G" ]; then
  paso "Esperando a que termine la campaña 4G ($LOG_4G)"
  # "Log: " es la última línea de noche_pi4g.sh; "*** FALLA" su salida por error.
  until grep -qE '^Log: |^\*\*\* FALLA' "$LOG_4G" 2>/dev/null; do sleep 60; done
  echo "Campaña 4G terminada."
fi

paso "Deteniendo rsu-agent en la Pi"
scripts/pi.sh stop agent "$HOST" || echo "*** no se pudo detener el agente; el runner lo verificará"

correr() {
  # $1 escenario, $2 sufijo de carpeta, resto: argumentos de broker/TLS.
  local escenario="$1" sufijo="$2" dir nuevo; shift 2
  paso "Corrida local: $escenario $sufijo"
  "$PY" scripts/campanas/lazo_centralizado.py --escenario "$escenario" --config local \
    --factor 1 --tope-repeticiones "$TOPE" "$@"
  dir="$(ls -dt resultados/campana/*_"${escenario}"_local 2>/dev/null | head -1)"
  if [ -n "$dir" ] && [ -f "$dir/config.json" ] && grep -q '"fecha_fin"' "$dir/config.json"; then
    nuevo="${dir}_${sufijo}"
    mv "$dir" "$nuevo"
    "$PY" scripts/analisis/lazo_centralizado.py --dir "$nuevo" > "$nuevo/analisis.txt" 2>&1 \
      && echo "Análisis: $nuevo/analisis.txt" || echo "(falló el análisis de $nuevo)"
    "$PY" scripts/analisis/frecuencia_actualizacion.py --dir "$nuevo"
  else
    echo "*** La corrida $escenario $sufijo no terminó."
  fi
}

TLS=(--broker-host localhost --broker-port 8883 --tls deploy/pki)
correr lazo 1hz_con-tls "${TLS[@]}"
correr desvio 1hz_con-tls "${TLS[@]}"
correr lazo 1hz_sin-tls --broker-host 127.0.0.1 --broker-port 1883

paso "Volviendo a iniciar rsu-agent en la Pi"
scripts/pi.sh start agent "$HOST" || echo "*** no se pudo iniciar el agente"
scripts/pi.sh status agent "$HOST" | head -4

paso "Fin de las corridas locales"
echo "Log: $LOG"
