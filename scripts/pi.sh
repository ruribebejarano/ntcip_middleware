#!/usr/bin/env bash
#
# Herramienta unica para desplegar, operar y recolectar resultados de la RSU
# (Raspberry Pi) desde la laptop, sin copiar comandos a mano por SSH.
#
# Uso:
#   scripts/pi.sh deploy   [host]
#   scripts/pi.sh start    <servicio> [host]
#   scripts/pi.sh stop     <servicio> [host]
#   scripts/pi.sh restart  <servicio> [host]
#   scripts/pi.sh status   <servicio> [host]
#   scripts/pi.sh logs     <servicio> [host]   (Ctrl+C para salir)
#   scripts/pi.sh fetch    [host]
#   scripts/pi.sh clock    [host]
#
# <servicio>: agent | controller | mosquitto
# [host]: alias SSH, "rsu" por defecto; "rsu2" para la segunda RSU, si ya
#         tiene su propio alias en ~/.ssh/config (ver docs/CONEXION_RASPBERRY.md).
#
# Requiere:
# - El alias SSH configurado (ver docs/CONEXION_RASPBERRY.md).
# - Las unidades systemd instaladas en la Pi (ver deploy/systemd/README.md)
#   para start/stop/restart/status/logs.
# - sudo sin contrasena en la Pi para los comandos systemctl/journalctl de
#   estas tres unidades (ver deploy/systemd/README.md); si no esta
#   configurado, start/stop/restart/logs van a pedir la contrasena de forma
#   interactiva (ssh -t).
#
# Este script NUNCA copia archivos sin commitear: git es la unica fuente de
# verdad (ver CLAUDE.md). "deploy" hace push desde la laptop y pull en la Pi;
# si algo no esta comiteado, no llega a la Pi.

set -euo pipefail

REMOTE_DIR="~/ntcip_middleware"
DEFAULT_HOST="rsu"

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

unit_for() {
  case "$1" in
    agent)      echo "rsu-agent.service" ;;
    controller) echo "rsu-controller.service" ;;
    mosquitto)  echo "mosquitto.service" ;;
    *)
      echo "Servicio desconocido: '$1' (usar agent | controller | mosquitto)" >&2
      exit 1
      ;;
  esac
}

cmd="${1:-}"
[ -z "$cmd" ] && usage

case "$cmd" in
  deploy)
    HOST="${2:-$DEFAULT_HOST}"
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"

    echo "==> git push origin $BRANCH (laptop)"
    git push origin "$BRANCH"

    OLD_HEAD="$(ssh "$HOST" "cd $REMOTE_DIR && git rev-parse HEAD")"
    echo "==> git pull --ff-only en $HOST ($REMOTE_DIR)"
    ssh "$HOST" "cd $REMOTE_DIR && git pull --ff-only"
    NEW_HEAD="$(ssh "$HOST" "cd $REMOTE_DIR && git rev-parse HEAD")"

    if [ "$OLD_HEAD" != "$NEW_HEAD" ] \
       && ssh "$HOST" "cd $REMOTE_DIR && git diff --name-only $OLD_HEAD $NEW_HEAD -- requirements.txt | grep -q ."; then
      echo "==> requirements.txt cambió: pip install en ~/rsu-env"
      ssh "$HOST" "source ~/rsu-env/bin/activate && pip install -r $REMOTE_DIR/requirements.txt"
    else
      echo "==> requirements.txt sin cambios, no se reinstala."
    fi

    echo "==> HEAD en $HOST tras el pull:"
    ssh "$HOST" "cd $REMOTE_DIR && git log -1 --oneline"
    echo "==> Si cambiaste código de agent/ o controller/, considera:"
    echo "    scripts/pi.sh restart controller $HOST && scripts/pi.sh restart agent $HOST"
    ;;

  start|stop|restart)
    SERVICIO="${2:-}"
    [ -z "$SERVICIO" ] && { echo "Falta <servicio> (agent|controller|mosquitto)" >&2; exit 1; }
    HOST="${3:-$DEFAULT_HOST}"
    UNIT="$(unit_for "$SERVICIO")"
    echo "==> sudo systemctl $cmd $UNIT en $HOST"
    ssh -t "$HOST" "sudo systemctl $cmd $UNIT"
    ;;

  status)
    SERVICIO="${2:-}"
    [ -z "$SERVICIO" ] && { echo "Falta <servicio> (agent|controller|mosquitto)" >&2; exit 1; }
    HOST="${3:-$DEFAULT_HOST}"
    UNIT="$(unit_for "$SERVICIO")"
    ssh "$HOST" "systemctl status $UNIT --no-pager" || true
    ;;

  logs)
    SERVICIO="${2:-}"
    [ -z "$SERVICIO" ] && { echo "Falta <servicio> (agent|controller|mosquitto)" >&2; exit 1; }
    HOST="${3:-$DEFAULT_HOST}"
    UNIT="$(unit_for "$SERVICIO")"
    echo "==> journalctl -u $UNIT -f en $HOST (Ctrl+C para salir)"
    ssh -t "$HOST" "sudo journalctl -u $UNIT -n 50 -f"
    ;;

  fetch)
    HOST="${2:-$DEFAULT_HOST}"
    DEST="resultados/${HOST}"
    mkdir -p "$DEST"
    echo "==> Copiando resultados/ de $HOST a $DEST/"
    if command -v rsync >/dev/null 2>&1; then
      rsync -avz "$HOST:$REMOTE_DIR/resultados/" "$DEST/"
    else
      scp -r "$HOST:$REMOTE_DIR/resultados/." "$DEST/"
    fi
    ;;

  clock)
    HOST="${2:-$DEFAULT_HOST}"
    REF="time.cloudflare.com"  # misma referencia que scripts/chrony/rsu-lab.conf
    echo "==> Offset de la Pi ($HOST) contra $REF (vía chronyc sources, no solo la mejor fuente):"
    ssh "$HOST" "chronyc sources -v | grep -E '$REF|MS Name'" \
      || echo "    chrony no responde en $HOST (¿está instalado y corriendo?)."
    echo "==> Offset de la laptop (Windows) contra $REF:"
    if command -v w32tm >/dev/null 2>&1; then
      # MSYS2_ARG_CONV_EXCL evita que Git Bash reescriba "/stripchart" etc.
      # como una ruta de archivo (bug conocido de MSYS2 con flags estilo "/x").
      MSYS2_ARG_CONV_EXCL="*" w32tm /stripchart /computer:"$REF" /samples:3 /dataonly
    else
      echo "    Correr en PowerShell (este shell no tiene w32tm en el PATH):"
      echo "    w32tm /stripchart /computer:$REF /samples:3 /dataonly"
    fi
    echo "==> Nota: si el servicio 'Windows Time' (w32time) no está corriendo en la"
    echo "    laptop, su reloj no se autocorrige y este offset puede crecer con el"
    echo "    tiempo. Verificar con: w32tm /query /status"
    ;;

  *)
    usage
    ;;
esac
