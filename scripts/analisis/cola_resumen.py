#!/usr/bin/env python3
"""Resumen de la prueba de colas (scripts/campanas/prueba_cola.sh,
docs/PRUEBA_COLA.md).

Para cada repetición de las corridas *_lazo_local_cola_*, reconstruye con
los eventos del servidor, de la RSU y del controlador emulado:

  d_emision_m   distancia a la línea de detención al emitirse el primer M1
  t_previo_s    tiempo en cola, desde el armado de la misión, antes del primer M1
  t_cola_s      tiempo total en cola (armado -> cabeza de la cola)
  verde_cola_s  segundos de verde concedido con el vehículo todavía en la
                cola (verde por prioridad -> cabeza de la cola); es el verde
                disponible para descargar la cola que lo precede
  emisiones     M1 iniciales (seq = 1) enviados a la RSU; más de uno indica
                suspensiones y re-emisiones
  m3_detenido   M3 por vehículo detenido (suspensiones)
  obtuvo_verde  si el verde por prioridad se concedió antes del cruce

La distancia de cada MP sale de la trayectoria base (sin ruido) de la
repetición: el MP de seq k es la fila k-1 (gateway/obu_emulada.py).

Uso:
    python scripts/analisis/cola_resumen.py                  # todas las corridas *_lazo_local_cola_*
    python scripts/analisis/cola_resumen.py --dir A --dir B --salida <carpeta>
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway.geometria import proyeccion_local  # noqa: E402
from leyenda_tabla import formalizar  # noqa: E402  (título corto y nota al pie)

ETIQUETAS = {
    "cola_geocerca_eta8": r"$R_{\mathrm{g}}$ 150~m o ETA 8~s",
    "cola_geocerca_eta16": r"$R_{\mathrm{g}}$ 150~m o ETA 16,3~s",
    "cola_eta16": r"Solo ETA 16,3~s, suspensión a 5~s",
    "cola_eta16_sin_suspension": r"Solo ETA 16,3~s, sin suspensión",
}
GRUPOS = {  # corridas que se reportan en una sola fila de la tabla
    "cola_geocerca_eta8": r"$R_{\mathrm{g}}$ 150~m o ETA (8~s o 16,3~s)",
    "cola_geocerca_eta16": r"$R_{\mathrm{g}}$ 150~m o ETA (8~s o 16,3~s)",
}


def _eventos(rep: Path) -> list[dict]:
    ev = []
    for f in rep.glob("eventos_*.csv"):
        with f.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["t"] = int(r["ts_ns"]) / 1e9
                r["x"] = json.loads(r["extra_json"]) if r.get("extra_json") else {}
                ev.append(r)
    ev.sort(key=lambda r: r["t"])
    return ev


def _distancias(rep: Path) -> list[float]:
    base = next(rep.glob("base_cola_*.csv"))
    with base.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    lat0, lon0 = float(filas[0]["lat"]), float(filas[0]["lon"])
    out = []
    for f in filas:
        x, y = proyeccion_local(float(f["lat"]), float(f["lon"]), lat0, lon0)
        out.append((x * x + y * y) ** 0.5)
    return out


def analizar_repeticion(rep: Path, largo_cola_m: float) -> dict:
    ev = _eventos(rep)
    dist = _distancias(rep)
    srv = [e for e in ev if e["nodo"] == "servidor"]
    t_armado = next(e["t"] for e in srv if e["tipo_evento"] == "mision_armada")
    mps = [e for e in srv if e["tipo_evento"] == "MP_rx"]

    def d_de_mp(e: dict) -> float:
        return dist[min(int(e["x"]["seq"]) - 1, len(dist) - 1)]

    t_cabeza = next((e["t"] for e in mps if d_de_mp(e) >= largo_cola_m), None)
    m1_ini = [e for e in srv if e["tipo_evento"] == "M1_tx" and not e["x"].get("renovacion")]
    m3 = [e for e in srv if e["tipo_evento"] == "M3_tx"]
    t_cruce = next((e["t"] for e in m3 if e["x"].get("motivo") == "cruce"), None)

    d_emision = t_m1 = None
    if m1_ini:
        t_m1 = m1_ini[0]["t"]
        previo = [e for e in mps if e["t"] <= t_m1]
        d_emision = largo_cola_m - d_de_mp(previo[-1]) if previo else None

    # Línea de tiempo del acceso solicitado: fase del controlador (todos sus
    # cambios quedan en ctrl_fase_cambio) y prioridad vigente. La prioridad
    # empieza cuando el controlador pasa a verde con prioridad activa o
    # cuando la RSU la pide con el controlador ya en verde (concesión
    # inmediata), y termina con la liberación (snmp clear_*) o con el paso
    # del controlador a otra fase.
    tramos: list[tuple[float, float]] = []  # verde por prioridad (inicio, fin)
    fase, inicio_prio, fase_al_cruce = None, None, None
    for e in ev:
        if t_cruce is not None and fase_al_cruce is None and e["t"] > t_cruce:
            fase_al_cruce = fase
        es_ctrl = e["nodo"].startswith("ctrl") and e["tipo_evento"] == "ctrl_fase_cambio"
        es_snmp = e["nodo"].startswith("rsu") and e["tipo_evento"] == "snmp_set_tx"
        if es_ctrl:
            fase = e["x"].get("fase")
            if fase == "verde" and e["x"].get("prioridad_activa") and inicio_prio is None:
                inicio_prio = e["t"]
            elif fase != "verde" and inicio_prio is not None:
                tramos.append((inicio_prio, e["t"]))
                inicio_prio = None
        elif es_snmp:
            accion = e["x"].get("accion", "")
            if accion == "request_priority" and e["x"].get("fase") == "verde" and inicio_prio is None:
                inicio_prio = e["t"]
            elif accion.startswith("clear") and inicio_prio is not None:
                tramos.append((inicio_prio, e["t"]))
                inicio_prio = None
    if inicio_prio is not None:
        tramos.append((inicio_prio, ev[-1]["t"]))
    if t_cruce is not None and fase_al_cruce is None:
        fase_al_cruce = fase

    verde_cola = None
    if t_cabeza is not None:
        verde_cola = sum(max(0.0, min(fin, t_cabeza) - ini) for ini, fin in tramos)

    return {
        "repeticion": rep.name,
        "d_emision_m": d_emision,
        "t_previo_s": None if t_m1 is None else t_m1 - t_armado,
        "t_cola_s": None if t_cabeza is None else t_cabeza - t_armado,
        "verde_cola_s": verde_cola,
        "cortes_verde": sum(1 for ini, fin in tramos if t_cabeza is not None and fin < t_cabeza),
        "emisiones": len(m1_ini),
        "m3_detenido": sum(1 for e in m3 if e["x"].get("motivo") == "detenido"),
        "fase_al_cruce": fase_al_cruce,
        "obtuvo_verde": fase_al_cruce == "verde",
    }


def _num(x: float | None, dec: int = 1) -> str:
    return "--" if x is None else f"{x:.{dec}f}".replace(".", ",")


def _rango(xs: list, dec: int = 1) -> str:
    xs = [x for x in xs if x is not None]
    if not xs:
        return "--"
    lo, hi = min(xs), max(xs)
    return _num(lo, dec) if abs(hi - lo) < 0.05 else f"{_num(lo, dec)}--{_num(hi, dec)}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", default=None)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    dirs = [Path(d) for d in args.dir] if args.dir else sorted(
        (RAIZ / "resultados" / "campana").glob("*_lazo_local_cola_*"))
    if not dirs:
        raise SystemExit("No hay corridas *_lazo_local_cola_* (scripts/campanas/prueba_cola.sh)")

    corridas = []
    for d in dirs:
        config = json.loads((d / "config.json").read_text(encoding="utf-8"))
        cola = config.get("cola") or {}
        reps = [analizar_repeticion(r, cola.get("largo_m", 280.0)) for r in sorted(d.glob("rep_*"))]
        etiqueta = next((k for k in sorted(ETIQUETAS, key=len, reverse=True) if d.name.endswith(k)), d.name)
        corridas.append({"corrida": d.name, "criterio": etiqueta, "cola": cola,
                         "r_g_m": config.get("r_g_m"), "eta_emision_s": config.get("eta_emision_s"),
                         "repeticiones": reps})
        print(f"{d.name}: {len(reps)} repeticiones")
        for r in reps:
            print(f"   {r['repeticion']}: d_emision={_num(r['d_emision_m'])} m, previo={_num(r['t_previo_s'])} s, "
                  f"cola={_num(r['t_cola_s'])} s, verde_en_cola={_num(r['verde_cola_s'])} s, "
                  f"cortes={r['cortes_verde']}, emisiones={r['emisiones']}, M3 detenido={r['m3_detenido']}, "
                  f"fase al cruce={r['fase_al_cruce']}")

    salida = Path(args.salida) if args.salida else dirs[-1].parent / "_cola"
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "cola_resumen.json").write_text(json.dumps(corridas, indent=2, ensure_ascii=False),
                                              encoding="utf-8")
    # Una fila por grupo: las dos corridas con geocerca dan el mismo punto de
    # emisión (con la geocerca, el umbral de ETA no llega a actuar en la cola),
    # así que se reportan juntas.
    grupos: dict[str, list[dict]] = {}
    for c in corridas:
        etiqueta = GRUPOS.get(c["criterio"], ETIQUETAS.get(c["criterio"], c["criterio"]))
        grupos.setdefault(etiqueta, []).extend(c["repeticiones"])
    filas = []
    for etiqueta, reps in grupos.items():
        filas.append(
            f"{etiqueta} & {len(reps)} & "
            f"{_rango([r['d_emision_m'] for r in reps])} & {_rango([r['t_previo_s'] for r in reps])} & "
            f"{_rango([r['t_cola_s'] for r in reps])} & {_rango([r['verde_cola_s'] for r in reps])} & "
            f"{_rango([float(r['cortes_verde']) for r in reps], 0)} & "
            f"{_rango([float(r['emisiones']) for r in reps], 0)} / {_rango([float(r['m3_detenido']) for r in reps], 0)} & "
            f"{sum(1 for r in reps if r['obtuvo_verde'])}/{len(reps)} \\\\")
    cola = corridas[0]["cola"]
    perfil = (f"{_num(cola.get('parada_s'), 0)}~s detenido y {_num(cola.get('avance_s'), 0)}~s a "
              f"{_num(cola.get('v_avance_kmh'), 0)}~km/h, en una cola de {_num(cola.get('largo_m'), 0)}~m")
    tex = "\n".join([
        r"\begin{table}[H]", r"\centering",
        r"\caption{Emisión de la solicitud con el vehículo en una cola. Perfil de parada y arranque: "
        + perfil + r"; controlador con los tiempos INDRA. $d_{em}$: distancia a la línea de detención al "
        r"emitirse el primer M1; $t_{previo}$: tiempo en cola antes de ese M1; $t_{cola}$: tiempo total en "
        r"cola; verde en cola: segundos de verde por prioridad con el vehículo todavía en la cola; cortes: "
        r"veces que ese verde se liberó antes de que el vehículo saliera de la cola; verde al cruce: "
        r"repeticiones con el acceso en verde cuando el servidor detectó el cruce; "
        r"emisiones / suspensiones: M1 iniciales y M3 por vehículo detenido. Rangos entre repeticiones. "
        r"Elaboración propia.}",
        r"\label{tab:cola}", r"\small", r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lrccccccc}", r"\toprule",
        r"Criterio & Rep. & $d_{em}$ (m) & $t_{previo}$ (s) & $t_{cola}$ (s) & Verde en cola (s) "
        r"& Cortes & Emisiones / susp. & Verde al cruce \\",
        r"\midrule", *filas, r"\bottomrule", r"\end{tabular}}", r"\end{table}", ""])
    (salida / "tabla_cola.tex").write_text(formalizar(tex), encoding="utf-8")
    print(f"\nResumen: {salida / 'cola_resumen.json'}\nTabla:   {salida / 'tabla_cola.tex'}")


if __name__ == "__main__":
    main()
