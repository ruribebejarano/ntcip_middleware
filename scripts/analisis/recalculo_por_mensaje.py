#!/usr/bin/env python3
"""OE4: recálculo de la campaña del Capítulo IV con los registros existentes,
sin nuevas mediciones.

1. RTT servidor--RSU POR MENSAJE: todos los pares M1/M2 (solicitud inicial y
   renovaciones), no un valor por repetición. Mediana, p95, p99 y máximo, con
   intervalo de confianza del 95 % por remuestreo (bootstrap) POR REPETICIÓN
   (se remuestrean repeticiones completas, no mensajes sueltos: los mensajes
   de una misma repetición comparten estado del enlace y no son
   independientes).
2. Tiempo de red sin depender del desfase de relojes, con las cuatro marcas
   t1 = M1_tx (servidor), t2 = M1_rx (RSU), t3 = M2_tx (RSU), t4 = M2_rx
   (servidor):
       retención en la RSU   h   = t3 - t2          (solo reloj de la RSU)
       tiempo de red         red = (t4 - t1) - h    (cada resta, un reloj)
       tramo de ida          ida = red / 2          (SUPUESTO de simetría)
       desfase de relojes    θ   = ((t2 - t1) + (t3 - t4)) / 2
                             (reloj RSU - reloj servidor; estimador de NTP,
                              RFC 5905, tomado del par con menor tiempo de
                              red de cada repetición, con error <= red_min/2)
   Con θ se separan la ida y la vuelta de cada mensaje, y la latencia del
   lazo por mensaje es L_corr = ida_corr + retención.
   La latencia del lazo se estima entonces sin cruzar relojes como
       L_est = ida + (decisión de la RSU - t2)
   y se compara con la medida cruda (decisión - t1), que sí los cruza.
3. Tasa de entrega por contador de secuencia: MP (OBU->servidor, solo con la
   misión armada), M1 y M3 (servidor->RSU) y M2 (RSU->servidor), con
   duplicados y la racha máxima sin renovación en la RSU frente a T_cad.
4. Error del ETA y anticipación: ETA que el servidor publicó (ME) al emitir
   cada M1 inicial frente al tiempo real hasta que el vehículo pasa por el
   centro de la intersección; anticipación A_v (verde -> cruce) frente a los
   dos límites de la ecuación eq:avmax de la tesis (T_m = 2 s, A_v,max =
   16 s); duración de la prioridad en la RSU (activación -> liberación).

Todos los procesos de la OBU emulada, el servidor y el broker corren en la
laptop: MP_tx, ME_rx, M1_tx, M2_rx y M3_tx comparten reloj.

Uso (raíz del repo):
    .venv/Scripts/python.exe scripts/analisis/recalculo_por_mensaje.py \
        --salida resultados/campana/_figuras_cap4_2026-11-11
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent.parent
C = RAIZ / "resultados" / "campana"
CONDICIONES = {  # mismas corridas que scripts/analisis/generar_cap4.sh
    "Local": ["20261104-002341_lazo_local_1hz_con-tls", "20261104-005352_desvio_local_1hz_con-tls"],
    "Wi-Fi": ["20261104-045004_lazo_pi-lan", "20261104-052338_desvio_pi-lan"],
    "4G": ["20261103-232704_lazo_pi-4g", "20261103-235034_desvio_pi-4g"],
}
REGISTRO = RAIZ / "scripts" / "campanas" / "fixtures" / "registro_rsu_1.json"
T_CAD_S = 3.0
T_M_S = 2.0
A_V_MAX_S = 16.0
B_BOOT = 2000
SEMILLA = 20261111
NS = 1e9
MS = 1e6


def leer(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    for e in filas:
        e["ts"] = int(e["ts_ns"])
        e["x"] = json.loads(e["extra_json"]) if e["extra_json"] else {}
    return filas


def proyeccion(lat, lon, lat0, lon0):
    r = 6_371_000.0
    return (r * math.radians(lon - lon0) * math.cos(math.radians(lat0)), r * math.radians(lat - lat0))


def pct(v, p):
    return float(np.percentile(np.asarray(v, dtype=float), p)) if len(v) else float("nan")


def bootstrap(grupos: list[list[float]], estad, rng) -> tuple[float, float]:
    """IC 95 % remuestreando repeticiones completas."""
    k = len(grupos)
    vals = []
    for _ in range(B_BOOT):
        idx = rng.integers(0, k, k)
        muestra = [x for i in idx for x in grupos[i]]
        if muestra:
            vals.append(estad(muestra))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def analizar_rep(rep: Path, centro) -> dict:
    srv = leer(rep / "eventos_servidor.csv")
    rsu = [e for f in sorted(rep.glob("eventos_rsu_*.csv")) for e in leer(f)]
    ctrl = [e for f in sorted(rep.glob("eventos_ctrl_*.csv")) for e in leer(f)]
    obu = leer(next(rep.glob("eventos_obu-*.csv")))
    r = defaultdict(list)

    # --- pares M1/M2 ---------------------------------------------------
    m1_tx = {(e["id_solicitud"], e["x"]["seq"]): e for e in srv if e["tipo_evento"] == "M1_tx"}
    m1_rx, dup_m1 = {}, 0
    for e in rsu:
        if e["tipo_evento"] == "M1_rx":
            if e["x"].get("duplicado"):
                dup_m1 += 1
            else:
                m1_rx.setdefault((e["id_solicitud"], e["x"]["seq"]), e["ts"])
    m2_tx = defaultdict(list)
    for e in rsu:
        if e["tipo_evento"] == "M2_tx":
            m2_tx[(e["id_solicitud"], e["x"].get("seq_ref"))].append(e["ts"])
    m2_rx = defaultdict(list)
    for e in srv:
        if e["tipo_evento"] == "M2_rx":
            m2_rx[(e["id_solicitud"], e["x"].get("seq_ref"))].append(e["ts"])
    decision = {}
    for e in rsu:
        if e["tipo_evento"] == "snmp_set_tx" and e["x"].get("origen") == "v2i" and \
                e["x"].get("accion") in ("request_priority", "en_cola_despeje", "rechazada"):
            decision.setdefault(e["id_solicitud"], e["ts"])

    thetas = []
    for (sid, seq), e in m1_tx.items():
        t1 = e["ts"]
        inicial = not e["x"].get("renovacion")
        t2 = m1_rx.get((sid, seq))
        t3 = (m2_tx.get((sid, seq)) or [None])[0]
        t4 = (m2_rx.get((sid, seq)) or [None])[0]
        if t4 is not None:
            r["rtt"].append((t4 - t1) / MS)
        if None not in (t2, t3, t4):
            h = (t3 - t2) / MS
            red = (t4 - t1) / MS - h
            r["ret"].append(h)
            r["red"].append(red)
            r["ida"].append(red / 2)
            th = ((t2 - t1) + (t3 - t4)) / 2 / MS
            thetas.append((red, th))
            if inicial and sid in decision:
                t_rsu = (decision[sid] - t2) / MS
                r["L_est"].append(red / 2 + t_rsu)
                r["L_cruda"].append((decision[sid] - t1) / MS)
    # Filtro de reloj de NTP (RFC 5905, sec. 10): el desfase de la
    # repeticion es el del par con MENOR tiempo de red, que es el menos
    # afectado por la asimetria entre ida y vuelta (su error es <= red/2).
    # La mediana de todos los pares se sesga en 4G, donde la cola de
    # retardo esta casi toda en la vuelta.
    theta = min(thetas)[1] if thetas else 0.0
    r["theta_cota"] = [min(thetas)[0] / 2] if thetas else []
    r["theta"] = [theta]
    # Ida y vuelta por separado, corrigiendo cada marca de la RSU con el
    # desfase de la repetición (filtro de reloj), no el del propio mensaje: un mensaje
    # con la vuelta retrasada no contamina su propia ida, que es lo que
    # supone el reparto simétrico red/2. L_corr = ida_corr + retención.
    for (sid, seq), e in m1_tx.items():
        t1 = e["ts"]
        t2 = m1_rx.get((sid, seq))
        t3 = (m2_tx.get((sid, seq)) or [None])[0]
        t4 = (m2_rx.get((sid, seq)) or [None])[0]
        if None in (t2, t3, t4):
            continue
        ida_c = (t2 - t1) / MS - theta
        r["ida_corr"].append(ida_c)
        r["vuelta_corr"].append((t4 - t3) / MS + theta)
        r["L_corr"].append(ida_c + (t3 - t2) / MS)
        r["fase_ret"].append((e["x"].get("renovacion", False), (t3 - t2) / MS))

    # --- entrega -------------------------------------------------------
    ent = Counter()
    t_arm = min(e["ts"] for e in srv if e["tipo_evento"] == "mision_armada")
    t_des = min((e["ts"] for e in srv if e["tipo_evento"] == "mision_desarmada"), default=None)
    mp_rx = {e["x"].get("seq") for e in srv if e["tipo_evento"] == "MP_rx"}
    for e in obu:
        if e["tipo_evento"] == "MP_tx" and e["ts"] >= t_arm and (t_des is None or e["ts"] < t_des):
            ent["MP_env"] += 1
            ent["MP_rec"] += e["x"]["seq"] in mp_rx
    ent["MP_dup"] += sum(1 for e in srv if e["tipo_evento"] == "MP_descartado")
    ent["M1_env"] += len(m1_tx)
    ent["M1_rec"] += sum(1 for k in m1_tx if k in m1_rx)
    ent["M1_dup"] += dup_m1
    m3_tx = {e["id_solicitud"]: e["ts"] for e in srv if e["tipo_evento"] == "M3_tx"}
    m3_rx = {}
    for e in rsu:
        if e["tipo_evento"] == "M3_rx":
            if e["x"].get("duplicado"):
                ent["M3_dup"] += 1
            else:
                m3_rx.setdefault(e["id_solicitud"], (e["ts"], e["x"].get("seq")))
    ent["M3_env"] += len(m3_tx)
    ent["M3_rec"] += sum(1 for s in m3_tx if s in m3_rx)
    # M2: respuestas a M1 (seq_ref de un M1) y del watchdog (seq_ref None).
    # Las respuestas a M3 no son observables: el servidor deja de seguir la
    # solicitud al cancelarla y no registra su M2 (procesar_m2).
    for (sid, sref), tss in m2_tx.items():
        if sref is not None and (sid, sref) not in m1_tx:
            continue  # respuesta a M3
        for i, t3 in enumerate(tss):
            recibidas = m2_rx.get((sid, sref), [])
            if i < len(recibidas):
                ent["M2_env"] += 1
                ent["M2_rec"] += 1
            elif sid in m3_tx and t3 - theta * MS > m3_tx[sid] - 1:
                ent["M2_no_obs"] += 1  # salió después de que el servidor canceló
            else:
                ent["M2_env"] += 1
    for k, tss in m2_rx.items():
        if k[1] is not None and len(tss) > 1:
            ent["M2_dup"] += len(tss) - 1

    # racha sin renovación en la RSU (un solo reloj)
    llegadas = defaultdict(list)
    for (sid, _seq), t in m1_rx.items():
        llegadas[sid].append(t)
    for sid, (t, _s) in m3_rx.items():
        llegadas[sid].append(t)
    for sid, v in llegadas.items():
        v.sort()
        r["racha"] += [(b - a) / NS for a, b in zip(v, v[1:])]

    # --- ETA, anticipación y duración ------------------------------------
    pts = []
    for e in obu:
        if e["tipo_evento"] == "MP_tx":
            x, y = proyeccion(e["x"]["lat"], e["x"]["lon"], *centro)
            pts.append((e["ts"], x, y))
    me = [(e["ts"], (e["x"].get("proximo") or {}).get("eta_s")) for e in obu if e["tipo_evento"] == "ME_rx"]
    for (sid, seq), e in m1_tx.items():
        if e["x"].get("renovacion"):
            continue
        t1 = e["ts"]
        # paso por el centro: mínima distancia a lo largo de los segmentos MP
        mejor = None
        for (ta, xa, ya), (tb, xb, yb) in zip(pts, pts[1:]):
            if tb < t1 - 2 * NS:
                continue
            dx, dy = xb - xa, yb - ya
            l2 = dx * dx + dy * dy
            u = 0.0 if l2 == 0 else max(0.0, min(1.0, (-xa * dx - ya * dy) / l2))
            d = math.hypot(xa + u * dx, ya + u * dy)
            if mejor is None or d < mejor[0]:
                mejor = (d, ta + u * (tb - ta))
        eta = next((v for t, v in me if t >= t1 and v is not None), None)
        if mejor is not None:
            real = (mejor[1] - t1) / NS
            r["A_e"].append(real)
            if eta is not None:
                r["eta_err"].append(eta - real)
            if sid in m3_tx:
                r["cruce_vs_centro"].append((m3_tx[sid] - mejor[1]) / NS)
        # verde (reloj de la Pi) -> M3 de cruce (laptop), corregido por theta
        verde = [c["ts"] for c in ctrl if c["tipo_evento"] == "ctrl_fase_cambio"
                 and c["id_solicitud"] == sid and c["x"].get("fase") == "verde"]
        act = [x["ts"] for x in rsu if x["tipo_evento"] == "snmp_set_tx" and x["id_solicitud"] == sid
               and x["x"].get("accion") in ("request_priority", "activar_cola_rf06")]
        t_verde = min(verde) if verde else (min(act) if act else None)
        m3c = next((x for x in srv if x["tipo_evento"] == "M3_tx" and x["id_solicitud"] == sid
                    and x["x"].get("motivo") == "cruce"), None)
        if t_verde is not None and m3c is not None:
            r["A_v"].append((m3c["ts"] - (t_verde - theta * MS)) / NS)
        lib = [x["ts"] for x in rsu if x["tipo_evento"] == "snmp_set_tx" and x["id_solicitud"] == sid
               and x["x"].get("accion") == "clear_priority_m3"]
        if act and lib:
            r["dur_prioridad"].append((min(lib) - min(act)) / NS)
    r["ent"] = [ent]
    return r


def resumir(grupos: list[list[float]], rng, con_ic=True) -> dict:
    todos = [x for g in grupos for x in g]
    if not todos:
        return {"n": 0}
    out = {"n": len(todos), "reps": len(grupos), "med": pct(todos, 50), "p95": pct(todos, 95),
           "p99": pct(todos, 99), "max": max(todos), "min": min(todos)}
    if con_ic:
        for nom, p in (("med", 50), ("p95", 95), ("p99", 99)):
            out[f"{nom}_ic"] = bootstrap(grupos, lambda v, p=p: pct(v, p), rng)
    return out


def coma(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def ic(s, k, d=1):
    a, b = s[f"{k}_ic"]
    return f"{coma(s[k], d)} [{coma(a, d)}; {coma(b, d)}]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    salida = RAIZ / args.salida if not Path(args.salida).is_absolute() else Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    reg = json.load(open(REGISTRO, encoding="utf-8"))["rsu"][0]["centro"]
    centro = (reg["lat"], reg["lon"])
    rng = np.random.default_rng(SEMILLA)

    res = {}
    for cond, corridas in CONDICIONES.items():
        reps = [analizar_rep(Path(p), centro) for d in corridas for p in sorted(glob.glob(str(C / d / "rep_*")))]
        g = lambda k: [r[k] for r in reps]  # noqa: E731
        ent = sum((r["ent"][0] for r in reps), Counter())
        res[cond] = {
            "repeticiones": len(reps),
            "rtt_ms": resumir(g("rtt"), rng),
            "retencion_rsu_ms": resumir(g("ret"), rng),
            "red_ms": resumir(g("red"), rng),
            "ida_ms": resumir(g("ida"), rng),
            "L_est_ms": resumir(g("L_est"), rng),
            "L_cruda_ms": resumir(g("L_cruda"), rng, con_ic=False),
            "ida_corr_ms": resumir(g("ida_corr"), rng),
            "vuelta_corr_ms": resumir(g("vuelta_corr"), rng),
            "L_corr_ms": resumir(g("L_corr"), rng),
            "desfase_theta_ms": resumir(g("theta"), rng, con_ic=False),
            "desfase_cota_error_ms": resumir(g("theta_cota"), rng, con_ic=False),
            "racha_s": resumir(g("racha"), rng, con_ic=False),
            "rachas_ge_tcad": sum(1 for r in reps for x in r["racha"] if x >= T_CAD_S),
            "entrega": dict(ent),
            "eta_err_s": resumir(g("eta_err"), rng, con_ic=False),
            "eta_err_abs_s": resumir([[abs(x) for x in r["eta_err"]] for r in reps], rng, con_ic=False),
            "A_e_s": resumir(g("A_e"), rng, con_ic=False),
            "cruce_M3_menos_centro_s": resumir(g("cruce_vs_centro"), rng, con_ic=False),
            "A_v_s": resumir(g("A_v"), rng, con_ic=False),
            "A_v_bajo_Tm": sum(1 for r in reps for x in r["A_v"] if x < T_M_S),
            "A_v_sobre_max": sum(1 for r in reps for x in r["A_v"] if x > A_V_MAX_S),
            "dur_prioridad_s": resumir(g("dur_prioridad"), rng, con_ic=False),
        }
    (salida / "recalculo_por_mensaje.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- tabla: RTT por mensaje y tiempo de red -------------------------
    fil = []
    for cond, x in res.items():
        for nom, k in (("RTT servidor--RSU", "rtt_ms"), ("Tiempo de red (RTT $-$ retención)", "red_ms"),
                       ("Retención en la RSU", "retencion_rsu_ms"),
                       ("Ida, corregida por desfase", "ida_corr_ms"), ("Vuelta, corregida por desfase", "vuelta_corr_ms"),
                       ("$L$ por mensaje (ida + retención)", "L_corr_ms")):
            s = x[k]
            fil.append(f"{nom} & {cond} & {s['n']} & {ic(s, 'med')} & {ic(s, 'p95')} & {ic(s, 'p99')} & {coma(s['max'], 1)} \\\\")
        fil.append("\\addlinespace")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption{RTT servidor--RSU por mensaje (solicitud inicial y "
           "renovaciones), tiempo de red y retención en la RSU, en ms. Entre corchetes, intervalo de confianza "
           "del 95~\\% por remuestreo de repeticiones completas. Cada métrica usa un solo reloj.}\n"
           "\\label{tab:rtt_mensaje}\n\\small\n\\begin{tabular}{llrlllr}\n\\toprule\n"
           "\\textbf{Métrica} & \\textbf{Enlace} & \\textbf{n} & \\textbf{Mediana} & \\textbf{p95} & "
           "\\textbf{p99} & \\textbf{Máx.} \\\\\n\\midrule\n" + "\n".join(fil[:-1]) +
           "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_rtt_mensaje.tex").write_text(tex, encoding="utf-8")

    # --- tabla: entrega ---------------------------------------------------
    fil = []
    for cond, x in res.items():
        e = x["entrega"]
        for m in ("MP", "M1", "M2", "M3"):
            env, rec, dup = e.get(f"{m}_env", 0), e.get(f"{m}_rec", 0), e.get(f"{m}_dup", 0)
            tasa = 100 * rec / env if env else float("nan")
            cota = 300 / env if env and rec == env else None  # regla del tres, en %
            fil.append(f"{m} & {cond} & {env} & {rec} & {env - rec} & {dup} & {coma(tasa, 2)}"
                       f"{(' ($\\geq$ ' + coma(100 - cota, 2) + ')') if cota else ''} \\\\")
        fil.append("\\addlinespace")
    tex = ("\\begin{table}[H]\n\\centering\n\\caption{Tasa de entrega por tipo de mensaje y enlace. Entre "
           "paréntesis, la cota inferior al 95~\\% de la tasa de entrega cuando no hubo pérdidas (regla del tres). "
           "MP cuenta solo los mensajes con la misión armada.}\n\\label{tab:entrega}\n\\small\n"
           "\\begin{tabular}{llrrrrl}\n\\toprule\n\\textbf{Mensaje} & \\textbf{Enlace} & \\textbf{Enviados} & "
           "\\textbf{Recibidos} & \\textbf{Perdidos} & \\textbf{Duplicados} & \\textbf{Entrega (\\%)} \\\\\n"
           "\\midrule\n" + "\n".join(fil[:-1]) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (salida / "tabla_entrega.tex").write_text(tex, encoding="utf-8")

    for cond, x in res.items():
        print(f"== {cond} ({x['repeticiones']} rep.)")
        for k in ("rtt_ms", "red_ms", "ida_ms", "retencion_rsu_ms", "L_est_ms", "L_cruda_ms", "ida_corr_ms", "vuelta_corr_ms", "L_corr_ms", "desfase_theta_ms", "desfase_cota_error_ms",
                  "racha_s", "eta_err_s", "eta_err_abs_s", "A_e_s", "cruce_M3_menos_centro_s", "A_v_s", "dur_prioridad_s"):
            s = x[k]
            if s.get("n"):
                extra = "".join(f" {q}_ic=[{s[q+'_ic'][0]:.2f};{s[q+'_ic'][1]:.2f}]" for q in ("med", "p95", "p99") if q + "_ic" in s)
                print(f"  {k:24s} n={s['n']:4d} min={s['min']:9.2f} med={s['med']:9.2f} p95={s['p95']:9.2f} "
                      f"p99={s['p99']:9.2f} max={s['max']:9.2f}{extra}")
        print(f"  rachas>=Tcad={x['rachas_ge_tcad']}  A_v<Tm={x['A_v_bajo_Tm']}  A_v>max={x['A_v_sobre_max']}")
        print(f"  entrega={x['entrega']}")


if __name__ == "__main__":
    main()
