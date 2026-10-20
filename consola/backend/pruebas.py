"""Botones "Lanzar prueba" de la pantalla de monitoreo: corren
gateway/obu_emulada.py como subproceso (igual que scripts/demo_lazo.sh,
pruebas 3-7) y transmiten su salida al registro "Eventos del lazo" /
"Trafico MQTT" de la consola via consola/backend/bus.py. Un boton
"Detener" mata el subproceso.

No duplica la logica del lazo (geometria, M1/M2/M3): solo lanza el mismo
script que ya usa la demo guiada, con los mismos argumentos."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

RAIZ = config.RAIZ


def _python_exe() -> str:
    for candidato in (RAIZ / ".venv" / "Scripts" / "python.exe", RAIZ / ".venv" / "bin" / "python"):
        if candidato.exists():
            return str(candidato)
    return sys.executable


# nombre -> (trayectoria relativa, args extra, detener_al_conceder)
PRUEBAS = {
    "lazo_completo": ("resultados/trayectorias/transversal_a_s1.csv", [], False),
    "dos_intersecciones": ("resultados/trayectorias/avenida_ab_s1.csv", [], False),
    "clase_no_reconocida": ("resultados/trayectorias/transversal_a_s1.csv", ["--clase-tipo", "5"], False),
    "caducidad": ("resultados/trayectorias/transversal_a_s1.csv", [], True),
    "vehiculo_detenido": ("resultados/trayectorias/detenido_en_cola_s1.csv", [], False),
}

_procesos_activos: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def _correr(nombre: str, broker_host: str) -> None:
    tray, extra, detener_al_conceder = PRUEBAS[nombre]
    cmd = [_python_exe(), "-u", "gateway/obu_emulada.py", "--broker-host", broker_host,
           "--trayectoria", tray, *extra]
    lineas: deque[str] = deque(maxlen=500)
    ESTADO.set_proceso(nombre, {"activo": True, "lineas": lineas})
    BUS.publicar("proceso", {"nombre": nombre, "accion": "iniciado", "comando": cmd})
    REGISTRO.registrar("Consola", "gateway/obu_emulada.py", "proceso local",
                       {"accion": "iniciar", "prueba": nombre, "cmd": cmd}, None)

    try:
        proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as exc:
        lineas.append(f"*** no se pudo iniciar: {exc} ***")
        ESTADO.set_proceso(nombre, {"activo": False, "lineas": lineas})
        BUS.publicar("proceso", {"nombre": nombre, "accion": "error", "detalle": str(exc)})
        return

    with _lock:
        _procesos_activos[nombre] = proc

    for linea in proc.stdout:
        linea = linea.rstrip("\n")
        lineas.append(linea)
        BUS.publicar("proceso_linea", {"nombre": nombre, "linea": linea})
        if detener_al_conceder and "estado=concedida" in linea:
            time.sleep(0.2)
            proc.terminate()
            lineas.append("*** detenida automaticamente tras CONCEDIDA (prueba de caducidad RF-09) ***")
            BUS.publicar("proceso_linea", {"nombre": nombre, "linea": lineas[-1]})
            break

    proc.wait(timeout=10)
    with _lock:
        _procesos_activos.pop(nombre, None)
    ESTADO.set_proceso(nombre, {"activo": False, "lineas": lineas})
    BUS.publicar("proceso", {"nombre": nombre, "accion": "terminado", "codigo": proc.returncode})
    REGISTRO.registrar("Consola", "gateway/obu_emulada.py", "proceso local",
                       {"accion": "terminado", "prueba": nombre}, {"codigo": proc.returncode})


def iniciar_prueba(nombre: str, broker_host: str) -> tuple[bool, str]:
    if nombre not in PRUEBAS:
        return False, f"prueba desconocida: {nombre} (usar una de {list(PRUEBAS)})"
    with _lock:
        if nombre in _procesos_activos:
            return False, "esa prueba ya esta corriendo"
    threading.Thread(target=_correr, args=(nombre, broker_host), name=f"prueba-{nombre}", daemon=True).start()
    return True, "iniciada"


def detener_prueba(nombre: str) -> tuple[bool, str]:
    with _lock:
        proc = _procesos_activos.get(nombre)
    if proc is None:
        return False, "esa prueba no esta corriendo"
    proc.terminate()
    REGISTRO.registrar("Consola", "gateway/obu_emulada.py", "proceso local",
                       {"accion": "detener", "prueba": nombre}, None)
    return True, "detenida"
