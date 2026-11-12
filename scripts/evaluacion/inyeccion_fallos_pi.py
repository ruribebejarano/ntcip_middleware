#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 1) con la RSU FÍSICA (Raspberry Pi por 4G).

Casos (--caso):
  rsu       se mata el proceso del agente con SIGKILL
            (sudo systemctl kill -s KILL rsu-agent.service); systemd lo
            reinicia a los 2 s (Restart=on-failure, RestartSec=2).
            Automático.
  enlace4g  el AUTOR desconecta el módem cuando el script lo indica y lo
            vuelve a conectar 20 s después. Interactivo; ver
            docs/PROCEDIMIENTO_PRUEBAS_FISICAS.md antes de correrlo (la Pi
            no debe tener otra ruta de salida, p. ej. Wi-Fi, durante la prueba).

Por repetición: este script (en la laptop) lanza el servidor y la OBU
emulada del escenario `lazo` contra el broker TLS de la campaña (8883), al
que ya está conectado el agente de la Pi; arranca en la Pi el observador
(scripts/evaluacion/observador_rsu.py) y, cuando el servidor recibe el M2
"concedida", espera 3 a 8 s e inyecta la falla. Al terminar, trae de la Pi
el CSV del observador, los eventos de la RSU y el journal del agente.

Todas las métricas se calculan con el reloj de la Pi:
  t_lib_m1  último M1 recibido por la RSU antes de la falla -> el
            controlador deja de tener la prioridad (observador)
  T_rec     rsu: muerte del proceso (journal) -> "Conectado al broker MQTT"
            del proceso reiniciado (journal);
            enlace4g: la interfaz del módem vuelve a estar "up"
            (observador) -> "Conectado al broker MQTT" (journal)
  retenida  prioridad activa al final de la repetición
Además, una sonda desde la laptop (M1 de prueba con la identidad del
servidor, como en inyeccion_fallos.py) confirma que la RSU responde.

Uso: .venv/Scripts/python.exe scripts/evaluacion/inyeccion_fallos_pi.py --caso rsu --repeticiones 10
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.campanas.lazo_centralizado import (  # noqa: E402
    ESCENARIOS, FIXTURES, _correr_obus, _detener, _lanzar_servidor, _trayectoria_con_ruido)
from scripts.evaluacion import inyeccion_fallos as base  # noqa: E402

HOST = "rsu"
DIR_PI = "~/ntcip_middleware"
PY_PI = "~/rsu-env/bin/python"
DURACION_CORTE_S = 20.0
NS = 1e9


def ssh(cmd: str, timeout: float = 60) -> str:
    r = subprocess.run(["ssh", HOST, cmd], capture_output=True, text=True, timeout=timeout)
    return r.stdout


def ssh_reintentar(cmd: str, limite_s: float = 300) -> str:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", HOST, cmd], capture_output=True, text=True,
                               timeout=60)
            if r.returncode == 0:
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    raise SystemExit(f"la Pi no respondió por SSH en {limite_s:.0f} s")


def esperar_concedida(rep: Path, limite_s: float = 150) -> bool:
    fin = time.monotonic() + limite_s
    f = rep / "eventos_servidor.csv"
    while time.monotonic() < fin:
        if f.exists() and '""estado"":""concedida""' in f.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(0.1)
    return False


def journal_ts(texto: str, patron: str, desde_ns: int) -> int | None:
    """Primera línea del journal (short-unix) que contiene `patron` después de desde_ns."""
    for ln in texto.splitlines():
        partes = ln.split(" ", 1)
        try:
            ts = int(float(partes[0]) * NS)
        except (ValueError, IndexError):
            continue
        if ts > desde_ns and patron in ln:
            return ts
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caso", required=True, choices=["rsu", "enlace4g"])
    ap.add_argument("--repeticiones", type=int, default=10)
    ap.add_argument("--semilla-base", type=int, default=700)
    args = ap.parse_args()
    base.PUERTO_BROKER = 8883  # broker de la campaña, al que se conecta el agente de la Pi
    corrida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_fallos_pi_{args.caso}"
    corrida.mkdir(parents=True)
    esc = ESCENARIOS["lazo"]
    filas = []
    for i in range(1, args.repeticiones + 1):
        rep = corrida / f"rep_{i:02d}"
        rep.mkdir()
        semilla = args.semilla_base + i
        obu_id = f"obu-fpi-{args.caso}-r{i:02d}"
        tray = rep / f"trayectoria_{obu_id}.csv"
        _trayectoria_con_ruido(FIXTURES / esc["obus"][0][1], tray, semilla, 5.0)
        t_ini_pi = int(ssh_reintentar("date +%s%N").strip())
        obs_pi = f"/tmp/obs_fallo_{i:02d}.csv"
        ssh(f"cd {DIR_PI} && nohup {PY_PI} scripts/evaluacion/observador_rsu.py --salida {obs_pi} "
            f"--duracion 220 > /dev/null 2>&1 &")
        servidor = _lanzar_servidor(rep, esc["grafo"], FIXTURES / esc["registro"], "127.0.0.1", 8883,
                                    base.TLS_DIR)
        time.sleep(random.Random(semilla + 10_000).uniform(0, 21))
        hilo = threading.Thread(target=_correr_obus, args=(rep, [(obu_id, "")], [tray], "127.0.0.1", 8883, 1.0,
                                                          base.TLS_DIR), daemon=True)
        hilo.start()
        res = {"rep": i, "caso": args.caso}
        if not esperar_concedida(rep):
            res["error"] = "sin M2 concedida"
        else:
            time.sleep(random.Random(semilla + 20_000).uniform(3.0, 8.0))
            if args.caso == "rsu":
                ssh("sudo systemctl kill -s KILL rsu-agent.service")
            else:
                print("\a\n" + "=" * 60 + "\n   DESCONECTE EL MÓDEM AHORA\n" + "=" * 60, flush=True)
                time.sleep(DURACION_CORTE_S)
                print("\a\n" + "=" * 60 + "\n   VUELVA A CONECTAR EL MÓDEM AHORA\n" + "=" * 60, flush=True)
            res["sonda"] = base._sonda(time.time_ns(), limite_s=240)
        hilo.join(timeout=240)
        time.sleep(3)
        _detener(servidor)
        # --- datos de la Pi (reloj de la Pi) -----------------------------------
        texto_obs = ssh_reintentar(f"sleep 1; cat {obs_pi}")
        (rep / "observador_pi.csv").write_text(texto_obs, encoding="utf-8")
        journal = ssh_reintentar(f"sudo journalctl -u rsu-agent.service -o short-unix --since @{t_ini_pi // 10**9}")
        (rep / "journal_agente.txt").write_text(journal, encoding="utf-8")
        eventos = ssh_reintentar(f"cd {DIR_PI} && tail -n 4000 resultados/eventos/eventos_rsu_1.csv")
        (rep / "eventos_rsu_pi.csv").write_text(eventos, encoding="utf-8")
        obs = [r for r in csv.DictReader(texto_obs.splitlines())]
        m1 = [int(r["ts_ns"]) for r in csv.DictReader(eventos.splitlines())
              if r.get("tipo_evento") == "M1_rx" and int(r["ts_ns"]) > t_ini_pi
              and not r["id_solicitud"].startswith("sonda")]
        if args.caso == "rsu":
            t_falla = journal_ts(journal, "killed", t_ini_pi) or journal_ts(journal, "Main process exited", t_ini_pi)
            t_up = t_falla
        else:
            caidas = [int(r["ts_ns"]) for r in obs if r["interfaz"] != "up"]
            t_falla = caidas[0] if caidas else None
            t_up = next((int(r["ts_ns"]) for r in obs if t_falla and int(r["ts_ns"]) > caidas[-1]
                         and r["interfaz"] == "up"), None)
        if t_falla:
            lib = next((int(r["ts_ns"]) for r in obs if int(r["ts_ns"]) > t_falla and r["prioridad_activa"] == "0"),
                       None)
            m1_antes = [t for t in m1 if t <= t_falla]
            con = journal_ts(journal, "Conectado al broker MQTT", t_up or t_falla)
            res.update(t_lib_m1_s=(lib - max(m1_antes)) / NS if lib and m1_antes else None,
                       t_lib_falla_s=(lib - t_falla) / NS if lib else None,
                       T_rec_s=(con - (t_up or t_falla)) / NS if con else None,
                       retenida=bool(obs) and obs[-1]["prioridad_activa"] == "1")
        (rep / "fallo.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        filas.append(res)
        print(f"[{args.caso} {i:02d}] t_lib(M1)={res.get('t_lib_m1_s')} T_rec={res.get('T_rec_s')} "
              f"retenida={res.get('retenida')} sonda={res.get('sonda', {}).get('intentos')} {res.get('error', '')}",
              flush=True)
    (corrida / "resultados.json").write_text(json.dumps({"caso": args.caso, "reps": filas}, indent=1, default=str),
                                             encoding="utf-8")
    print(f"Salida en {corrida}")


if __name__ == "__main__":
    main()
