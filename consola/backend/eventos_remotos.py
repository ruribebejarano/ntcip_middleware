"""Eventos de la RSU y del controlador (RF-10, common/events.py), traidos
por SSH cada 3 s: `ssh <alias> tail -n 500 eventos_rsu_<id>.csv` y lo mismo
para eventos_ctrl_<id>.csv (ver docs/CONEXION_RASPBERRY.md). Se traducen a
texto legible con la MISMA logica que scripts/demo/linea_tiempo.py, ahora
en common/traduccion_eventos.py (se extrajo de ese script para que ambos
la compartan, sin duplicarla).

Ademas, las ordenes que la RSU le da al controlador (visibles en
eventos_rsu_<id>.csv como snmp_set_tx con accion request_priority,
activar_cola_rf06, clear_priority_m3 o rechazada, y en eventos_ctrl como
ctrl_fase_cambio por caducidad_prioridad) se incorporan al registro de
comandos (pantalla 3) como canal "TCP RSU->controlador"."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import threading
import time

from common.traduccion_eventos import FASE, describir
from consola.backend import config
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

_ACCIONES_ORDEN_CTRL = {
    "request_priority": "request_priority",
    "activar_cola_rf06": "request_priority (fin del despeje, RF-06)",
    "clear_priority_m3": "clear_priority",
    "rechazada": "rechazada (RF-05, no llega al controlador)",
}


def _tail_remoto(nombre_archivo: str, n: int = 500) -> list[dict]:
    """Corre `ssh <alias> tail -n N <archivo>` y parsea las filas CSV
    (mismo formato que common/events.py). Devuelve [] si el SSH falla (la
    consola no debe caerse si la Pi no responde)."""
    remoto = f"{config.SSH_REMOTE_DIR}/resultados/eventos/{nombre_archivo}"
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", config.SSH_HOST_ALIAS, f"tail -n {n} {remoto}"],
            capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [{"_error": str(exc)}]
    if r.returncode != 0:
        return [{"_error": r.stderr.decode("utf-8", errors="replace").strip() or "ssh fallo"}]
    texto = r.stdout.decode("utf-8", errors="replace")
    filas = []
    lector = csv.DictReader(io.StringIO(texto), fieldnames=("ts_ns", "nodo", "tipo_evento", "id_solicitud", "extra_json"))
    for f in lector:
        if f["ts_ns"] == "ts_ns":  # cabecera, puede venir si el archivo tiene <n lineas
            continue
        try:
            ts_ns = int(f["ts_ns"])
        except (TypeError, ValueError):
            continue
        try:
            extra = json.loads(f.get("extra_json") or "{}")
        except json.JSONDecodeError:
            extra = {}
        filas.append({"ts_ns": ts_ns, "tipo": f["tipo_evento"], "id": f["id_solicitud"], "x": extra})
    return filas


def _procesar_rsu(filas: list[dict]) -> None:
    desde = ESTADO.ultimo_ts_rsu_ns()
    nuevas = [f for f in filas if f["ts_ns"] > desde]
    if not nuevas:
        return
    ESTADO.set_ultimo_ts_rsu_ns(max(f["ts_ns"] for f in nuevas))
    for f in sorted(nuevas, key=lambda e: e["ts_ns"]):
        frase = describir("RSU", f)
        if frase:
            e = {"ts": f["ts_ns"] / 1e9, "origen": "RSU", "frase": frase, "tipo_evento": f["tipo"], "id_solicitud": f["id"]}
            ESTADO.agregar_evento_lazo(e)
            BUS.publicar("evento_lazo", e)
        if f["tipo"] == "snmp_set_tx":
            accion = f["x"].get("accion")
            if accion in _ACCIONES_ORDEN_CTRL:
                REGISTRO.registrar("RSU", "Controlador", "TCP RSU->controlador",
                                   {"orden": _ACCIONES_ORDEN_CTRL[accion], "motivo": f["x"].get("motivo")},
                                   {"fase": f["x"].get("fase")}, id_solicitud=f["id"])


def _procesar_ctrl(filas: list[dict]) -> None:
    desde = ESTADO.ultimo_ts_ctrl_ns()
    nuevas = [f for f in filas if f["ts_ns"] > desde]
    if not nuevas:
        return
    ESTADO.set_ultimo_ts_ctrl_ns(max(f["ts_ns"] for f in nuevas))
    for f in sorted(nuevas, key=lambda e: e["ts_ns"]):
        frase = describir("CTRL", f)
        if frase:
            e = {"ts": f["ts_ns"] / 1e9, "origen": "CTRL", "frase": frase, "tipo_evento": f["tipo"], "id_solicitud": f["id"]}
            ESTADO.agregar_evento_lazo(e)
            BUS.publicar("evento_lazo", e)
        if f["tipo"] == "ctrl_fase_cambio":
            fase = FASE.get(f["x"].get("fase"), f["x"].get("fase"))
            REGISTRO.registrar("Controlador", "Controlador", "TCP RSU->controlador",
                               {"orden": "ctrl_fase_cambio", "motivo": f["x"].get("motivo")},
                               {"fase": fase}, id_solicitud=f["id"])


def _ciclo() -> None:
    nombre_rsu = f"eventos_rsu_{config.RSU_ID}.csv"
    nombre_ctrl = f"eventos_ctrl_{config.RSU_ID}.csv"
    while True:
        t0 = time.time()
        filas_rsu = _tail_remoto(nombre_rsu)
        if filas_rsu and "_error" in filas_rsu[0]:
            BUS.publicar("eventos_remotos_error", {"detalle": filas_rsu[0]["_error"]})
        else:
            _procesar_rsu(filas_rsu)
            REGISTRO.registrar("Consola", "RSU (SSH)", "SSH", f"tail -n 500 {nombre_rsu}",
                               {"filas_nuevas": len(filas_rsu)})

        filas_ctrl = _tail_remoto(nombre_ctrl)
        if filas_ctrl and "_error" not in filas_ctrl[0]:
            _procesar_ctrl(filas_ctrl)
            REGISTRO.registrar("Consola", "Controlador (SSH)", "SSH", f"tail -n 500 {nombre_ctrl}",
                               {"filas_nuevas": len(filas_ctrl)})

        time.sleep(max(0.0, 3.0 - (time.time() - t0)))


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_ciclo, name="eventos-remotos", daemon=True)
    hilo.start()
    return hilo
