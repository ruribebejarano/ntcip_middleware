#!/usr/bin/env python3
"""Tablas y figuras de las pruebas de la Fase 4 que no las generan sus
propios scripts: carga (prueba 2), handshake (3) y bytes por mensaje (5).
Las de fallos (1), SNMPv3 (4), conflicto (6), direccionamiento (7) y
recuperación del plan (8) las escriben fallos_resumen.py, snmp_niveles.py,
conflicto_resumen.py, direccionamiento_ruido.py y recuperacion_plan.py;
scripts/analisis/generar_fase4.sh reúne todo.

Uso: .venv/Scripts/python.exe scripts/evaluacion/resumen_fase4.py \
        --carga <dir> --handshake-4g <dir> --handshake-wifi <dir> \
        --bytes-tls <dir> --bytes-sin-tls <dir> --salida <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

RSU_REALES = {"201", "202", "203"}
SOBRECARGA_TLS13 = 22  # encabezado 5 + tipo de contenido 1 + etiqueta AES-GCM 16


def pct(v, p):
    if not v:
        return float("nan")
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def coma(x, d=1):
    return "--" if x != x else f"{x:.{d}f}".replace(".", ",")


def leer(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for r in filas:
        r["x"] = json.loads(r["extra_json"]) if r.get("extra_json") else {}
        r["ts"] = int(r["ts_ns"])
    return filas


# --- carga ---------------------------------------------------------------

def carga(dir_: Path, salida: Path) -> dict:
    res = json.loads((dir_ / "resultados.json").read_text(encoding="utf-8"))
    por_n: dict[int, dict] = defaultdict(lambda: defaultdict(list))
    for r in res:
        rep = dir_ / r["rep"]
        srv = leer(rep / "eventos_servidor.csv")
        m1 = {}
        for e in srv:
            if e["tipo_evento"] == "M1_tx":
                m1[(e["id_solicitud"], e["x"].get("seq"))] = (e["ts"], e["x"].get("rsu_id"))
        for e in srv:
            if e["tipo_evento"] == "M2_rx":
                k = (e["id_solicitud"], e["x"].get("seq_ref"))
                if k in m1:
                    t, rsu = m1.pop(k)
                    por_n[r["n"]]["rtt_real" if rsu in RSU_REALES else "rtt_sint"].append((e["ts"] - t) / 1e6)
        ultimo_mp, dec = {}, []
        for e in srv:
            if e["tipo_evento"] == "MP_rx":
                ultimo_mp[e["id_solicitud"]] = e["ts"]
            elif e["tipo_evento"] == "M1_tx" and e["x"].get("mision_id") in ultimo_mp:
                dec.append((e["ts"] - ultimo_mp[e["x"]["mision_id"]]) / 1e6)
        por_n[r["n"]]["decision"] += dec
        por_t = defaultdict(lambda: defaultdict(float))
        rss = defaultdict(float)
        with (rep / "recursos.csv").open(newline="") as fh:
            for m in csv.DictReader(fh):
                por_t[m["rol"]][m["ts_ns"]] += float(m["cpu_pct"])
                rss[m["rol"]] = max(rss[m["rol"]], float(m["rss_mb"]))
        for rol, d in por_t.items():
            por_n[r["n"]][f"cpu_{rol}"] += list(d.values())
            por_n[r["n"]][f"rss_{rol}"].append(rss[rol])
        por_n[r["n"]]["mp"].append((r["mp_rx"], r["mp_tx"]))
        por_n[r["n"]]["m2"].append((r["m2_recibidos"], r["m1_enviados"]))
        por_n[r["n"]]["misiones"].append(r["misiones_armadas"])
    filas, resumen = [], {}
    for n in sorted(por_n):
        d = por_n[n]
        mp_rx, mp_tx = map(sum, zip(*d["mp"]))
        m2_rx, m1_tx = map(sum, zip(*d["m2"]))
        s = {"repeticiones": len(d["misiones"]), "misiones": sum(d["misiones"]),
             "decision_med": pct(d["decision"], 50), "decision_p95": pct(d["decision"], 95),
             "rtt_real_n": len(d["rtt_real"]), "rtt_real_med": pct(d["rtt_real"], 50),
             "rtt_real_p95": pct(d["rtt_real"], 95), "rtt_sint_med": pct(d["rtt_sint"], 50),
             "rtt_sint_p95": pct(d["rtt_sint"], 95), "mp": [mp_rx, mp_tx], "m2": [m2_rx, m1_tx],
             "cpu_servidor_p95": pct(d["cpu_servidor"], 95), "cpu_broker_p95": pct(d["cpu_broker"], 95),
             "cpu_rsu_real_p95": pct(d.get("cpu_rsu_real", []), 95),
             "rss_servidor_max": max(d["rss_servidor"]), "rss_broker_max": max(d["rss_broker"])}
        resumen[n] = s
        filas.append(f"{n} & {coma(s['decision_med'], 2)} / {coma(s['decision_p95'], 2)} & "
                     f"{coma(s['rtt_real_med'])} / {coma(s['rtt_real_p95'])} & "
                     f"{coma(s['rtt_sint_med'])} / {coma(s['rtt_sint_p95'])} & "
                     f"{mp_tx - mp_rx} / {m1_tx - m2_rx} de {mp_tx} / {m1_tx} & {coma(s['cpu_servidor_p95'])} & "
                     f"{coma(s['cpu_broker_p95'])} \\\\")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Carga del servidor y del broker]{Carga del servidor "
           "central y del \\emph{broker} con $N$ misiones simultáneas, una RSU por misión (tres RSU completas y "
           "el resto sintéticas, que responden M2 sin controlador), tres repeticiones por $N$ en la condición "
           "local. Decisión: desde el último MP de la misión hasta su M1 (reloj del servidor). RTT: pares M1/M2 "
           "con las RSU completas y con las sintéticas. CPU: percentil 95 de las muestras a 1~Hz, en "
           "porcentaje de un núcleo. Pérdidas: mensajes enviados y no recibidos, sobre el total enviado en las "
           "tres repeticiones.}\n\\label{tab:carga}\n\\footnotesize\n"
           "\\begin{tabular}{r>{\\centering\\arraybackslash}p{1.7cm}>{\\centering\\arraybackslash}p{1.8cm}"
           ">{\\centering\\arraybackslash}p{1.6cm}>{\\centering\\arraybackslash}p{2.8cm}"
           ">{\\centering\\arraybackslash}p{1.3cm}>{\\centering\\arraybackslash}p{1.4cm}}\n\\toprule\n"
           "$N$ & \\textbf{Decisión med./p95 (ms)} & \\textbf{RTT RSU compl. med./p95 (ms)} & "
           "\\textbf{RTT sint. med./p95 (ms)} & \\textbf{Pérdidas MP / M2} & \\textbf{CPU srv. p95 (\\%)} & "
           "\\textbf{CPU broker p95 (\\%)} \\\\\n\\midrule\n" + "\n".join(filas) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_carga.tex").write_text(tex, encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ns = sorted(resumen)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.8))
    a1.plot(ns, [resumen[n]["decision_p95"] for n in ns], "o-", color="#4C72B0", label="Decisión p95")
    a1.plot(ns, [resumen[n]["rtt_real_p95"] for n in ns], "s--", color="#55A868", label="RTT RSU completas p95")
    a1.set_xlabel("Misiones simultáneas $N$")
    a1.set_ylabel("ms")
    a1.set_xscale("log")
    a1.set_xticks(ns, [str(n) for n in ns])
    a1.grid(alpha=0.3)
    a1.legend(fontsize=7)
    a2.plot(ns, [resumen[n]["cpu_servidor_p95"] for n in ns], "o-", color="#4C72B0", label="Servidor")
    a2.plot(ns, [resumen[n]["cpu_broker_p95"] for n in ns], "s--", color="#C44E52", label="Broker")
    a2.set_xlabel("Misiones simultáneas $N$")
    a2.set_ylabel("CPU p95 (% de un núcleo)")
    a2.set_xscale("log")
    a2.set_xticks(ns, [str(n) for n in ns])
    a2.grid(alpha=0.3)
    a2.legend(fontsize=7)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(salida / f"fig_carga.{ext}", dpi=200)
    plt.close(fig)
    return resumen


# --- handshake -------------------------------------------------------------

NOMBRE_CASO = {"tcp": "TCP sin TLS (línea base)", "tls13": "TLS 1.3, completo",
               "tls13_res": "TLS 1.3, sesión reanudada", "tls12": "TLS 1.2, completo"}


def handshake(dirs: dict[str, Path], salida: Path) -> dict:
    filas, resumen = [], {}
    for enlace, d in dirs.items():
        with (d / "handshake.csv").open(newline="", encoding="utf-8") as fh:
            r = list(csv.DictReader(fh))
        filas.append(f"\\multicolumn{{6}}{{l}}{{\\textbf{{{enlace}}}}} \\\\")
        for caso, nombre in NOMBRE_CASO.items():
            x = [y for y in r if y["caso"] == caso and not y["error"]]
            err = sum(1 for y in r if y["caso"] == caso and y["error"])
            t = [float(y["t_total_ms"]) for y in x]
            tls = [float(y["t_tls_ms"]) for y in x]
            b = [int(y["hs_sub"]) + int(y["hs_baj"]) + int(y["mqtt_sub"]) + int(y["mqtt_baj"]) for y in x]
            s = {"n": len(x), "errores": err, "total_med": pct(t, 50), "total_p95": pct(t, 95),
                 "tls_med": pct(tls, 50), "bytes_med": pct(b, 50),
                 "reanudadas": sum(y["reanudada"] == "True" for y in x)}
            resumen[f"{enlace}|{caso}"] = s
            filas.append(f"\\quad {nombre} & {s['n']} & {coma(s['total_med'])} & {coma(s['total_p95'])} & "
                         f"{coma(s['tls_med'])} & {coma(s['bytes_med'], 0)} \\\\")
        filas.append("\\addlinespace")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Costo de establecer la conexión segura]{Costo de "
           "establecer la conexión con el \\emph{broker} desde la RSU, por enlace: desde el inicio de la conexión "
           "TCP hasta el CONNACK de MQTT, con autenticación mutua en los casos con TLS; 30 rondas por enlace, "
           "con los cuatro casos intercalados en cada ronda. Bytes: carga TCP en ambos sentidos durante el "
           "\\emph{handshake} y el CONNECT/CONNACK, sin encabezados IP ni TCP.}\n\\label{tab:handshake}\n"
           "\\footnotesize\n\\begin{tabular}{lrrrrr}\n\\toprule\n\\textbf{Caso} & \\textbf{n} & "
           "\\textbf{Total med. (ms)} & \\textbf{Total p95 (ms)} & \\textbf{Solo TLS med. (ms)} & "
           "\\textbf{Bytes} \\\\\n\\midrule\n" + "\n".join(filas[:-1]) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_handshake.tex").write_text(tex, encoding="utf-8")
    return resumen


# --- bytes por mensaje -----------------------------------------------------

MENSAJES = [("MI", "obu|subida|PUBLISH_MI"), ("MP", "obu|subida|PUBLISH_MP"), ("MF", "obu|subida|PUBLISH_MF"),
            ("MR", "obu|bajada|PUBLISH_MR"), ("ME", "obu|bajada|PUBLISH_ME"), ("M1", "rsu|bajada|PUBLISH_M1"),
            ("M2", "rsu|subida|PUBLISH_M2"), ("M3", "rsu|bajada|PUBLISH_M3"),
            ("PUBACK", "rsu|bajada|PUBACK"), ("PINGREQ/PINGRESP", "rsu|subida|PINGREQ")]


def bytes_mensaje(d_tls: Path, d_sin: Path, salida: Path) -> dict:
    sin = json.loads((d_sin / "resumen.json").read_text(encoding="utf-8"))
    tls = json.loads((d_tls / "resumen.json").read_text(encoding="utf-8"))
    filas = []
    for nombre, clave in MENSAJES:
        v = sin["por_clase"].get(clave)
        if not v:
            continue
        rango = f"{v['bytes_min']}--{v['bytes_max']}" if v["bytes_min"] != v["bytes_max"] else str(v["bytes_mediana"])
        filas.append(f"{nombre} & {rango} & {v['bytes_mediana'] + SOBRECARGA_TLS13} \\\\")

    def medias(r, clave):
        return sum(x[clave] for x in r["por_repeticion"]) / len(r["por_repeticion"])

    res = {"sin_tls": {k: medias(sin, k) for k in ("rsu_mision", "rsu_total", "obu_mision", "servidor_mision")},
           "tls": {k: medias(tls, k) for k in ("rsu_mision", "rsu_total", "obu_mision", "servidor_mision")},
           "reposo_sin_tls_B_h": sin["rsu_reposo"]["bytes_por_hora"], "reposo_tls_B_h": tls["rsu_reposo"]["bytes_por_hora"]}
    agregados = [
        ("RSU, por misión (M1, M2, M3 y acuses)", res["sin_tls"]["rsu_mision"], res["tls"]["rsu_mision"]),
        ("RSU, por conexión (incluye el \\emph{handshake})", res["sin_tls"]["rsu_total"] - res["sin_tls"]["rsu_mision"],
         res["tls"]["rsu_total"] - res["tls"]["rsu_mision"]),
        ("RSU, en reposo (\\emph{keepalive}), por hora", res["reposo_sin_tls_B_h"], res["reposo_tls_B_h"]),
        ("OBU, por misión", res["sin_tls"]["obu_mision"], res["tls"]["obu_mision"]),
        ("Servidor, por misión (una RSU)", res["sin_tls"]["servidor_mision"], res["tls"]["servidor_mision"]),
    ]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Bytes por mensaje con y sin TLS]{Bytes por mensaje y por "
           "misión, medidos en la carga TCP entre cada cliente y el \\emph{broker} (sin encabezados IP ni TCP), "
           "en cinco misiones del escenario de lazo. Sin TLS se lee cada paquete MQTT; con TLS~1.3 cada paquete "
           "viaja en un registro de 22 bytes más (encabezado, tipo de contenido y etiqueta de autenticación), "
           "verificado sobre los registros capturados. Los agregados son el promedio de las cinco misiones; el "
           "reposo se midió durante 5~min con la RSU conectada y sin misión.}\n\\label{tab:bytes}\n\\small\n"
           "\\begin{tabular}{lrr}\n\\toprule\n\\textbf{Mensaje o agregado} & \\textbf{Sin TLS (B)} & "
           "\\textbf{Con TLS 1.3 (B)} \\\\\n\\midrule\n" + "\n".join(filas) + "\n\\addlinespace\n" +
           "\n".join(f"{n} & {coma(a, 0)} & {coma(b, 0)} \\\\" for n, a, b in agregados) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_bytes.tex").write_text(tex, encoding="utf-8")

    # proyección mensual por RSU, con TLS: reposo + misiones + una conexión por día
    hs = res["tls"]["rsu_total"] - res["tls"]["rsu_mision"]
    filas = []
    for mis_dia in (1, 10, 50, 200):
        mes = 30 * (24 * res["reposo_tls_B_h"] + mis_dia * res["tls"]["rsu_mision"] + hs)
        filas.append(f"{mis_dia} & {coma(mes / 1e6, 2)} \\\\")
    res["proyeccion_MB_mes"] = {m: 30 * (24 * res["reposo_tls_B_h"] + m * res["tls"]["rsu_mision"] + hs) / 1e6
                                for m in (1, 10, 50, 200)}
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Proyección mensual de datos por RSU]{Proyección del consumo "
           "mensual de datos de una RSU con TLS~1.3, a partir de la Tabla~\\ref{tab:bytes}: reposo continuo, una "
           "conexión por día y el número indicado de misiones atendidas por día (30 días; carga TCP, sin "
           "encabezados IP ni TCP, por lo que el consumo facturado es algo mayor).}\n\\label{tab:proyeccion_datos}\n"
           "\\small\n\\begin{tabular}{rr}\n\\toprule\n\\textbf{Misiones por día} & \\textbf{MB por mes} \\\\\n"
           "\\midrule\n" + "\n".join(filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_proyeccion_datos.tex").write_text(tex, encoding="utf-8")
    return res


def snmp_niveles(d: Path, salida: Path) -> dict:
    """Tabla de la prueba 4 a partir del resumen.json que snmp_niveles.py
    escribió en la Raspberry Pi (su propia tabla es más ancha que la página)."""
    r = json.loads((d / "resumen.json").read_text(encoding="utf-8"))
    nombre = {"noAuthNoPriv": "Sin seguridad (noAuthNoPriv)", "authNoPriv": "Autenticación (authNoPriv)",
              "authPriv": "Autenticación y cifrado (authPriv)"}
    filas = [f"{nombre[n]} & {s['n']} & {coma(s['proc_med_ms'], 2)} / {coma(s['proc_p95_ms'], 2)} & "
             f"{coma(s['rtt_med_ms'], 2)} & {s['bytes_solicitud']} & {s['errores']} \\\\" for n, s in r["niveles"].items()]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Costo de SNMPv3 por nivel de seguridad]{Costo de SNMPv3 por "
           "nivel de seguridad en la RSU física: escrituras de \\texttt{phaseMinimumGreen} desde un gestor en la "
           "misma máquina, en bloques de 100 intercalados entre niveles. El procesamiento se mide en el agente, "
           "desde la llegada del datagrama hasta la salida de la respuesta; autenticación con SHA-256 y cifrado "
           "con AES-128. Solicitud y respuesta tienen el mismo tamaño.}\n\\label{tab:snmp_niveles}\n"
           "\\footnotesize\n\\begin{tabular}{lrrrrr}\n\\toprule\n\\textbf{Nivel} & \\textbf{n} & "
           "\\textbf{Proc. med./p95 (ms)} & \\textbf{RTT med. (ms)} & \\textbf{Bytes} & \\textbf{Errores} "
           "\\\\\n\\midrule\n" + "\n".join(filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_snmp_niveles.tex").write_text(tex, encoding="utf-8")
    return r["niveles"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carga", required=True)
    ap.add_argument("--snmp", required=True)
    ap.add_argument("--handshake-4g", required=True)
    ap.add_argument("--handshake-wifi", required=True)
    ap.add_argument("--bytes-tls", required=True)
    ap.add_argument("--bytes-sin-tls", required=True)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    res = {"carga": carga(Path(a.carga), salida),
           "handshake": handshake({"4G": Path(a.handshake_4g), "Wi-Fi": Path(a.handshake_wifi)}, salida),
           "bytes": bytes_mensaje(Path(a.bytes_tls), Path(a.bytes_sin_tls), salida),
           "snmp": snmp_niveles(Path(a.snmp), salida)}
    (salida / "resumen_fase4.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str),
                                               encoding="utf-8")
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
