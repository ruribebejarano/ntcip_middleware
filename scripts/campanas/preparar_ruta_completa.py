#!/usr/bin/env python3
"""Prepara las trayectorias base de la campaña de ruta completa
(scripts/campanas/ruta_completa.py) y las valida SIN RED con el mismo
gestor de misión del servidor (servidor/gestor_mision.py), con reloj falso
y sin broker, RSU ni controladores: solo comprueba qué solicitudes emitiría
el servidor con cada trayectoria, con el MISMO ruido GNSS (misma función y
misma semilla) que aplicará el runner en esa repetición.

Escribe en scripts/campanas/fixtures/ruta_completa/:
  trayectoria_A.csv              base del escenario A (la misma para las 5
                                 repeticiones: cambia solo el ruido)
  trayectoria_B_s<semilla>.csv   un perfil sintético por repetición de B
  trayectoria_C.csv              desvío (punto de salida elegido aquí, ver
                                 elegir_desvio())
  validacion_sin_red.json        resultado de la simulación por repetición

Uso:
    python scripts/campanas/preparar_ruta_completa.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import cargar_registro, proyeccion_local  # noqa: E402
from scripts.campanas.lazo_centralizado import _trayectoria_con_ruido  # noqa: E402
from scripts.trayectorias import generar_ruta as gr  # noqa: E402
from servidor import rutas  # noqa: E402
from servidor.gestor_mision import GestorMision  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
REGISTRO = FIX / "registro_ruta_hospital_nino.json"
SALIDA = FIX / "ruta_completa"
ORIGEN = (-12.074664, -77.082933)       # Av. La Marina (corrida de tres RSU)
DESTINO = (-12.0649978, -77.0464372)    # Instituto Nacional de Salud del Niño, Breña (OSM way/194898813)
V_A_KMH = 36.0
SIGMA_POS_M = 5.0
SEMILLAS = {"A": [101, 102, 103, 104, 105], "B": [201, 202, 203, 204, 205], "C": [301]}
RSU_DIRIGIDA = {0: "101", 1: "104"}     # B: detención dirigida, alternando por semilla


def simular(G, registro, base: Path, semilla: int) -> dict:
    """Corre la trayectoria (con el ruido de la repetición) por GestorMision
    con reloj falso. Devuelve lo que el servidor habría emitido."""
    with tempfile.TemporaryDirectory() as tmp:
        ruidosa = Path(tmp) / "t.csv"
        _trayectoria_con_ruido(base, ruidosa, semilla, SIGMA_POS_M)
        with ruidosa.open(newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
    reloj = [0.0]
    eventos: list[tuple[float, str, str, dict]] = []

    class Registro:
        def log(self, tipo, id_ref, **extra):
            eventos.append((reloj[0], tipo, id_ref, extra))

    g = GestorMision(G, registro, enviar_m1=lambda *a: None, enviar_m3=lambda *a: None,
                     enviar_mr=lambda *a: None, enviar_me=lambda *a: None, eventos=Registro(),
                     ahora=lambda: reloj[0])
    origen = (float(filas[0]["lat"]), float(filas[0]["lon"]))
    destino = (float(filas[-1]["lat"]), float(filas[-1]["lon"]))
    mision = g.armar_mision("obu", 1, origen, destino)
    paradas_ini = [p.rsu_id for p in mision.ruta.paradas]
    for k, f in enumerate(filas, start=1):
        reloj[0] = float(f["t_s"])
        g.procesar_mp("obu", float(f["lat"]), float(f["lon"]), float(f["velocidad_kmh"]), float(f["rumbo_deg"]),
                      seq=k, fuente_velocidad="sintetica")
    por_parada: dict[str, dict] = {}
    activos: list[tuple[float, float]] = []
    for t, tipo, ref, ex in eventos:
        if tipo == "M1_tx" and not ex.get("renovacion"):
            por_parada.setdefault(ref, {"rsu_id": ex.get("rsu_id"), "m1": [], "m3": []})["m1"].append(t)
        elif tipo == "M3_tx" and ref in por_parada:
            por_parada[ref]["m3"].append((t, ex.get("motivo")))
    for ref, d in por_parada.items():
        fin = d["m3"][-1][0] if d["m3"] else reloj[0]
        activos.append((d["m1"][0], fin))
    max_sim = max((sum(a <= t < b for a, b in activos) for t, *_ in eventos), default=0)
    return {
        "semilla": semilla,
        "paradas_iniciales": paradas_ini,
        "solicitudes": [{"rsu_id": d["rsu_id"], "m1_s": d["m1"], "m3": d["m3"]} for d in por_parada.values()],
        "max_simultaneas": max_sim,
        "recalculos": sum(1 for _, tipo, _, _ in eventos if tipo == "ruta_recalculada"),
        "suspensiones": [(t, ex.get("interseccion_id")) for t, tipo, _, ex in eventos
                         if tipo == "solicitud_suspendida_detenido"],
        "fin": [ex.get("motivo") for _, tipo, _, ex in eventos if tipo == "mision_desarmada"],
        "duracion_s": reloj[0],
    }


def elegir_desvio(G, ruta, paradas, registro) -> tuple[list[tuple[float, float]], dict]:
    """Salida de la ruta en Av. Brasil con la solicitud de la RSU 108 ya
    activa: se prueba cada calle lateral (sucesor que no está en la ruta) de
    los nodos de la ruta en esa ventana, y se sigue por la ruta que el
    servidor calcularía desde ahí. Se queda con la primera que, simulada con
    el ruido de la repetición, recalcula una sola vez, cancela la solicitud
    vigente y termina en destino."""
    geo = ruta.geometria
    d108 = next(p.distancia_llegada_m for p in paradas if p.rsu_id == "108")
    nodos_ruta = {n.nodo_id for n in geo}
    candidatos = [i for i, n in enumerate(geo) if d108 - 160 <= n.distancia_acumulada_m <= d108 - 10]
    probados = []
    for i in candidatos:
        for vecino in sorted(G.successors(geo[i].nodo_id)):
            if vecino in nodos_ruta:
                continue
            try:
                resto = rutas.calcular_ruta(G, (float(G.nodes[vecino]["y"]), float(G.nodes[vecino]["x"])), DESTINO)
            except rutas.SinRutaError:
                continue
            if geo[i].nodo_id in {n.nodo_id for n in resto.geometria}:
                continue  # vuelve por el mismo cruce: no es un desvío
            puntos = [(n.lat, n.lon) for n in geo[: i + 1]] + [(n.lat, n.lon) for n in resto.geometria]
            pol = gr.Polilinea(puntos)
            corte = geo[i].distancia_acumulada_m
            filas = gr.recorrer(pol, gr.perfil_constante(pol.largo, V_A_KMH),
                                tramo_de=lambda s, c=corte: "ruta" if s <= c else "desvio")
            lejos = max(rutas.proyectar_sobre_ruta(ruta, f["lat"], f["lon"]).distancia_perpendicular_m for f in filas)
            if lejos < 80:
                continue
            base = SALIDA / "trayectoria_C.csv"
            gr.escribir(filas, base)
            sim = simular(G, registro, base, SEMILLAS["C"][0])
            m3_108 = [m for s in sim["solicitudes"] if s["rsu_id"] == "108" for m in s["m3"]]
            # Válido si recalcula, termina en destino y la solicitud de la
            # RSU 108 queda cancelada ANTES de llegar a ella (el motivo lo
            # decide la geocerca al girar; se reporta tal cual).
            t_llegada_108 = (d108 - 0.0) / (V_A_KMH / 3.6)
            ok = (sim["recalculos"] >= 1 and sim["fin"] == ["destino"]
                  and any(t < t_llegada_108 for t, _ in m3_108))
            probados.append({"nodo_salida": geo[i].nodo_id, "acum_salida_m": round(corte, 1), "calle_lateral": vecino,
                             "max_fuera_de_ruta_m": round(lejos, 1), "recalculos": sim["recalculos"],
                             "m3_rsu_108": m3_108, "fin": sim["fin"], "valido": ok})
            if ok:
                return puntos, {"elegido": probados[-1], "probados": probados, "sim": sim}
    raise SystemExit(f"Ningún desvío válido en la ventana; probados: {json.dumps(probados, indent=1)}")


def main() -> None:
    G = rutas.cargar_grafo()
    registro = cargar_registro(REGISTRO)
    ruta = rutas.planificar_ruta(G, registro, ORIGEN, DESTINO)
    if len(ruta.paradas) != len(registro):
        raise SystemExit(f"El servidor solo ve {len(ruta.paradas)} de {len(registro)} RSU en la ruta")
    pol = gr.Polilinea([(n.lat, n.lon) for n in ruta.geometria])
    SALIDA.mkdir(parents=True, exist_ok=True)
    validacion: dict = {"ruta_m": round(ruta.longitud_total_m, 1),
                        "paradas": {p.rsu_id: round(p.distancia_llegada_m, 1) for p in ruta.paradas},
                        "A": [], "B": [], "C": None}

    base_a = SALIDA / "trayectoria_A.csv"
    gr.escribir(gr.recorrer(pol, gr.perfil_constante(pol.largo, V_A_KMH)), base_a)
    for s in SEMILLAS["A"]:
        validacion["A"].append(simular(G, registro, base_a, s))

    for k, s in enumerate(SEMILLAS["B"]):
        rnd = random.Random(s)
        dirigida = RSU_DIRIGIDA[k % 2]
        pos_dirigida = validacion["paradas"][dirigida] - 40.0
        detenciones = [(pos_dirigida, rnd.randint(10, 20))]
        n_azar = rnd.choice([2, 3])
        while len(detenciones) < 1 + n_azar:
            pos = rnd.uniform(300.0, pol.largo - 300.0)
            if all(abs(pos - p) >= 200.0 for p, _ in detenciones):
                detenciones.append((pos, rnd.randint(5, 20)))
        filas = gr.recorrer(pol, gr.perfil_variable(pol.largo, rnd, detenciones))
        base_b = SALIDA / f"trayectoria_B_s{s}.csv"
        gr.escribir(filas, base_b)
        sim = simular(G, registro, base_b, s)
        sim["detenciones"] = [{"pos_m": round(p, 1), "dur_s": d, "dirigida_rsu": dirigida if i == 0 else None}
                              for i, (p, d) in enumerate(detenciones)]
        validacion["B"].append(sim)

    _, info_c = elegir_desvio(G, ruta, ruta.paradas, registro)
    validacion["C"] = info_c

    (SALIDA / "validacion_sin_red.json").write_text(json.dumps(validacion, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
    for esc in ("A", "B"):
        for v in validacion[esc]:
            n_cruce = sum(1 for s in v["solicitudes"] if any(m == "cruce" for _, m in s["m3"]))
            print(f"{esc} s{v['semilla']}: {v['duracion_s']:.0f} s, {len(v['solicitudes'])} solicitudes, "
                  f"{n_cruce} con cruce, max simultáneas {v['max_simultaneas']}, suspensiones {v['suspensiones']}, "
                  f"fin {v['fin']}")
    c = validacion["C"]
    print(f"C: salida en {c['elegido']['acum_salida_m']} m (nodo {c['elegido']['nodo_salida']} -> "
          f"{c['elegido']['calle_lateral']}), {c['elegido']['max_fuera_de_ruta_m']} m fuera de ruta, "
          f"recálculos {c['sim']['recalculos']}, M3 RSU 108 {c['elegido']['m3_rsu_108']}, "
          f"duración {c['sim']['duracion_s']:.0f} s, fin {c['sim']['fin']}")
    print(f"Escrito en {SALIDA}")


if __name__ == "__main__":
    main()
