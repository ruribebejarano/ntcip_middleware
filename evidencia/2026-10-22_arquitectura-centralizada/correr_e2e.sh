#!/usr/bin/env bash
# Orquesta la prueba de punta a punta local (fase 3.8): broker local
# (servicio Mosquitto ya corriendo en 127.0.0.1:1883, sin TLS en esta
# etapa) + 2x controller_emulator.py + 2x agent/rsu_middleware.py +
# servidor/main.py (grafo sintetico) + gateway/obu_emulada.py.
set -u
cd "$(dirname "$0")/../.." || exit 1
RAIZ="$(pwd)"
EV="evidencia/2026-10-22_arquitectura-centralizada"
PY="$RAIZ/.venv/Scripts/python.exe"

mkdir -p "$EV"
rm -f "$EV"/*.txt

echo "=== Lanzando controladores emulados (9001, 9002) ==="
"$PY" -u controller/controller_emulator.py --port 9001 > "$EV/controller_sint1.txt" 2>&1 &
PID_C1=$!
"$PY" -u controller/controller_emulator.py --port 9002 > "$EV/controller_sint2.txt" 2>&1 &
PID_C2=$!
sleep 1

echo "=== Lanzando RSU SINT-1 y SINT-2 ==="
RSU_ID=SINT-1 CONTROLLER_PORT=9001 SNMP_PORT=1171 "$PY" -u agent/rsu_middleware.py > "$EV/rsu_sint1.txt" 2>&1 &
PID_R1=$!
RSU_ID=SINT-2 CONTROLLER_PORT=9002 SNMP_PORT=1172 "$PY" -u agent/rsu_middleware.py > "$EV/rsu_sint2.txt" 2>&1 &
PID_R2=$!
sleep 1

echo "=== Lanzando servidor central (grafo sintetico) ==="
GRAFO_SINTETICO=1 REGISTRO_RSU_PATH="$EV/registro_rsu_e2e.json" "$PY" -u servidor/main.py > "$EV/servidor.txt" 2>&1 &
PID_S=$!
sleep 1.5

echo "=== Lanzando OBU emulada (recorrido recto A->G, factor 8) ==="
"$PY" -u gateway/obu_emulada.py --broker-host 127.0.0.1 \
    --trayectoria "$EV/trayectoria_recta_e2e.csv" --factor 8 --obu-id obu-e2e-1 \
    > "$EV/obu.txt" 2>&1
echo "=== OBU terminada, esperando 3 s para que drenen los ultimos mensajes ==="
sleep 3

echo "=== Deteniendo procesos ==="
kill $PID_S $PID_R1 $PID_R2 $PID_C1 $PID_C2 2>/dev/null
sleep 1
echo "=== Fin ==="
