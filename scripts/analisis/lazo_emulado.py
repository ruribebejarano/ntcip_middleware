#!/usr/bin/env python3
"""Analisis del lazo OBU -> broker -> RSU -> controlador con M1/M2/M3
(gateway/obu_emulada.py + agent/rsu_middleware.py), segun las metricas de
ssec:metricas de main.tex.

Por solicitud (id_solicitud) y en conjunto:

  RTT M1/M2        tiempo de ida y vuelta medido con el reloj de la OBU
                   (Correlation Data de MQTT 5): NO depende de sincronizar
                   relojes. Es la metrica mas robusta de esta etapa.
  t_V2I            M1_rx(seq 1) - M1_tx(seq 1): OBU -> broker -> RSU.
                   Cruza dos relojes: valido solo con chrony/W32Time
                   sincronizados, o si OBU y RSU corren en la misma maquina.
  t_RSU            primer snmp_set_tx - M1_rx(seq 1): validacion + RF-05/06.
  espera_despeje   activacion de la cola RF-06 - primer snmp_set_tx (si la
                   solicitud llego en ambar o todo rojo).
  t_hasta_verde    ctrl_fase_cambio a "verde" con este id - M1_tx(seq 1).
  t_concedida_obu  primer M2 "concedida" - M1_tx(seq 1), ambos en la OBU.
  PDR              mensajes M1/M3 unicos recibidos por la RSU / enviados.
  acierto_acceso   M1 cuya (interseccion, acceso) coincide con la verdad de
                   terreno de la trayectoria / M1 enviados.

*** Datos de trayectorias SINTETICAS: estas cifras caracterizan el canal y
la logica, no el comportamiento de un vehiculo real. ***

Uso:
    python3 scripts/analisis/lazo_emulado.py --dir resultados/lazo_emulado/<corrida> \\
        [--dir resultados/rsu/eventos]   # eventos de la Pi traidos con scripts/pi.sh fetch
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.events import (  # noqa: E402
    EVT_CTRL_FASE_CAMBIO,
    EVT_M1_RX,
    EVT_M1_TX,
    EVT_M2_RX,
    EVT_M3_RX,
    EVT_M3_TX,
    EVT_SNMP_SET_TX,
    iter_eventos,
)

MS = 1_000_000.0


def percentil(valores: list[float], q: float) -> float | None:
    """Percentil por rango mas cercano (q en 0..100)."""
    if not valores:
        return None
    v = sorted(valores)
    k = max(0, min(len(v) - 1, math.ceil(q / 100.0 * len(v)) - 1))
    return v[k]


def resumen(valores: list[float]) -> dict:
    if not valores:
        return {"n": 0}
    return {
        "n": len(valores),
        "media": sum(valores) / len(valores),
        "mediana": percentil(valores, 50),
        "p95": percentil(valores, 95),
        "max": max(valores),
        "min": min(valores),
    }


def cargar(directorios: list[Path]) -> list[dict]:
    eventos = []
    for d in directorios:
        for sub in [d, *[p for p in d.rglob("*") if p.is_dir()]]:
            eventos.extend(iter_eventos(sub))
    # Un mismo archivo puede aparecer dos veces si se pasan carpetas anidadas
    vistos, unicos = set(), []
    for e in sorted(eventos, key=lambda e: e["ts_ns"]):
        clave = (e["ts_ns"], e["nodo"], e["tipo_evento"], e["id_solicitud"])
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(e)
    return unicos


def analizar(eventos: list[dict]) -> tuple[list[dict], dict]:
    por_id: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        por_id[e["id_solicitud"]].append(e)

    filas, rtts, pdr_env, pdr_rx, aciertos, m1_total = [], [], 0, 0, 0, 0
    for id_sol, evs in por_id.items():
        m1_tx = [e for e in evs if e["tipo_evento"] == EVT_M1_TX and "seq" in e["extra"]]
        if not m1_tx:
            continue  # no es una solicitud de la OBU emulada (legado, SNMP manual, ciclo normal)
        m3_tx = [e for e in evs if e["tipo_evento"] == EVT_M3_TX]
        m1_rx = [e for e in evs if e["tipo_evento"] == EVT_M1_RX and not e["extra"].get("duplicado")]
        m3_rx = [e for e in evs if e["tipo_evento"] == EVT_M3_RX and not e["extra"].get("duplicado")]
        m2_rx = [e for e in evs if e["tipo_evento"] == EVT_M2_RX]
        sets = [e for e in evs if e["tipo_evento"] == EVT_SNMP_SET_TX]
        verde = [e for e in evs if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO and e["extra"].get("fase") == "verde"]

        t0 = m1_tx[0]["ts_ns"]
        rx1 = next((e for e in m1_rx if e["extra"].get("seq") == 1), None)
        set1 = sets[0] if sets else None
        cola = next((e for e in sets if e["extra"].get("accion") == "activar_cola_rf06"), None)
        concedida = next((e for e in m2_rx if e["extra"].get("estado") == "concedida"), None)
        rechazada = next((e for e in m2_rx if e["extra"].get("estado") == "rechazada"), None)
        rtt = [float(e["extra"]["rtt_ms"]) for e in m2_rx if e["extra"].get("rtt_ms") is not None]
        rtts.extend(rtt)

        enviados = len(m1_tx) + len(m3_tx)
        recibidos = len({e["extra"].get("seq") for e in m1_rx + m3_rx})
        pdr_env += enviados
        pdr_rx += recibidos
        ok_acceso = sum(1 for e in m1_tx
                        if e["extra"].get("interseccion_id") == e["extra"].get("verdad_interseccion")
                        and e["extra"].get("acceso") == e["extra"].get("verdad_acceso"))
        aciertos += ok_acceso
        m1_total += len(m1_tx)

        x = m1_tx[0]["extra"]
        filas.append({
            "id_solicitud": id_sol,
            "trayectoria": x.get("trayectoria"),
            "rsu_id": x.get("rsu_id"),
            "interseccion_id": x.get("interseccion_id"),
            "acceso": x.get("acceso"),
            "m1_enviados": len(m1_tx),
            "m3_enviado": bool(m3_tx),
            "m3_motivo": m3_tx[0]["extra"].get("motivo") if m3_tx else "",
            "pdr": recibidos / enviados if enviados else None,
            "resultado": ("rechazada" if rechazada else "concedida" if concedida else
                          "sin_verde" if m2_rx else "sin_respuesta"),
            "t_V2I_ms": (rx1["ts_ns"] - t0) / MS if rx1 else None,
            "t_RSU_ms": (set1["ts_ns"] - rx1["ts_ns"]) / MS if (set1 and rx1) else None,
            "espera_despeje_ms": (cola["ts_ns"] - set1["ts_ns"]) / MS if (cola and set1) else None,
            "t_hasta_verde_ms": (verde[0]["ts_ns"] - t0) / MS if verde else None,
            "t_concedida_obu_ms": (concedida["ts_ns"] - t0) / MS if concedida else None,
            "rtt_mediana_ms": percentil(rtt, 50),
            "rtt_p95_ms": percentil(rtt, 95),
            "acierto_acceso": ok_acceso / len(m1_tx),
        })

    def col(nombre):
        return [f[nombre] for f in filas if f[nombre] is not None]

    global_ = {
        "solicitudes": len(filas),
        "resultados": {r: sum(1 for f in filas if f["resultado"] == r)
                       for r in ("concedida", "sin_verde", "rechazada", "sin_respuesta")},
        "pdr": pdr_rx / pdr_env if pdr_env else None,
        "mensajes_enviados": pdr_env,
        "mensajes_recibidos": pdr_rx,
        "acierto_acceso": aciertos / m1_total if m1_total else None,
        "rtt_m1_m2_ms": resumen(rtts),
        "t_V2I_ms": resumen(col("t_V2I_ms")),
        "t_RSU_ms": resumen(col("t_RSU_ms")),
        "espera_despeje_ms": resumen(col("espera_despeje_ms")),
        "t_hasta_verde_ms": resumen(col("t_hasta_verde_ms")),
        "t_concedida_obu_ms": resumen(col("t_concedida_obu_ms")),
    }
    return filas, global_


def _fmt(r: dict) -> str:
    if not r.get("n"):
        return "sin datos"
    return (f"n={r['n']}, mediana={r['mediana']:.1f}, p95={r['p95']:.1f}, "
            f"media={r['media']:.1f}, max={r['max']:.1f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True,
                    help="carpeta con eventos_*.csv (se puede repetir; se busca tambien en subcarpetas)")
    ap.add_argument("--salida", default=None, help="carpeta de salida (por defecto, el primer --dir)")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.dir]
    filas, g = analizar(cargar(dirs))
    if not filas:
        print("No hay solicitudes de la OBU emulada (M1_tx con seq) en esas carpetas.", file=sys.stderr)
        raise SystemExit(1)

    salida = Path(args.salida) if args.salida else dirs[0]
    salida.mkdir(parents=True, exist_ok=True)
    with (salida / "lazo_por_solicitud.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    (salida / "lazo_resumen.json").write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")

    r = g["resultados"]
    print(f"Solicitudes: {g['solicitudes']}  (concedidas {r['concedida']}, sin verde {r['sin_verde']}, "
          f"rechazadas {r['rechazada']}, sin respuesta {r['sin_respuesta']})")
    print(f"PDR M1/M3: {g['pdr']:.3f} ({g['mensajes_recibidos']}/{g['mensajes_enviados']})")
    print(f"Acierto de acceso: {g['acierto_acceso']:.3f}")
    print(f"RTT M1/M2 (ms, reloj de la OBU):   {_fmt(g['rtt_m1_m2_ms'])}")
    print(f"t_V2I (ms, dos relojes):           {_fmt(g['t_V2I_ms'])}")
    print(f"t_RSU (ms):                        {_fmt(g['t_RSU_ms'])}")
    print(f"Espera de despeje RF-06 (ms):      {_fmt(g['espera_despeje_ms'])}")
    print(f"M1 -> verde en el controlador (ms): {_fmt(g['t_hasta_verde_ms'])}")
    print(f"M1 -> M2 'concedida' en la OBU (ms): {_fmt(g['t_concedida_obu_ms'])}")
    print(f"\nDetalle: {salida / 'lazo_por_solicitud.csv'}\nResumen: {salida / 'lazo_resumen.json'}")


if __name__ == "__main__":
    main()
