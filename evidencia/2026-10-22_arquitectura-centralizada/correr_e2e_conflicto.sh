#!/usr/bin/env bash
# Prueba de punta a punta local, escenario de CONFLICTO (fase 3.8): dos
# misiones (OBU emuladas) que llegan al mismo cruce sintetico por accesos
# incompatibles (grupos semaforicos distintos); debe arbitrar el servidor
# (servidor/conflictos.py) -- gana la mision B (clase 1).
set -u
cd "$(dirname "$0")/../.." || exit 1
RAIZ="$(pwd)"
EV="evidencia/2026-10-22_arquitectura-centralizada"
PY="$RAIZ/.venv/Scripts/python.exe"

mkdir -p "$EV"
rm -f "$EV"/*conflicto*.txt

echo "=== Lanzando controlador emulado (9003) ==="
"$PY" -u controller/controller_emulator.py --port 9003 > "$EV/controller_conflicto.txt" 2>&1 &
PID_C=$!
sleep 1

echo "=== Lanzando RSU X-RSU ==="
RSU_ID=X-RSU CONTROLLER_PORT=9003 SNMP_PORT=1173 "$PY" -u agent/rsu_middleware.py > "$EV/rsu_conflicto.txt" 2>&1 &
PID_R=$!
sleep 1

echo "=== Lanzando servidor central (grafo sintetico de cruce) ==="
GRAFO_SINTETICO=cruce REGISTRO_RSU_PATH="$EV/registro_rsu_e2e_conflicto.json" "$PY" -u servidor/main.py > "$EV/servidor_conflicto.txt" 2>&1 &
PID_S=$!
sleep 1.5

echo "=== Lanzando OBU-A (S->N, clase 2) y OBU-B (O->E, clase 1) casi simultaneas ==="
# Misma clase (1, la unica reconocida por RF-05 en este banco de pruebas,
# ver agent/ntcip1211.py CLASES_EMERGENCIA_RECONOCIDAS): el arbitraje de
# servidor/conflictos.py desempata por ETA (gana la que llega antes), no
# por clase -- ver evidencia/2026-10-22_arquitectura-centralizada/NOTAS.md.
"$PY" -u gateway/obu_emulada.py --broker-host 127.0.0.1 \
    --trayectoria "$EV/trayectoria_cruce_a_e2e.csv" --factor 8 --obu-id obu-e2e-a --clase-tipo 1 \
    > "$EV/obu_a_conflicto.txt" 2>&1 &
PID_OA=$!
sleep 0.2
"$PY" -u gateway/obu_emulada.py --broker-host 127.0.0.1 \
    --trayectoria "$EV/trayectoria_cruce_b_e2e.csv" --factor 8 --obu-id obu-e2e-b --clase-tipo 1 \
    > "$EV/obu_b_conflicto.txt" 2>&1 &
PID_OB=$!

wait $PID_OA $PID_OB
echo "=== Las dos OBU terminaron, esperando 3 s ==="
sleep 3

echo "=== Deteniendo procesos ==="
kill $PID_S $PID_R $PID_C 2>/dev/null
sleep 1
echo "=== Fin ==="
