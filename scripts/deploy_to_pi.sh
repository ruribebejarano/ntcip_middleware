#!/usr/bin/env bash
#
# Sincroniza la Raspberry Pi con lo último commiteado en git (git es la única
# fuente de verdad, ver CLAUDE.md). NO copia archivos sin commitear: si algo
# no está en el repo remoto, este script no lo va a desplegar.
#
# Requiere el alias SSH "rsu" en ~/.ssh/config (ver docs/CONEXION_RASPBERRY.md
# y scripts/check_pi.sh para diagnosticar la conexión).
#
# Uso:
#   ./scripts/deploy_to_pi.sh
#
# Esto NO reinicia el agente automáticamente: el agente SNMPv3 hoy se corre a
# mano (ver docs/agent.md). El script solo deja el código actualizado; el
# reinicio queda a criterio de quien esté probando en ese momento.

set -euo pipefail

HOST="rsu"
REMOTE_DIR="~/ntcip_middleware"

echo "==> git pull en la Pi ($REMOTE_DIR)"
ssh "$HOST" "cd $REMOTE_DIR && git pull --ff-only"

echo "==> HEAD en la Pi tras el pull:"
ssh "$HOST" "cd $REMOTE_DIR && git log -1 --oneline"

echo "==> Listo. Para correr el agente manualmente:"
echo "    ssh rsu"
echo "    source ~/rsu-env/bin/activate && python3 agent/rsu_snmpv3_agent.py"
