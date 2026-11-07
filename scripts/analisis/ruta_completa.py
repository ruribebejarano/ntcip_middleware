#!/usr/bin/env python3
"""Análisis de la campaña de ruta completa (scripts/campanas/ruta_completa.py):
una misión con 13 RSU por repetición, condición local (un solo reloj).

Reutiliza, sin cambiarlos:
  - scripts/analisis/lazo_centralizado.py::analizar  (RTT_srv, t_RSU, L,
    anticipación real, fase de decisión, T_desp, resultado), las mismas
    definiciones de la campaña principal;
  - scripts/analisis/llegadas_verde_contrafactual.py::fase_natural_en_cruce
    y demora_hasta_verde_s (método de la Tabla 4.10).

Agrega, por RSU y repetición:
  - anticipación hasta el centro de la intersección: del verde concedido
    (primer M2 "concedida" en el servidor) al instante de máxima cercanía de
    la trayectoria MP_tx de la OBU al centro de la RSU (mismo método que
    resultados/campana/_figuras_cap4_2026-11-04/anticipacion_hasta_centro.py,
    generalizado a un centro por RSU);
  - renovaciones (M1 seq > 1), caducidades en la RSU y mayor hueco entre M1
    recibidos en la RSU;
  - solicitudes activas a la vez (de M1 seq 1 al último M3, en el servidor);
  - contrafactual EXACTO, como contraste: el controlador registra el
    instante de inicio de su ciclo (ctrl_inicio, epoch_wall_ns), así que la
    fase del plan sin prioridad en el cruce se calcula sin suponer llegada
    uniforme. El método de la tesis sigue siendo el principal.
  - escenario B: error del ETA del M1 inicial frente al cruce real, y
    solicitudes con el vehículo detenido mientras el verde estaba concedido
    (tiempo de verde pedido "de más");
  - escenario C: recálculo de ruta y cancelaciones.

Uso:
    python scripts/analisis/ruta_completa.py --dir <corrida A> --dir <corrida B> --dir <corrida C> \\
        --salida resultados/ruta_completa/analisis
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import analizar, cargar, percentil  # noqa: E402
from llegadas_verde_contrafactual import demora_hasta_verde_s, fase_natural_en_cruce  # noqa: E402
from common.events import iter_eventos  # noqa: E402
from gateway.geometria import proyeccion_local  # noqa: E402

NS = 1e9
ORDEN = [("verde", 8.0), ("amarillo", 3.0), ("todo_rojo", 2.0), ("rojo_general", 8.0)]
CICLO = sum(d for _, d in ORDEN)
ANTICIPACION_MIN_S = 8.0


def fase_plan(epoch_ns: int, ts_ns: int) -> tuple[str, float]:
    """(fase del plan, segundos transcurridos dentro de esa fase) a ts_ns."""
    t = ((ts_ns - epoch_ns) / NS) % CICLO
    acc = 0.0
    for nombre, d in ORDEN:
        if t < acc + d:
            return nombre, t - acc
        acc += d
    return ORDEN[-1][0], 0.0


def espera_exacta(fase: str, dentro: float) -> float:
    if fase == "verde":
        return 0.0
    idx = [n for n, _ in ORDEN].index(fase)
    resto = sum(d for _, d in ORDEN[idx + 1:])
    return (dict(ORDEN)[fase] - dentro) + resto


def cargar_base(rep: Path) -> list[dict]:
    with (rep / "trayectoria_base.csv").open(newline="", encoding="utf-8") as fh:
        return [{k: (float(v) if k not in ("tramo",) else v) for k, v in r.items()} for r in csv.DictReader(fh)]


def analizar_repeticion(rep: Path, escenario: str, centros: dict[str, tuple[float, float]],
                        acum: dict[str, float]) -> tuple[list[dict], dict]:
    eventos = sorted(iter_eventos(rep), key=lambda e: e["ts_ns"])
    _, filas, _ = analizar(eventos)
    por_id: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        por_id[e["id_solicitud"]].append(e)
    inicio_ctrl = {e["nodo"].split("_")[1]: e["extra"]["epoch_wall_ns"] for e in eventos
                   if e["tipo_evento"] == "ctrl_inicio"}
    eta_est: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] == "eta_estimado":
            eta_est[e["extra"].get("rsu_id")].append(e)
    base = cargar_base(rep)
    mp = [(e["ts_ns"], e["extra"]) for e in eventos if e["tipo_evento"] == "MP_tx"]
    # Instante de pared de cada fila de la trayectoria (t_tray_s -> ts del MP_tx).
    ts_de_fila = {round(x["t_tray_s"], 1): ts for ts, x in mp}

    def ts_cruce_s(acum_m: float) -> int | None:
        for f in base:
            if f["s_m"] >= acum_m and f.get("tramo", "ruta") == "ruta":
                return ts_de_fila.get(round(f["t_s"], 1))
        return None

    def ts_detenido(a: int, b: int) -> float:
        n = 0
        for f in base:
            ts = ts_de_fila.get(round(f["t_s"], 1))
            if ts is not None and a <= ts <= b and f["detenida"] == 1:
                n += 1
        return float(n)

    salida = []
    intervalos = []
    for f in filas:
        sid, rid = f["id_solicitud"], f["rsu_id"]
        evs = por_id[sid]
        m1_srv = [e for e in evs if e["tipo_evento"] == "M1_tx"]
        m1_rsu = sorted(e["ts_ns"] for e in evs if e["tipo_evento"] == "M1_rx")
        m3 = [e for e in evs if e["tipo_evento"] == "M3_tx"]
        concedida = [e["ts_ns"] for e in evs if e["tipo_evento"] == "M2_rx" and e["extra"].get("estado") == "concedida"]
        t_m1 = min(e["ts_ns"] for e in m1_srv) if m1_srv else None
        t_fin = max((e["ts_ns"] for e in m3), default=None)
        if t_m1 is not None:
            intervalos.append((t_m1, t_fin or t_m1))
        # Anticipación hasta el centro.
        ant_centro = dist_min = None
        if concedida and rid in centros:
            tg = min(concedida)
            lat_c, lon_c = centros[rid]
            pts = [(ts, *proyeccion_local(x["lat"], x["lon"], lat_c, lon_c)) for ts, x in mp
                   if t_m1 is None or ts >= t_m1 - 2 * NS]
            mejor = None
            for (ta, xa, ya), (tb, xb, yb) in zip(pts, pts[1:]):
                dx, dy = xb - xa, yb - ya
                l2 = dx * dx + dy * dy
                u = 0.0 if l2 == 0 else max(0.0, min(1.0, (-xa * dx - ya * dy) / l2))
                d = math.hypot(xa + u * dx, ya + u * dy)
                if mejor is None or d < mejor[0]:
                    mejor = (d, ta + u * (tb - ta))
            if mejor:
                dist_min, ant_centro = mejor[0], (mejor[1] - tg) / NS
        # Contrafactual: método de la tesis y exacto (contraste).
        fase_tesis, metodo = fase_natural_en_cruce(evs, f["resultado"])
        cruce = next((e for e in m3 if e["extra"].get("motivo") == "cruce"), None)
        fase_exacta = espera_exacta_s = None
        if cruce is not None and rid in inicio_ctrl:
            fase_exacta, dentro = fase_plan(inicio_ctrl[rid], cruce["ts_ns"])
            espera_exacta_s = espera_exacta(fase_exacta, dentro)
        # Escenario B: ETA del M1 inicial frente al cruce real.
        # t_servicio del M1: si lo emitió la geocerca, el servidor pone la
        # anticipación mínima (8 s), no el ETA. El error del ETA se mide con
        # el último eta_estimado del servidor para esa RSU antes del M1.
        t_servicio_m1 = next((e["extra"].get("t_servicio") for e in m1_srv if e["extra"].get("seq") == 1), None)
        eta_m1 = None
        if t_m1 is not None:
            previos = [e for e in eta_est.get(rid, []) if e["ts_ns"] <= t_m1]
            if previos:
                eta_m1 = previos[-1]["extra"].get("eta_s")
        ts_real = ts_cruce_s(acum[rid]) if rid in acum and escenario != "ruta_C" else None
        err_eta = ((ts_real - t_m1) / NS - eta_m1) if (ts_real and t_m1 and eta_m1 is not None) else None
        # Segundos con el vehículo detenido mientras la solicitud estaba
        # vigente: desde cada concesión hasta el M3 siguiente (si la
        # solicitud se suspendió por detención, el tramo suspendido no
        # cuenta: ahí no hay prioridad pedida).
        verde_de_mas = 0.0
        ts_m3 = sorted(e["ts_ns"] for e in m3)
        inicio_seg = None
        for ts, tipo in sorted([(c, "c") for c in concedida] + [(x, "m3") for x in ts_m3]):
            if tipo == "c" and inicio_seg is None:
                inicio_seg = ts
            elif tipo == "m3" and inicio_seg is not None:
                verde_de_mas += ts_detenido(inicio_seg, ts)
                inicio_seg = None
        huecos = [(b - a) / NS for a, b in zip(m1_rsu, m1_rsu[1:])]
        salida.append({
            **f,
            "repeticion": rep.name, "escenario": escenario,
            "acum_m": acum.get(rid),
            "anticipacion_centro_s": ant_centro, "dist_min_centro_m": dist_min,
            "n_m1": len(m1_srv), "renovaciones": sum(1 for e in m1_srv if e["extra"].get("renovacion")),
            "caducidades": sum(1 for e in evs if e["tipo_evento"] == "caducidad"),
            "mayor_hueco_m1_s": max(huecos) if huecos else None,
            "motivos_m3": ";".join(e["extra"].get("motivo", "") for e in m3),
            "fase_sin_prioridad_tesis": fase_tesis, "metodo_contrafactual": metodo,
            "demora_evitada_tesis_s": demora_hasta_verde_s(fase_tesis)[0] if fase_tesis else None,
            "fase_sin_prioridad_exacta": fase_exacta, "demora_evitada_exacta_s": espera_exacta_s,
            "t_servicio_m1_s": t_servicio_m1, "eta_m1_s": eta_m1, "t_m1_a_cruce_real_s": (ts_real - t_m1) / NS if (ts_real and t_m1) else None,
            "error_eta_s": err_eta,
            "suspendida_detenido": sum(1 for e in evs if e["tipo_evento"] == "solicitud_suspendida_detenido"),
            "verde_con_vehiculo_detenido_s": verde_de_mas,
        })
    # Simultaneidad: instantes de M1 inicial/M3 como bordes.
    bordes = sorted({t for a, b in intervalos for t in (a, b)})
    max_sim = max((sum(1 for a, b in intervalos if a <= t < b) for t in bordes), default=0)
    resumen_rep = {"repeticion": rep.name, "escenario": escenario, "n_solicitudes": len(salida),
                   "max_simultaneas": max_sim,
                   "suspensiones": sum(1 for e in eventos if e["tipo_evento"] == "solicitud_suspendida_detenido"),
                   "recalculos": sum(1 for e in eventos if e["tipo_evento"] == "ruta_recalculada")}
    if escenario == "ruta_C":
        resumen_rep["desvio"] = analizar_desvio(eventos, base, ts_de_fila)
    return salida, resumen_rep


def analizar_desvio(eventos: list[dict], base: list[dict], ts_de_fila: dict) -> dict:
    salida_fila = next((f for f in base if f["tramo"] == "desvio"), None)
    ts_salida = ts_de_fila.get(round(salida_fila["t_s"], 1)) if salida_fila else None
    recalc = [e for e in eventos if e["tipo_evento"] == "ruta_recalculada"]
    mr = [e for e in eventos if e["tipo_evento"] == "MR_rx"]
    detalle = []
    for r in recalc:
        mp_previo = max((e for e in eventos if e["tipo_evento"] == "MP_rx" and e["ts_ns"] <= r["ts_ns"]),
                        key=lambda e: e["ts_ns"], default=None)
        mr_obu = next((e for e in mr if e["ts_ns"] >= r["ts_ns"]), None)
        detalle.append({
            "desde_salida_de_ruta_s": (r["ts_ns"] - ts_salida) / NS if ts_salida else None,
            "mp_rx_a_recalculo_ms": (r["ts_ns"] - mp_previo["ts_ns"]) / 1e6 if mp_previo else None,
            "recalculo_a_mr_en_obu_ms": (mr_obu["ts_ns"] - r["ts_ns"]) / 1e6 if mr_obu else None,
            "paradas_antes": r["extra"].get("n_paradas_antes"), "paradas_despues": r["extra"].get("n_paradas_despues"),
        })
    m3 = [{"id_solicitud": e["id_solicitud"], "motivo": e["extra"].get("motivo"),
           "desde_salida_de_ruta_s": (e["ts_ns"] - ts_salida) / NS if ts_salida else None}
          for e in eventos if e["tipo_evento"] == "M3_tx" and e["extra"].get("motivo") != "cruce"
          or (e["tipo_evento"] == "M3_tx" and ts_salida and abs(e["ts_ns"] - ts_salida) < 5 * NS)]
    return {"salida_de_ruta_s_m": salida_fila["s_m"] if salida_fila else None, "recalculos": detalle,
            "cancelaciones": m3}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    todas, reps = [], []
    for d in map(Path, args.dir):
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        reg = json.loads((RAIZ / cfg["registro"]).read_text(encoding="utf-8"))
        centros = {r["rsu_id"]: (r["centro"]["lat"], r["centro"]["lon"]) for r in reg["rsu"]}
        val = json.loads((RAIZ / "scripts/campanas/fixtures/ruta_completa/validacion_sin_red.json")
                         .read_text(encoding="utf-8"))
        acum = {k: float(v) for k, v in val["paradas"].items()}  # distancia del nodo de la parada (servidor)
        for rep in sorted(p for p in d.iterdir() if p.is_dir() and p.name.startswith("rep_")):
            filas, r = analizar_repeticion(rep, cfg["escenario"], centros, acum)
            r["corrida"] = d.name
            r["semilla"] = cfg["repeticiones"].get(rep.name, {}).get("semilla")
            for f in filas:
                f["corrida"], f["semilla"] = d.name, r["semilla"]
            todas.extend(filas)
            reps.append(r)

    campos = list(todas[0].keys()) if todas else []
    with (salida / "por_parada.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(todas)
    (salida / "por_repeticion.json").write_text(json.dumps(reps, indent=1, ensure_ascii=False), encoding="utf-8")

    def nums(filas, k):
        return [f[k] for f in filas if isinstance(f.get(k), (int, float))]

    resumen = {}
    for esc in sorted({f["escenario"] for f in todas}):
        fs = [f for f in todas if f["escenario"] == esc]
        cruces = [f for f in fs if f["ultimo_m3_motivo"] == "cruce"]
        ant = nums(fs, "anticipacion_real_s")
        antc = nums(fs, "anticipacion_centro_s")
        cond = defaultdict(int)
        for f in fs:
            cond[f["condicion_llegada"] or "sin_dato"] += 1
        con_tesis = [f for f in cruces if f["metodo_contrafactual"] != "sin_dato"]
        n_rep = len({f["repeticion"] for f in fs})
        demora_tesis = sum(f["demora_evitada_tesis_s"] or 0 for f in con_tesis)
        demora_exacta = sum(f["demora_evitada_exacta_s"] or 0 for f in cruces if f["demora_evitada_exacta_s"] is not None)
        resumen[esc] = {
            "repeticiones": n_rep, "solicitudes": len(fs),
            "concedidas": sum(1 for f in fs if f["resultado"] == "concedida"),
            "con_cruce": len(cruces),
            "condicion_llegada": dict(cond),
            "anticipacion_real_s": {"min": min(ant, default=None), "mediana": percentil(ant, 50),
                                     "p95": percentil(ant, 95), "max": max(ant, default=None),
                                     "menores_a_8s": sum(1 for a in ant if a < ANTICIPACION_MIN_S),
                                     "n": len(ant)},
            "anticipacion_centro_s": {"min": min(antc, default=None), "mediana": percentil(antc, 50),
                                       "negativas": sum(1 for a in antc if a < 0), "n": len(antc)},
            "RTT_srv_ms": {"mediana": percentil(nums(fs, "RTT_srv_ms"), 50), "p95": percentil(nums(fs, "RTT_srv_ms"), 95),
                           "max": max(nums(fs, "RTT_srv_ms"), default=None)},
            "t_RSU_ms": {"mediana": percentil(nums(fs, "t_RSU_ms"), 50), "p95": percentil(nums(fs, "t_RSU_ms"), 95)},
            "L_ms": {"mediana": percentil(nums(fs, "L_ms"), 50), "p95": percentil(nums(fs, "L_ms"), 95),
                     "max": max(nums(fs, "L_ms"), default=None)},
            "T_desp_ms": {"n": len(nums(fs, "T_desp_ms")), "mediana": percentil(nums(fs, "T_desp_ms"), 50),
                          "max": max(nums(fs, "T_desp_ms"), default=None)},
            "renovaciones_por_solicitud_mediana": percentil(nums(fs, "renovaciones"), 50),
            "caducidades": sum(nums(fs, "caducidades")),
            "mayor_hueco_m1_s": max(nums(fs, "mayor_hueco_m1_s"), default=None),
            "max_simultaneas": max((r["max_simultaneas"] for r in reps if r["escenario"] == esc), default=None),
            "contrafactual_tesis": {
                "n": len(con_tesis),
                "pct_verde_con_prioridad": 100.0 * sum(1 for f in cruces if f["obtuvo_verde"]) / len(cruces) if cruces else None,
                "pct_verde_sin_prioridad_est": 100.0 * sum(1 for f in con_tesis if f["fase_sin_prioridad_tesis"] == "verde") / len(con_tesis) if con_tesis else None,
                "demora_evitada_total_s": demora_tesis,
                "demora_evitada_por_mision_s": demora_tesis / n_rep if n_rep else None,
            },
            "contrafactual_exacto": {
                "n": sum(1 for f in cruces if f["fase_sin_prioridad_exacta"]),
                "pct_verde_sin_prioridad": 100.0 * sum(1 for f in cruces if f["fase_sin_prioridad_exacta"] == "verde") / len(cruces) if cruces else None,
                "demora_evitada_por_mision_s": demora_exacta / n_rep if n_rep else None,
            },
        }
        if esc == "ruta_B":
            err = nums(fs, "error_eta_s")
            resumen[esc]["eta"] = {"n": len(err), "error_mediana_s": percentil(err, 50),
                                   "error_abs_p95_s": percentil([abs(x) for x in err], 95),
                                   "error_min_s": min(err, default=None), "error_max_s": max(err, default=None)}
            resumen[esc]["detenido"] = {
                "suspensiones": sum(nums(fs, "suspendida_detenido")),
                "solicitudes_con_verde_y_vehiculo_detenido": sum(1 for f in fs if f["verde_con_vehiculo_detenido_s"] > 0),
                "verde_con_vehiculo_detenido_total_s": sum(nums(fs, "verde_con_vehiculo_detenido_s")),
                "verde_con_vehiculo_detenido_max_s": max(nums(fs, "verde_con_vehiculo_detenido_s"), default=None),
            }
        if esc == "ruta_C":
            resumen[esc]["desvio"] = [r.get("desvio") for r in reps if r["escenario"] == esc]
    (salida / "resumen.json").write_text(json.dumps(resumen, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
