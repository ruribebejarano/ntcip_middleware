#!/usr/bin/env python3
"""Resume una evaluación: misiones, RSU, latencia, frecuencia, GNSS y error del ETA.

Las RSU y el servidor corren en la misma laptop, así que L usa un solo reloj.
Escribe resumen.txt y paradas.csv en la carpeta de la evaluación.

Uso:
    python scripts/evaluacion/resumen.py --dir resultados/evaluacion/<carpeta>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
from lazo_centralizado import analizar, cargar, percentil  # noqa: E402

UMBRAL_L_MS = 1000.0
ANTICIPACION_MIN_S = 8.0
T_CAD_S = 3.0
RADIO_PASO_M = 30.0        # el recorrido debe pasar a esta distancia del centro de la RSU
UMBRAL_DETENIDO_KMH = 1.0  # igual que el servidor: por debajo, el vehículo está detenido


def centros_rsu(directorio: Path) -> dict[str, tuple[float, float]]:
    """Centro de cada RSU, del registro que anotó evaluar.ps1 en estado.json."""
    estado = directorio / "estado.json"
    if not estado.exists():
        return {}
    texto = estado.read_text(encoding="utf-8-sig")
    registro = Path(json.loads(texto).get("registro") or "")
    candidatos = [registro, RAIZ / "resultados" / "evaluacion" / "rutas" / registro.name.split("\\")[-1]]
    for c in candidatos:
        if c.name and c.exists():
            datos = json.loads(c.read_text(encoding="utf-8"))
            return {str(r["rsu_id"]): (r["centro"]["lat"], r["centro"]["lon"]) for r in datos.get("rsu", [])}
    return {}


def _xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    return (lon - lon0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 110574


def paso_por_centro(mps: list[tuple[float, float, float]], centro: tuple[float, float]) -> tuple[float, float] | None:
    """Instante (s) y distancia (m) del punto del recorrido más cercano al centro,
    interpolando entre MP consecutivos. mps: (t_s, lat, lon) en orden."""
    mejor = None
    for (ta, la, oa), (tb, lb, ob) in zip(mps, mps[1:]):
        xa, ya = _xy(la, oa, *centro)
        xb, yb = _xy(lb, ob, *centro)
        dx, dy = xb - xa, yb - ya
        largo = dx * dx + dy * dy
        u = 0.0 if largo == 0 else max(0.0, min(1.0, (-xa * dx - ya * dy) / largo))
        d = math.hypot(xa + u * dx, ya + u * dy)
        if mejor is None or d < mejor[1]:
            mejor = (ta + u * (tb - ta), d)
    return mejor


HORIZONTE_ETA_S = 8.0       # el error se mide en la estimación más cercana a este ETA (margen de RF-13)
VENTANA_HORIZONTE_S = 2.0   # ... siempre que esté a menos de esto del horizonte


def error_eta(eventos: list[dict], centros: dict[str, tuple[float, float]]) -> list[dict]:
    """Error del ETA del servidor, una fila por paso por una RSU.

    El servidor registra con cada MP su ETA a la siguiente RSU (evento
    eta_estimado). El instante real de llegada es el del punto del recorrido
    más cercano al centro de la RSU, interpolando entre MP. Se toma la
    estimación más cercana a HORIZONTE_ETA_S y se compara: error = tiempo real
    restante - ETA (positivo: el vehículo llegó más tarde). Todo usa el reloj
    del servidor (MP_rx y eta_estimado), así que no cruza relojes."""
    mps: dict[str, list[tuple[float, float, float, object]]] = defaultdict(list)
    etas: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for e in eventos:
        x = e["extra"]
        if e["tipo_evento"] == "MP_rx" and x.get("lat") is not None:
            mps[e["id_solicitud"]].append((e["ts_ns"] / 1e9, float(x["lat"]), float(x["lon"]), x.get("velocidad_kmh")))
        elif e["tipo_evento"] == "eta_estimado" and x.get("eta_s") is not None:
            etas[(e["id_solicitud"], str(x.get("rsu_id")))].append((e["ts_ns"] / 1e9, float(x["eta_s"])))
    filas = []
    for (mision, rsu_id), estimaciones in etas.items():
        centro = centros.get(rsu_id)
        if centro is None:
            continue
        estimaciones.sort()
        t0, t1 = estimaciones[0][0], estimaciones[-1][0]
        tramo = sorted(m for m in mps.get(mision, []) if t0 - 2 <= m[0] <= t1 + 60)
        paso = paso_por_centro([(t, la, lo) for t, la, lo, _ in tramo], centro)
        if paso is None or paso[1] > RADIO_PASO_M:
            continue
        previas = [(t, eta) for t, eta in estimaciones if t <= paso[0]]
        if not previas:
            continue
        t_est, eta = min(previas, key=lambda te: abs(te[1] - HORIZONTE_ETA_S))
        if abs(eta - HORIZONTE_ETA_S) > VENTANA_HORIZONTE_S:
            continue
        real = paso[0] - t_est
        detenido = any(v is not None and float(v) < UMBRAL_DETENIDO_KMH for t, _, _, v in tramo if t_est <= t <= paso[0])
        filas.append({"mision_id": mision, "rsu_id": rsu_id, "eta_s": round(eta, 2),
                      "t_real_hasta_centro_s": round(real, 2), "error_eta_s": round(real - eta, 2),
                      "con_detencion": detenido, "distancia_paso_m": round(paso[1], 1)})
    return filas


def error_eta_al_solicitar(eventos: list[dict], centros: dict[str, tuple[float, float]]) -> list[dict]:
    """Error del ETA en el momento de pedir prioridad, una fila por solicitud.

    El servidor deja de registrar eta_estimado de una RSU en cuanto le envía
    el M1. Si la geocerca abre la solicitud a ~150 m (lo normal), nunca hay
    un ETA cercano a 8 s y error_eta() queda sin datos (prueba con GPS real
    del 2026-11-11). Aquí se toma el último ETA antes del primer M1, que es
    el que el servidor tenía al decidir, y se compara con el tiempo real
    hasta pasar por el centro de la RSU. Solo reloj del servidor."""
    mps: dict[str, list[tuple[float, float, float, object]]] = defaultdict(list)
    etas: dict[tuple[str, str], list[tuple[float, float, object, object]]] = defaultdict(list)
    primer_m1: dict[str, dict] = {}
    for e in eventos:
        x = e["extra"]
        if e["tipo_evento"] == "MP_rx" and x.get("lat") is not None:
            mps[e["id_solicitud"]].append((e["ts_ns"] / 1e9, float(x["lat"]), float(x["lon"]), x.get("velocidad_kmh")))
        elif e["tipo_evento"] == "eta_estimado" and x.get("eta_s") is not None:
            etas[(e["id_solicitud"], str(x.get("rsu_id")))].append(
                (e["ts_ns"] / 1e9, float(x["eta_s"]), x.get("distancia_restante_m"), x.get("velocidad_kmh")))
        elif e["tipo_evento"] == "M1_tx" and not x.get("renovacion") and e["id_solicitud"] not in primer_m1:
            primer_m1[e["id_solicitud"]] = {"ts": e["ts_ns"] / 1e9, "mision_id": x.get("mision_id"),
                                           "rsu_id": str(x.get("rsu_id")), "t_servicio": x.get("t_servicio")}
    filas = []
    for id_sol, m1 in primer_m1.items():
        centro = centros.get(m1["rsu_id"])
        previas = [p for p in sorted(etas.get((m1["mision_id"], m1["rsu_id"]), [])) if p[0] <= m1["ts"]]
        if centro is None or not previas:
            continue
        t_est, eta, distancia, velocidad = previas[-1]
        tramo = sorted(m for m in mps.get(m1["mision_id"], []) if t_est - 2 <= m[0] <= t_est + 600)
        paso = paso_por_centro([(t, la, lo) for t, la, lo, _ in tramo], centro)
        if paso is None or paso[1] > RADIO_PASO_M:
            continue
        real = paso[0] - t_est
        detenido = any(v is not None and float(v) < UMBRAL_DETENIDO_KMH for t, _, _, v in tramo if t_est <= t <= paso[0])
        filas.append({"id_solicitud": id_sol, "mision_id": m1["mision_id"], "rsu_id": m1["rsu_id"],
                      "abierta_por": "geocerca" if m1["t_servicio"] == ANTICIPACION_MIN_S else "eta",
                      "eta_al_solicitar_s": round(eta, 2), "distancia_al_solicitar_m": distancia,
                      "velocidad_al_solicitar_kmh": velocidad, "t_real_hasta_centro_al_solicitar_s": round(real, 2),
                      "error_eta_al_solicitar_s": round(real - eta, 2), "con_detencion_al_solicitar": detenido})
    return filas


def intervalos_mp(eventos: list[dict]) -> list[float]:
    """Intervalos entre MP recibidos por el servidor, misión por misión."""
    por_mision: dict[str, list[int]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] == "MP_rx":
            por_mision[e["id_solicitud"]].append(e["ts_ns"])
    salida: list[float] = []
    for marcas in por_mision.values():
        marcas.sort()
        salida.extend((b - a) / 1e9 for a, b in zip(marcas, marcas[1:]))
    return salida


def veredicto(cumple: bool) -> str:
    return "cumple" if cumple else "NO CUMPLE"


def texto_resumen(eventos: list[dict], centros: dict[str, tuple[float, float]] | None = None) -> tuple[str, list[dict]]:
    _misiones, paradas, g = analizar(eventos, 0.0, True)
    conteo = Counter(e["tipo_evento"] for e in eventos)
    lineas: list[str] = []
    salida = lineas.append

    salida(f"Misiones armadas: {conteo['mision_armada']}  desarmadas: {conteo['mision_desarmada']}")
    motivos = Counter(str(e["extra"].get("motivo")) for e in eventos if e["tipo_evento"] == "mision_desarmada")
    if motivos:
        salida("Fin de misión por motivo: " + ", ".join(f"{k}: {v}" for k, v in motivos.items()))
    salida(f"Recálculos por desvío: {conteo['ruta_recalculada']}")
    salida("")

    resultados = Counter(str(f.get("resultado")) for f in paradas)
    salida(f"Paradas en RSU: {len(paradas)} (" + ", ".join(f"{k}: {v}" for k, v in resultados.items()) + ")")
    salida(f"Caducidades: {conteo['caducidad']}")
    if not paradas:
        salida("AVISO: ninguna solicitud llegó a una RSU. Revisa que el recorrido pase por ellas.")

    l = g["L_ms"]
    if l.get("n"):
        salida(f"L: mediana {l['mediana']:.2f} ms, p95 {l['p95']:.2f} ms, máx. {l['max']:.2f} ms "
               f"(RNF-01, p95 <= {UMBRAL_L_MS:.0f} ms: {veredicto(l['p95'] <= UMBRAL_L_MS)})")
    rtt = g["RTT_srv_ms"]
    if rtt.get("n"):
        salida(f"RTT servidor-RSU: mediana {rtt['mediana']:.2f} ms, p95 {rtt['p95']:.2f} ms")

    anticipaciones = [f["anticipacion_real_s"] for f in paradas if f.get("anticipacion_real_s") is not None]
    if anticipaciones:
        minima = min(anticipaciones)
        salida(f"Anticipación real: n={len(anticipaciones)}, mediana {percentil(anticipaciones, 50):.2f} s, "
               f"mínima {minima:.2f} s (margen de {ANTICIPACION_MIN_S:.0f} s: "
               f"{veredicto(minima >= ANTICIPACION_MIN_S)})")
    sin_cruce = len(paradas) - len(anticipaciones)
    if sin_cruce:
        salida(f"Paradas sin cruce detectado: {sin_cruce}")
    salida("")

    intervalos = intervalos_mp(eventos)
    if intervalos:
        huecos = sum(1 for i in intervalos if i > T_CAD_S)
        mediana = percentil(intervalos, 50)
        salida(f"MP recibidos: {conteo['MP_rx']}; intervalo mediana {mediana:.3f} s, "
               f"p95 {percentil(intervalos, 95):.3f} s, máx. {max(intervalos):.3f} s "
               f"(RNF-02, 1 Hz: {veredicto(mediana <= 1.05)})")
        salida(f"Huecos de MP mayores que {T_CAD_S:.0f} s: {huecos}")
    salida(f"MP descartados por el servidor: {conteo['MP_descartado']}")

    fuentes = Counter(str(e["extra"].get("fuente_velocidad")) for e in eventos if e["tipo_evento"] == "MP_rx")
    total = sum(fuentes.values())
    if total:
        salida("Fuente de velocidad: " + ", ".join(f"{k} {100 * v / total:.1f} %" for k, v in fuentes.most_common()))
        sin_dato = sum(1 for e in eventos if e["tipo_evento"] == "MP_rx" and e["extra"].get("velocidad_kmh") is None)
        salida(f"MP sin velocidad (dato nulo): {100 * sin_dato / total:.1f} %")

    filas_eta = error_eta(eventos, centros or {})
    if filas_eta:
        salida("")
        salida(f"Error del ETA a ~{HORIZONTE_ETA_S:.0f} s del cruce (real - estimado; positivo = llegó más tarde):")
        for nombre, grupo in (("todas", filas_eta),
                              ("sin detención", [f for f in filas_eta if not f["con_detencion"]]),
                              ("con detención", [f for f in filas_eta if f["con_detencion"]])):
            errores = [f["error_eta_s"] for f in grupo]
            if errores:
                salida(f"  {nombre}: n={len(errores)}, mediana {percentil(errores, 50):+.2f} s, "
                       f"p95 del error absoluto {percentil([abs(v) for v in errores], 95):.2f} s")
        for fila in paradas:
            extra = next((f for f in filas_eta if f["mision_id"] == fila.get("mision_id")
                          and f["rsu_id"] == str(fila.get("rsu_id"))), {})
            for k in ("eta_s", "t_real_hasta_centro_s", "error_eta_s", "con_detencion"):
                fila[k] = extra.get(k)
    filas_sol = error_eta_al_solicitar(eventos, centros or {})
    if filas_sol:
        salida("")
        salida("Error del ETA al pedir prioridad (último ETA antes del M1; real - estimado; positivo = llegó más tarde):")
        for nombre, grupo in (("todas", filas_sol),
                              ("sin detención", [f for f in filas_sol if not f["con_detencion_al_solicitar"]]),
                              ("con detención", [f for f in filas_sol if f["con_detencion_al_solicitar"]])):
            errores = [f["error_eta_al_solicitar_s"] for f in grupo]
            if errores:
                salida(f"  {nombre}: n={len(errores)}, mediana {percentil(errores, 50):+.2f} s, "
                       f"p95 del error absoluto {percentil([abs(v) for v in errores], 95):.2f} s, "
                       f"ETA al pedir mediana {percentil([f['eta_al_solicitar_s'] for f in grupo], 50):.1f} s")
        abiertas = Counter(f["abierta_por"] for f in filas_sol)
        salida("  Solicitudes abiertas por: " + ", ".join(f"{k} {v}" for k, v in abiertas.items())
               + " (geocerca = t_servicio de 8 s)")
        por_id = {f["id_solicitud"]: f for f in filas_sol}
        for fila in paradas:
            extra = por_id.get(fila.get("id_solicitud"), {})
            for k in ("abierta_por", "eta_al_solicitar_s", "distancia_al_solicitar_m", "velocidad_al_solicitar_kmh",
                      "t_real_hasta_centro_al_solicitar_s", "error_eta_al_solicitar_s", "con_detencion_al_solicitar"):
                fila[k] = extra.get(k)
    if not filas_eta and centros:
        salida("")
        if not any(e["tipo_evento"] == "eta_estimado" for e in eventos):
            salida("Error del ETA: sin datos (el servidor de esta corrida no registraba eta_estimado).")
        else:
            salida(f"Error del ETA a ~{HORIZONTE_ETA_S:.0f} s: sin datos (ningún ETA cercano a {HORIZONTE_ETA_S:.0f} s "
                   f"antes de pasar a menos de {RADIO_PASO_M:.0f} m del centro: la geocerca pidió prioridad antes; "
                   "ver el error al pedir prioridad).")
    return "\n".join(lineas) + "\n", paradas


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True)
    args = ap.parse_args()
    eventos = cargar([args.dir])
    if not eventos:
        sys.exit(f"No hay eventos en {args.dir}.")
    texto, paradas = texto_resumen(eventos, centros_rsu(args.dir))
    (args.dir / "resumen.txt").write_text(texto, encoding="utf-8")
    if paradas:
        with (args.dir / "paradas.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(paradas[0].keys()))
            w.writeheader()
            w.writerows(paradas)
    print(texto)
    print(f"Guardado en {args.dir}")


if __name__ == "__main__":
    main()
