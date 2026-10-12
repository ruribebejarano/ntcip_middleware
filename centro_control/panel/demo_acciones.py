"""Botones de "casos de prueba" del panel -- reimplementan en Python (no
invocan scripts/demo_asesor.sh) las acciones SNMP de sus pasos 0, 1, 3, 4,
5 y 6. demo_asesor.sh es un script bash interactivo, con pausas y pasos
encadenados (espera activamente a que el controlador llegue a una fase
concreta) pensado para una demo guiada en vivo -- no esta hecho para que
un boton externo dispare "solo el paso 4", y no se modifica aqui (ya esta
probado y listo para la reunion). En su lugar, cada funcion de aqui hace
la misma operacion SNMP de punta a punta usando snmp_helpers (que a su
vez usa centro_control/software_gestion.py), e informa el resultado real
segun la fase del controlador en el momento del clic -- no fuerza ni
espera una fase concreta como sí hace demo_asesor.sh, para mantener esto
simple y sin bloquear la interfaz. Pasos 2 (ciclo del controlador, ~25s de
observacion) y 7 (lazo V2I via MQTT) no tienen un boton equivalente aqui:
el primero no es una accion puntual, y el segundo requiere un cliente MQTT
además de SNMP -- ver bitacora del panel para esta limitacion."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from agent.ntcip1211 import SolicitudPrioridadAbsoluta, codificar  # noqa: E402
from centro_control.panel import config, snmp_helpers  # noqa: E402
from centro_control.panel.ntcip_objetos import NTCIP_ASC, PRGPRIORITYREQUESTABSOLUTE  # noqa: E402
from centro_control.software_gestion import SnmpError, snmp_set  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# En Windows, "bash" en el PATH normalmente resuelve a C:\Windows\System32\bash.exe
# (el lanzador de WSL), NO a Git Bash -- subprocess.run(["bash", ...]) falla
# con "execvpe(/bin/bash) failed" porque scripts/*.sh usan sintaxis de Git
# Bash. Se busca el bash.exe real de Git Bash explícitamente.
_CANDIDATOS_BASH = [
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
]
_BASH_EXE = next((p for p in _CANDIDATOS_BASH if Path(p).exists()), "bash")


def _correr(cmd: list[str], timeout: float = 20.0) -> tuple[bool, str]:
    if cmd and cmd[0] == "bash":
        cmd = [_BASH_EXE] + cmd[1:]
    try:
        r = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, timeout=timeout,
        )
        # encoding="utf-8" explicito (no text=True): el default de Windows
        # es cp1252, que revienta con UnicodeDecodeError ante cualquier
        # byte no-ASCII que venga de journalctl en la Pi (acentos, etc.) y
        # pierde en silencio la salida de ese subproceso.
        salida = (
            (r.stdout or b"").decode("utf-8", errors="replace")
            + (r.stderr or b"").decode("utf-8", errors="replace")
        )
        return r.returncode == 0, salida.strip()
    except subprocess.TimeoutExpired:
        return False, f"Tiempo de espera agotado ({timeout}s) ejecutando {' '.join(cmd)}"
    except OSError as exc:
        return False, f"No se pudo ejecutar {' '.join(cmd)}: {exc}"


def estado_del_banco() -> tuple[bool, str]:
    """Paso 0 de demo_asesor.sh: check_pi.sh + pi.sh status + pi.sh clock."""
    ok1, out1 = _correr(["bash", "scripts/check_pi.sh"], timeout=15)
    ok2, out2 = _correr(["bash", "scripts/pi.sh", "status", "agent"], timeout=15)
    ok3, out3 = _correr(["bash", "scripts/pi.sh", "status", "controller"], timeout=15)
    ok4, out4 = _correr(["bash", "scripts/pi.sh", "status", "mosquitto"], timeout=15)
    ok5, out5 = _correr(["bash", "scripts/pi.sh", "clock"], timeout=25)
    texto = (
        f"== check_pi.sh ==\n{out1}\n\n"
        f"== pi.sh status agent ==\n{out2}\n\n"
        f"== pi.sh status controller ==\n{out3}\n\n"
        f"== pi.sh status mosquitto ==\n{out4}\n\n"
        f"== pi.sh clock ==\n{out5}"
    )
    return (ok1 and ok2 and ok3 and ok4), texto


def ntcip1202_walk() -> tuple[bool, str]:
    """Paso 1 de demo_asesor.sh: snmpwalk del subarbol NTCIP 1202 (asc.phase)."""
    try:
        pares = snmp_helpers.walk_crudo(NTCIP_ASC)
    except SnmpError as exc:
        return False, f"Error SNMP: {exc}"
    if not pares:
        return False, "(sin resultados)"
    return True, "\n".join(f"{oid} = {val}" for oid, val in pares)


def _construir_solicitud(clase_tipo: int, vehiculo_id: str) -> SolicitudPrioridadAbsoluta:
    return SolicitudPrioridadAbsoluta(
        id_solicitud=77,
        vehiculo_id=vehiculo_id.encode("utf-8")[:17],
        clase_tipo=clase_tipo,
        clase_nivel=1,
        estrategia=1,
        t_servicio_deseado=8,
        t_salida_estimada=13,
        t_solicitud=int(time.time()),
    )


def set_ntcip1211(clase_tipo: int, vehiculo_id: str) -> tuple[bool, str]:
    """Pasos 3/4 (clase reconocida: SET aceptado o encolado segun la fase
    actual del controlador -- no se fuerza ni se espera una fase concreta,
    a diferencia de demo_asesor.sh) y 5 (RF-05, clase no reconocida,
    siempre falla con wrongValue sin importar la fase)."""
    solicitud = _construir_solicitud(clase_tipo, vehiculo_id)
    datos = codificar(solicitud)
    a = snmp_helpers.auth()
    try:
        snmp_set(
            config.SNMP_HOST, config.SNMP_PORT, a,
            PRGPRIORITYREQUESTABSOLUTE, datos, value_type="bytes",
        )
    except SnmpError as exc:
        return (clase_tipo not in (1,)), (
            f"SET rechazado por SNMP: {exc}\n"
            f"({'esperado: RF-05, clase no reconocida' if clase_tipo != 1 else 'inesperado'})"
        )

    time.sleep(0.3)  # margen para que priorityRequestTable refleje el SET
    filas = snmp_helpers.leer_priority_request_table()
    fila1 = filas[0]
    return True, (
        f"SET aceptado (29 bytes OER, clase_tipo={clase_tipo}, vehiculo_id='{vehiculo_id}').\n"
        f"priorityRequestTable fila 1: estado={fila1['estado_nombre']} "
        f"(priorityRequestStatusInPRS={fila1.get('priorityRequestStatusInPRS', '?')}), "
        f"vehiculo_id leido='{fila1.get('priorityRequestVehicleID', '?')}'"
    )


def set_rf06_clase_reconocida() -> tuple[bool, str]:
    return set_ntcip1211(clase_tipo=1, vehiculo_id="ambulancia-panel")


def set_rf05_clase_no_reconocida() -> tuple[bool, str]:
    return set_ntcip1211(clase_tipo=5, vehiculo_id="auto-panel")


def caducidad_rf09() -> tuple[bool, str]:
    """Paso 6: hace un SET valido y sondea priorityRequestStatusInPRS de
    la fila 1 cada ~0.3s durante ~6s, mostrando la linea de tiempo real
    (readyQueued/activeProcessing -> closedTimeToLiveError a los T_cad=3s
    desde la ultima actualizacion)."""
    ok, msg_set = set_rf06_clase_reconocida()
    if not ok:
        return False, f"No se pudo hacer el SET inicial: {msg_set}"

    lineas = [msg_set, "", "== Sondeo de priorityRequestStatusInPRS (fila 1) =="]
    t0 = time.time()
    ultimo = None
    while time.time() - t0 < 6.0:
        filas = snmp_helpers.leer_priority_request_table()
        estado = filas[0]["estado_nombre"]
        if estado != ultimo:
            lineas.append(f"t={time.time() - t0:5.2f}s  priorityRequestStatusInPRS.1 = {estado}")
            ultimo = estado
        time.sleep(0.3)
    return True, "\n".join(lineas)


# (id, etiqueta, funcion, requerimiento RF/RNF)
ACCIONES = [
    ("banco", "Estado del banco", estado_del_banco, "RF-10 / scripts/check_pi.sh"),
    ("ntcip1202", "NTCIP 1202: snmpwalk de fase", ntcip1202_walk, "RF-08"),
    ("rf06", "NTCIP 1211: SET con clase reconocida", set_rf06_clase_reconocida, "RF-06 / RF-07"),
    ("rf05", "NTCIP 1211: SET con clase NO reconocida", set_rf05_clase_no_reconocida, "RF-05"),
    ("rf09", "Caducidad de una solicitud (sondeo ~6s)", caducidad_rf09, "RF-09 / RNF-03"),
]
