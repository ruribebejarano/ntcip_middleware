#!/usr/bin/env python3
"""OE3 (Fase 4, prueba 4): costo de SNMPv3 por nivel de seguridad en la RSU.

Lanza una instancia APARTE del agente (agent/rsu_middleware.py) y de su
controlador emulado, en puertos propios (SNMP 1171, controlador 9171,
RSU_ID 171) y con un broker MQTT local sin TLS (el agente lo necesita para
arrancar; aquí no se usa). El agente de operación no se toca. La instancia
arranca con:
  RSU_SNMP_USUARIOS_LAB=1   usuarios lab-noauth (noAuthNoPriv) y lab-auth
                            (authNoPriv, SHA-256) además del de operación
                            (authPriv, SHA-256 + AES-128);
  RSU_SNMP_MEDIR_PROC=<csv> marca de llegada del datagrama y de salida de
                            la respuesta en el propio agente.
El gestor, en la MISMA máquina (loopback), escribe phaseMinimumGreen.1 con su
mismo valor (no altera el ciclo) en bloques de 100, intercalando los tres
niveles, hasta --por-nivel escrituras por nivel. Métrica principal: tiempo de
procesamiento en el agente (salida - llegada); además, el RTT en el gestor y
los bytes de cada solicitud y respuesta.

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_snmp_niveles_<etiqueta>/
  proc_agente.csv, solicitudes.csv, resumen.json, tabla_snmp_niveles.tex

Uso (raíz del repo; en la Raspberry Pi para el resultado de la tesis):
  python3 scripts/evaluacion/snmp_niveles.py --etiqueta pi [--por-nivel 1000] [--broker-port 1883]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

import asyncio  # noqa: E402

# API asíncrona: con este commit de pysnmp, la API síncrona cierra el
# transporte al terminar cada llamada y no permite reutilizar el motor.
from pysnmp.hlapi.asyncio import (  # noqa: E402
    ContextData, Integer, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, UsmUserData, setCmd,
    usmAesCfb128Protocol, usmHMAC192SHA256AuthProtocol)

SNMP_PORT, CTRL_PORT, RSU_ID = 1171, 9171, "171"
OID_VERDE_MIN = "1.3.6.1.4.1.1206.4.2.1.1.2.1.4.1"
AUTH, PRIV = "labAuthPass123", "labPrivPass123"  # claves de laboratorio del agente (agent/rsu_middleware.py)
NIVELES = {
    "noAuthNoPriv": UsmUserData("lab-noauth"),
    "authNoPriv": UsmUserData("lab-auth", authKey=AUTH, authProtocol=usmHMAC192SHA256AuthProtocol),
    "authPriv": UsmUserData("rsuLabUser", authKey=AUTH, privKey=PRIV, authProtocol=usmHMAC192SHA256AuthProtocol,
                            privProtocol=usmAesCfb128Protocol),
}
BLOQUE = 100


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


async def escribir(motor, usuario, destino):
    return await setCmd(motor, usuario, destino, ContextData(),
                        ObjectType(ObjectIdentity(OID_VERDE_MIN), Integer(8)))


async def medir(args, proc_csv: Path, filas: list, bloques: list) -> None:
    motor = SnmpEngine()
    destino = UdpTransportTarget(("127.0.0.1", SNMP_PORT), timeout=2, retries=0)
    for u in NIVELES.values():  # calentamiento: descubrimiento del engineID y sincronización de tiempo
        await escribir(motor, u, destino)
    for b in range(args.por_nivel // BLOQUE):
        for n, u in NIVELES.items():
            antes = lineas(proc_csv)
            for _ in range(BLOQUE):
                t0 = time.perf_counter_ns()
                ei, es, _ix, _vb = await escribir(motor, u, destino)
                t1 = time.perf_counter_ns()
                filas.append((b, n, (t1 - t0) / 1e6, str(ei or es or "")))
            bloques.append((n, antes, lineas(proc_csv)))
        print(f"bloque {b + 1}/{args.por_nivel // BLOQUE}", flush=True)


def lineas(ruta: Path) -> int:
    return sum(1 for _ in ruta.open(encoding="utf-8")) if ruta.exists() else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--etiqueta", required=True)
    ap.add_argument("--por-nivel", type=int, default=1000)
    ap.add_argument("--broker-port", type=int, default=1883)
    args = ap.parse_args()
    salida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_snmp_niveles_{args.etiqueta}"
    salida.mkdir(parents=True)
    proc_csv = salida / "proc_agente.csv"
    env = dict(os.environ, RSU_ID=RSU_ID, SNMP_PORT=str(SNMP_PORT), CONTROLLER_PORT=str(CTRL_PORT),
               MQTT_BROKER_HOST="127.0.0.1", MQTT_BROKER_PORT=str(args.broker_port), RSU_EVENTOS_DIR=str(salida),
               RSU_SNMP_USUARIOS_LAB="1", RSU_SNMP_MEDIR_PROC=str(proc_csv), PYTHONIOENCODING="utf-8")
    for k in ("RSU_TLS_CA", "RSU_TLS_CERT", "RSU_TLS_KEY"):
        env.pop(k, None)
    ctrl = subprocess.Popen([sys.executable, "-u", str(RAIZ / "controller" / "controller_emulator.py"), "--port",
                             str(CTRL_PORT)], stdout=(salida / "controller.log").open("w"),
                            stderr=subprocess.STDOUT, env=env, cwd=RAIZ)
    time.sleep(2.0)
    agente = subprocess.Popen([sys.executable, "-u", str(RAIZ / "agent" / "rsu_middleware.py")],
                              stdout=(salida / "agent.log").open("w"), stderr=subprocess.STDOUT, env=env, cwd=RAIZ)
    time.sleep(6.0)
    filas, bloques = [], []
    try:
        asyncio.run(medir(args, proc_csv, filas, bloques))
    finally:
        agente.terminate()
        ctrl.terminate()
        agente.wait(10)
        ctrl.wait(10)
    with (salida / "solicitudes.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bloque", "nivel", "rtt_gestor_ms", "error"])
        w.writerows(filas)
    with proc_csv.open(encoding="utf-8") as fh:
        proc = list(csv.DictReader(fh))
    res = {"etiqueta": args.etiqueta, "por_nivel": args.por_nivel, "niveles": {}}
    for n in NIVELES:
        filas_ag = []
        for nb, a, d in bloques:
            if nb == n:
                filas_ag += proc[a - 1:d - 1][-BLOQUE:]  # -1: encabezado del CSV
        t = [(int(r["t_out_ns"]) - int(r["t_in_ns"])) / 1e6 for r in filas_ag]
        rtt = [x for _b, nn, x, e in filas if nn == n and not e]
        errores = sum(1 for _b, nn, _x, e in filas if nn == n and e)
        res["niveles"][n] = {"n": len(t), "proc_med_ms": pct(t, 50), "proc_p95_ms": pct(t, 95),
                             "proc_max_ms": max(t), "rtt_med_ms": pct(rtt, 50), "rtt_p95_ms": pct(rtt, 95),
                             "bytes_solicitud": int(pct([int(r["bytes_in"]) for r in filas_ag], 50)),
                             "bytes_respuesta": int(pct([int(r["bytes_out"]) for r in filas_ag], 50)),
                             "errores": errores}
    (salida / "resumen.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    coma = lambda x, d=2: f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    fil = [f"{n} & {s['n']} & {coma(s['proc_med_ms'])} & {coma(s['proc_p95_ms'])} & {coma(s['rtt_med_ms'])} & "
           f"{s['bytes_solicitud']} / {s['bytes_respuesta']} & {s['errores']} \\\\" for n, s in res["niveles"].items()]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Costo de SNMPv3 por nivel de seguridad]{Costo de SNMPv3 por "
           "nivel de seguridad en la RSU: escrituras de \\texttt{phaseMinimumGreen} desde un gestor en la misma "
           "máquina, en bloques de 100 intercalados entre niveles. El procesamiento se mide en el agente, desde la "
           "llegada del datagrama hasta la salida de la respuesta; autenticación con SHA-256 y cifrado con "
           "AES-128.}\n\\label{tab:snmp_niveles}\n\\small\n\\begin{tabular}{lrrrrrr}\n\\toprule\n"
           "\\textbf{Nivel} & \\textbf{n} & \\textbf{Proc. med. (ms)} & \\textbf{Proc. p95 (ms)} & "
           "\\textbf{RTT med. (ms)} & \\textbf{Bytes sol./resp.} & \\textbf{Errores} \\\\\n\\midrule\n" +
           "\n".join(fil) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_snmp_niveles.tex").write_text(tex, encoding="utf-8")
    print(json.dumps(res, indent=1))
    print(f"Salida en {salida}")


if __name__ == "__main__":
    main()
