#!/usr/bin/env bash
#
# Demo guiada del lazo de priorizacion con la OBU emulada, para mostrar en
# vivo al asesor. Un solo script: se ubica solo en la carpeta del repo, corre
# cada prueba, muestra el comando que ejecuta y explica en espanol que paso,
# con una linea de tiempo que junta OBU (laptop), RSU y controlador (Pi).
#
# Uso (Git Bash, desde cualquier carpeta):
#   /e/Tesis/ntcip_middleware/scripts/demo_lazo.sh              # todas las pruebas, con pausas
#   /e/Tesis/ntcip_middleware/scripts/demo_lazo.sh --solo 3     # solo la prueba 3
#   /e/Tesis/ntcip_middleware/scripts/demo_lazo.sh --desde 4    # de la 4 en adelante
#   /e/Tesis/ntcip_middleware/scripts/demo_lazo.sh --sin-pausas # de corrido
#
# Pruebas: 0 estado del banco · 1 la RSU escucha su tema · 2 NTCIP 1202 por SNMPv3
#          3 lazo completo · 4 dos intersecciones · 5 RF-05 · 6 RF-09 · 7 vehiculo detenido
#          8 pruebas unitarias · 9 diagrama de secuencia
#
# Cada prueba se guarda (sin colores) en evidencia/demo_lazo_<fecha>/.

set -u
cd "$(dirname "$0")/.." || exit 1
RAIZ="$(pwd)"

HOST="rsu"
REMOTO="~/ntcip_middleware"
BROKER="127.0.0.1"
RSU_ID="1"

if   [ -x .venv/Scripts/python.exe ]; then PY=".venv/Scripts/python.exe"
elif [ -x .venv/bin/python ];         then PY=".venv/bin/python"
else PY="python"; fi

MOSQ_PUB=""
for d in "/c/Program Files (x86)/mosquitto" "/c/Program Files/mosquitto" "/usr/bin"; do
  if [ -x "$d/mosquitto_pub.exe" ]; then MOSQ_PUB="$d/mosquitto_pub.exe"; break; fi
  if [ -x "$d/mosquitto_pub" ];     then MOSQ_PUB="$d/mosquitto_pub";     break; fi
done

PAUSAS=1; SOLO=""; DESDE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --sin-pausas) PAUSAS=0 ;;
    --solo)  SOLO="$2"; shift ;;
    --desde) DESDE="$2"; shift ;;
    *) echo "Opcion desconocida: $1"; exit 1 ;;
  esac
  shift
done

EVID="evidencia/demo_lazo_$(date +%Y-%m-%d_%H%M)"
TMPD="resultados/demo_lazo_tmp"
mkdir -p "$EVID" "$TMPD"
export DEMO_COLOR=1

AZ=$'\033[1;36m'; AM=$'\033[1;33m'; VE=$'\033[1;32m'; RO=$'\033[1;31m'; GR=$'\033[2m'; NE=$'\033[1m'; FI=$'\033[0m'

declare -a RESUMEN=()

titulo() {  # numero, titulo, requerimientos
  echo
  echo "${AZ}══════════════════════════════════════════════════════════════════════════════${FI}"
  echo "${AZ}  PRUEBA $1 · $2${FI}"
  [ -n "${3:-}" ] && echo "${AZ}  Verifica: $3${FI}"
  echo "${AZ}══════════════════════════════════════════════════════════════════════════════${FI}"
}
explica() { echo "${NE}$*${FI}"; }
observar() { echo "${AM}  Que observar:${FI} $*"; }
comando() { echo "${GR}  \$ $*${FI}"; }
pausa() {
  [ "$PAUSAS" = "1" ] || return 0
  echo; read -r -p "  [Enter para continuar] " _
}
resultado() {  # numero, titulo, ok(0/1), detalle
  if [ "$3" = "0" ]; then echo "${VE}  ✔ RESULTADO: $4${FI}"
  else echo "${RO}  ✘ RESULTADO: $4${FI}"; fi
}

traer_eventos_pi() {  # copia los eventos de la RSU y del controlador (solo las ultimas filas)
  ssh "$HOST" "tail -n 3000 $REMOTO/resultados/eventos/eventos_rsu_${RSU_ID}.csv" > "$TMPD/eventos_rsu_${RSU_ID}.csv.tmp" 2>/dev/null
  ssh "$HOST" "tail -n 3000 $REMOTO/resultados/eventos/eventos_ctrl_${RSU_ID}.csv" > "$TMPD/eventos_ctrl_${RSU_ID}.csv.tmp" 2>/dev/null
  for f in rsu ctrl; do
    src="$TMPD/eventos_${f}_${RSU_ID}.csv.tmp"
    dst="$TMPD/eventos_${f}_${RSU_ID}.csv"
    # tail puede cortar la cabecera: se repone
    { echo "ts_ns,nodo,tipo_evento,id_solicitud,extra_json"; grep -v '^ts_ns,' "$src"; } > "$dst"
    rm -f "$src"
  done
}

linea_tiempo() {  # desde_epoch -> imprime la linea de tiempo y la deja en $LINEA
  traer_eventos_pi
  echo
  echo "${NE}  Linea de tiempo (OBU = reloj de la laptop; RSU y controlador = reloj de la Pi):${FI}"
  LINEA="$("$PY" scripts/demo/linea_tiempo.py --desde "$1" \
           --obu resultados/eventos/eventos_obu.csv \
           --rsu "$TMPD/eventos_rsu_${RSU_ID}.csv" --ctrl "$TMPD/eventos_ctrl_${RSU_ID}.csv")"
  echo "$LINEA"
}

correr_obu() {  # trayectoria [args extra] -> corre la OBU y despues la linea de tiempo
  local tray="$1"; shift
  DESDE_TS=$(date +%s)
  comando "$PY gateway/obu_emulada.py --broker-host $BROKER --trayectoria $tray $*"
  echo "${GR}  (la primera solicitud sale a los ~40 s, cuando el vehiculo entra en la geocerca de 150 m)${FI}"
  echo
  "$PY" -u gateway/obu_emulada.py --broker-host "$BROKER" --trayectoria "$tray" "$@" 2>&1 | sed 's/^/  OBU> /'
  sleep 2
  linea_tiempo "$((DESDE_TS - 1))"
}

debe_correr() {
  local n="$1"
  if [ -n "$SOLO" ]; then [ "$n" = "$SOLO" ]; return; fi
  [ "$n" -ge "$DESDE" ]
}

# --------------------------------------------------------------------------
prueba_0() {
  titulo 0 "Estado del banco de pruebas" "que todo este listo antes de empezar"
  local ok=0
  comando "tailscale status"
  local ts; ts="$(tailscale status 2>/dev/null)"
  for eq in laptopricardoub rsu-01; do
    if echo "$ts" | grep -q "$eq"; then
      if echo "$ts" | grep "$eq" | grep -q offline; then echo "  ${RO}✘${FI} $eq offline"; ok=1
      else echo "  ${VE}✔${FI} $eq en la red Tailscale"; fi
    else echo "  ${RO}✘${FI} $eq no aparece en Tailscale"; ok=1; fi
  done

  comando "Get-Service mosquitto   (broker en la laptop)"
  local est; est="$(powershell.exe -NoProfile -Command "(Get-Service mosquitto).Status" 2>/dev/null | tr -d '\r')"
  if [ "$est" = "Running" ]; then echo "  ${VE}✔${FI} Mosquitto corriendo en la laptop"
  else echo "  ${RO}✘${FI} Mosquitto: '${est:-no encontrado}'. En PowerShell (admin): Restart-Service mosquitto"; ok=1; fi

  comando "ssh $HOST systemctl is-active rsu-controller rsu-agent"
  local act; act="$(ssh -o ConnectTimeout=8 "$HOST" "systemctl is-active rsu-controller rsu-agent" 2>/dev/null | tr '\n' ' ')"
  if [ "$act" = "active active " ]; then echo "  ${VE}✔${FI} En la Raspberry Pi: controlador y RSU activos"
  else
    echo "  ${RO}✘${FI} Servicios en la Pi: '${act:-sin respuesta}'"
    echo "    Para arrancarlos: scripts/pi.sh start controller && scripts/pi.sh start agent"; ok=1
  fi

  comando "ssh $HOST journalctl -u rsu-agent   (ultima conexion al broker)"
  local log; log="$(ssh -o ConnectTimeout=8 "$HOST" "journalctl -u rsu-agent -n 400 --no-pager" 2>/dev/null)"
  local con; con="$(echo "$log" | grep "Conectado al broker" | tail -1)"
  local esc; esc="$(echo "$log" | grep "Escuchando solicitudes" | tail -1)"
  if [ -n "$con" ]; then
    local ipb; ipb="$(echo "$con" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+' | head -1)"
    echo "  ${VE}✔${FI} La RSU esta conectada al broker de la laptop ($ipb), ultima conexion: $(echo "$con" | awk '{print $1" "$2" "$3}')"
  else echo "  ${RO}✘${FI} No se ve 'Conectado al broker' en el log de la RSU"; ok=1; fi
  if [ -n "$esc" ]; then
    echo "  ${VE}✔${FI} Temas a los que la RSU esta suscrita:"
    echo "$esc" | grep -oE "'[^']+'" | tr -d "'" | sed 's/^/        · /'
  fi

  comando "scripts/pi.sh clock"
  scripts/pi.sh clock 2>/dev/null | grep -E "time.cloudflare|^[0-9]{2}:[0-9]{2}:[0-9]{2}," | sed 's/^/  /'
  echo "${GR}  (la diferencia entre ambos relojes solo afecta a las mediciones que cruzan dos equipos)${FI}"

  resultado 0 "Estado del banco" "$ok" "$([ $ok = 0 ] && echo 'banco listo' || echo 'corregir lo marcado con ✘ antes de seguir')"
}

prueba_1() {
  titulo 1 "Arquitectura: la RSU escucha SOLO el tema de su interseccion" "esquema E2+E4 (broker central, un tema por RSU)"
  cat <<EOF
    Laptop                                    Raspberry Pi (rsu-01)
    ┌──────────────────────┐   Tailscale     ┌──────────────────────────┐
    │ OBU emulada  ──M1/M3─┼──►  broker  ◄───┼── RSU 1 (cliente MQTT)   │
    │              ◄──M2───┤   Mosquitto     │   suscrita a rsu/1/...   │
    │ Centro de control ───┼── SNMPv3 ──────►│   agente NTCIP 1202/1211 │
    └──────────────────────┘                 │   controlador emulado    │
                                             └──────────────────────────┘
EOF
  explica "  La suscripcion la hace el programa de la RSU al arrancar (no es un comando aparte)."
  explica "  Para demostrarlo, publicamos a mano un M1 en dos temas distintos, como si fuera una OBU:"
  if [ -z "$MOSQ_PUB" ]; then
    echo "  ${RO}No encuentro mosquitto_pub.exe; se omite esta prueba.${FI}"; resultado 1 "La RSU escucha su tema" 1 "falta mosquitto_pub"; return
  fi
  local id="manual-$(date +%H%M%S)"
  local desde; desde=$(date +%s)
  local m1="{\"tipo\":\"M1\",\"id_solicitud\":\"$id\",\"vehiculo_id\":\"manual\",\"interseccion_id\":\"OSM-C24\",\"acceso\":\"O\",\"clase\":1,\"velocidad_kmh\":40,\"ts_ms\":0,\"seq\":1}"

  echo; explica "  a) M1 al tema de la RSU 1 (rsu/1/solicitudes): la RSU debe reaccionar"
  comando "mosquitto_pub -t rsu/1/solicitudes -m '{\"tipo\":\"M1\", ... }'"
  "$MOSQ_PUB" -h "$BROKER" -V mqttv5 -t "rsu/1/solicitudes" -D publish response-topic "veh/manual/respuestas" -m "$m1"
  echo "${GR}  (esperando 5 s: como nadie envia actualizaciones, la RSU la cancelara sola a los 3 s)${FI}"
  sleep 5
  linea_tiempo "$desde"
  local ok_a=1; echo "$LINEA" | grep -q "recibe M1 nueva por rsu/1/solicitudes" && ok_a=0

  echo; explica "  b) El mismo M1 al tema rsu/2/solicitudes: la RSU 1 NO debe enterarse"
  local desde2; desde2=$(date +%s)
  local m1b="${m1/$id/$id-b}"
  comando "mosquitto_pub -t rsu/2/solicitudes -m '{\"tipo\":\"M1\", ... }'"
  "$MOSQ_PUB" -h "$BROKER" -V mqttv5 -t "rsu/2/solicitudes" -m "$m1b"
  sleep 3
  linea_tiempo "$desde2"
  local ok_b=0; echo "$LINEA" | grep -q "$id-b\|recibe M1" && ok_b=1
  observar "en (a) la RSU recibe, acepta y luego caduca; en (b) no aparece nada de la RSU."
  resultado 1 "La RSU escucha su tema" "$(( ok_a || ok_b ))" "la RSU 1 solo procesa lo publicado en rsu/1/solicitudes"
}

prueba_2() {
  titulo 2 "Supervision NTCIP 1202 por SNMPv3 desde el centro de control" "objetos reales de NTCIP 1202, SNMPv3 autenticado y cifrado, por Tailscale"
  comando "$PY centro_control/software_gestion.py walk --host rsu-01 --port 1161 --v3-user rsuLabUser ... 1.3.6.1.4.1.1206.4.2.1"
  echo
  local salida
  salida="$("$PY" centro_control/software_gestion.py walk --host rsu-01 --port 1161 \
      --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 \
      1.3.6.1.4.1.1206.4.2.1 2>&1)"
  echo "$salida" | "$PY" scripts/demo/snmp_legible.py
  local ok=$?
  observar "los tiempos (verde 8 s, ambar 3,0 s, todo rojo 2,0 s) y que luz esta encendida ahora."
  resultado 2 "NTCIP 1202 por SNMPv3" "$ok" "$([ $ok = 0 ] && echo 'el centro de control lee la RSU' || echo 'sin respuesta SNMP')"
}

prueba_3() {
  titulo 3 "Lazo completo: solicitud, espera de despeje, verde y cancelacion" "RF-11, RF-03, RF-06, RF-07, RF-08, RF-04"
  explica "  El vehiculo cruza la interseccion OSM-C24 por la calle transversal (acceso Oeste)."
  correr_obu resultados/trayectorias/transversal_a_s1.csv
  observar "M1 nueva al entrar en la geocerca → (si estaba en ambar/todo rojo) la RSU espera → VERDE → M3 al cruzar → se libera."
  local ok=1; echo "$LINEA" | grep -q "CONCEDIDA" && echo "$LINEA" | grep -q "CANCELACION" && ok=0
  resultado 3 "Lazo completo" "$ok" "$([ $ok = 0 ] && echo 'verde concedido y liberado al cruzar' || echo 'no se vio CONCEDIDA y CANCELACION')"
}

prueba_4() {
  titulo 4 "Dos intersecciones seguidas (problema A/B)" "RF-11 (interseccion por delante) y enrutamiento por tema"
  explica "  Tras cruzar A (OSM-C24) la OBU la descarta porque quedo detras y pide a B (OSM-C902), aunque A siga mas cerca."
  explica "  Las solicitudes a B van a rsu/2/solicitudes: sin una RSU 2 desplegada, nadie responde (es lo esperado)."
  correr_obu resultados/trayectorias/avenida_ab_s1.csv
  local ok=1; echo "$LINEA" | grep -q "rsu/2/solicitudes" && ok=0
  observar "la segunda 'NUEVA SOLICITUD' va al tema rsu/2 y la RSU 1 no la procesa."
  resultado 4 "Dos intersecciones" "$ok" "$([ $ok = 0 ] && echo 'la OBU paso de A a B y cambio de tema' || echo 'no se vio la solicitud a rsu/2')"
}

prueba_5() {
  titulo 5 "Clase de vehiculo no reconocida" "RF-05"
  explica "  La OBU se identifica con clase 5 (no es de emergencia)."
  correr_obu resultados/trayectorias/transversal_a_s1.csv --clase-tipo 5
  local ok=1; echo "$LINEA" | grep -q "RECHAZA" && ! echo "$LINEA" | grep -q "por la prioridad" && ok=0
  observar "la RSU RECHAZA y el semaforo nunca cambia 'por la prioridad'."
  resultado 5 "RF-05 clase no reconocida" "$ok" "$([ $ok = 0 ] && echo 'rechazada sin tocar el controlador' || echo 'revisar')"
}

prueba_6() {
  titulo 6 "Caducidad: la OBU deja de transmitir a mitad de la aproximacion" "RF-09 (T_cad = 3 s)"
  explica "  Se corta la OBU automaticamente en cuanto obtiene el verde, como si perdiera la senal."
  local desde; desde=$(date +%s)
  local log="$TMPD/obu_caducidad.log"
  comando "$PY gateway/obu_emulada.py --broker-host $BROKER --trayectoria resultados/trayectorias/transversal_a_s1.csv   (se corta al recibir CONCEDIDA)"
  "$PY" -u gateway/obu_emulada.py --broker-host "$BROKER" --trayectoria resultados/trayectorias/transversal_a_s1.csv > "$log" 2>&1 &
  local pid=$!
  local n=0
  until grep -q "estado=concedida" "$log" 2>/dev/null || [ $n -ge 120 ]; do sleep 1; n=$((n+1)); done
  kill "$pid" 2>/dev/null
  [ -r "/proc/$pid/winpid" ] && taskkill //F //PID "$(cat /proc/$pid/winpid)" >/dev/null 2>&1
  sed 's/^/  OBU> /' "$log"
  echo "  ${RO}OBU> *** OBU cortada (simula perdida de conexion) ***${FI}"
  echo "${GR}  (esperando 6 s a que la RSU note el silencio)${FI}"
  sleep 6
  linea_tiempo "$((desde - 1))"
  local ok=1; echo "$LINEA" | grep -q "CADUCIDAD" && ok=0
  observar "unos 3 s despues de la ultima actualizacion: CADUCIDAD en la RSU y el semaforo vuelve a su ciclo."
  resultado 6 "RF-09 caducidad" "$ok" "$([ $ok = 0 ] && echo 'la RSU libero el controlador sola' || echo 'no se vio la caducidad')"
}

prueba_7() {
  titulo 7 "Vehiculo detenido 20 s en la cola" "RF-03 (actualizacion a 1 Hz) y renovacion de la prioridad"
  explica "  El vehiculo se detiene a 80 m de la interseccion. Cada M1 renueva la prioridad: el verde debe sostenerse hasta que cruce."
  correr_obu resultados/trayectorias/detenido_en_cola_s1.csv
  local ok=1; echo "$LINEA" | grep -q "CONCEDIDA" && ! echo "$LINEA" | grep -q "fin del tiempo maximo" && ok=0
  observar "entre CONCEDIDA y la CANCELACION no hay ningun cambio de semaforo."
  resultado 7 "Vehiculo detenido" "$ok" "$([ $ok = 0 ] && echo 'verde sostenido hasta el cruce' || echo 'el verde se interrumpio')"
}

prueba_8() {
  titulo 8 "Pruebas unitarias" "codificacion NTCIP 1211, RF-05, RF-06, RF-09, geometria y cancelacion"
  "$PY" -c "import pytest" 2>/dev/null || { comando "$PY -m pip install pytest"; "$PY" -m pip install -q pytest; }
  comando "$PY -m pytest -q tests"
  "$PY" -m pytest -q tests 2>&1 | tail -5 | sed 's/^/  /'
  local ok=${PIPESTATUS[0]}
  resultado 8 "Pruebas unitarias" "$ok" "$([ $ok = 0 ] && echo 'todas pasan' || echo 'hay pruebas fallando')"
}

prueba_9() {
  titulo 9 "Diagrama de secuencia de la ultima solicitud" "figura para el Capitulo IV"
  "$PY" -c "import matplotlib" 2>/dev/null || { comando "$PY -m pip install matplotlib"; "$PY" -m pip install -q matplotlib; }
  traer_eventos_pi
  comando "$PY scripts/analisis/secuencia_recorrido.py --dir resultados/eventos --dir $TMPD"
  local sal; sal="$("$PY" scripts/analisis/secuencia_recorrido.py --dir resultados/eventos --dir "$TMPD" --salida "$EVID" 2>&1)"
  echo "$sal" | sed 's/^/  /'
  local png; png="$(echo "$sal" | grep -o '[^ ]*\.png' | head -1)"
  if [ -n "$png" ] && [ -f "$png" ]; then
    cmd.exe //c start "" "$(cygpath -w "$png" 2>/dev/null || echo "$png")" >/dev/null 2>&1
    resultado 9 "Diagrama de secuencia" 0 "imagen en $png"
  else resultado 9 "Diagrama de secuencia" 1 "no se genero la imagen"; fi
}

# --------------------------------------------------------------------------
echo "${NE}Demo del lazo de priorizacion · $(date '+%d/%m/%Y %H:%M') · repo: $RAIZ${FI}"
echo "${GR}Evidencia de esta sesion: $EVID/${FI}"

for n in 0 1 2 3 4 5 6 7 8 9; do
  if debe_correr "$n"; then
    archivo="$EVID/$(printf '%02d' "$n")_prueba.txt"
    "prueba_$n" 2>&1 | tee >(sed 's/\x1b\[[0-9;]*m//g' > "$archivo")
    # tee corre en un subshell: el resumen se reconstruye desde el archivo
    sleep 0.3
    linea_res="$(grep -E '✔ RESULTADO|✘ RESULTADO' "$archivo" | tail -1)"
    RESUMEN+=("$( [ "${linea_res#*✔}" != "$linea_res" ] && echo "${VE}✔${FI}" || echo "${RO}✘${FI}" ) Prueba $n: ${linea_res#*RESULTADO: }")
    pausa
  fi
done

echo
echo "${AZ}══════════════════════════════  RESUMEN  ══════════════════════════════${FI}"
for r in "${RESUMEN[@]}"; do echo "  $r"; done
echo "${GR}  Todo quedo guardado en $EVID/${FI}"
