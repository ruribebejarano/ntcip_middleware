#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 1): inyección de fallos con una prioridad activa
(RNF-07 fallo seguro, RNF-08 recuperación), en la condición LOCAL.

Casos (--caso):
  broker    se mata el broker MQTT (una instancia propia de esta prueba, en
            el puerto 8885, con la misma configuración TLS 1.3 + mTLS y ACL
            que la campaña) y se vuelve a lanzar 20 s después;
  servidor  se mata servidor/main.py y se vuelve a lanzar 20 s después;
  rsu       se mata agent/rsu_middleware.py (kill, sin cierre ordenado) y se
            vuelve a lanzar 2 s después, como lo hace systemd en la Raspberry
            Pi (deploy/systemd/rsu-agent.service: Restart=on-failure,
            RestartSec=2).
El corte del enlace 4G solo puede hacerse con la RSU física (procedimiento
aparte, lo ejecuta el autor).

Cada repetición: escenario `lazo` de la campaña (misma trayectoria, mismo
ruido GNSS y misma pausa aleatoria). Un observador consulta el controlador
emulado a 10 Hz por su propio protocolo. Cuando la prioridad está activa, se
espera un tiempo aleatorio de 3 a 8 s y se inyecta la falla.

Métricas por repetición:
  t_lib_falla   falla -> el controlador deja de tener la prioridad activa
  t_lib_m1      último M1 recibido por la RSU antes de la falla -> liberación
                (la referencia de RNF-07: <= T_cad + Δt = 4 s; en el caso
                rsu, por el límite de sostenimiento del controlador, 15 s)
  T_rec         restauración -> primera respuesta M2 de la RSU a una sonda
                (un M1 de prueba que esta herramienta publica con la
                identidad del servidor cada 0,5 s y luego cancela con M3)
  reanudada     si la misión en curso volvió a emitir M1 a la RSU tras la
                restauración (antes del cruce)
  retenida      si al final de la repetición el controlador sigue con una
                prioridad activa

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_fallos_<caso>/rep_XX/ con los
eventos de todos los nodos, observador.csv y fallo.json; resultados.json en
la carpeta de la corrida.

Uso: .venv/Scripts/python.exe scripts/evaluacion/inyeccion_fallos.py --caso broker [--repeticiones 10]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

import paho.mqtt.client as mqtt  # noqa: E402
from paho.mqtt.packettypes import PacketTypes  # noqa: E402
from paho.mqtt.properties import Properties  # noqa: E402

from scripts.campanas.lazo_centralizado import (  # noqa: E402
    CONTROLLER_PORT, ESCENARIOS, FIXTURES, PY, RSU_ID, SNMP_PORT, _correr_obus, _detener,
    _esperar_en_log, _esperar_puertos_libres, _lanzar_local, _lanzar_servidor, _rutas_tls,
    _trayectoria_con_ruido)

MOSQUITTO = r"C:\Program Files (x86)\Mosquitto\mosquitto.exe"
PUERTO_BROKER = 8885
TLS_DIR = RAIZ / "deploy" / "pki"
DURACION_FALLA_S = {"broker": 20.0, "servidor": 20.0, "rsu": 2.0}
PERIODO_OBS_S = 0.1
PAUSA_MAX_S = 21.0
NS = 1e9


def _lanzar_broker(salida: Path, n: int) -> subprocess.Popen:
    conf = (TLS_DIR / "mosquitto_laptop_tls.conf").read_text(encoding="utf-8")
    conf = conf.replace("listener 8883", f"listener {PUERTO_BROKER}")
    ruta = salida / "mosquitto_fallos.conf"
    ruta.write_text(conf, encoding="utf-8")
    log = salida / f"broker_{n}.log"
    p = subprocess.Popen([MOSQUITTO, "-c", str(ruta), "-v"], stdout=log.open("w"), stderr=subprocess.STDOUT)
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", PUERTO_BROKER), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise SystemExit("el broker de la prueba no abrió el puerto")


def _lanzar_agente(rep_dir: Path) -> subprocess.Popen:
    """Mismo entorno que lazo_centralizado._lanzar_local, solo el agente."""
    ca, cert, key = _rutas_tls(TLS_DIR, "rsu", RSU_ID)
    env = dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir), RSU_ID=RSU_ID, CONTROLLER_PORT=str(CONTROLLER_PORT),
               SNMP_PORT=str(SNMP_PORT), MQTT_BROKER_HOST="127.0.0.1", MQTT_BROKER_PORT=str(PUERTO_BROKER),
               RSU_TLS_CA=ca, RSU_TLS_CERT=cert, RSU_TLS_KEY=key)
    log = rep_dir / "agent_reinicio.log"
    return subprocess.Popen([PY, "-u", str(RAIZ / "agent" / "rsu_middleware.py")],
                            stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT, env=env, cwd=RAIZ)


class Observador(threading.Thread):
    """Consulta el controlador a 10 Hz; guarda (ts_ns, prioridad_activa, fase)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.muestras: list[tuple[int, bool, str]] = []
        self.parar = threading.Event()

    def run(self) -> None:
        s = socket.create_connection(("127.0.0.1", CONTROLLER_PORT), timeout=2)
        f = s.makefile("r", encoding="utf-8")
        while not self.parar.is_set():
            s.sendall(b'{"cmd": "get_status"}\n')
            e = json.loads(f.readline())
            self.muestras.append((time.time_ns(), bool(e["prioridad_activa"]), e["fase"]))
            time.sleep(PERIODO_OBS_S)
        s.close()

    def activa(self) -> bool:
        return bool(self.muestras) and self.muestras[-1][1]


def _sonda(desde_ns: int, limite_s: float = 90.0) -> dict:
    """Publica un M1 de prueba cada 0,5 s (identidad del servidor) hasta
    recibir su M2; luego lo cancela con M3. Devuelve el instante del primer
    M2 y cuántos intentos hicieron falta."""
    ca, cert, key = _rutas_tls(TLS_DIR, "servidor", None)
    recibido: dict = {}
    conectado = threading.Event()

    def on_connect(c, *_a, **_k):
        c.subscribe("servidor/central/respuestas", qos=1)
        conectado.set()

    def on_message(_c, _u, msg):
        try:
            d = json.loads(msg.payload)
        except ValueError:
            return
        if str(d.get("id_solicitud", "")).startswith("sonda-") and "ts_ns" not in recibido:
            recibido.update(ts_ns=time.time_ns(), id=d["id_solicitud"], estado=d.get("estado"))

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sonda-fallos-{uuid.uuid4().hex[:6]}",
                    protocol=mqtt.MQTTv5)
    c.tls_set(ca_certs=ca, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    c.on_connect, c.on_message = on_connect, on_message
    c.reconnect_delay_set(min_delay=0.5, max_delay=0.5)
    c.loop_start()
    try:
        c.connect_async("127.0.0.1", PUERTO_BROKER, keepalive=10)
        intentos, ids = 0, []
        while time.time_ns() - desde_ns < limite_s * NS and "ts_ns" not in recibido:
            if conectado.is_set() and c.is_connected():
                sid = f"sonda-{uuid.uuid4().hex[:6]}"
                props = Properties(PacketTypes.PUBLISH)
                props.ResponseTopic = "servidor/central/respuestas"
                props.CorrelationData = b"1"
                cuerpo = {"tipo": "M1", "id_solicitud": sid, "mision_id": "sonda", "obu_id": "sonda", "clase": 1,
                          "acceso": "S", "t_servicio": 10, "seq": 1, "ts_ms": int(time.time() * 1000),
                          "origen": "sonda"}
                c.publish(f"rsu/{RSU_ID}/solicitudes", json.dumps(cuerpo), qos=1, properties=props)
                intentos += 1
                ids.append(sid)
            time.sleep(0.5)
        if "ts_ns" in recibido:
            m3 = {"tipo": "M3", "id_solicitud": recibido["id"], "seq": 2, "motivo": "sonda",
                  "ts_ms": int(time.time() * 1000)}
            props = Properties(PacketTypes.PUBLISH)
            props.ResponseTopic = "servidor/central/respuestas"
            props.CorrelationData = b"2"
            c.publish(f"rsu/{RSU_ID}/solicitudes", json.dumps(m3), qos=1, properties=props).wait_for_publish(3)
        return {**recibido, "intentos": intentos}
    finally:
        time.sleep(0.3)
        c.loop_stop()
        c.disconnect()


def _leer_eventos(rep_dir: Path, nodo_prefijo: str) -> list[dict]:
    filas = []
    for f in rep_dir.glob(f"eventos_{nodo_prefijo}*.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["x"] = json.loads(r["extra_json"]) if r.get("extra_json") else {}
                r["ts"] = int(r["ts_ns"])
                filas.append(r)
    return sorted(filas, key=lambda r: r["ts"])


def repeticion(caso: str, rep_dir: Path, semilla: int, broker_ref: list) -> dict:
    esc = ESCENARIOS["lazo"]
    obu_id = f"obu-fallo-{caso}-r{rep_dir.name[-2:]}"
    tray = rep_dir / f"trayectoria_{obu_id}.csv"
    _trayectoria_con_ruido(FIXTURES / esc["obus"][0][1], tray, semilla, 5.0)
    pausa = random.Random(semilla + 10_000).uniform(0, PAUSA_MAX_S)
    ctrl, agent = _lanzar_local(rep_dir, TLS_DIR, "127.0.0.1", PUERTO_BROKER)
    servidor = _lanzar_servidor(rep_dir, esc["grafo"], FIXTURES / esc["registro"], "127.0.0.1", PUERTO_BROKER,
                                TLS_DIR)
    obs = Observador()
    obs.start()
    time.sleep(pausa)
    hilo_obu = threading.Thread(target=_correr_obus, args=(rep_dir, [(obu_id, "")], [tray], "127.0.0.1",
                                                           PUERTO_BROKER, 1.0, TLS_DIR), daemon=True)
    hilo_obu.start()
    res: dict = {"caso": caso, "semilla": semilla, "pausa_s": round(pausa, 2)}
    reiniciado = None
    try:
        t0 = time.monotonic()
        while not obs.activa():
            if time.monotonic() - t0 > 120 or not hilo_obu.is_alive():
                res["error"] = "la prioridad nunca se activó"
                return res
            time.sleep(0.05)
        t_act = time.time_ns()
        espera = random.Random(semilla + 20_000).uniform(3.0, 8.0)
        time.sleep(espera)
        t_falla = time.time_ns()
        if caso == "broker":
            broker_ref[0].kill()
            broker_ref[0].wait()
        elif caso == "servidor":
            servidor.kill()
            servidor.wait()
        else:
            agent.kill()
            agent.wait()
        res.update(t_activacion_ns=t_act, espera_s=round(espera, 2), t_falla_ns=t_falla)
        time.sleep(DURACION_FALLA_S[caso])
        if caso == "broker":
            broker_ref[0] = _lanzar_broker(rep_dir.parent, int(rep_dir.name[-2:]))
        elif caso == "servidor":
            shutil.copy(rep_dir / "servidor.log", rep_dir / "servidor_antes_falla.log")
            servidor = _lanzar_servidor(rep_dir, esc["grafo"], FIXTURES / esc["registro"], "127.0.0.1",
                                        PUERTO_BROKER, TLS_DIR)
        else:
            reiniciado = _lanzar_agente(rep_dir)
        t_rest = time.time_ns()
        res["t_restauracion_ns"] = t_rest
        res["sonda"] = _sonda(t_rest)
        hilo_obu.join(timeout=180)
        time.sleep(5.0)
        res["retenida"] = obs.activa()
    finally:
        obs.parar.set()
        obs.join(timeout=2)
        _detener(servidor, ctrl, agent if caso != "rsu" else None, reiniciado)
        _esperar_puertos_libres([(CONTROLLER_PORT, "tcp"), (SNMP_PORT, "udp")])
        with (rep_dir / "observador.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ts_ns", "prioridad_activa", "fase"])
            w.writerows(obs.muestras)

    # --- métricas a partir del observador y de los eventos --------------
    lib = next((ts for ts, act, _ in obs.muestras if ts > t_falla and not act), None)
    rsu = _leer_eventos(rep_dir, "rsu")
    m1_antes = [e["ts"] for e in rsu if e["tipo_evento"] == "M1_rx" and e["ts"] <= t_falla
                and not str(e["id_solicitud"]).startswith("sonda")]
    m1_despues = [e["ts"] for e in rsu if e["tipo_evento"] == "M1_rx" and e["ts"] > t_rest
                  and not str(e["id_solicitud"]).startswith("sonda")]
    res.update(
        t_lib_falla_s=(lib - t_falla) / NS if lib else None,
        t_lib_m1_s=(lib - max(m1_antes)) / NS if lib and m1_antes else None,
        T_rec_s=(res["sonda"]["ts_ns"] - t_rest) / NS if res.get("sonda", {}).get("ts_ns") else None,
        reanudada=bool(m1_despues),
        caducidad_rsu=any(e["tipo_evento"] == "caducidad" for e in rsu),
    )
    (rep_dir / "fallo.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caso", required=True, choices=list(DURACION_FALLA_S))
    ap.add_argument("--repeticiones", type=int, default=10)
    ap.add_argument("--semilla-base", type=int, default=500)
    args = ap.parse_args()
    corrida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_fallos_{args.caso}"
    corrida.mkdir(parents=True)
    broker = [_lanzar_broker(corrida, 0)]
    filas = []
    try:
        for i in range(1, args.repeticiones + 1):
            rep_dir = corrida / f"rep_{i:02d}"
            rep_dir.mkdir()
            r = repeticion(args.caso, rep_dir, args.semilla_base + i, broker)
            filas.append(r)
            print(f"[{args.caso} {i:02d}] t_lib(falla)={r.get('t_lib_falla_s')} t_lib(M1)={r.get('t_lib_m1_s')} "
                  f"T_rec={r.get('T_rec_s')} reanudada={r.get('reanudada')} retenida={r.get('retenida')} "
                  f"{r.get('error', '')}", flush=True)
    finally:
        _detener(broker[0])
    (corrida / "resultados.json").write_text(json.dumps({"caso": args.caso, "reps": filas}, indent=1),
                                             encoding="utf-8")
    print(f"Salida en {corrida}")


if __name__ == "__main__":
    main()
