#!/usr/bin/env python3
"""Reproducción animada de repeticiones de la campaña de ruta completa.

Lee los registros de eventos de una o varias repeticiones (OBU, servidor,
RSU y controladores) y genera UNA página HTML autocontenida que reproduce
el recorrido: posición enviada por la OBU, fase de cada controlador
(plan reconstruido desde ctrl_inicio + verde por prioridad registrado),
mensajes M1/M2/M3, acciones de la RSU y las métricas medidas por
intersección (analisis/por_parada.csv). No calcula nada nuevo: solo
reordena lo registrado.

Uso:
    python scripts/analisis/reproduccion_ruta.py \
        --rep resultados/ruta_completa/20261107-123645_A/rep_01 \
        --rep resultados/ruta_completa/20261107-132149_B/rep_01 \
        --rep resultados/ruta_completa/20261107-141431_C/rep_01 \
        --analisis resultados/ruta_completa/analisis \
        --salida resultados/ruta_completa/reproduccion/reproduccion_ruta.html
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import cargar_registro, proyeccion_local  # noqa: E402
from servidor import rutas  # noqa: E402

NS = 1_000_000_000
FIX = RAIZ / "scripts" / "campanas" / "fixtures"
REGISTRO = FIX / "registro_ruta_hospital_nino.json"
PLANTILLA = Path(__file__).resolve().parent / "plantillas" / "reproduccion_ruta.html"
ORIGEN = (-12.074664, -77.082933)
DESTINO = (-12.0649978, -77.0464372)
NOMBRES = {"A": "A · 36 km/h constante", "B": "B · perfil sintético variable", "C": "C · desvío fuera de ruta"}


def leer_eventos(p: Path) -> list[dict]:
    with p.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for f in filas:
        f["ts_ns"] = int(f["ts_ns"])
        f["extra"] = json.loads(f.get("extra_json") or "{}")
    return filas


def num(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def extraer(rep: Path, metricas: list[dict], ref: tuple[float, float]) -> dict:
    corrida = rep.parent.name
    esc = corrida.rsplit("_", 1)[-1]
    srv = leer_eventos(rep / "eventos_servidor.csv")
    t0 = next(e["ts_ns"] for e in srv if e["tipo_evento"] == "mision_armada")

    def t(ts: int) -> float:
        return round((ts - t0) / NS, 3)

    def xy(lat: float, lon: float) -> list[float]:
        x, y = proyeccion_local(lat, lon, *ref)
        return [round(x, 1), round(y, 1)]

    obu = leer_eventos(next(rep.glob("eventos_obu-*.csv")))
    vehiculo = [[t(e["ts_ns"]), *xy(e["extra"]["lat"], e["extra"]["lon"]),
                 round(e["extra"]["velocidad_kmh"], 1), round(e["extra"]["rumbo_deg"], 1)]
                for e in obu if e["tipo_evento"] == "MP_tx"]

    eventos: list[dict] = []
    m1_primero: dict[str, float] = {}
    rsu_de: dict[str, str] = {}
    estado_m2: dict[str, str] = {}
    eta: list[list] = []
    for e in srv:
        tipo, sid, ex = e["tipo_evento"], e["id_solicitud"], e["extra"]
        if tipo == "M1_tx":
            rsu_de[sid] = ex.get("rsu_id", rsu_de.get(sid))
            if sid not in m1_primero:
                m1_primero[sid] = e["ts_ns"]
                eventos.append({"t": t(e["ts_ns"]), "k": "M1", "rsu": rsu_de[sid],
                                "t_servicio": ex.get("t_servicio")})
        elif tipo == "M2_rx":
            est = ex.get("estado")
            if estado_m2.get(sid) != est:
                estado_m2[sid] = est
                eventos.append({"t": t(e["ts_ns"]), "k": "M2", "rsu": rsu_de.get(sid), "estado": est,
                                "rtt_ms": round((e["ts_ns"] - m1_primero[sid]) / 1e6, 1) if sid in m1_primero else None})
        elif tipo == "M3_tx":
            eventos.append({"t": t(e["ts_ns"]), "k": "M3", "rsu": rsu_de.get(sid), "motivo": ex.get("motivo")})
        elif tipo == "eta_estimado":
            eta.append([t(e["ts_ns"]), ex.get("rsu_id"), ex.get("eta_s"), ex.get("distancia_restante_m")])
        elif tipo == "ruta_recalculada":
            eventos.append({"t": t(e["ts_ns"]), "k": "recalculo", "antes": ex.get("n_paradas_antes"),
                            "despues": ex.get("n_paradas_despues")})
        elif tipo == "vehiculo_detenido":
            eventos.append({"t": t(e["ts_ns"]), "k": "detenido"})
        elif tipo == "solicitud_suspendida_detenido":
            eventos.append({"t": t(e["ts_ns"]), "k": "suspendida", "rsu": rsu_de.get(sid),
                            "seg": ex.get("segundos_detenido")})
        elif tipo == "mision_desarmada":
            eventos.append({"t": t(e["ts_ns"]), "k": "fin", "motivo": ex.get("motivo")})

    # Tramos de verde por prioridad: el controlador solo registra
    # ctrl_fase_cambio cuando la fase VISIBLE cambia, así que si el plan ya
    # estaba en verde al activar o al liberar la prioridad no queda evento.
    # Por eso los tramos salen de las órdenes SNMP de la RSU al controlador
    # (activar: request_priority / activar_cola*, liberar: clear_priority*),
    # y se cierran antes si el controlador registró una caducidad.
    controladores: dict[str, dict] = {}
    ordenes: dict[str, list[tuple[float, str]]] = {}
    for p in sorted(rep.glob("eventos_rsu_*.csv")):
        rid = p.stem.rsplit("_", 1)[-1]
        for e in leer_eventos(p):
            if e["tipo_evento"] == "snmp_set_tx":
                acc = e["extra"].get("accion") or ""
                eventos.append({"t": t(e["ts_ns"]), "k": "snmp", "rsu": rid, "accion": acc,
                                "fase": e["extra"].get("fase")})
                ordenes.setdefault(rid, []).append((t(e["ts_ns"]), acc))
    for p in sorted(rep.glob("eventos_ctrl_*.csv")):
        rid = p.stem.rsplit("_", 1)[-1]
        evs = leer_eventos(p)
        ini = next(e for e in evs if e["tipo_evento"] == "ctrl_inicio")["extra"]
        caducidades = [t(e["ts_ns"]) for e in evs if e["tipo_evento"] == "ctrl_fase_cambio"
                       and e["extra"].get("motivo") == "caducidad_prioridad"]
        prioridad, abierto = [], None
        for ts, acc in sorted(ordenes.get(rid, [])):
            if acc.startswith(("request_priority", "activar_cola")) and abierto is None:
                abierto = ts
            elif acc.startswith("clear_priority") and abierto is not None:
                fin = min([ts] + [c for c in caducidades if abierto < c < ts])
                prioridad.append([abierto, fin])
                abierto = None
        if abierto is not None:
            fin = next((c for c in caducidades if c > abierto), None)
            prioridad.append([abierto, fin])
        controladores[rid] = {
            "epoca": round((ini["epoch_wall_ns"] - t0) / NS, 3),
            "ciclo": [["verde", ini["verde_s"]], ["amarillo", ini["amarillo_ds"] / 10],
                      ["todo_rojo", ini["todo_rojo_ds"] / 10], ["rojo_general", ini["rojo_general_s"]]],
            "prioridad": prioridad,
        }

    medidas = {}
    for f in metricas:
        if f["corrida"] == corrida and f["repeticion"] == rep.name:
            medidas[f["rsu_id"]] = {
                "anticipacion_real_s": num(f["anticipacion_real_s"]),
                "anticipacion_centro_s": num(f["anticipacion_centro_s"]),
                "rtt_ms": num(f["RTT_srv_ms"]), "l_ms": num(f["L_ms"]),
                "condicion": f["condicion_llegada"] or None,
                "fase_sin_prioridad": f["fase_sin_prioridad_exacta"] or None,
                "demora_evitada_s": num(f["demora_evitada_exacta_s"]),
                "t_servicio": num(f["t_servicio_m1_s"]), "motivos": f["motivos_m3"],
                "renovaciones": int(f["renovaciones"] or 0),
                "dist_min_centro_m": num(f["dist_min_centro_m"]),
            }
    eventos.sort(key=lambda e: e["t"])
    cfg = json.loads((rep.parent / "config.json").read_text(encoding="utf-8"))
    semilla = cfg["repeticiones"][rep.name]["semilla"]
    return {"id": f"{esc}-{rep.name}", "escenario": esc, "nombre": f"{NOMBRES.get(esc, esc)} · {rep.name.replace('_', ' ')}",
            "semilla": semilla, "corrida": corrida, "vehiculo": vehiculo, "eventos": eventos, "eta": eta,
            "controladores": controladores, "medidas": medidas,
            "duracion": vehiculo[-1][0] if vehiculo else 0}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rep", type=Path, action="append", required=True)
    ap.add_argument("--analisis", type=Path, required=True)
    ap.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args()

    registro = cargar_registro(REGISTRO)
    G = rutas.cargar_grafo()
    ruta = rutas.planificar_ruta(G, registro, ORIGEN, DESTINO)
    lats = [n.lat for n in ruta.geometria]
    lons = [n.lon for n in ruta.geometria]
    ref = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)

    def xy(lat, lon):
        x, y = proyeccion_local(lat, lon, *ref)
        return [round(x, 1), round(y, 1)]

    ruta_xy = [xy(n.lat, n.lon) for n in ruta.geometria]
    xs = [p[0] for p in ruta_xy]
    ys = [p[1] for p in ruta_xy]
    margen = 450.0
    caja = (min(xs) - margen, max(xs) + margen, min(ys) - margen, max(ys) + margen)
    calles = []
    vistos = set()
    for u, v in G.edges():
        if (v, u) in vistos:
            continue
        vistos.add((u, v))
        a = xy(G.nodes[u]["y"], G.nodes[u]["x"])
        b = xy(G.nodes[v]["y"], G.nodes[v]["x"])
        if all(caja[0] <= p[0] <= caja[1] and caja[2] <= p[1] <= caja[3] for p in (a, b)):
            calles.append(a + b)
    with (args.analisis / "por_parada.csv").open(newline="", encoding="utf-8") as fh:
        metricas = list(csv.DictReader(fh))
    acum = {p.rsu_id: round(p.distancia_llegada_m, 1) for p in ruta.paradas}
    rsus = [{"id": i.rsu_id, "xy": xy(i.lat, i.lon), "acum_m": acum.get(i.rsu_id)} for i in registro]
    datos = {
        "ruta": ruta_xy, "ruta_m": round(ruta.longitud_total_m, 1), "calles": calles, "rsus": rsus,
        "origen": ruta_xy[0], "destino": ruta_xy[-1],
        "repeticiones": [extraer(r, metricas, ref) for r in args.rep],
    }
    html = PLANTILLA.read_text(encoding="utf-8").replace(
        "/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False, separators=(",", ":")))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(html, encoding="utf-8")
    print(f"{len(calles)} tramos de calle, {len(datos['repeticiones'])} repeticiones -> {args.salida} "
          f"({args.salida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
