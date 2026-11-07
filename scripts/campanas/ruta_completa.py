#!/usr/bin/env python3
"""Campaña de ruta completa: una misión desde Av. La Marina hasta el
Instituto Nacional de Salud del Niño (Breña), con una RSU emulada en cada
intersección semaforizada de la ruta (13, ver
scripts/campanas/fixtures/registro_ruta_hospital_nino.json), en la
condición LOCAL (todo en esta laptop: broker TLS 1.3 + mTLS, servidor,
13 agentes rsu_middleware.py, 13 controladores emulados y la OBU emulada).

Mismo mecanismo que scripts/campanas/lazo_centralizado.py (reutiliza sus
funciones; ese archivo no se modifica), con estas diferencias:
  - N RSU a la vez, cada una con su controlador, puertos propios
    (controlador 9101.., SNMP 1171..) y RSU_ID 101..113 (no chocan con el
    agente real de la Raspberry Pi, RSU_ID 1, aunque se conecte al mismo
    broker).
  - Número FIJO de repeticiones (sin cuotas adaptativas por condición de
    llegada: con 13 RSU por repetición las tres condiciones aparecen solas).
  - Sin pausa aleatoria: cada controlador arranca con un desfase aleatorio
    dentro del ciclo de 21 s (controller_emulator.py --desfase-s), derivado
    de la semilla y guardado en rep_XX/desfases.json.
  - Grafo real (data/grafo_san_miguel_real.graphml), no el sintético.

Escenarios (trayectorias base en scripts/campanas/fixtures/ruta_completa/,
generadas y validadas sin red por scripts/campanas/preparar_ruta_completa.py):
  A  36 km/h constante, la misma base con ruido GNSS distinto por semilla.
  B  perfil SINTÉTICO de velocidad variable, una base por semilla.
  C  desvío.

Salida: resultados/ruta_completa/<AAAAMMDD-HHMMSS>_<escenario>/ con
config.json y rep_XX/ (eventos_*.csv de todos los nodos, logs, trayectoria
base y con ruido, desfases.json, memoria.json).

Prerrequisito: el broker TLS de la campaña corriendo en 8883
(deploy/pki/mosquitto_laptop_tls.conf).

Uso:
    python scripts/campanas/ruta_completa.py --escenario A --semillas 101 102 103 104 105 \\
        --broker-port 8883 --tls deploy/pki
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from scripts.campanas.lazo_centralizado import (  # noqa: E402
    PY,
    _commit,
    _correr_obus,
    _detener,
    _esperar_en_log,
    _memoria_libre_mb,
    _puerto_libre,
    _rutas_tls,
    _trayectoria_con_ruido,
)

FIX = Path(__file__).resolve().parent / "fixtures"
REGISTRO = FIX / "registro_ruta_hospital_nino.json"
BASES = FIX / "ruta_completa"
CICLO_S = 8.0 + 3.0 + 2.0 + 8.0  # plan por defecto del controlador emulado
CTRL_BASE, SNMP_BASE = 9101, 1171
SIGMA_POS_M = 5.0


def base_de(escenario: str, semilla: int) -> Path:
    if escenario == "A":
        return BASES / "trayectoria_A.csv"
    if escenario == "B":
        return BASES / f"trayectoria_B_s{semilla}.csv"
    return BASES / "trayectoria_C.csv"


def desfases_de(semilla: int, rsu_ids: list[str]) -> dict[str, float]:
    rnd = random.Random(semilla * 7919)
    return {r: round(rnd.uniform(0.0, CICLO_S), 3) for r in rsu_ids}


class MuestreoMemoria(threading.Thread):
    """Memoria libre de la laptop cada 5 s durante la repetición."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.muestras: list[float] = []
        self._fin = threading.Event()

    def run(self) -> None:
        while not self._fin.is_set():
            m = _memoria_libre_mb()
            if m is not None:
                self.muestras.append(round(m, 1))
            self._fin.wait(5.0)

    def detener(self) -> None:
        self._fin.set()
        self.join(timeout=6)


def _lanzar_rsus(rep_dir: Path, rsus: list[dict], desfases: dict[str, float], tls_dir: Path,
                 broker_host: str, broker_port: int) -> list[subprocess.Popen]:
    procesos: list[subprocess.Popen] = []
    ctrl_logs = []
    for k, r in enumerate(rsus):
        rid = r["rsu_id"]
        entorno = dict(os.environ, RSU_ID=rid, RSU_EVENTOS_DIR=str(rep_dir), PYTHONIOENCODING="utf-8")
        log = rep_dir / f"controller_{rid}.log"
        p = subprocess.Popen([PY, "-u", str(RAIZ / "controller" / "controller_emulator.py"),
                              "--port", str(CTRL_BASE + k), "--desfase-s", str(desfases[rid])],
                             stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT, env=entorno, cwd=RAIZ)
        procesos.append(p)
        ctrl_logs.append(log)
    for log in ctrl_logs:
        if not _esperar_en_log(log, "escuchando en", timeout=30):
            _detener(*procesos)
            raise SystemExit(f"[ruta] controlador sin arrancar, ver {log}")
    agent_logs = []
    for k, r in enumerate(rsus):
        rid = r["rsu_id"]
        ca, cert, key = _rutas_tls(tls_dir, "rsu", rid)
        entorno = dict(os.environ, RSU_ID=rid, RSU_EVENTOS_DIR=str(rep_dir), PYTHONIOENCODING="utf-8",
                       CONTROLLER_PORT=str(CTRL_BASE + k), SNMP_PORT=str(SNMP_BASE + k),
                       MQTT_BROKER_HOST=broker_host, MQTT_BROKER_PORT=str(broker_port),
                       RSU_TLS_CA=ca, RSU_TLS_CERT=cert, RSU_TLS_KEY=key)
        log = rep_dir / f"agent_{rid}.log"
        p = subprocess.Popen([PY, "-u", str(RAIZ / "agent" / "rsu_middleware.py")],
                             stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT, env=entorno, cwd=RAIZ)
        procesos.append(p)
        agent_logs.append(log)
    for log in agent_logs:
        if not _esperar_en_log(log, "[middleware] Conectado al broker MQTT", timeout=60):
            _detener(*procesos)
            raise SystemExit(f"[ruta] agente sin conexión al broker, ver {log}")
    return procesos


def _lanzar_servidor(rep_dir: Path, tls_dir: Path, broker_host: str, broker_port: int) -> subprocess.Popen:
    ca, cert, key = _rutas_tls(tls_dir, "servidor", None)
    entorno = dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir), GRAFO_SINTETICO="0", PYTHONIOENCODING="utf-8",
                   REGISTRO_RSU_PATH=str(REGISTRO), MQTT_BROKER_HOST=broker_host, MQTT_BROKER_PORT=str(broker_port),
                   SERVIDOR_TLS_CA=ca, SERVIDOR_TLS_CERT=cert, SERVIDOR_TLS_KEY=key)
    log = rep_dir / "servidor.log"
    p = subprocess.Popen([PY, "-u", str(RAIZ / "servidor" / "main.py")], stdout=log.open("w", encoding="utf-8"),
                         stderr=subprocess.STDOUT, env=entorno, cwd=RAIZ)
    # Carga el grafo real antes de conectarse: más que los 8 s de lazo_centralizado.
    if not _esperar_en_log(log, "[servidor] Conectado al broker", timeout=90):
        _detener(p)
        raise SystemExit(f"[ruta] servidor sin conexión al broker, ver {log}")
    return p


def _conexiones(log: Path) -> int:
    try:
        texto = log.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    return texto.count("Conectado al broker")


def _verificar_repeticion(rep_dir: Path, rsu_ids: list[str]) -> dict:
    """Chequeos de la repetición: una sola conexión por proceso y una
    respuesta M2 por cada solicitud emitida. No borra nada."""
    from common.events import iter_eventos

    problemas = []
    for rid in rsu_ids:
        if _conexiones(rep_dir / f"agent_{rid}.log") > 1:
            problemas.append(f"agente {rid}: más de una conexión al broker (choque de client_id)")
    if _conexiones(rep_dir / "servidor.log") > 1:
        problemas.append("servidor: más de una conexión al broker")
    eventos = list(iter_eventos(rep_dir))
    m1 = {e["id_solicitud"] for e in eventos if e["tipo_evento"] == "M1_tx" and e["nodo"] == "servidor"}
    m2 = {e["id_solicitud"] for e in eventos if e["tipo_evento"] == "M2_rx"}
    sin_respuesta = sorted(m1 - m2)
    if sin_respuesta:
        problemas.append(f"solicitudes sin M2: {sin_respuesta}")
    paradas = next((e["extra"].get("n_paradas") for e in eventos if e["tipo_evento"] == "ruta_calculada"), None)
    if paradas != len(rsu_ids):
        problemas.append(f"la ruta tiene {paradas} paradas, se esperaban {len(rsu_ids)}")
    return {"solicitudes": len(m1), "con_m2": len(m1 & m2), "paradas_ruta": paradas, "problemas": problemas}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escenario", required=True, choices=["A", "B", "C"])
    ap.add_argument("--semillas", type=int, nargs="+", required=True)
    ap.add_argument("--broker-host", default="127.0.0.1")
    ap.add_argument("--broker-port", type=int, default=8883)
    ap.add_argument("--tls", default=str(RAIZ / "deploy" / "pki"))
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "ruta_completa"))
    ap.add_argument("--etiqueta", default="", help="sufijo de la carpeta (p. ej. 'prueba')")
    ap.add_argument("--memoria-minima-mb", type=float, default=1024.0,
                    help="aborta antes de una repetición si la memoria libre es menor")
    args = ap.parse_args()
    tls_dir = Path(args.tls)

    registro = json.loads(REGISTRO.read_text(encoding="utf-8"))
    rsus = registro["rsu"]
    rsu_ids = [r["rsu_id"] for r in rsus]

    ocupados = [p for k in range(len(rsus)) for p, proto in ((CTRL_BASE + k, "tcp"), (SNMP_BASE + k, "udp"))
                if not _puerto_libre(p, proto)]
    if ocupados:
        raise SystemExit(f"[ruta] puertos ocupados antes de empezar: {ocupados}")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    nombre = f"{ts}_{args.escenario}" + (f"_{args.etiqueta}" if args.etiqueta else "")
    corrida = Path(args.salida) / nombre
    corrida.mkdir(parents=True, exist_ok=True)

    config = {
        "fecha_inicio": datetime.now().isoformat(timespec="seconds"),
        "commit": _commit(),
        "escenario": f"ruta_{args.escenario}",
        "config": "local",
        "factor": 1.0,
        "broker": f"{args.broker_host}:{args.broker_port}",
        "tls": True,
        "registro": str(REGISTRO.relative_to(RAIZ)),
        "rsus": [{"rsu_id": r["rsu_id"], "interseccion_id": r["interseccion_id"], "acum_m": r["acum_m"]} for r in rsus],
        "semillas": args.semillas,
        "sigma_pos_m": SIGMA_POS_M,
        "plan_controlador_s": {"verde": 8, "amarillo": 3, "todo_rojo": 2, "rojo_general": 8},
        "memoria_libre_mb_inicio": _memoria_libre_mb(),
        "repeticiones": {},
    }
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Corrida {corrida.name}: escenario {args.escenario}, semillas {args.semillas}, "
          f"{len(rsus)} RSU, memoria libre {config['memoria_libre_mb_inicio']:.0f} MB")

    for i, semilla in enumerate(args.semillas, start=1):
        mem = _memoria_libre_mb()
        if mem is not None and mem < args.memoria_minima_mb:
            config["abortada"] = f"memoria libre {mem:.0f} MB < {args.memoria_minima_mb:.0f} MB antes de rep_{i:02d}"
            print(f"*** {config['abortada']}")
            break
        rep = f"rep_{i:02d}"
        rep_dir = corrida / rep
        rep_dir.mkdir(parents=True, exist_ok=True)
        obu_id = f"obu-ruta-{args.escenario.lower()}-s{semilla}"
        base = base_de(args.escenario, semilla)
        shutil.copy(base, rep_dir / "trayectoria_base.csv")
        tray = rep_dir / f"trayectoria_{obu_id}.csv"
        _trayectoria_con_ruido(base, tray, semilla, SIGMA_POS_M)
        desfases = desfases_de(semilla, rsu_ids)
        (rep_dir / "desfases.json").write_text(json.dumps({"semilla": semilla, "desfase_s": desfases}, indent=1),
                                               encoding="utf-8")
        print(f"[{i}/{len(args.semillas)}] {rep}: semilla {semilla}, obu {obu_id}")

        memoria = MuestreoMemoria()
        memoria.start()
        t_ini = time.time_ns()
        procesos: list[subprocess.Popen] = []
        servidor = None
        t_arranque = time.monotonic()
        try:
            procesos = _lanzar_rsus(rep_dir, rsus, desfases, tls_dir, args.broker_host, args.broker_port)
            servidor = _lanzar_servidor(rep_dir, tls_dir, args.broker_host, args.broker_port)
            arranque_s = time.monotonic() - t_arranque
            _correr_obus(rep_dir, [(obu_id, base.name)], [tray], args.broker_host, args.broker_port, 1.0, tls_dir)
            time.sleep(3.0)  # drenar M2/ME finales, igual que lazo_centralizado.py
        finally:
            _detener(*( [servidor] if servidor else []), *procesos)
            memoria.detener()
        t_fin = time.time_ns()
        for _ in range(40):
            if all(_puerto_libre(CTRL_BASE + k, "tcp") and _puerto_libre(SNMP_BASE + k, "udp")
                   for k in range(len(rsus))):
                break
            time.sleep(0.25)
        chequeo = _verificar_repeticion(rep_dir, rsu_ids)
        (rep_dir / "memoria.json").write_text(json.dumps({"libre_mb": memoria.muestras}), encoding="utf-8")
        config["repeticiones"][rep] = {
            "semilla": semilla, "obu_id": obu_id, "trayectoria_base": base.name, "t_ini_ns": t_ini, "t_fin_ns": t_fin,
            "arranque_s": round(arranque_s, 1), "duracion_s": round((t_fin - t_ini) / 1e9, 1),
            "memoria_libre_min_mb": min(memoria.muestras) if memoria.muestras else None, **chequeo,
        }
        (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        estado = "OK" if not chequeo["problemas"] else f"PROBLEMAS: {chequeo['problemas']}"
        print(f"    arranque {arranque_s:.1f} s, duración {(t_fin - t_ini) / 1e9:.0f} s, "
              f"memoria libre mín {config['repeticiones'][rep]['memoria_libre_min_mb']} MB, "
              f"{chequeo['con_m2']}/{chequeo['solicitudes']} solicitudes con M2 -> {estado}")

    config["fecha_fin"] = datetime.now().isoformat(timespec="seconds")
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {corrida}")


if __name__ == "__main__":
    main()
