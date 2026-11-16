#!/usr/bin/env bash
#
# Prueba dirigida de RF-11 con los tiempos de un controlador real (manual
# INDRA, ejemplo E06-01: ámbar 3 s, rojo-rojo 1 s, verde mínimo 5 s, verdes
# de plan 50/28/20 s, ciclo de 110 s). Corre en la laptop, condición local,
# con TLS 1.3 + mTLS, cuatro corridas seguidas (desatendidas):
#
#   velocidad 36 y 60 km/h  x  emisión por geocerca (R_g 150 m, ETA 8 s,
#   el criterio de la campaña) o solo por ETA (umbral 16,3 s)
#
# Umbral de ETA: T_act + Δt = (L + T_desp,max + T_m) + Δt
#              = (0,33 + 13 + 2) + 1 ≈ 16,3 s, con L = p95 por 4G (330,9 ms),
#   T_desp,max = (3 + 1) + (5 + 3 + 1) = 13 s (la solicitud llega al empezar
#   el ámbar del propio acceso y luego la fase siguiente cumple verde mínimo,
#   ámbar y rojo-rojo) y Δt = 1 s porque el servidor evalúa el ETA una vez
#   por MP (1 Hz).
#
# Uso (Git Bash, raíz del repo; broker TLS de la laptop en 8883 corriendo):
#   bash scripts/campanas/prueba_rf11_indra.sh            # 12 repeticiones por corrida
#   REPS=2 bash scripts/campanas/prueba_rf11_indra.sh     # prueba corta
#
# Procedimiento completo y análisis: docs/PRUEBA_RF11_TIEMPOS_REALES.md

set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${PY:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python3
REPS="${REPS:-12}"
ETA_SOLO="${ETA_SOLO:-16.3}"
BROKER_PORT="${BROKER_PORT:-8883}"
# Alias SSH de la Pi para la verificación de choque de client_id. Con un
# broker propio en otro puerto (BROKER_PORT=8884) no hay choque posible y se
# puede pasar HOST_RSU=ninguno para saltar la consulta a la Pi.
HOST_RSU="${HOST_RSU:-rsu}"

correr() {  # velocidad r_g eta etiqueta
  "$PY" scripts/campanas/lazo_centralizado.py --escenario lazo --config local \
    --broker-host 127.0.0.1 --broker-port "$BROKER_PORT" --tls deploy/pki \
    --controlador-indra --velocidad-kmh "$1" --r-g "$2" --eta-emision "$3" \
    --repeticiones "$REPS" --pausa-max 110 --etiqueta "$4" --host-rsu "$HOST_RSU"
}

correr 36 150 8 rf11_indra_v36_geocerca
correr 60 150 8 rf11_indra_v60_geocerca
correr 36 0 "$ETA_SOLO" rf11_indra_v36_eta
correr 60 0 "$ETA_SOLO" rf11_indra_v60_eta

echo
echo "Listo. Corridas en resultados/campana/*_lazo_local_rf11_indra_*"
