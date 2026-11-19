#!/usr/bin/env bash
#
# Prueba de colas (docs/PRUEBA_COLA.md): el vehículo de emergencia queda en
# una cola de 280 m antes de la RSU y avanza por pulsos (20 s detenido,
# 8 s a 15 km/h) hasta la línea de detención; desde ahí sigue a 36 km/h.
# Controlador emulado con los tiempos del manual INDRA, condición local,
# TLS 1.3 + mTLS, con un broker PROPIO en 127.0.0.1:8884 (no choca con el
# broker de la laptop ni con el agente de la Raspberry Pi).
#
# Tres criterios de emisión:
#   cola_geocerca_eta8    R_g 150 m o ETA 8 s      (el de la campaña)
#   cola_geocerca_eta16   R_g 150 m o ETA 16,3 s   (umbral INDRA)
#   cola_eta16            solo ETA 16,3 s          (R_g = 0)
#
# Uso (Git Bash, raíz del repo):
#   bash scripts/campanas/prueba_cola.sh               # 3 repeticiones por criterio
#   REPS=1 COLA_LARGO=120 bash scripts/campanas/prueba_cola.sh   # prueba corta
#
# Análisis: python scripts/analisis/cola_resumen.py

set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${PY:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python3
REPS="${REPS:-3}"
PERFIL="${PERFIL:-20,8,15}"
COLA_LARGO="${COLA_LARGO:-280}"
PUERTO="${PUERTO:-8884}"
SOLO="${SOLO:-}"   # p. ej. SOLO=cola_eta16 para correr un solo criterio
# Suspensión por vehículo detenido del servidor (vacío = desactivada, el
# valor por defecto; 5 = la regla de la campaña).
T_DETENIDO="${T_DETENIDO:-}"
SUFIJO="${SUFIJO:-}"   # se agrega a la etiqueta de cada corrida
MOSQ="${MOSQ:-/c/Program Files (x86)/Mosquitto/mosquitto.exe}"

conf="$(mktemp -d)/mosquitto_cola.conf"
sed -e "s/^listener 8883 /listener $PUERTO /" -e 's/^log_dest stdout/log_dest none/' \
  deploy/pki/mosquitto_laptop_tls.conf > "$conf"
"$MOSQ" -c "$conf" &
MOSQ_PID=$!
trap 'kill $MOSQ_PID 2>/dev/null || true' EXIT
sleep 1

correr() {  # r_g eta etiqueta
  if [ -n "$SOLO" ] && [ "$SOLO" != "$3" ]; then return; fi
  SERVIDOR_T_DETENIDO_MAX_S="$T_DETENIDO" "$PY" scripts/campanas/lazo_centralizado.py --escenario lazo --config local \
    --broker-host 127.0.0.1 --broker-port "$PUERTO" --tls deploy/pki \
    --controlador-indra --cola "$PERFIL" --cola-largo-m "$COLA_LARGO" \
    --r-g "$1" --eta-emision "$2" \
    --repeticiones "$REPS" --pausa-max 60 --etiqueta "$3$SUFIJO" --host-rsu ninguno
}

correr 150 8 cola_geocerca_eta8
correr 150 16.3 cola_geocerca_eta16
correr 0 16.3 cola_eta16

echo
echo "Listo. Corridas en resultados/campana/*_lazo_local_cola_*"
