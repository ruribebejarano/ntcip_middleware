#!/usr/bin/env python3
"""OE4 (Fase 4, prueba 6): resumen del escenario de conflicto entre dos
misiones en la misma intersección, corrido en el banco con
scripts/campanas/lazo_centralizado.py --escenario conflicto --config local.

Por repetición, con los eventos del servidor (un solo reloj) y del
controlador emulado:
  decisión         qué misión quedó atendida y cuál en espera, y si la
                   decisión coincide con servidor/conflictos.py (lo verifica
                   scripts/analisis/lazo_centralizado.py, aquí se resume);
  t_arbitraje      MP que dispara el arbitraje -> evento conflicto_arbitrado
  t_desalojo       conflicto_arbitrado -> M3 (motivo conflicto) a la misión
                   desplazada, si había una ya atendida
  t_liberacion     ese M3 -> liberación registrada por el controlador
  estado final     el controlador termina sin prioridad activa y la RSU sin
                   solicitudes abiertas (ningún M1 sin su M3)

Uso: .venv/Scripts/python.exe scripts/evaluacion/conflicto_resumen.py --dir resultados/campana/<corrida>_conflicto_local
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def leer(f: Path) -> list[dict]:
    with f.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for r in filas:
        r["x"] = json.loads(r["extra_json"]) if r.get("extra_json") else {}
        r["ts"] = int(r["ts_ns"])
    return sorted(filas, key=lambda r: r["ts"])


def pct(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (k - i)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    corrida = Path(args.dir)
    reps = []
    for rep in sorted(corrida.glob("rep_*")):
        srv = leer(rep / "eventos_servidor.csv")
        ctrl = leer(next(rep.glob("eventos_ctrl_*.csv")))
        rsu = leer(next(rep.glob("eventos_rsu_*.csv")))
        arb = [e for e in srv if e["tipo_evento"] == "conflicto_arbitrado"]
        if not arb:
            reps.append({"rep": rep.name, "conflicto": False})
            continue
        a = arb[0]
        mp_previo = max(e["ts"] for e in srv if e["tipo_evento"] == "MP_rx" and e["ts"] <= a["ts"])
        m3c = next((e for e in srv if e["tipo_evento"] == "M3_tx" and e["x"].get("motivo") == "conflicto"
                    and e["ts"] >= a["ts"]), None)
        lib = None
        if m3c is not None:
            lib = next((e for e in ctrl if e["x"].get("motivo") == "liberacion_manual"
                        and e["id_solicitud"] == m3c["id_solicitud"] and e["ts"] >= m3c["ts"]), None)
        abiertas = {e["id_solicitud"] for e in rsu if e["tipo_evento"] == "M1_rx"} - \
                   {e["id_solicitud"] for e in rsu if e["tipo_evento"] == "M3_rx"}
        ultimo_ctrl = ctrl[-1]
        reps.append({
            "rep": rep.name, "conflicto": True,
            "atendida": a["x"].get("atendidos"), "en_espera": a["x"].get("en_espera"),
            "candidatos": a["x"].get("candidatos"),
            "t_arbitraje_ms": (a["ts"] - mp_previo) / 1e6,
            "desalojo": m3c is not None,
            "t_desalojo_ms": (m3c["ts"] - a["ts"]) / 1e6 if m3c else None,
            "t_liberacion_ms": (lib["ts"] - m3c["ts"]) / 1e6 if lib else None,
            "final_prioridad_activa": bool(ultimo_ctrl["x"].get("prioridad_activa")),
            "solicitudes_abiertas_rsu": sorted(abiertas),
        })
    con = [r for r in reps if r["conflicto"]]
    ta = [r["t_arbitraje_ms"] for r in con]
    td = [r["t_desalojo_ms"] for r in con if r["t_desalojo_ms"] is not None]
    tl = [r["t_liberacion_ms"] for r in con if r["t_liberacion_ms"] is not None]
    analisis = (corrida / "analisis.txt").read_text(encoding="utf-8", errors="replace")
    res = {"repeticiones": len(reps), "con_conflicto": len(con),
           "t_arbitraje_ms": {"med": pct(ta, 50), "max": max(ta)} if ta else None,
           "desalojos": len(td),
           "t_desalojo_ms": {"med": pct(td, 50), "max": max(td)} if td else None,
           "t_liberacion_ms": {"med": pct(tl, 50), "max": max(tl)} if tl else None,
           "final_con_prioridad": sum(r["final_prioridad_activa"] for r in con),
           "final_con_solicitudes_abiertas": sum(1 for r in con if r["solicitudes_abiertas_rsu"]),
           "analisis_lazo_centralizado": [ln for ln in analisis.splitlines()
                                          if ln.startswith(("Arbitraje consistente", "Ganadores", "Perdedores"))],
           "reps": reps}
    (corrida / "conflicto_resumen.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    coma = lambda x, d=2: f"{x:.{d}f}".replace(".", ",")  # noqa: E731
    gan = [c for r in con for c in (r.get("candidatos") or []) if c["mision_id"] in (r.get("atendida") or [])]
    per = [c for r in con for c in (r.get("candidatos") or []) if c["mision_id"] in (r.get("en_espera") or [])]
    lin = res["analisis_lazo_centralizado"]
    filas = [
        ("Repeticiones con conflicto detectado", f"{len(con)} de {len(reps)}"),
        ("Decisión consistente con la política de arbitraje", lin[0].split(": ")[-1] if lin else "--"),
        ("ETA de la misión atendida / desplazada (mediana, s)",
         f"{coma(pct([c['eta_s'] for c in gan], 50), 1)} / {coma(pct([c['eta_s'] for c in per], 50), 1)}"),
        ("Tiempo de arbitraje: MP $\\to$ decisión (mediana / máx., ms)",
         f"{coma(res['t_arbitraje_ms']['med'])} / {coma(res['t_arbitraje_ms']['max'])}"),
        ("Decisión $\\to$ M3 a la misión desplazada (mediana / máx., ms)",
         f"{coma(res['t_desalojo_ms']['med'])} / {coma(res['t_desalojo_ms']['max'])}" if res["t_desalojo_ms"] else "--"),
        ("M3 $\\to$ liberación en el controlador (mediana / máx., ms)",
         f"{coma(res['t_liberacion_ms']['med'])} / {coma(res['t_liberacion_ms']['max'])}" if res["t_liberacion_ms"] else "--"),
        ("Misión desplazada: atendida después / cruzó sin prioridad",
         (lin[2].split("(")[1].split(",")[0].split(": ")[1] + " / " + lin[2].split(", ")[1].split(": ")[1])
         if len(lin) > 2 else "--"),
        ("Final con prioridad activa / con solicitudes abiertas",
         f"{res['final_con_prioridad']} / {res['final_con_solicitudes_abiertas']}"),
    ]
    tex = ("\\begin{table}[H]\n\\centering\n\\caption[Conflicto entre dos misiones en el banco]{Conflicto entre "
           "dos misiones que llegan a la misma intersección por accesos incompatibles, en el banco de pruebas "
           f"(condición local, {len(reps)} repeticiones). Los tiempos usan un solo reloj.}}\n"
           "\\label{tab:conflicto}\n\\small\n\\begin{tabular}{lr}\n\\toprule\n"
           "\\textbf{Métrica} & \\textbf{Valor} \\\\\n\\midrule\n" +
           "\n".join(f"{a} & {b} \\\\" for a, b in filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")
    (corrida / "tabla_conflicto.tex").write_text(tex, encoding="utf-8")
    for k, v in res.items():
        if k != "reps":
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
