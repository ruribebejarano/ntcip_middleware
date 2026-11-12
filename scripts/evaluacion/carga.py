#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 2): carga del servidor central y del broker con
N misiones simultáneas, N ∈ {1, 10, 50, 100}, en la condición LOCAL.

Topología (opción A del diseño aprobado): una RSU por misión, para que la
carga que crece sea la del servidor y la del broker, no los conflictos.
  - Grafo sintético con 100 calles paralelas (copias desplazadas de la
    recta de la campaña, separadas 0,012° de longitud, ~1,3 km), cada una
    con su intersección y su RSU (ids 201..300). Coordenadas inventadas.
  - Las RSU 201..203 son reales (agent/rsu_middleware.py + controlador
    emulado); el resto son RSU SINTÉTICAS: un cliente MQTT 5 con TLS 1.3 y
    mTLS por RSU (su propio certificado), que responde cada M1/M3 con un M2
    por el Response Topic con su Correlation Data, sin SNMP ni controlador.
  - Las N OBU son instancias de gateway/obu_emulada.py::ObuEmulada (el
    mismo código de la campaña), en hilos de un solo proceso, para no
    lanzar 100 intérpretes en un equipo con poca memoria libre.
  - Broker TLS de la campaña (8883) y servidor/main.py sin cambios.
Las N misiones arrancan escalonadas en 0..5 s y duran ~88 s.

Métricas por repetición (3 por N):
  decisión del servidor  M1_tx - último MP_rx de esa misión (reloj del servidor)
  RTT servidor--RSU      M1_tx -> M2_rx de cada par (reloj del servidor)
  entrega                MP_rx/MP_tx y M2 recibidos/M1 enviados
  CPU y memoria          psutil a 1 Hz: servidor, broker, RSU reales,
                         proceso de RSU sintéticas y proceso de OBU

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_carga/ con N_<n>_rep_<k>/
(eventos, logs, recursos.csv) y resultados.json.

Uso: .venv/Scripts/python.exe scripts/evaluacion/carga.py [--n 1 10 50 100] [--repeticiones 3]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import ssl
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

import networkx as nx  # noqa: E402

from gateway.geometria import proyeccion_local  # noqa: E402
from scripts.campanas.lazo_centralizado import (  # noqa: E402
    FIXTURES, PY, _detener, _esperar_en_log, _rutas_tls, _trayectoria_con_ruido)

TLS_DIR = RAIZ / "deploy" / "pki"
BROKER = ("127.0.0.1", 8883)
N_MAX = 100
DLON = 0.012
RSU_BASE = 201
N_REALES = 3
CTRL_BASE, SNMP_BASE = 9201, 1281
NODOS_RECTA = [("A", -12.1100), ("B", -12.1087), ("C", -12.1074), ("D", -12.1061), ("E", -12.1048),
               ("F", -12.1035), ("G", -12.1022)]
LON0 = -77.0320


def construir_mundo(dir_: Path) -> tuple[Path, Path, list[Path]]:
    G = nx.DiGraph()
    rsus = []
    for k in range(N_MAX):
        lon = LON0 + k * DLON
        nodos = [(f"{n}{k}", lat, lon) for n, lat in NODOS_RECTA]
        for nid, lat, lo in nodos:
            G.add_node(nid, x=lo, y=lat)
        for (n1, la1, lo1), (n2, la2, lo2) in zip(nodos[:-1], nodos[1:]):
            d = math.hypot(*proyeccion_local(la2, lo2, la1, lo1))
            G.add_edge(n1, n2, length=d)
            G.add_edge(n2, n1, length=d)
        rsus.append({"rsu_id": str(RSU_BASE + k), "interseccion_id": f"C{k}", "codigo_mml": None,
                     "centro": {"lat": -12.1074, "lon": lon},
                     "accesos": [{"acceso_id": "S", "rumbo_llegada_deg": 0.0, "grupo_semaforico": 1}]})
    grafo = dir_ / "grafo_carga.graphml"
    nx.write_graphml(G, str(grafo))
    registro = dir_ / "registro_carga.json"
    registro.write_text(json.dumps({"version": "carga-sintetica", "descripcion": "SINTETICO: 100 calles "
                                    "paralelas, una RSU por calle (scripts/evaluacion/carga.py)", "rsu": rsus},
                                   indent=1), encoding="utf-8")
    base = FIXTURES / "trayectoria_lazo_base.csv"
    with base.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    trays = []
    for k in range(N_MAX):
        p = dir_ / f"tray_base_{k:03d}.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0]))
            w.writeheader()
            for f in filas:
                w.writerow({**f, "lon": f"{float(f['lon']) + k * DLON:.7f}"})
        trays.append(p)
    return grafo, registro, trays


# --- proceso hijo: N OBU en hilos -----------------------------------------

def modo_obus(args) -> None:
    from gateway.obu_emulada import ObuEmulada
    obus = []
    for k, tray in enumerate(args.trayectorias):
        ns = argparse.Namespace(broker_host=BROKER[0], broker_port=BROKER[1], trayectoria=tray,
                                obu_id=f"obu-carga-{args.etiqueta}-{k:03d}", clase_tipo=1, factor=1.0,
                                espera_final=3.0, tls_ca=args.tls[0], tls_cert=None, tls_key=None)
        ca, cert, key = _rutas_tls(TLS_DIR, "obu", ns.obu_id)
        ns.tls_ca, ns.tls_cert, ns.tls_key = ca, cert, key
        obus.append(ObuEmulada(ns))
    rnd = random.Random(args.semilla)
    hilos = []
    for o in obus:
        h = threading.Thread(target=o.correr, daemon=True)
        hilos.append(h)
    print("OBUS_LISTAS", flush=True)
    for h in hilos:
        h.start()
        time.sleep(rnd.uniform(0, 5.0 / max(1, len(hilos))))
    for h in hilos:
        h.join()
    print("OBUS_FIN", flush=True)


# --- proceso hijo: RSU sintéticas -----------------------------------------

def modo_rsus(args) -> None:
    import paho.mqtt.client as mqtt
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    from common.events import EventLogger

    clientes, conectadas = [], threading.Semaphore(0)
    for rid in args.rsu_ids:
        ev = EventLogger(f"rsu_{rid}")
        ca, cert, key = _rutas_tls(TLS_DIR, "rsu", rid)
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"rsu-sintetica-{rid}", protocol=mqtt.MQTTv5)
        c.tls_set(ca_certs=ca, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        def on_connect(cl, _u, _f, _rc, _p=None, rid=rid):
            cl.subscribe(f"rsu/{rid}/solicitudes", qos=1)
            conectadas.release()

        def on_message(cl, _u, msg, ev=ev):
            d = json.loads(msg.payload)
            tipo, sid, seq = d.get("tipo"), str(d.get("id_solicitud")), d.get("seq")
            ev.log("M1_rx" if tipo == "M1" else "M3_rx", sid, seq=seq)
            props_in = msg.properties
            rt = getattr(props_in, "ResponseTopic", None)
            if not rt:
                return
            props = Properties(PacketTypes.PUBLISH)
            corr = getattr(props_in, "CorrelationData", None)
            if corr is not None:
                props.CorrelationData = corr
            cuerpo = {"tipo": "M2", "id_solicitud": sid, "estado": "concedida" if tipo == "M1" else "cancelada",
                      "fase": "verde", "seq_ref": seq, "ts_ms": int(time.time() * 1000)}
            cl.publish(rt, json.dumps(cuerpo), qos=1, properties=props)
            ev.log("M2_tx", sid, seq_ref=seq, estado=cuerpo["estado"])

        c.on_connect, c.on_message = on_connect, on_message
        c.connect(*BROKER, keepalive=30)
        c.loop_start()
        clientes.append(c)
    for _ in args.rsu_ids:
        conectadas.acquire(timeout=60)
    print("RSUS_LISTAS", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


# --- orquestador -----------------------------------------------------------

def _leer(rep: Path, patron: str) -> list[dict]:
    out = []
    for f in rep.glob(patron):
        with f.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["x"] = json.loads(r["extra_json"]) if r.get("extra_json") else {}
                r["ts"] = int(r["ts_ns"])
                out.append(r)
    return sorted(out, key=lambda r: r["ts"])


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def pid_broker() -> int | None:
    import psutil
    for c in psutil.net_connections("tcp"):
        if c.laddr and c.laddr.port == BROKER[1] and c.status == psutil.CONN_LISTEN:
            return c.pid
    return None


def repeticion(n: int, rep: Path, grafo: Path, registro: Path, trays: list[Path], semilla: int) -> dict:
    import psutil
    rnd = random.Random(semilla)
    ids = [str(RSU_BASE + k) for k in range(n)]
    reales, sinteticas = ids[:N_REALES], ids[N_REALES:]
    env_base = dict(os.environ, RSU_EVENTOS_DIR=str(rep), PYTHONIOENCODING="utf-8")
    procesos, roles = [], {}
    # RSU reales
    for k, rid in enumerate(reales):
        e = dict(env_base, RSU_ID=rid)
        lc = rep / f"controller_{rid}.log"
        p = subprocess.Popen([PY, "-u", str(RAIZ / "controller" / "controller_emulator.py"), "--port",
                              str(CTRL_BASE + k), "--desfase-s", f"{rnd.uniform(0, 21):.2f}"],
                             stdout=lc.open("w"), stderr=subprocess.STDOUT, env=e, cwd=RAIZ)
        procesos.append(p)
        _esperar_en_log(lc, "escuchando en", timeout=30)
        ca, cert, key = _rutas_tls(TLS_DIR, "rsu", rid)
        e.update(CONTROLLER_PORT=str(CTRL_BASE + k), SNMP_PORT=str(SNMP_BASE + k), MQTT_BROKER_HOST=BROKER[0],
                 MQTT_BROKER_PORT=str(BROKER[1]), RSU_TLS_CA=ca, RSU_TLS_CERT=cert, RSU_TLS_KEY=key)
        la = rep / f"agent_{rid}.log"
        p = subprocess.Popen([PY, "-u", str(RAIZ / "agent" / "rsu_middleware.py")], stdout=la.open("w"),
                             stderr=subprocess.STDOUT, env=e, cwd=RAIZ)
        procesos.append(p)
        roles[p.pid] = "rsu_real"
        if not _esperar_en_log(la, "[middleware] Conectado al broker MQTT", timeout=60):
            raise SystemExit(f"agente {rid} sin conectar, ver {la}")
    # RSU sintéticas
    if sinteticas:
        ls = rep / "rsus_sinteticas.log"
        p = subprocess.Popen([PY, "-u", __file__, "--modo", "rsus", "--rsu-ids", *sinteticas], stdout=ls.open("w"),
                             stderr=subprocess.STDOUT, env=env_base, cwd=RAIZ)
        procesos.append(p)
        roles[p.pid] = "rsu_sinteticas"
        if not _esperar_en_log(ls, "RSUS_LISTAS", timeout=180):
            raise SystemExit(f"RSU sintéticas sin conectar, ver {ls}")
    # servidor
    ca, cert, key = _rutas_tls(TLS_DIR, "servidor", None)
    lsv = rep / "servidor.log"
    srv = subprocess.Popen([PY, "-u", str(RAIZ / "servidor" / "main.py")], stdout=lsv.open("w"),
                           stderr=subprocess.STDOUT, cwd=RAIZ,
                           env=dict(env_base, GRAFO_SINTETICO="0", GRAFO_PATH=str(grafo),
                                    REGISTRO_RSU_PATH=str(registro), MQTT_BROKER_HOST=BROKER[0],
                                    MQTT_BROKER_PORT=str(BROKER[1]), SERVIDOR_TLS_CA=ca, SERVIDOR_TLS_CERT=cert,
                                    SERVIDOR_TLS_KEY=key))
    procesos.append(srv)
    roles[srv.pid] = "servidor"
    if not _esperar_en_log(lsv, "[servidor] Conectado al broker", timeout=60):
        raise SystemExit(f"servidor sin conectar, ver {lsv}")
    # trayectorias con ruido
    trs = []
    for k in range(n):
        d = rep / f"trayectoria_{k:03d}.csv"
        _trayectoria_con_ruido(trays[k], d, semilla * 1000 + k, 5.0)
        trs.append(str(d))
    lo = rep / "obus.log"
    obus = subprocess.Popen([PY, "-u", __file__, "--modo", "obus", "--etiqueta", rep.name, "--semilla",
                             str(semilla), "--trayectorias", *trs], stdout=lo.open("w", encoding="utf-8"),
                            stderr=subprocess.STDOUT, env=env_base, cwd=RAIZ)
    roles[obus.pid] = "obus"
    roles[pid_broker()] = "broker"
    # muestreo de recursos a 1 Hz hasta que terminan las OBU
    ps = {pid: psutil.Process(pid) for pid in roles if pid}
    for p in ps.values():
        p.cpu_percent(None)
    muestras = []
    while obus.poll() is None:
        time.sleep(1.0)
        t = time.time_ns()
        for pid, p in ps.items():
            try:
                muestras.append((t, roles[pid], pid, p.cpu_percent(None), p.memory_info().rss / 2**20))
            except psutil.Error:
                pass
    time.sleep(3.0)
    _detener(*procesos)
    with (rep / "recursos.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_ns", "rol", "pid", "cpu_pct", "rss_mb"])
        w.writerows(muestras)

    # --- métricas ------------------------------------------------------------
    srv_ev = _leer(rep, "eventos_servidor*.csv")
    obu_ev = _leer(rep, "eventos_obu-carga-*.csv")
    mision_obu = {e["id_solicitud"]: e["x"].get("obu_id") for e in srv_ev if e["tipo_evento"] == "mision_armada"}
    ultimo_mp, decision = {}, []
    m1_tx, m2_rx = {}, {}
    for e in srv_ev:
        if e["tipo_evento"] == "MP_rx":  # id_ref = mision_id
            ultimo_mp[e["id_solicitud"]] = e["ts"]
        elif e["tipo_evento"] == "M1_tx":
            mid = e["x"].get("mision_id")
            if mid in ultimo_mp:
                decision.append((e["ts"] - ultimo_mp[mid]) / 1e6)
            m1_tx[(e["id_solicitud"], e["x"].get("seq"))] = e["ts"]
        elif e["tipo_evento"] == "M2_rx":
            m2_rx.setdefault((e["id_solicitud"], e["x"].get("seq_ref")), e["ts"])
    rtt = [(m2_rx[k] - t) / 1e6 for k, t in m1_tx.items() if k in m2_rx]
    mp_tx = sum(1 for e in obu_ev if e["tipo_evento"] == "MP_tx")
    mp_rx = sum(1 for e in srv_ev if e["tipo_evento"] == "MP_rx")
    rec = defaultdict(list)
    for _t, rol, _pid, cpu, mem in muestras:
        rec[rol].append((cpu, mem))
    # por instante: suma de los procesos de un mismo rol
    por_t = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for t, rol, _pid, cpu, mem in muestras:
        por_t[rol][t][0] += cpu
        por_t[rol][t][1] += mem
    recursos = {rol: {"cpu_med": pct([v[0] for v in d.values()], 50), "cpu_p95": pct([v[0] for v in d.values()], 95),
                      "rss_max_mb": max(v[1] for v in d.values())} for rol, d in por_t.items()}
    return {"n": n, "rep": rep.name, "misiones_armadas": len(mision_obu),
            "decision_ms": {"n": len(decision), "med": pct(decision, 50), "p95": pct(decision, 95),
                            "max": max(decision) if decision else None},
            "rtt_ms": {"n": len(rtt), "med": pct(rtt, 50), "p95": pct(rtt, 95), "max": max(rtt) if rtt else None},
            "m1_enviados": len(m1_tx), "m2_recibidos": len(rtt), "mp_tx": mp_tx, "mp_rx": mp_rx,
            "recursos": recursos}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modo", choices=["orquestar", "obus", "rsus"], default="orquestar")
    ap.add_argument("--n", type=int, nargs="+", default=[1, 10, 50, 100])
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--trayectorias", nargs="*")
    ap.add_argument("--rsu-ids", nargs="*")
    ap.add_argument("--etiqueta", default="")
    ap.add_argument("--semilla", type=int, default=1)
    args = ap.parse_args()
    if args.modo == "obus":
        args.tls = (None,)
        return modo_obus(args)
    if args.modo == "rsus":
        return modo_rsus(args)
    if pid_broker() is None:
        raise SystemExit("No hay broker TLS escuchando en 8883")
    corrida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_carga"
    corrida.mkdir(parents=True)
    grafo, registro, trays = construir_mundo(corrida)
    resultados = []
    for rep_k in range(1, args.repeticiones + 1):
        for n in args.n:  # N intercalados entre repeticiones
            rep = corrida / f"N_{n:03d}_rep_{rep_k}"
            rep.mkdir()
            r = repeticion(n, rep, grafo, registro, trays, semilla=100 * n + rep_k)
            resultados.append(r)
            print(f"N={n:3d} rep {rep_k}: misiones {r['misiones_armadas']}, decisión p95 "
                  f"{r['decision_ms']['p95']}, RTT p50/p95 {r['rtt_ms']['med']}/{r['rtt_ms']['p95']}, "
                  f"M2 {r['m2_recibidos']}/{r['m1_enviados']}, MP {r['mp_rx']}/{r['mp_tx']}, "
                  f"CPU servidor p95 {r['recursos'].get('servidor', {}).get('cpu_p95')}", flush=True)
            (corrida / "resultados.json").write_text(json.dumps(resultados, indent=1), encoding="utf-8")
    print(f"Salida en {corrida}")


if __name__ == "__main__":
    main()
