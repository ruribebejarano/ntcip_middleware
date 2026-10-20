"""Configuracion de la consola, desde consola/.env (no se commitea, ver
.gitignore y consola/.env.example). Mismo patron que
centro_control/panel/config.py: valores de laboratorio por defecto si no
hay .env, con un aviso explicito."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

ENV_ENCONTRADO = _ENV_PATH.exists()

MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "127.0.0.1")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))

SNMP_HOST = os.environ.get("SNMP_HOST", "rsu-01")
SNMP_PORT = int(os.environ.get("SNMP_PORT", "1161"))
SNMP_USER = os.environ.get("SNMP_USER", "rsuLabUser")
SNMP_AUTH_KEY = os.environ.get("SNMP_AUTH_KEY", "labAuthPass123")
SNMP_PRIV_KEY = os.environ.get("SNMP_PRIV_KEY", "labPrivPass123")

RSU_ID = os.environ.get("RSU_ID", "1")

SSH_HOST_ALIAS = os.environ.get("SSH_HOST_ALIAS", "rsu")
SSH_REMOTE_DIR = os.environ.get("SSH_REMOTE_DIR", "~/ntcip_middleware")

CONSOLA_HOST = os.environ.get("CONSOLA_HOST", "127.0.0.1")
CONSOLA_PORT = int(os.environ.get("CONSOLA_PORT", "8080"))

# Rutas locales (laptop), relativas a la raiz del repo.
OBU_ESTADO_LOCAL = RAIZ / "resultados" / "obu_vivo" / "estado.json"
REGISTRO_RSU = RAIZ / "config" / "registro_rsu.json"
DIR_LAZO_EMULADO = RAIZ / "resultados" / "lazo_emulado"
DIR_CONSOLA = RAIZ / "resultados" / "consola"
REGISTRO_COMANDOS_PATH = DIR_CONSOLA / "registro_comandos.jsonl"
DIR_TRAYECTORIAS = RAIZ / "resultados" / "trayectorias"
