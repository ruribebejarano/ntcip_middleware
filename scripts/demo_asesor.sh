#!/usr/bin/env bash
#
# Demo guiada del banco de pruebas para mostrarla en vivo al asesor.
# Cada paso: encabezado grande (número, título, requerimiento RF/RNF de
# main.tex), el comando real contra la Pi (alias SSH "rsu"), una línea de
# qué observar, y una pausa "Enter para continuar" (salvo con --sin-pausas).
# La salida de cada paso se guarda también en evidencia/demo_AAAA-MM-DD/.
#
# Uso:
#   bash scripts/demo_asesor.sh              (con pausas, para el ensayo/la reunión)
#   bash scripts/demo_asesor.sh --sin-pausas  (de corrido, para probar el script)
#
# Requiere: alias SSH "rsu" (ver scripts/check_pi.sh), snmpget/snmpset/snmpwalk
# en la Pi (ya instalados, ver docs/agent.md), los tres servicios activos
# (scripts/pi.sh status agent|controller|mosquitto).
#
# Los pasos que necesitan logica Python en la Pi (3, 4, 5, 6) escriben un
# .py local a un archivo temporal, lo copian con scp a /tmp en la Pi, lo
# corren por ssh y borran la copia remota -- evitar escapar Python dentro de
# un "ssh ... python3 -c \"...\"" (comillas/f-strings rompen esa forma).

set -uo pipefail

HOST="rsu"
REMOTE_DIR="~/ntcip_middleware"
FECHA="$(date +%Y-%m-%d)"
EVID_DIR="evidencia/demo_${FECHA}"
mkdir -p "$EVID_DIR"

SIN_PAUSAS=0
[ "${1:-}" = "--sin-pausas" ] && SIN_PAUSAS=1

# --- credenciales/OID SNMP, iguales a agent/rsu_middleware.py ---
SNMP_USER="rsuLabUser"
SNMP_AUTH="labAuthPass123"
SNMP_PRIV="labPrivPass123"
SNMP_DEST="127.0.0.1:1161"   # desde dentro de la Pi (no expuesto fuera de localhost+SSH)

OID_ASC="1.3.6.1.4.1.1206.4.2.1.1"
OID_PHASEYELLOW="${OID_ASC}.2.1.8.1"
OID_PHASEREDCLEAR="${OID_ASC}.2.1.9.1"

# --- colores (legibles en Git Bash) ---
if [ -t 1 ]; then
  C_TITULO="\033[1;97;44m"
  C_REQ="\033[1;33m"
  C_OBS="\033[1;36m"
  C_OK="\033[1;32m"
  C_FALLO="\033[1;31m"
  C_CMD="\033[0;90m"
  C_RESET="\033[0m"
else
  C_TITULO=""; C_REQ=""; C_OBS=""; C_OK=""; C_FALLO=""; C_CMD=""; C_RESET=""
fi

declare -a RESUMEN_PASO RESUMEN_REQ RESUMEN_RESULT
TMP_REMOTOS=()

limpiar_tmp_remotos() {
  if [ "${#TMP_REMOTOS[@]}" -gt 0 ]; then
    ssh "$HOST" "rm -f ${TMP_REMOTOS[*]}" >/dev/null 2>&1
  fi
}
trap limpiar_tmp_remotos EXIT

pausar() {
  [ "$SIN_PAUSAS" = "1" ] && return 0
  printf "\n%bEnter para continuar...%b" "$C_OBS" "$C_RESET"
  read -r _
}

encabezado() {
  local numero="$1" titulo="$2" requerimiento="$3"
  echo
  printf "%b================================================================%b\n" "$C_TITULO" "$C_RESET"
  printf "%b  PASO %s: %s%b\n" "$C_TITULO" "$numero" "$titulo" "$C_RESET"
  printf "%b================================================================%b\n" "$C_TITULO" "$C_RESET"
  printf "%bRequerimiento verificado: %s%b\n" "$C_REQ" "$requerimiento" "$C_RESET"
}

observar() {
  printf "%bQué observar: %s%b\n" "$C_OBS" "$1" "$C_RESET"
}

comando() {
  printf "%b\$ %s%b\n" "$C_CMD" "$1" "$C_RESET"
}

marcar() {
  RESUMEN_PASO+=("$1")
  RESUMEN_REQ+=("$2")
  if [ "$3" = "0" ]; then
    RESUMEN_RESULT+=("OK")
    printf "%b>>> OK%b\n" "$C_OK" "$C_RESET"
  else
    RESUMEN_RESULT+=("FALLO")
    printf "%b>>> FALLO%b\n" "$C_FALLO" "$C_RESET"
  fi
}

# Copia un .py local a /tmp en la Pi y lo corre con el venv de la Pi,
# agregando stdout+stderr a $2 (archivo de evidencia). $1 = ruta local del
# .py. Deja el nombre remoto registrado para borrarlo al salir.
correr_python_remoto() {
  local local_py="$1" archivo_evid="$2"
  local remoto="/tmp/$(basename "$local_py")"
  TMP_REMOTOS+=("$remoto")
  scp -q "$local_py" "$HOST:$remoto" >> "$archivo_evid" 2>&1
  ssh "$HOST" "source ~/rsu-env/bin/activate && cd $REMOTE_DIR && python3 $remoto" >> "$archivo_evid" 2>&1
  return $?
}

# ===========================================================================
# Paso 0: estado del banco
# ===========================================================================
encabezado "0" "Estado del banco de pruebas" "(verificación operativa previa, sin requerimiento específico)"
observar "Los tres servicios 'active (running)' y un desfase de reloj de pocos ms entre la Pi y la laptop."
archivo0="$EVID_DIR/00_estado-del-banco.txt"
{
  echo "\$ scripts/check_pi.sh"
  bash scripts/check_pi.sh 2>&1
  echo
  echo "\$ scripts/pi.sh status agent"
  scripts/pi.sh status agent 2>&1 | head -6
  echo
  echo "\$ scripts/pi.sh status controller"
  scripts/pi.sh status controller 2>&1 | head -6
  echo
  echo "\$ scripts/pi.sh status mosquitto"
  scripts/pi.sh status mosquitto 2>&1 | head -6
  echo
  echo "\$ scripts/pi.sh clock"
  scripts/pi.sh clock 2>&1
} > "$archivo0" 2>&1
cat "$archivo0"
if [ "$(grep -c 'active (running)' "$archivo0")" -ge 3 ]; then
  marcar "0. Estado del banco" "-" 0
else
  marcar "0. Estado del banco" "-" 1
fi
pausar

# ===========================================================================
# Paso 1: snmpwalk NTCIP 1202
# ===========================================================================
encabezado "1" "Lectura de NTCIP 1202 (fase y tiempos reales)" "RF-08, RNF-05"
observar "maxPhases=1, los tiempos de phaseTable (verde/ámbar/todo rojo) y el bit activo de phaseStatusGroupTable."
archivo1="$EVID_DIR/01_snmpwalk-ntcip1202.txt"
cmd_mostrar="snmpwalk -v3 -u $SNMP_USER -l authPriv -a SHA -A *** -x AES -X *** -n \"\" $SNMP_DEST $OID_ASC"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en $HOST, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo1"
ssh "$HOST" "source ~/rsu-env/bin/activate && snmpwalk -v3 -u $SNMP_USER -l authPriv -a SHA -A $SNMP_AUTH -x AES -X $SNMP_PRIV -n '' $SNMP_DEST $OID_ASC" >> "$archivo1" 2>&1
r1=$?
cat "$archivo1"
if [ "$r1" = "0" ] && grep -q "$OID_ASC" "$archivo1"; then
  marcar "1. snmpwalk NTCIP 1202" "RF-08, RNF-05" 0
else
  marcar "1. snmpwalk NTCIP 1202" "RF-08, RNF-05" 1
fi
pausar

# ===========================================================================
# Paso 2: ciclo del controlador (~25 s)
# ===========================================================================
encabezado "2" "Ciclo del controlador en vivo (~25 s)" "RF-06, RF-08"
observar "Las transiciones verde -> amarillo -> todo_rojo -> rojo_general -> verde, con su motivo (ciclo_normal)."
echo "Nota: el emulador solo avanza de fase cuando algo lo consulta (get_status);"
echo "no tiene un hilo de reloj propio (ver controller/controller_emulator.py,"
echo "_advance_locked). Este paso sondea activamente cada 0.3s durante 25s --"
echo "lo mismo que haría cualquier gestor SNMP real preguntando el estado --"
echo "para que el ciclo avance y se vea en vivo."
archivo2="$EVID_DIR/02_ciclo-controlador.txt"
cmd_mostrar="python3 (sondeo de get_status cada 0.3s, 25s) + journalctl -u rsu-controller (línea de tiempo)"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en $HOST, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo2"
py2="$(mktemp /tmp/demo_paso2_XXXXXX.py 2>/dev/null || mktemp -t demo_paso2)"
cat > "$py2" <<'PYEOF'
import json, socket, time

def get_fase():
    with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
        s.sendall(b'{"cmd": "get_status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            buf += s.recv(4096)
    return json.loads(buf)

print("== Sondeando get_status cada 0.3s durante 25s (impulsa el avance de fase) ==")
t0 = time.monotonic()
ultimo = None
while time.monotonic() - t0 < 25:
    st = get_fase()
    if st["fase"] != ultimo:
        print(f"t={time.monotonic()-t0:5.2f}s  fase = {st['fase']}")
        ultimo = st["fase"]
    time.sleep(0.3)
PYEOF
correr_python_remoto "$py2" "$archivo2"
rm -f "$py2"
{
  echo ""
  echo "== journalctl -u rsu-controller --since '-26 seconds' --no-pager =="
} >> "$archivo2"
ssh "$HOST" "journalctl -u rsu-controller --since '-26 seconds' --no-pager" >> "$archivo2" 2>&1
cat "$archivo2"
if grep -q "Fase ->" "$archivo2"; then
  marcar "2. Ciclo del controlador" "RF-06, RF-08" 0
else
  marcar "2. Ciclo del controlador" "RF-06, RF-08" 1
fi
pausar

# ===========================================================================
# Paso 3: solicitud NTCIP 1211 aceptada en fase segura
# ===========================================================================
encabezado "3" "Solicitud NTCIP 1211 aceptada (fase ya segura)" "RF-07"
observar "El SET se acepta (sin error SNMP) y priorityRequestStatusInPRS de la fila 1 queda en 4 (activeProcessing)."
archivo3="$EVID_DIR/03_snmpset-aceptado-ntcip1211.txt"
cmd_mostrar="python3 (construye los 29 bytes OER) + snmpset prgPriorityRequestAbsolute + snmpwalk priorityRequestTable"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en $HOST, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo3"
py3="$(mktemp /tmp/demo_paso3_XXXXXX.py 2>/dev/null || mktemp -t demo_paso3)"
cat > "$py3" <<'PYEOF'
import json, socket, subprocess, sys, time
sys.path.insert(0, "/home/ricardoub/ntcip_middleware")
from agent.ntcip1211 import SolicitudPrioridadAbsoluta, codificar

def get_fase():
    with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
        s.sendall(b'{"cmd": "get_status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            buf += s.recv(4096)
    return json.loads(buf)

print("== Esperando fase segura ('verde' o 'rojo_general') ==")
t0 = time.monotonic()
while time.monotonic() - t0 < 30:
    st = get_fase()
    if st["fase"] in ("verde", "rojo_general"):
        break
    time.sleep(0.1)
else:
    print("timeout esperando fase segura"); sys.exit(1)
print(f"Fase confirmada: {st}")

s = SolicitudPrioridadAbsoluta(
    id_solicitud=90, vehiculo_id=b"ambulancia-demo", clase_tipo=1, clase_nivel=1,
    estrategia=1, t_servicio_deseado=8, t_salida_estimada=13, t_solicitud=int(time.time()),
)
hexdata = codificar(s).hex()
print(f"\n29 bytes OER (hex): {hexdata}")
print("  priorityRequestID=90 | vehiculo_id='ambulancia-demo' | clase_tipo=1 (maxima precedencia)")
print("  clase_nivel=1 | estrategia=1 | t_servicio_deseado=8s | t_salida_estimada=13s")

SNMP_BASE = ["snmpset", "-v3", "-u", "rsuLabUser", "-l", "authPriv", "-a", "SHA",
             "-A", "labAuthPass123", "-x", "AES", "-X", "labPrivPass123", "-n", "",
             "127.0.0.1:1161"]
print("\n== snmpset prgPriorityRequestAbsolute ==")
r = subprocess.run(SNMP_BASE + ["1.3.6.1.4.1.1206.4.2.5.2.8.0", "x", hexdata],
                    capture_output=True, text=True, timeout=10)
print((r.stdout + r.stderr).strip())

time.sleep(0.3)
SNMPGET_BASE = [x.replace("snmpset", "snmpget") for x in SNMP_BASE]
print("\n== snmpwalk (snmpget por columna) priorityRequestTable fila 1 ==")
cols = [
    ("1.3.6.1.4.1.1206.4.2.5.1.1.1.2.1", "priorityRequestID"),
    ("1.3.6.1.4.1.1206.4.2.5.1.1.1.3.1", "priorityRequestVehicleID"),
    ("1.3.6.1.4.1.1206.4.2.5.1.1.1.4.1", "priorityRequestVehicleClassType"),
    ("1.3.6.1.4.1.1206.4.2.5.1.1.1.9.1", "priorityRequestStatusInPRS"),
]
for oid, nombre in cols:
    r = subprocess.run(SNMPGET_BASE + [oid], capture_output=True, text=True, timeout=10)
    print(f"{nombre}: {(r.stdout + r.stderr).strip()}")

print("\n== consulta directa al controlador (confirma verde forzado) ==")
print(get_fase())

with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
    s.sendall(b'{"cmd": "clear_priority"}\n')
    buf = b""
    while not buf.endswith(b"\n"):
        buf += s.recv(4096)
print("(prioridad liberada a mano para dejar el banco limpio:", json.loads(buf), ")")
PYEOF
correr_python_remoto "$py3" "$archivo3"
r3=$?
rm -f "$py3"
cat "$archivo3"
if grep -q "priorityRequestStatusInPRS: .*= INTEGER: 4" "$archivo3"; then
  marcar "3. SET aceptado (fase segura)" "RF-07" 0
else
  marcar "3. SET aceptado (fase segura)" "RF-07" 1
fi
pausar

# ===========================================================================
# Paso 4: solicitud durante ámbar/todo_rojo -> cola + activación automática
# ===========================================================================
encabezado "4" "Solicitud durante el despeje (ámbar/todo rojo)" "RF-06, RF-09, RNF-03"
observar "priorityRequestStatusInPRS pasa de 2 (readyQueued) a 4 (activeProcessing) solo al terminar el despeje, sin que se rechace el SET."
echo "Nota: desde el cambio de hoy, RF-06 YA NO rechaza durante el despeje: encola"
echo "(readyQueued) y activa sola la solicitud en cuanto termina, si sigue vigente"
echo "(TTL de RNF-03 = 3s). El despeje real del banco (ámbar+todo_rojo = 5s) es mas"
echo "largo que el TTL (3s), asi que para esta demo se acorta brevemente via SNMP"
echo "(phaseYellowChange/phaseRedClear, ya RW de NTCIP 1202) y se restaura al salir"
echo "incluso si el paso falla (trap de limpieza)."

archivo4="$EVID_DIR/04_cola-y-activacion-rf06.txt"
> "$archivo4"

restaurar_timings() {
  ssh "$HOST" "source ~/rsu-env/bin/activate && snmpset -v3 -u $SNMP_USER -l authPriv -a SHA -A $SNMP_AUTH -x AES -X $SNMP_PRIV -n '' $SNMP_DEST $OID_PHASEYELLOW i 30 $OID_PHASEREDCLEAR i 20" >/dev/null 2>&1
}
trap 'restaurar_timings; limpiar_tmp_remotos' EXIT

comando "snmpset phaseYellowChange=1.0s phaseRedClear=1.0s (temporal, para la demo)"
{
  echo "\$ snmpset phaseYellowChange=1.0s phaseRedClear=1.0s (temporal, para la demo)"
} >> "$archivo4"
ssh "$HOST" "source ~/rsu-env/bin/activate && snmpset -v3 -u $SNMP_USER -l authPriv -a SHA -A $SNMP_AUTH -x AES -X $SNMP_PRIV -n '' $SNMP_DEST $OID_PHASEYELLOW i 10 $OID_PHASEREDCLEAR i 10" >> "$archivo4" 2>&1

py4="$(mktemp /tmp/demo_paso4_XXXXXX.py 2>/dev/null || mktemp -t demo_paso4)"
cat > "$py4" <<'PYEOF'
import json, socket, subprocess, sys, time
sys.path.insert(0, "/home/ricardoub/ntcip_middleware")
from agent.ntcip1211 import SolicitudPrioridadAbsoluta, codificar

def get_fase():
    with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
        s.sendall(b'{"cmd": "get_status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            buf += s.recv(4096)
    return json.loads(buf)

print("\n== Esperando fase 'amarillo' ==")
t0 = time.monotonic()
while time.monotonic() - t0 < 20:
    st = get_fase()
    if st["fase"] == "amarillo":
        break
    time.sleep(0.1)
else:
    print("timeout esperando amarillo"); sys.exit(1)
print(f"Fase confirmada: {st}")

s = SolicitudPrioridadAbsoluta(
    id_solicitud=91, vehiculo_id=b"ambulancia-rf06d", clase_tipo=1, clase_nivel=1,
    estrategia=1, t_servicio_deseado=8, t_salida_estimada=13, t_solicitud=int(time.time()),
)
hexdata = codificar(s).hex()
SNMP_BASE = ["snmpset", "-v3", "-u", "rsuLabUser", "-l", "authPriv", "-a", "SHA",
             "-A", "labAuthPass123", "-x", "AES", "-X", "labPrivPass123", "-n", "",
             "127.0.0.1:1161"]
print("\n== snmpset prgPriorityRequestAbsolute durante 'amarillo' (SET se acepta igual) ==")
r = subprocess.run(SNMP_BASE + ["1.3.6.1.4.1.1206.4.2.5.2.8.0", "x", hexdata],
                    capture_output=True, text=True, timeout=10)
print((r.stdout + r.stderr).strip())

SNMPGET_BASE = [x.replace("snmpset", "snmpget") for x in SNMP_BASE]
STATUS_OID = "1.3.6.1.4.1.1206.4.2.5.1.1.1.9.1"
print("\n== Poll de priorityRequestStatusInPRS fila 1 (2=readyQueued, 4=activeProcessing) ==")
t0 = time.monotonic()
ultimo = None
while time.monotonic() - t0 < 6:
    r = subprocess.run(SNMPGET_BASE + [STATUS_OID], capture_output=True, text=True, timeout=5)
    out = (r.stdout + r.stderr).strip()
    valor = out.split(":")[-1].strip() if ":" in out else out
    if valor != ultimo:
        print(f"t={time.monotonic()-t0:5.2f}s  priorityRequestStatusInPRS.1 = {valor}")
        ultimo = valor
        if valor == "4":
            break
    time.sleep(0.15)

print("\n== consulta directa al controlador ==")
print(get_fase())

with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
    s.sendall(b'{"cmd": "clear_priority"}\n')
    buf = b""
    while not buf.endswith(b"\n"):
        buf += s.recv(4096)
print("(prioridad liberada a mano para dejar el banco limpio:", json.loads(buf), ")")
PYEOF
correr_python_remoto "$py4" "$archivo4"
r4=$?
rm -f "$py4"

comando "journalctl -u rsu-agent -u rsu-controller --since '-15 seconds' --no-pager"
{
  echo ""
  echo "== journalctl -u rsu-agent -u rsu-controller --since '-15 seconds' --no-pager =="
} >> "$archivo4"
ssh "$HOST" "journalctl -u rsu-agent -u rsu-controller --since '-15 seconds' --no-pager" >> "$archivo4" 2>&1

comando "snmpset phaseYellowChange=3.0s phaseRedClear=2.0s (restaurar valores originales)"
{
  echo ""
  echo "\$ snmpset phaseYellowChange=3.0s phaseRedClear=2.0s (restaurar valores originales)"
} >> "$archivo4"
restaurar_timings
echo "OK restaurado" >> "$archivo4"
trap limpiar_tmp_remotos EXIT

cat "$archivo4"
if grep -q "priorityRequestStatusInPRS.1 = 4" "$archivo4" && [ "$r4" = "0" ]; then
  marcar "4. Cola y activación (RF-06)" "RF-06, RF-09, RNF-03" 0
else
  marcar "4. Cola y activación (RF-06)" "RF-06, RF-09, RNF-03" 1
fi
pausar

# ===========================================================================
# Paso 5: clase de vehículo no reconocida
# ===========================================================================
encabezado "5" "Clase de vehículo no reconocida" "RF-05"
observar "El SET devuelve wrongValue de inmediato: la solicitud no crea fila ni en cola ni activa."
archivo5="$EVID_DIR/05_clase-no-reconocida-rf05.txt"
cmd_mostrar="snmpset prgPriorityRequestAbsolute con priorityRequestVehicleClassType=5 (no reconocida)"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en $HOST, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo5"
py5="$(mktemp /tmp/demo_paso5_XXXXXX.py 2>/dev/null || mktemp -t demo_paso5)"
cat > "$py5" <<'PYEOF'
import subprocess, sys, time
sys.path.insert(0, "/home/ricardoub/ntcip_middleware")
from agent.ntcip1211 import SolicitudPrioridadAbsoluta, codificar
s = SolicitudPrioridadAbsoluta(
    id_solicitud=92, vehiculo_id=b"auto-particular", clase_tipo=5, clase_nivel=1,
    estrategia=1, t_servicio_deseado=8, t_salida_estimada=13, t_solicitud=int(time.time()),
)
hexdata = codificar(s).hex()
SNMP_BASE = ["snmpset", "-v3", "-u", "rsuLabUser", "-l", "authPriv", "-a", "SHA",
             "-A", "labAuthPass123", "-x", "AES", "-X", "labPrivPass123", "-n", "",
             "127.0.0.1:1161"]
print("priorityRequestVehicleClassType=5 (CLASES_EMERGENCIA_RECONOCIDAS={1})")
r = subprocess.run(SNMP_BASE + ["1.3.6.1.4.1.1206.4.2.5.2.8.0", "x", hexdata],
                    capture_output=True, text=True, timeout=10)
print((r.stdout + r.stderr).strip())
PYEOF
correr_python_remoto "$py5" "$archivo5"
r5=$?
rm -f "$py5"
cat "$archivo5"
if grep -qi "wrongValue" "$archivo5"; then
  marcar "5. Clase no reconocida" "RF-05" 0
else
  marcar "5. Clase no reconocida" "RF-05" 1
fi
pausar

# ===========================================================================
# Paso 6: caducidad (RF-09, RNF-03)
# ===========================================================================
encabezado "6" "Caducidad de una solicitud sin actualizar (3 s)" "RF-09, RNF-03"
observar "Exactamente 3 s después de la solicitud, el middleware la libera y el controlador vuelve a su ciclo normal."
archivo6="$EVID_DIR/06_caducidad-rf09.txt"
cmd_mostrar="snmpset (fase segura, sin refrescar) + journalctl -u rsu-agent -u rsu-controller (línea de tiempo)"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en $HOST, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo6"
py6="$(mktemp /tmp/demo_paso6_XXXXXX.py 2>/dev/null || mktemp -t demo_paso6)"
cat > "$py6" <<'PYEOF'
import json, socket, subprocess, sys, time
sys.path.insert(0, "/home/ricardoub/ntcip_middleware")
from agent.ntcip1211 import SolicitudPrioridadAbsoluta, codificar

def get_fase():
    with socket.create_connection(("127.0.0.1", 9000), timeout=2) as s:
        s.sendall(b'{"cmd": "get_status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            buf += s.recv(4096)
    return json.loads(buf)

t0 = time.monotonic()
while time.monotonic() - t0 < 30:
    st = get_fase()
    if st["fase"] in ("verde", "rojo_general"):
        break
    time.sleep(0.1)
else:
    print("timeout esperando fase segura"); sys.exit(1)
print(f"Fase confirmada: {st}")

s = SolicitudPrioridadAbsoluta(
    id_solicitud=93, vehiculo_id=b"ambulancia-ttl", clase_tipo=1, clase_nivel=1,
    estrategia=1, t_servicio_deseado=8, t_salida_estimada=13, t_solicitud=int(time.time()),
)
hexdata = codificar(s).hex()
SNMP_BASE = ["snmpset", "-v3", "-u", "rsuLabUser", "-l", "authPriv", "-a", "SHA",
             "-A", "labAuthPass123", "-x", "AES", "-X", "labPrivPass123", "-n", "",
             "127.0.0.1:1161"]
print("\n== snmpset prgPriorityRequestAbsolute (no se vuelve a refrescar) ==")
r = subprocess.run(SNMP_BASE + ["1.3.6.1.4.1.1206.4.2.5.2.8.0", "x", hexdata],
                    capture_output=True, text=True, timeout=10)
print((r.stdout + r.stderr).strip())
print("Esperando ~4 s para que caduque el TTL de RNF-03 (3s)...")
time.sleep(4)
print(get_fase())
PYEOF
correr_python_remoto "$py6" "$archivo6"
rm -f "$py6"
{
  echo ""
  echo "== journalctl -u rsu-agent -u rsu-controller --since '-10 seconds' --no-pager =="
} >> "$archivo6"
ssh "$HOST" "journalctl -u rsu-agent -u rsu-controller --since '-10 seconds' --no-pager" >> "$archivo6" 2>&1
cat "$archivo6"
if grep -q "caducad" "$archivo6"; then
  marcar "6. Caducidad (RF-09)" "RF-09, RNF-03" 0
else
  marcar "6. Caducidad (RF-09)" "RF-09, RNF-03" 1
fi
pausar

# ===========================================================================
# Paso 7: lazo V2I completo (OBU -> MQTT -> RSU -> NTCIP -> controlador)
# ===========================================================================
encabezado "7" "Lazo V2I completo: OBU simulada -> MQTT -> NTCIP 1211 -> controlador" "RF-03, RF-04, RF-07, RF-10, RNF-01"
observar "El controlador fuerza verde para la OBU simulada, y latencia_tramos.py muestra los tramos t_V2I/t_RSU/t_NTCIP de esa solicitud."
archivo7="$EVID_DIR/07_lazo-v2i-completo.txt"
PI_IP="$(ssh -G "$HOST" | awk '/^hostname /{print $2}')"
# Preferir el venv del proyecto (ya tiene paho-mqtt instalado). En Git Bash
# / Windows, "python3" suele resolver al stub de Microsoft Store (falla con
# "no se encontró Python"), no al interprete real -- se prueba cada
# candidato y se verifica que de verdad corra antes de confiar en el.
PYBIN=""
for candidato in ".venv/Scripts/python.exe" python python3 "/c/Program Files/Python313/python.exe"; do
  if "$candidato" --version >/dev/null 2>&1; then PYBIN="$candidato"; break; fi
done
if [ -z "$PYBIN" ]; then
  echo "No se encontró un interprete de Python funcional en la laptop." | tee -a "$archivo7"
  PYBIN="python"
fi

cmd_mostrar="$PYBIN gateway/obu_simulator.py --broker-host $PI_IP --vehiculo-id ambulancia-demo-v2i --eta-seg 8 --clase-tipo 1"
comando "$cmd_mostrar"
{
  echo "\$ $cmd_mostrar"
  echo "(ejecutado en la laptop, $(date '+%Y-%m-%d %H:%M:%S'))"
  echo
} > "$archivo7"
"$PYBIN" gateway/obu_simulator.py --broker-host "$PI_IP" --vehiculo-id ambulancia-demo-v2i --eta-seg 8 --clase-tipo 1 >> "$archivo7" 2>&1
echo "Esperando ~6 s para que el controlador reaccione (incluye el caso de llegar en despeje)..." >> "$archivo7"
sleep 6

comando "scripts/pi.sh fetch (copia resultados/ de la Pi a resultados/rsu/)"
{
  echo ""
  echo "\$ scripts/pi.sh fetch"
} >> "$archivo7"
scripts/pi.sh fetch >> "$archivo7" 2>&1

COMBINADO="resultados/demo_combinado"
rm -rf "$COMBINADO"
mkdir -p "$COMBINADO"
cp resultados/eventos/eventos_obu.csv "$COMBINADO/" 2>/dev/null
cp resultados/rsu/eventos/eventos_rsu_1.csv "$COMBINADO/" 2>/dev/null
cp resultados/rsu/eventos/eventos_ctrl_1.csv "$COMBINADO/" 2>/dev/null

comando "python scripts/analisis/latencia_tramos.py --dir $COMBINADO"
{
  echo ""
  echo "\$ python scripts/analisis/latencia_tramos.py --dir $COMBINADO"
} >> "$archivo7"
"$PYBIN" scripts/analisis/latencia_tramos.py --dir "$COMBINADO" >> "$archivo7" 2>&1
r7=$?
if [ -f "$COMBINADO/latencia_tramos.csv" ]; then
  {
    echo ""
    echo "== $COMBINADO/latencia_tramos.csv =="
    cat "$COMBINADO/latencia_tramos.csv"
  } >> "$archivo7"
fi
cat "$archivo7"
if [ "$r7" = "0" ] && [ -s "$COMBINADO/latencia_tramos.csv" ] && [ "$(wc -l < "$COMBINADO/latencia_tramos.csv")" -ge 2 ]; then
  marcar "7. Lazo V2I completo" "RF-03, RF-04, RF-07, RF-10, RNF-01" 0
else
  marcar "7. Lazo V2I completo" "RF-03, RF-04, RF-07, RF-10, RNF-01" 1
fi
pausar

# ===========================================================================
# Resumen final
# ===========================================================================
echo
printf "%b================================================================%b\n" "$C_TITULO" "$C_RESET"
printf "%b  RESUMEN%b\n" "$C_TITULO" "$C_RESET"
printf "%b================================================================%b\n" "$C_TITULO" "$C_RESET"
fallos=0
for i in "${!RESUMEN_PASO[@]}"; do
  if [ "${RESUMEN_RESULT[$i]}" = "OK" ]; then
    printf "%b  %-45s %-40s OK%b\n" "$C_OK" "${RESUMEN_PASO[$i]}" "${RESUMEN_REQ[$i]}" "$C_RESET"
  else
    printf "%b  %-45s %-40s FALLO%b\n" "$C_FALLO" "${RESUMEN_PASO[$i]}" "${RESUMEN_REQ[$i]}" "$C_RESET"
    fallos=$((fallos + 1))
  fi
done
echo
echo "Evidencia guardada en: $EVID_DIR/"
if [ "$fallos" = "0" ]; then
  printf "%bTodos los pasos OK.%b\n" "$C_OK" "$C_RESET"
  exit 0
else
  printf "%b%d paso(s) con FALLO -- revisar antes de la reunión.%b\n" "$C_FALLO" "$fallos" "$C_RESET"
  exit 1
fi
