#!/usr/bin/env python3
"""Análisis de las pruebas de seguridad operativa
(scripts/seguridad/prueba_seguridad_operativa.py).

Por repetición, con los eventos de todos los nodos (un solo reloj: todo
corre en esta máquina):

  Respuesta en capas (mision_falsa, clon, inundacion):
    t_deteccion_s    primer MP anómalo enviado por el atacante -> alerta del
                     servidor (en mision_falsa, misión armada -> aviso de
                     verificación con el despacho)
    t_contencion_s   alerta -> comando aplicado en el servidor (incluye el
                     retardo humano emulado del operador, o 0 si es automático)
    t_m3_rsu_ms      comando aplicado -> M3 recibido por la RSU
    t_liberacion_ms  comando aplicado -> el controlador sale de la prioridad
                     del atacante (si la tenía)
    verdes_atacante  verdes por prioridad que obtuvo la misión del atacante
    s_verde_atacante segundos de verde por prioridad del atacante

  Lazo legítimo (inundacion, base):
    L_ms             M1_tx (servidor) -> M1_rx (RSU), todos los M1
    RTT_ms           M1_tx -> M2_rx (servidor), por seq
    entrega          M1 enviados / recibidos

Uso:
    python scripts/seguridad/analisis_seguridad_operativa.py --dir <corrida> [--dir <corrida> ...]
    python scripts/seguridad/analisis_seguridad_operativa.py               # todas en resultados/seguridad/
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import iter_eventos  # noqa: E402
from gateway.geometria import proyeccion_local  # noqa: E402

NS = 1e9
MS = 1e6


def _pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _est(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": min(xs), "mediana": statistics.median(xs), "p95": _pctl(xs, 0.95), "max": max(xs)}


def _rep(rep_dir: Path) -> dict:
    ev = sorted(iter_eventos(rep_dir), key=lambda e: e["ts_ns"])
    atacante = next((e["nodo"] for e in ev if e["nodo"].startswith(("obu-falsa", "obu-clon", "obu-flood"))), None)
    legit = next((e["nodo"] for e in ev if e["nodo"].startswith("obu-legit")), None)
    misiones = {e["extra"].get("obu_id"): e["id_solicitud"] for e in ev if e["tipo_evento"] == "mision_armada"}
    r: dict = {"rep": rep_dir.name, "atacante": atacante}

    if atacante:
        mis_at = misiones.get(atacante)
        alertas = [e for e in ev if e["tipo_evento"] == "alerta_seguridad" and e["extra"].get("obu_id") == atacante]
        anomalas = [e for e in alertas if e["extra"].get("alerta") != "verificacion_despacho"]
        alerta = anomalas[0] if anomalas else (alertas[0] if alertas else None)
        r["alertas"] = sorted({e["extra"].get("alerta") for e in alertas})
        # Inicio del ataque
        t0 = None
        if atacante.startswith("obu-falsa"):
            t0 = next((e["ts_ns"] for e in ev if e["tipo_evento"] == "mision_armada"
                       and e["extra"].get("obu_id") == atacante), None)
        else:
            mp = [e for e in ev if e["nodo"] == atacante and e["tipo_evento"] == "MP_tx"]
            if atacante.startswith("obu-clon"):
                for a, b in zip(mp, mp[1:]):
                    x, y = proyeccion_local(b["extra"]["lat"], b["extra"]["lon"], a["extra"]["lat"], a["extra"]["lon"])
                    if math.hypot(x, y) > 1000:
                        t0 = b["ts_ns"]
                        break
            elif mp:
                t0 = mp[0]["ts_ns"]
        r["t_deteccion_s"] = (alerta["ts_ns"] - t0) / NS if (alerta and t0) else None
        cmd = next((e for e in ev if e["tipo_evento"] == "comando_operador"
                    and e["extra"].get("obu_id") == atacante
                    and e["extra"].get("accion") in ("suspender_obu", "suspender_mision")), None)
        r["origen_contencion"] = cmd["extra"].get("origen") if cmd else None
        r["motivo_contencion"] = cmd["extra"].get("motivo") if cmd else None
        r["t_contencion_s"] = (cmd["ts_ns"] - alerta["ts_ns"]) / NS if (cmd and alerta) else None
        ids_at = {e["id_solicitud"] for e in ev if e["tipo_evento"] == "M1_tx"
                  and e["extra"].get("mision_id") == mis_at}
        if cmd:
            m3 = next((e for e in ev if e["tipo_evento"] == "M3_rx" and e["id_solicitud"] in ids_at
                       and e["ts_ns"] >= cmd["ts_ns"]), None)
            r["t_m3_rsu_ms"] = (m3["ts_ns"] - cmd["ts_ns"]) / MS if m3 else None
        # Solo el verde concedido por la prioridad (no el evento de
        # liberación, que también puede reportar fase verde por el verde
        # mínimo de salida, ni un verde del plan registrado con el último id).
        verdes = [e for e in ev if e["nodo"].startswith("ctrl") and e["tipo_evento"] == "ctrl_fase_cambio"
                  and e["extra"].get("fase") == "verde" and e["extra"].get("prioridad_activa") is True
                  and e["id_solicitud"] in ids_at]
        liberaciones = [e for e in ev if e["nodo"].startswith("ctrl") and e["tipo_evento"] == "ctrl_fase_cambio"
                        and str(e["extra"].get("motivo", "")).startswith(("liberacion", "caducidad"))
                        and e["id_solicitud"] in ids_at]
        r["verdes_atacante"] = len(verdes)
        s_verde = 0.0
        for v in verdes:
            fin = next((l for l in liberaciones if l["ts_ns"] > v["ts_ns"]), None)
            if fin:
                s_verde += (fin["ts_ns"] - v["ts_ns"]) / NS
        r["s_verde_atacante"] = s_verde
        if cmd:
            lib = next((l for l in liberaciones if l["ts_ns"] >= cmd["ts_ns"]), None)
            r["t_liberacion_ms"] = (lib["ts_ns"] - cmd["ts_ns"]) / MS if lib else None
        r["mp_atacante_tx"] = sum(1 for e in ev if e["nodo"] == atacante and e["tipo_evento"] == "MP_tx")
        rech = [e["extra"].get("ignorados", 0) for e in ev if e["tipo_evento"] == "MP_rechazado_suspendida"
                and e["extra"].get("obu_id") == atacante]
        r["mp_atacante_ignorados_min"] = max(rech) if rech else 0

    if legit:
        mis = misiones.get(legit)
        m1_tx = {(e["id_solicitud"], e["extra"].get("seq")): e["ts_ns"] for e in ev
                 if e["tipo_evento"] == "M1_tx" and e["extra"].get("mision_id") == mis}
        m1_rx = {(e["id_solicitud"], e["extra"].get("seq")): e["ts_ns"] for e in ev
                 if e["tipo_evento"] == "M1_rx" and not e["extra"].get("duplicado")}
        m2_rx = {(e["id_solicitud"], e["extra"].get("seq_ref")): e["ts_ns"] for e in ev
                 if e["tipo_evento"] == "M2_rx"}
        r["L_ms"] = [(m1_rx[k] - t) / MS for k, t in m1_tx.items() if k in m1_rx]
        r["RTT_ms"] = [(m2_rx[k] - t) / MS for k, t in m1_tx.items() if k in m2_rx]
        r["m1_tx"] = len(m1_tx)
        r["m1_rx"] = sum(1 for k in m1_tx if k in m1_rx)
        r["verde_legit"] = any(e["nodo"].startswith("ctrl") and e["tipo_evento"] == "ctrl_fase_cambio"
                               and e["extra"].get("fase") == "verde"
                               and str(e["id_solicitud"]).startswith(str(mis)) for e in ev) or None
    return r


def _fmt(x) -> str:
    if x is None:
        return "--"
    if isinstance(x, float):
        return f"{x:.2f}"
    return str(x)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", default=None)
    args = ap.parse_args()
    dirs = [Path(d) for d in args.dir] if args.dir else sorted(
        p for p in (RAIZ / "resultados" / "seguridad").glob("2*_*") if p.is_dir())
    for d in dirs:
        config = json.loads((d / "config.json").read_text(encoding="utf-8"))
        reps = [_rep(r) for r in sorted(d.glob("rep_*"))]
        L = [x for r in reps for x in r.get("L_ms", [])]
        rtt = [x for r in reps for x in r.get("RTT_ms", [])]
        resumen = {
            "corrida": d.name, "escenario": config["escenario"], "politica": config["politica"],
            "retardo_s": None if config.get("sin_operador") else config["retardo_s"],
            "confirmacion_s": config.get("confirmacion_s"), "hz": config.get("hz"),
            "repeticiones": reps,
            "L_ms": _est(L), "RTT_ms": _est(rtt),
            "m1_entrega": f"{sum(r.get('m1_rx', 0) for r in reps)}/{sum(r.get('m1_tx', 0) for r in reps)}",
        }
        (d / "seguridad_resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False, default=str),
                                                  encoding="utf-8")
        print(f"\n== {d.name}: escenario={resumen['escenario']} política={resumen['politica']} "
              f"retardo={resumen['retardo_s']} confirmación={resumen['confirmacion_s']} hz={resumen['hz']}")
        for r in reps:
            if r.get("atacante"):
                print(f"  {r['rep']}: alertas={r.get('alertas')} detección={_fmt(r.get('t_deteccion_s'))} s "
                      f"contención={_fmt(r.get('t_contencion_s'))} s ({r.get('origen_contencion')}, "
                      f"{r.get('motivo_contencion')}) M3->RSU={_fmt(r.get('t_m3_rsu_ms'))} ms "
                      f"liberación={_fmt(r.get('t_liberacion_ms'))} ms verdes atacante={r.get('verdes_atacante')} "
                      f"({_fmt(r.get('s_verde_atacante'))} s) MP atacante={r.get('mp_atacante_tx')} "
                      f"ignorados>={r.get('mp_atacante_ignorados_min')}")
            if r.get("L_ms") is not None and "m1_tx" in r:
                print(f"  {r['rep']}: legítima M1 {r['m1_rx']}/{r['m1_tx']}, verde={r.get('verde_legit')}, "
                      f"L med {_fmt(statistics.median(r['L_ms']) if r['L_ms'] else None)} ms")
        if L:
            e = resumen["L_ms"]
            print(f"  L legítima (ms): n={e['n']} mediana={_fmt(e['mediana'])} p95={_fmt(e['p95'])} max={_fmt(e['max'])}; "
                  f"RTT p95={_fmt(resumen['RTT_ms'].get('p95'))}; entrega M1 {resumen['m1_entrega']}")


if __name__ == "__main__":
    main()
