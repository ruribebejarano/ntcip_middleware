"""Configuracion del panel: credenciales SNMP desde .env (NO desde el
codigo -- antes vivian hardcodeadas en varios scripts del repo, p. ej.
scripts/demo_asesor.sh y agent/rsu_middleware.py; .env no se toca aqui).

Busca centro_control/panel/.env (sin commitear, en .gitignore) y, si no
existe, usa los mismos valores de laboratorio que el resto del repo como
default (documentados en .env.example) para que el panel arranque igual
en una instalacion nueva, con un aviso explicito de que son credenciales
de laboratorio."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

SNMP_HOST = os.environ.get("SNMP_HOST", "192.168.18.175")
SNMP_PORT = int(os.environ.get("SNMP_PORT", "1161"))
SNMP_USER = os.environ.get("SNMP_USER", "rsuLabUser")
SNMP_AUTH_KEY = os.environ.get("SNMP_AUTH_KEY", "labAuthPass123")
SNMP_PRIV_KEY = os.environ.get("SNMP_PRIV_KEY", "labPrivPass123")

SSH_HOST_ALIAS = os.environ.get("SSH_HOST_ALIAS", "rsu")  # ver ~/.ssh/config

ENV_ENCONTRADO = _ENV_PATH.exists()
