"""Estado del banco de pruebas cada 15 s: tailscale status, servicios
systemd en la RSU, ultima conexion al broker vista en el log de
rsu-agent, y el desfase de relojes (reutiliza scripts/pi.sh clock tal
cual, por bash -- NO reimplementa chronyc/w32tm)."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path

from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

_CANDIDATOS_BASH = [
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
]
_BASH_EXE = next((p for p in _CANDIDATOS_BASH if Path(p).exists()), "bash")


def _correr(cmd: list[str], timeout: float = 12.0) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=config.RAIZ, capture_output=True, timeout=timeout)
        salida = (r.stdout or b"").decode("utf-8", errors="replace") + (r.stderr or b"").decode("utf-8", errors="replace")
        return r.returncode == 0, salida.strip()
    except subprocess.TimeoutExpired:
        return False, f"tiempo de espera agotado ({timeout}s)"
    except OSError as exc:
        return False, str(exc)


def _tailscale() -> dict:
    ok, salida = _correr(["tailscale", "status"])
    if not ok:
        return {"ok": False, "detalle": salida or "tailscale no disponible"}
    equipos = {"laptopricardoub": False, "rsu-01": False}
    for linea in salida.splitlines():
        for eq in equipos:
            if eq in linea:
                equipos[eq] = "offline" not in linea
    faltan = [eq for eq, presente in equipos.items() if not presente]
    return {"ok": not faltan, "detalle": "en la red" if not faltan else f"sin ver: {', '.join(faltan)}"}


def _servicios_rsu() -> tuple[dict, dict]:
    ok, salida = _correr(["ssh", "-o", "ConnectTimeout=6", config.SSH_HOST_ALIAS,
                          "systemctl is-active rsu-controller rsu-agent"])
    if ok:
        partes = salida.split()
        servicios = {"controller": partes[0] if len(partes) > 0 else "sin respuesta",
                     "agent": partes[1] if len(partes) > 1 else "sin respuesta"}
    else:
        servicios = {"controller": "sin respuesta", "agent": "sin respuesta"}
    rsu_ssh = {"ok": ok, "detalle": "responde por SSH" if ok else (salida or "sin respuesta")}
    return servicios, rsu_ssh


def _broker_rsu() -> dict:
    ok, salida = _correr(["ssh", "-o", "ConnectTimeout=6", config.SSH_HOST_ALIAS,
                          "journalctl -u rsu-agent -n 400 --no-pager"])
    if not ok:
        return {"ok": False, "detalle": salida or "sin respuesta SSH"}
    lineas = [l for l in salida.splitlines() if "Conectado al broker" in l]
    if not lineas:
        return {"ok": False, "detalle": "no aparece 'Conectado al broker' en las ultimas 400 lineas"}
    ultima = lineas[-1]
    m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", ultima)
    return {"ok": True, "detalle": f"ultima conexion a {m.group(1) if m else '?'}: {ultima[:19]}"}


def _desfase_reloj() -> dict:
    ok, salida = _correr([_BASH_EXE, "scripts/pi.sh", "clock", config.SSH_HOST_ALIAS], timeout=25.0)
    hay_error = ("no responde" in salida) or not salida
    return {"ok": ok and not hay_error, "detalle": salida[-600:] if salida else "sin datos"}


def _ciclo() -> None:
    while True:
        t0 = time.time()
        ts_tailscale = _tailscale()
        servicios, rsu_ssh = _servicios_rsu()
        broker_rsu = _broker_rsu()
        desfase = _desfase_reloj()
        banco = {"tailscale": ts_tailscale, "rsu_ssh": rsu_ssh, "servicios": servicios,
                 "broker_rsu": broker_rsu, "desfase_reloj": desfase}
        ESTADO.set_banco(banco)
        BUS.publicar("banco", banco)
        REGISTRO.registrar("Consola", "Banco de pruebas", "SSH",
                           "tailscale status; systemctl is-active; journalctl; pi.sh clock", banco)
        time.sleep(max(0.0, 15.0 - (time.time() - t0)))


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_ciclo, name="estado-banco", daemon=True)
    hilo.start()
    return hilo
