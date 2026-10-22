#!/usr/bin/env bash
# Prueba de punta a punta local, escenario de DESVIO (fase 3.8): la OBU se
# aparta de la ruta calculada (~100 m al este, supera UMBRAL_DESVIO_M=60 m
# de servidor/gestor_mision.py) y vuelve; el servidor debe detectarlo y
# recalcular (servidor/rutas.py::planificar_ruta de nuevo).
set -u
cd "$(dirname "$0")/../.." || exit 1
RAIZ="$(pwd)"
EV="evidencia/2026-10-22_arquitectura-centralizada"
PY="$RAIZ/.venv/Scripts/python.exe"

mkdir -p "$EV"
rm -f "$EV"/*desvio*.txt

echo "=== Lanzando controladores emulados (9004, 9005) ==="
"$PY" -u controller/controller_emulator.py --port 9004 > "$EV/controller_desvio_sint1.txt" 2>&1 &
PID_C1=$!
"$PY" -u controller/controller_emulator.py --port 9005 > "$EV/controller_desvio_sint2.txt" 2>&1 &
PID_C2=$!
sleep 1

echo "=== Lanzando RSU SINT-1 y SINT-2 ==="
RSU_ID=SINT-1 CONTROLLER_PORT=9004 SNMP_PORT=1174 "$PY" -u agent/rsu_middleware.py > "$EV/rsu_desvio_sint1.txt" 2>&1 &
PID_R1=$!
RSU_ID=SINT-2 CONTROLLER_PORT=9005 SNMP_PORT=1175 "$PY" -u agent/rsu_middleware.py > "$EV/rsu_desvio_sint2.txt" 2>&1 &
PID_R2=$!
sleep 1

echo "=== Lanzando servidor central (grafo sintetico recto) ==="
GRAFO_SINTETICO=recta REGISTRO_RSU_PATH="$EV/registro_rsu_e2e.json" "$PY" -u servidor/main.py > "$EV/servidor_desvio.txt" 2>&1 &
PID_S=$!
sleep 1.5

echo "=== Lanzando OBU emulada (con excursion este en paso_m=300,320,340) ==="
"$PY" -u gateway/obu_emulada.py --broker-host 127.0.0.1 \
    --trayectoria "$EV/trayectoria_desvio_e2e.csv" --factor 8 --obu-id obu-e2e-desvio \
    > "$EV/obu_desvio.txt" 2>&1
sleep 3

echo "=== Deteniendo procesos ==="
kill $PID_S $PID_R1 $PID_R2 $PID_C1 $PID_C2 2>/dev/null
sleep 1
echo "=== Fin ==="
