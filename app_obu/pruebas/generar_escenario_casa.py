"""Genera el escenario "casa" (prueba caminando con GPS real, ver
app_obu/README.md, seccion "Escenario casa").

A partir de un origen y un destino:

1. Verifica que data/grafo_san_miguel_real.graphml los cubra (dentro de la
   caja del grafo y a poca distancia del nodo mas cercano). Si no, imprime
   el comando de scripts/datos/regenerar_grafo.py que haria falta (caja que
   une la actual con los dos puntos nuevos, para no romper los otros
   escenarios) y termina con codigo 2.
2. Calcula la ruta real con servidor/rutas.py::calcular_ruta (la MISMA que
   calculara el servidor al recibir el MI).
3. Elige una interseccion semaforizada de OSM sobre la ruta: un nodo de la
   ruta con highway=traffic_signals en el propio grafo (o a <= 25 m de uno,
   porque OSM a veces etiqueta la senal en el nodo de aproximacion y no en
   el de cruce), con street_count >= 3, a >= --min-desde-origen-m del origen
   (para que la entrada a la geocerca R_g ocurra ya caminando) y a >= 60 m
   del destino. Entre las que califican, la primera por la ruta.
4. Escribe registro_rsu_casa.json (rsu_id --rsu-id, por defecto 7) con
   accesos y rumbos calculados desde la geometria real del grafo, igual que
   registro_rsu_hospital_nino.json.
5. Escribe trayectoria_casa.csv a --velocidad-kmh (5 km/h por defecto), 1 Hz,
   para un ensayo previo en modo "Ruta emulada" o con gateway/obu_emulada.py.
6. Simula servidor/gestor_mision.py::GestorMision con esa trayectoria (reloj
   falso, sin MQTT) y reporta cuando se enviaria el M1, con que t_servicio,
   y el ETA que veria la OBU -- para revisar el comportamiento a pie.

Correr desde la raiz del repo (necesita servidor/ y gateway/):

    python app_obu/pruebas/generar_escenario_casa.py --origen LAT,LON --destino LAT,LON
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from gateway.geometria import (  # noqa: E402
    ParametrosGeometria,
    cargar_registro,
    delta_psi,
    proyeccion_local,
    rumbo_entre,
)
from servidor import rutas as rutas_mod  # noqa: E402
from servidor.gestor_mision import (  # noqa: E402
    ANTICIPACION_MINIMA_S,
    VELOCIDAD_RESPALDO_KMH,
    GestorMision,
)

DIR_PRUEBAS = Path(__file__).resolve().parent
DISTANCIA_AVISO_NODO_M = 80.0    # mas lejos que esto del nodo mas cercano: aviso (la ruta empieza/termina en ese nodo)
DISTANCIA_MAX_NODO_M = 300.0     # mas lejos que esto: el grafo no cubre el punto (le falta la zona)
RADIO_SENAL_CERCANA_M = 25.0
DEDUP_ACCESOS_DEG = 20.0


def _punto(texto: str) -> tuple[float, float]:
    lat, lon = (float(x) for x in texto.split(","))
    return lat, lon


def _dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    x, y = proyeccion_local(lat1, lon1, lat2, lon2)
    return math.hypot(x, y)


def verificar_cobertura(G, puntos: dict[str, tuple[float, float]]) -> bool:
    lats = [d["y"] for _, d in G.nodes(data=True)]
    lons = [d["x"] for _, d in G.nodes(data=True)]
    caja = (min(lats), max(lats), min(lons), max(lons))
    print(f"Caja del grafo: lat [{caja[0]:.5f}, {caja[1]:.5f}]  lon [{caja[2]:.5f}, {caja[3]:.5f}]  "
          f"({G.number_of_nodes()} nodos)")
    ok = True
    for nombre, (lat, lon) in puntos.items():
        dentro = caja[0] <= lat <= caja[1] and caja[2] <= lon <= caja[3]
        nid = rutas_mod.nodo_mas_cercano(G, lat, lon)
        d = _dist(lat, lon, G.nodes[nid]["y"], G.nodes[nid]["x"])
        estado = "FUERA" if not dentro or d > DISTANCIA_MAX_NODO_M else (
            "AVISO: la ruta arrancara/terminara en ese nodo" if d > DISTANCIA_AVISO_NODO_M else "OK")
        print(f"  {nombre}: {lat:.6f},{lon:.6f}  dentro_caja={dentro}  nodo_mas_cercano={nid} a {d:.0f} m  -> {estado}")
        ok = ok and estado != "FUERA"
    if not ok:
        margen = 0.006
        norte = max(caja[1], *(p[0] + margen for p in puntos.values()))
        sur = min(caja[0], *(p[0] - margen for p in puntos.values()))
        este = max(caja[3], *(p[1] + margen for p in puntos.values()))
        oeste = min(caja[2], *(p[1] - margen for p in puntos.values()))
        print("\nEl grafo actual NO cubre el escenario. Para regenerarlo (requiere osmnx e internet;"
              " la caja une la actual con los puntos nuevos, asi los otros escenarios siguen funcionando):")
        print(f"    python scripts/datos/regenerar_grafo.py --norte {norte:.5f} --sur {sur:.5f} "
              f"--este {este:.5f} --oeste {oeste:.5f}")
        print("Ojo: si la caja crece mucho, el servidor tarda mas en cargar el grafo y en nodo_mas_cercano"
              " (busqueda lineal).")
    return ok


def candidatas_semaforo(G, ruta, min_desde_origen_m: float) -> list[dict]:
    senales = [(nid, d["y"], d["x"]) for nid, d in G.nodes(data=True) if d.get("highway") == "traffic_signals"]
    salida = []
    total = ruta.longitud_total_m
    for i, nodo in enumerate(ruta.geometria):
        if i == 0 or i == len(ruta.geometria) - 1:
            continue
        if nodo.distancia_acumulada_m < min_desde_origen_m or total - nodo.distancia_acumulada_m < 60.0:
            continue
        datos = G.nodes[nodo.nodo_id]
        if int(datos.get("street_count", 0) or 0) < 3:
            continue
        cercanas = [s for s in senales if _dist(nodo.lat, nodo.lon, s[1], s[2]) <= RADIO_SENAL_CERCANA_M]
        if not cercanas:
            continue
        salida.append({
            "indice": i, "nodo": nodo, "propio": datos.get("highway") == "traffic_signals",
            "senales": [s[0] for s in cercanas], "street_count": int(datos.get("street_count")),
        })
    return salida


def nombre_calle(G, u: str, v: str) -> str:
    datos = G[u][v] if G.has_edge(u, v) else (G[v][u] if G.has_edge(v, u) else {})
    return str(datos.get("name") or "(sin nombre)")


def construir_accesos(G, ruta, indice: int) -> list[dict]:
    """Un acceso por cada vecino real del nodo (entrante o saliente: un
    peaton/vehiculo puede llegar por cualquiera), con el rumbo de llegada
    vecino -> nodo, igual que rutas._rumbo_llegada_en_nodo. El que usa la
    ruta va primero (acceso A, grupo 1)."""
    nodo = ruta.geometria[indice]
    previo = ruta.geometria[indice - 1]
    vecinos = [previo.nodo_id] + [n for n in set(G.predecessors(nodo.nodo_id)) | set(G.successors(nodo.nodo_id))
                                  if n != previo.nodo_id]
    accesos: list[dict] = []
    for vec in vecinos:
        dv = G.nodes[vec]
        rumbo = rumbo_entre(dv["y"], dv["x"], nodo.lat, nodo.lon)
        if any(delta_psi(rumbo, a["rumbo_llegada_deg"]) < DEDUP_ACCESOS_DEG for a in accesos):
            continue
        es_ruta = vec == previo.nodo_id
        accesos.append({
            "rumbo_llegada_deg": round(rumbo, 1),
            "nota": f"{nombre_calle(G, vec, nodo.nodo_id)} (nodo {vec} -> {nodo.nodo_id})"
                    + (" -- acceso que usa la ruta de este escenario" if es_ruta else ""),
        })
    rumbo_ruta = accesos[0]["rumbo_llegada_deg"]
    for letra, a in zip("ABCDEFGH", accesos):
        a["acceso_id"] = letra
        # Relleno: mismo grupo para el acceso de la ruta y su opuesto (~180 deg).
        a["grupo_semaforico"] = 1 if delta_psi(a["rumbo_llegada_deg"], rumbo_ruta) < 45 or \
            delta_psi(a["rumbo_llegada_deg"], (rumbo_ruta + 180) % 360) < 45 else 2
    return [{"acceso_id": a["acceso_id"], "rumbo_llegada_deg": a["rumbo_llegada_deg"],
             "grupo_semaforico": a["grupo_semaforico"], "nota": a["nota"]} for a in accesos]


def muestrear_trayectoria(ruta, velocidad_kmh: float) -> list[dict]:
    v = velocidad_kmh / 3.6
    geo = ruta.geometria
    filas = []
    t = 0
    while True:
        s = min(t * v, ruta.longitud_total_m)
        for j in range(1, len(geo)):
            if geo[j].distancia_acumulada_m >= s:
                break
        a, b = geo[j - 1], geo[j]
        tramo = b.distancia_acumulada_m - a.distancia_acumulada_m
        f = 0.0 if tramo <= 0 else (s - a.distancia_acumulada_m) / tramo
        filas.append({
            "t_s": t, "lat": round(a.lat + f * (b.lat - a.lat), 7), "lon": round(a.lon + f * (b.lon - a.lon), 7),
            "rumbo_deg": round(rumbo_entre(a.lat, a.lon, b.lat, b.lon), 1),
            "velocidad_kmh": velocidad_kmh if s < ruta.longitud_total_m else 0.0,
            "distancia_acumulada_m": round(s, 1),
        })
        if s >= ruta.longitud_total_m:
            return filas
        t += 1


def simular_servidor(G, registro_path: Path, origen, destino, filas: list[dict], centro) -> dict | None:
    """GestorMision real, reloj falso a 1 Hz, sin MQTT: cuando sale el M1 y
    por que via (geocerca R_g o anticipacion por ETA)."""
    reloj = {"t": 0.0}
    m1s: list[tuple[float, dict]] = []
    gestor = GestorMision(
        G, cargar_registro(registro_path),
        enviar_m1=lambda rsu, c: m1s.append((reloj["t"], c)),
        enviar_m3=lambda rsu, c: None,
        enviar_mr=lambda obu, c: None,
        enviar_me=lambda obu, c: None,
        ahora=lambda: reloj["t"],
    )
    mision = gestor.armar_mision("ses-sim", 1, origen, destino)
    primero = None
    for f in filas:
        reloj["t"] = float(f["t_s"])
        n_antes = len(m1s)
        gestor.procesar_mp("ses-sim", f["lat"], f["lon"], f["velocidad_kmh"], f["rumbo_deg"], seq=f["t_s"])
        if len(m1s) > n_antes and primero is None:
            primero = (f, m1s[n_antes][1], mision.seguidor.solicitud_vigente)
    if primero is None:
        return None
    f, m1, por_geocerca = primero
    parada = next(iter(mision.paradas.values())).parada
    return {
        "t_s": f["t_s"],
        "d_radial_m": _dist(f["lat"], f["lon"], *centro),
        "restante_m": parada.distancia_llegada_m - f["distancia_acumulada_m"],
        "t_servicio": m1["t_servicio"],
        "via": "geocerca" if por_geocerca else "eta",
        "renovaciones": sum(1 for _, c in m1s if c["seq"] > 1),
    }


def armar_registro(args, G, ruta, calles, cand) -> dict:
    nodo = cand["nodo"]
    return {
        "version": f"app-obu-{args.sufijo}",
        "descripcion": (
            f"Registro de RSU para el escenario '{args.sufijo}' (prueba caminando con GPS real, ver app_obu/README.md). "
            f"Generado por app_obu/pruebas/generar_escenario_casa.py. SOLO rsu_id {args.rsu_id} (1: Pi real; 2/3: mesa/PUCP; "
            "4-6: hospital_nino -- mismo RSU_ID contra el mismo broker = mismo client_id MQTT, Mosquitto expulsa a uno)."
        ),
        "origen": {
            "origen": {"lat": args.origen[0], "lon": args.origen[1]},
            "destino": {"lat": args.destino[0], "lon": args.destino[1]},
            "ruta_calculada": f"servidor/rutas.py::calcular_ruta sobre {Path(args.grafo).name}: "
                              f"{ruta.longitud_total_m:.1f} m, {len(ruta.geometria)} nodos. "
                              + " -> ".join(f"{n} ({d:.0f} m)" for n, d in calles),
            "fuente_semaforo": f"nodo OSM {nodo.nodo_id} de la ruta (street_count={cand['street_count']}), "
                               f"highway=traffic_signals {'en el propio nodo' if cand['propio'] else 'en nodos a <= 25 m: ' + ', '.join(cand['senales'])}.",
            "accesos": "rumbo_llegada_deg calculado desde la geometria real del grafo (gateway.geometria.rumbo_entre vecino -> nodo).",
            "grupo_semaforico": "Valor de relleno; el plan semaforico real lo entrega el CCGT.",
        },
        "rsu": [{
            "rsu_id": str(args.rsu_id),
            "interseccion_id": f"OSM-CASA-{nodo.nodo_id}",
            "codigo_mml": None,
            "centro": {"lat": round(nodo.lat, 7), "lon": round(nodo.lon, 7)},
            "accesos": construir_accesos(G, ruta, cand["indice"]),
        }],
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--origen", type=_punto, required=True, help="LAT,LON")
    ap.add_argument("--destino", type=_punto, required=True, help="LAT,LON")
    ap.add_argument("--rsu-id", default="7")
    ap.add_argument("--velocidad-kmh", type=float, default=5.0)
    ap.add_argument("--min-desde-origen-m", type=float, default=200.0,
                    help="distancia minima por la ruta entre el origen y el semaforo elegido")
    ap.add_argument("--nodo", default=None, help="forzar el nodo OSM del semaforo (de la lista de candidatas)")
    ap.add_argument("--grafo", default=str(rutas_mod.GRAFO_REAL_DEFAULT))
    ap.add_argument("--salida-dir", default=str(DIR_PRUEBAS))
    ap.add_argument("--sufijo", default="casa", help="registro_rsu_<sufijo>.json, trayectoria_<sufijo>.csv")
    args = ap.parse_args()

    G = rutas_mod.cargar_grafo(args.grafo)
    print("=== 1. Cobertura del grafo ===")
    if not verificar_cobertura(G, {"origen": args.origen, "destino": args.destino}):
        sys.exit(2)

    print("\n=== 2. Ruta (servidor/rutas.py::calcular_ruta) ===")
    ruta = rutas_mod.calcular_ruta(G, args.origen, args.destino)
    print(f"  {ruta.longitud_total_m:.1f} m, {len(ruta.geometria)} nodos, "
          f"~{ruta.longitud_total_m / (args.velocidad_kmh / 3.6) / 60:.1f} min a {args.velocidad_kmh} km/h")
    calles = []
    for a, b in zip(ruta.geometria, ruta.geometria[1:]):
        n = nombre_calle(G, a.nodo_id, b.nodo_id)
        if not calles or calles[-1][0] != n:
            calles.append((n, a.distancia_acumulada_m))
    print("  " + " -> ".join(f"{n} ({d:.0f} m)" for n, d in calles))
    filas = muestrear_trayectoria(ruta, args.velocidad_kmh)

    print(f"\n=== 3. Semaforos OSM sobre la ruta (cada uno simulado con GestorMision a {args.velocidad_kmh} km/h) ===")
    cands = candidatas_semaforo(G, ruta, args.min_desde_origen_m)
    if args.nodo:
        cands = [c for c in cands if c["nodo"].nodo_id == args.nodo]
    if not cands:
        print(f"  Ningun nodo de la ruta con traffic_signals (<= {RADIO_SENAL_CERCANA_M:.0f} m) a >= "
              f"{args.min_desde_origen_m:.0f} m del origen{' (o --nodo no esta entre ellos)' if args.nodo else ''}. "
              "Probar con --min-desde-origen-m menor u otra ruta.")
        sys.exit(3)
    salida_dir = Path(args.salida_dir)
    tmp = salida_dir / f".registro_rsu_{args.sufijo}.tmp.json"
    for c in cands:
        n = c["nodo"]
        c["registro"] = armar_registro(args, G, ruta, calles, c)
        tmp.write_text(json.dumps(c["registro"], ensure_ascii=False), encoding="utf-8")
        plan = rutas_mod.planificar_ruta(G, cargar_registro(tmp), args.origen, args.destino)
        c["detectada"] = bool(plan.paradas) and plan.paradas[0].acceso_id == "A"
        c["sim"] = simular_servidor(G, tmp, args.origen, args.destino, filas, (n.lat, n.lon)) if c["detectada"] else None
        sim = c["sim"]
        resumen = ("no la detecta planificar_ruta" if not c["detectada"] else "sin M1" if sim is None else
                   f"M1 por {sim['via']} a {sim['restante_m']:.0f} m por la ruta ({sim['d_radial_m']:.0f} m radial), "
                   f"{sim['renovaciones']} renovaciones")
        print(f"  nodo {n.nodo_id}  acum={n.distancia_acumulada_m:.0f} m  {n.lat:.6f},{n.lon:.6f}  "
              f"street_count={c['street_count']}  senal_en_nodo={c['propio']}  -> {resumen}")
    tmp.unlink(missing_ok=True)
    buenas = [c for c in cands if c["sim"] and c["sim"]["via"] == "geocerca"]
    elegida = buenas[0] if buenas else next((c for c in cands if c["sim"]), None)
    if elegida is None:
        sys.exit("  Ninguna candidata produce un M1 en la simulacion.")
    if not buenas:
        print("  AVISO: ninguna candidata dispara por geocerca (el origen queda dentro de R_i + margen y el "
              "seguidor la da por cruzada antes de tiempo); se usa la primera con M1 por ETA, sin renovaciones.")
    nodo = elegida["nodo"]
    print(f"  -> elegida: nodo {nodo.nodo_id} (acum {nodo.distancia_acumulada_m:.0f} m)")

    registro_path = salida_dir / f"registro_rsu_{args.sufijo}.json"
    registro_path.write_text(json.dumps(elegida["registro"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n=== 4. {registro_path.name} (rsu_id {args.rsu_id}) ===")
    for a in elegida["registro"]["rsu"][0]["accesos"]:
        print(f"  {a['acceso_id']}: {a['rumbo_llegada_deg']:6.1f} deg  grupo {a['grupo_semaforico']}  {a['nota']}")

    tray_path = salida_dir / f"trayectoria_{args.sufijo}.csv"
    with tray_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"\n=== 5. {tray_path.name}: {len(filas)} muestras a {args.velocidad_kmh} km/h ===")

    print("\n=== 6. Cuando sale el M1 ===")
    p = ParametrosGeometria()
    v_ms = args.velocidad_kmh / 3.6
    sim = elegida["sim"]
    print(f"  Parametros: R_i={p.r_i_m:.0f} m (+{p.margen_histeresis_m:.0f}), R_g={p.r_g_m:.0f} m, psi_tol={p.psi_tol_deg:.0f} deg, "
          f"ANTICIPACION_MINIMA_S={ANTICIPACION_MINIMA_S}, VELOCIDAD_RESPALDO_KMH={VELOCIDAD_RESPALDO_KMH}")
    print(f"  Primer M1 a los {sim['t_s']} s de caminata, via {sim['via']}: a {sim['d_radial_m']:.0f} m en linea recta "
          f"del centro, {sim['restante_m']:.0f} m por la ruta (~{sim['restante_m'] / v_ms:.0f} s reales a "
          f"{args.velocidad_kmh} km/h), t_servicio={sim['t_servicio']} s; {sim['renovaciones']} renovaciones a 1 Hz.")
    print(f"  Disparo por ETA (respaldo si la geocerca no actua): a {ANTICIPACION_MINIMA_S * v_ms:.0f} m del cruce a "
          f"{args.velocidad_kmh} km/h; con el MP en <= 1 km/h (detenido) el servidor asume {VELOCIDAD_RESPALDO_KMH} km/h "
          f"-> a {ANTICIPACION_MINIMA_S * VELOCIDAD_RESPALDO_KMH / 3.6:.0f} m.")


if __name__ == "__main__":
    main()
