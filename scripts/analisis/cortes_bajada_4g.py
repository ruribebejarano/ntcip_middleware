#!/usr/bin/env python3
"""OE5: episodios de ida lenta servidor -> RSU en la campaña 4G y su margen
frente a la caducidad de la RSU (T_CAD_SEGUNDOS, RF-09).

Para cada sesión 4G (laptop y nube) cuenta:
  - los M1 cuya ida corregida (t2 - t1 - desfase de la repetición, mismo
    desfase que recalculo_por_mensaje.py) supera UMBRAL_MS, y los episodios
    (repeticiones distintas) en que ocurren;
  - si el M1 lento fue el primero de la solicitud o una renovación;
  - la mayor brecha entre dos M1 consecutivos recibidos por la RSU para una
    misma solicitud, que es lo que compara la caducidad con su plazo;
  - los eventos de caducidad registrados por la RSU;
  - para cada episodio, cuánto después del M1 lento llegó el siguiente
    (si llega ~1 RTT después, y no pegado, el siguiente también se perdió y
    se retransmitió: pérdida recuperada por TCP, no una simple cola).

Uso:
    python scripts/analisis/cortes_bajada_4g.py --salida resultados/campana/_campana_nube

Escribe cortes_bajada_4g.json y cortes_bajada_4g.txt.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recalculo_por_mensaje as rpm  # noqa: E402
from latencia_percentiles_fhwa import SESIONES  # noqa: E402

sys.path.insert(0, str(rpm.RAIZ))
from agent.ntcip1211 import T_CAD_SEGUNDOS  # noqa: E402

UMBRAL_MS = 1000.0


def analizar_sesion(corridas: list[str], centro) -> dict:
    lentos, brechas, caducidad = [], [], Counter()
    n_m1 = 0
    for d in corridas:
        for rep in sorted((rpm.C / d).glob("rep_*")):
            srv = rpm.leer(rep / "eventos_servidor.csv")
            rsu = [e for f in sorted(rep.glob("eventos_rsu_*.csv")) for e in rpm.leer(f)]
            theta = rpm.analizar_rep(rep, centro)["theta"][0]
            tx = sorted((e["ts"], e["id_solicitud"], e["x"]["seq"], bool(e["x"].get("renovacion")))
                        for e in srv if e["tipo_evento"] == "M1_tx")
            rx = {}
            for e in rsu:
                if e["tipo_evento"] == "M1_rx" and not e["x"].get("duplicado"):
                    rx.setdefault((e["id_solicitud"], e["x"]["seq"]), e["ts"])
                if e["tipo_evento"] == "caducidad":
                    caducidad[f"{d}/{rep.name}"] += 1
            llegadas = sorted(rx.values())
            for t1, sid, seq, renov in tx:
                t2 = rx.get((sid, seq))
                if t2 is None:
                    continue
                n_m1 += 1
                ida = (t2 - t1) / rpm.MS - theta
                if ida > UMBRAL_MS:
                    sig = next((t for t in llegadas if t > t2), None)
                    lentos.append({
                        "corrida": d, "rep": rep.name, "solicitud": sid, "seq": seq,
                        "renovacion": renov, "ida_ms": round(ida, 1),
                        "siguiente_llega_ms": None if sig is None else round((sig - t2) / rpm.MS, 1),
                    })
            por_sol = defaultdict(list)
            for (sid, _), t in rx.items():
                por_sol[sid].append(t)
            for sid, ts in por_sol.items():
                ts.sort()
                brechas += [((b - a) / rpm.NS, f"{d}/{rep.name}") for a, b in zip(ts, ts[1:])]
    brechas.sort(reverse=True)
    episodios = sorted({(x["corrida"], x["rep"]) for x in lentos})
    return {
        "n_m1": n_m1,
        "m1_ida_mayor_umbral": len(lentos),
        "episodios": len(episodios),
        "m1_lentos_iniciales": sum(not x["renovacion"] for x in lentos),
        "lentos": lentos,
        "brecha_max_s": round(brechas[0][0], 2) if brechas else None,
        "brecha_max_en": brechas[0][1] if brechas else None,
        "margen_caducidad_s": round(T_CAD_SEGUNDOS - brechas[0][0], 2) if brechas else None,
        "eventos_caducidad": sum(caducidad.values()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", required=True, type=Path)
    a = ap.parse_args()
    reg = json.load(open(rpm.REGISTRO, encoding="utf-8"))["rsu"][0]["centro"]
    centro = (reg["lat"], reg["lon"])
    res = {"umbral_ms": UMBRAL_MS, "t_cad_s": T_CAD_SEGUNDOS, "sesiones": {}}
    lineas = [f"Umbral de ida lenta: {UMBRAL_MS:.0f} ms; caducidad de la RSU: {T_CAD_SEGUNDOS:.1f} s"]
    for nombre, corridas in SESIONES.items():
        r = analizar_sesion(corridas, centro)
        res["sesiones"][nombre] = r
        lineas.append(
            f"{nombre}: {r['m1_ida_mayor_umbral']} de {r['n_m1']} M1 con ida > {UMBRAL_MS:.0f} ms "
            f"en {r['episodios']} episodios ({r['m1_lentos_iniciales']} iniciales); "
            f"brecha máx. entre M1 recibidos {r['brecha_max_s']} s ({r['brecha_max_en']}), "
            f"margen {r['margen_caducidad_s']} s; caducidades {r['eventos_caducidad']}")
        for x in r["lentos"]:
            lineas.append(f"    {x['corrida']}/{x['rep']} seq {x['seq']} "
                          f"{'renovación' if x['renovacion'] else 'inicial'}: ida {x['ida_ms']} ms, "
                          f"siguiente M1 {x['siguiente_llega_ms']} ms después")
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "cortes_bajada_4g.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    texto = "\n".join(lineas) + "\n"
    (a.salida / "cortes_bajada_4g.txt").write_text(texto, encoding="utf-8")
    print(texto, end="")


if __name__ == "__main__":
    main()
