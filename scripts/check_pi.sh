#!/usr/bin/env bash
#
# Verifica la conectividad con la Raspberry Pi del banco de pruebas (alias SSH
# "rsu", definido en ~/.ssh/config) y su estado de sincronización con git.
#
# Uso:
#   ./scripts/check_pi.sh
#
# No modifica nada en la Pi ni en la red: solo lee. Si algo falla, indica el
# paso exacto que no se pudo completar.

set -euo pipefail

HOST="rsu"
REMOTE_DIR="~/ntcip_middleware"

echo "==> Probando SSH contra el alias '$HOST' (ver ~/.ssh/config)"
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" true 2>/dev/null; then
  echo "No se pudo conectar por SSH a '$HOST'."
  echo "Posibles causas: la Pi está apagada, cambió de IP (actualizar HostName"
  echo "en ~/.ssh/config), o falta copiar la clave pública con:"
  echo "  ssh-copy-id -i ~/.ssh/id_ed25519_rsu.pub $HOST"
  exit 1
fi
echo "    OK: la Pi responde por SSH."

echo "==> Estado del repo en la Pi ($REMOTE_DIR)"
ssh "$HOST" "cd $REMOTE_DIR 2>/dev/null && git status --short --branch || echo 'No se encontró el repo en esa ruta.'"

echo "==> Entorno virtual (~/rsu-env)"
ssh "$HOST" "test -f ~/rsu-env/bin/activate && echo '    OK: ~/rsu-env existe.' || echo '    Aviso: ~/rsu-env no encontrado.'"

echo "==> Listo."
