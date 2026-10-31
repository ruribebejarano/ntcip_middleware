"""Genera el escenario "zona PUCP": hospitales/clínicas cercanos (de OSM) y
un registro de RSU con las intersecciones semaforizadas reales por las que
pasan las rutas desde la PUCP hacia ellos, más todas las que están en un
radio del campus (ver app_obu/README.md, sección
"Zona PUCP").

Entradas:
- un JSON de Overpass con amenity/healthcare = hospital|clinic (y opcional
  highway=traffic_signals, no se usa: los semáforos salen del propio grafo
  para que coincidan con los nodos por los que enruta el servidor);
- data/grafo_san_miguel_real.graphml (servidor/rutas.py).

Salidas (en --salida-dir, por defecto app_obu/pruebas/):
- hospitales_zona_pucp.json  hospitales + clínicas con emergencia, dentro del
                             grafo (también se copia a los assets de la app);
- registro_rsu_zona_pucp.json rsu_id desde 11 (1: Pi; 2-7: otros escenarios):
                             primero las elegidas por rutas (11-20), luego
                             las del radio (--radio-m, 1,5 km por defecto).

Criterio de elección de las RSU (todo sobre el grafo real):
1. ruta servidor/rutas.py::calcular_ruta desde la base (PUCP, Av.
   Universitaria) hacia cada hospital;
2. nodo de esas rutas con highway=traffic_signals propio o a <= 25 m, y
   street_count >= 3 (cruce real);
3. se cuentan cuántas rutas pasan por cada uno y se eligen, de mayor a menor,
   los que estén a >= --separacion-m de los ya elegidos y a >= 350 m en
   línea recta de la base (R_i + margen de gateway/geometria.py: más cerca,
   el seguidor de geocerca puede darlos por cruzados antes de tiempo, ver
   README "Velocidad a pie").
Los accesos son todos los tramos reales que llegan al nodo (rumbo vecino ->
nodo), como en generar_escenario_casa.py.

Uso (desde la raíz del repo):
    python app_obu/pruebas/generar_zona_pucp.py --overpass overpass.json
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from gateway.geometria import cargar_registro, delta_psi, proyeccion_local, rumbo_entre  # noqa: E402
from servidor import rutas as rutas_mod  # noqa: E402

DIR_PRUEBAS = Path(__file__).resolve().parent
ASSETS_APP = RAIZ / "app_obu" / "app" / "src" / "main" / "assets" / "zona"
BASE_PUCP = (-12.071468, -77.078353)  # mismo origen que el escenario PUCP (Av. Universitaria)
CENTRO_PUCP = (-12.0691, -77.0791)    # centro del campus, para el radio de RSU
RSU_ID_INICIAL = 11


def _dist(a, b) -> float:
    x, y = proyeccion_local(a[0], a[1], b[0], b[1])
    return math.hypot(x, y)


def leer_hospitales(ruta_overpass: Path, G) -> list[dict]:
    datos = json.loads(ruta_overpass.read_text(encoding="utf-8"))
    lats = [d["y"] for _, d in G.nodes(data=True)]
    lons = [d["x"] for _, d in G.nodes(data=True)]
    caja = (min(lats), max(lats), min(lons), max(lons))
    salida: dict[str, dict] = {}
    for e in datos["elements"]:
        t = e.get("tags", {})
        tipo = t.get("amenity") or t.get("healthcare")
        if tipo not in ("hospital", "clinic") or not t.get("name"):
            continue
        # Solo hospitales y clínicas con emergencia: los consultorios
        # (ópticas, dentistas, estética...) no son destino de una ambulancia.
        if tipo == "clinic" and t.get("emergency") != "yes":
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if not (caja[0] + 0.002 <= lat <= caja[1] - 0.002 and caja[2] + 0.002 <= lon <= caja[3] - 0.002):
            continue
        nombre = t["name"].strip()
        if nombre in salida:
            continue
        salida[nombre] = {
            "nombre": nombre, "tipo": tipo, "lat": round(lat, 7), "lon": round(lon, 7),
            "emergencia": t.get("emergency") == "yes", "osm": f"{e['type']}/{e['id']}",
        }
    return sorted(salida.values(), key=lambda h: _dist(BASE_PUCP, (h["lat"], h["lon"])))


def accesos_de(G, nodo_id: str) -> list[dict]:
    d = G.nodes[nodo_id]
    vecinos = sorted(set(G.predecessors(nodo_id)) | set(G.successors(nodo_id)))
    crudos = []
    for v in vecinos:
        dv = G.nodes[v]
        rumbo = rumbo_entre(dv["y"], dv["x"], d["y"], d["x"])
        if any(delta_psi(rumbo, c[0]) < 20 for c in crudos):
            continue
        datos = G[v][nodo_id] if G.has_edge(v, nodo_id) else G[nodo_id][v]
        nombre = str(datos.get("name") or "(sin nombre)")
        if nombre.startswith("["):  # OSMnx guarda como texto la lista de nombres de una arista fusionada
            nombre = ast.literal_eval(nombre)[0]
        crudos.append((rumbo, f"{nombre} (nodo {v} -> {nodo_id})"))
    crudos.sort()
    base = crudos[0][0]
    salida = []
    for letra, (rumbo, nota) in zip("ABCDEFGH", crudos):
        # Relleno: mismo grupo semafórico para accesos paralelos u opuestos al primero.
        grupo = 1 if min(delta_psi(rumbo, base), delta_psi(rumbo, (base + 180) % 360)) < 45 else 2
        salida.append({"acceso_id": letra, "rumbo_llegada_deg": round(rumbo, 1), "grupo_semaforico": grupo, "nota": nota})
    return salida


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overpass", required=True, type=Path)
    ap.add_argument("--n-rsu", type=int, default=10)
    ap.add_argument("--separacion-m", type=float, default=250.0)
    ap.add_argument("--min-desde-base-m", type=float, default=350.0)
    ap.add_argument("--radio-m", type=float, default=1500.0,
                    help="además: toda intersección semaforizada a menos de esto del centro de la PUCP (0 = ninguna)")
    ap.add_argument("--separacion-radio-m", type=float, default=120.0,
                    help="separación mínima de las RSU agregadas por radio respecto de las demás")
    ap.add_argument("--salida-dir", type=Path, default=DIR_PRUEBAS)
    ap.add_argument("--sin-assets", action="store_true", help="no copiar a los assets de la app")
    args = ap.parse_args()

    G = rutas_mod.cargar_grafo()
    hospitales = leer_hospitales(args.overpass, G)
    print(f"{len(hospitales)} hospitales/clínicas con emergencia dentro del grafo")

    senales = [(nid, d["y"], d["x"]) for nid, d in G.nodes(data=True) if d.get("highway") == "traffic_signals"]
    pasos: Counter[str] = Counter()
    candidatos_por_ruta: dict[str, set[str]] = {}
    for h in hospitales:
        ruta = rutas_mod.calcular_ruta(G, BASE_PUCP, (h["lat"], h["lon"]))
        vistos = set()
        for n in ruta.geometria[1:-1]:
            if int(G.nodes[n.nodo_id].get("street_count", 0) or 0) < 3:
                continue
            if _dist((n.lat, n.lon), BASE_PUCP) < args.min_desde_base_m:
                continue
            if not any(_dist((n.lat, n.lon), (s[1], s[2])) <= 25 for s in senales):
                continue
            vistos.add(n.nodo_id)
        candidatos_por_ruta[h["nombre"]] = vistos
        pasos.update(vistos)

    # Greedy: primero el cruce que da semáforo a más rutas que todavía no
    # tienen ninguno; con todas cubiertas (o sin forma de cubrirlas), el más
    # transitado. Siempre respetando la separación mínima entre RSU.
    def lejos_de_elegidos(nid: str) -> bool:
        p = (G.nodes[nid]["y"], G.nodes[nid]["x"])
        return all(_dist(p, (G.nodes[e]["y"], G.nodes[e]["x"])) >= args.separacion_m for e in elegidos)

    # Las RSU ya publicadas por rutas (registro existente) se conservan con
    # su rsu_id: la demo, la consola y las notas ya las nombran así.
    previo = args.salida_dir / "registro_rsu_zona_pucp.json"
    elegidos: list[str] = []
    if previo.exists():
        for r in json.loads(previo.read_text(encoding="utf-8"))["rsu"]:
            if r.get("criterio", "rutas_hospitales") == "rutas_hospitales":
                elegidos.append(r["interseccion_id"].removeprefix("OSM-ZONA-"))
        print(f"Se conservan {len(elegidos)} RSU por rutas de {previo.name}")
    while len(elegidos) < args.n_rsu:
        sin_cubrir = [r for r, c in candidatos_por_ruta.items() if c and not (c & set(elegidos))]
        opciones = sorted(n for n in pasos if n not in elegidos and lejos_de_elegidos(n))  # orden fijo: desempate reproducible
        if not opciones:
            break
        elegidos.append(max(opciones, key=lambda n: (sum(n in candidatos_por_ruta[r] for r in sin_cubrir), pasos[n])))
    n_por_rutas = len(elegidos)

    # Segunda etapa: TODA intersección semaforizada dentro de --radio-m del
    # campus, para que cualquier ruta que salga de la PUCP o pase cerca
    # encuentre semáforos (no solo las rutas hacia los hospitales). Las
    # señales de OSM se agrupan por cruce (<= 40 m) y se representa cada
    # cruce con el nodo del grafo con street_count >= 3 más cercano a su
    # centroide; se agregan de la más cercana a la más lejana del campus.
    # Van DESPUÉS de las elegidas por rutas: así esas conservan sus rsu_id.
    if args.radio_m > 0:
        grupos: list[list[tuple[float, float]]] = []
        for _, la, lo in senales:
            for g in grupos:
                cx = sum(p[0] for p in g) / len(g)
                cy = sum(p[1] for p in g) / len(g)
                if _dist((la, lo), (cx, cy)) <= 40:
                    g.append((la, lo))
                    break
            else:
                grupos.append([(la, lo)])
        cruces = []
        for g in grupos:
            c = (sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g))
            if _dist(c, CENTRO_PUCP) > args.radio_m:
                continue
            cerca = [(_dist(c, (d["y"], d["x"])), nid) for nid, d in G.nodes(data=True)
                     if int(d.get("street_count", 0) or 0) >= 3 and abs(d["y"] - c[0]) < 0.0005 and abs(d["x"] - c[1]) < 0.0005]
            cerca = [x for x in cerca if x[0] <= 40]
            if cerca:
                cruces.append(min(cerca)[1])
        for nid in sorted(set(cruces), key=lambda n: _dist((G.nodes[n]["y"], G.nodes[n]["x"]), CENTRO_PUCP)):
            p = (G.nodes[nid]["y"], G.nodes[nid]["x"])
            if nid in elegidos or _dist(p, BASE_PUCP) < 100:
                continue
            if any(_dist(p, (G.nodes[e]["y"], G.nodes[e]["x"])) < args.separacion_radio_m for e in elegidos):
                continue
            elegidos.append(nid)
    print(f"{n_por_rutas} RSU por rutas a hospitales + {len(elegidos) - n_por_rutas} por radio de {args.radio_m:.0f} m")

    rsu = []
    for i, nid in enumerate(elegidos):
        d = G.nodes[nid]
        acc = accesos_de(G, nid)
        calles = sorted({a["nota"].split(" (nodo")[0] for a in acc})
        rsu.append({
            "rsu_id": str(RSU_ID_INICIAL + i),
            "interseccion_id": f"OSM-ZONA-{nid}",
            "nombre": " / ".join(c for c in calles if c != "(sin nombre)")[:80] or f"nodo {nid}",
            "codigo_mml": None,
            "centro": {"lat": round(d["y"], 7), "lon": round(d["x"], 7)},
            "rutas_que_pasan": pasos[nid],
            "criterio": "rutas_hospitales" if i < n_por_rutas else f"radio_{args.radio_m:.0f}m",
            "accesos": acc,
        })
    registro = {
        "version": "app-obu-zona-pucp",
        "descripcion": (
            f"Registro 'zona PUCP' (ver app_obu/README.md): {len(rsu)} RSU en cruces semaforizados reales "
            f"(highway=traffic_signals de {Path(rutas_mod.GRAFO_REAL_DEFAULT).name}) por los que pasan las rutas "
            "del servidor desde la PUCP (Av. Universitaria) hacia los hospitales y clínicas con emergencia de "
            "hospitales_zona_pucp.json, más toda intersección semaforizada a menos de "
            f"{args.radio_m:.0f} m del campus. Generado por app_obu/pruebas/generar_zona_pucp.py. rsu_id desde 11 (1: Pi; "
            "2-7: otros escenarios -- mismo RSU_ID contra el mismo broker = mismo client_id MQTT)."
        ),
        "origen": {"base": {"lat": BASE_PUCP[0], "lon": BASE_PUCP[1]},
                   "grupo_semaforico": "Valor de relleno; el plan semafórico real lo entrega el CCGT."},
        "rsu": rsu,
    }
    args.salida_dir.mkdir(parents=True, exist_ok=True)
    p_reg = args.salida_dir / "registro_rsu_zona_pucp.json"
    p_hos = args.salida_dir / "hospitales_zona_pucp.json"
    p_reg.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    p_hos.write_text(json.dumps({
        "fuente": "OpenStreetMap (Overpass API), amenity/healthcare = hospital|clinic; clínicas solo con emergency=yes. "
                  "© colaboradores de OpenStreetMap, ODbL.",
        "base": {"nombre": "PUCP (Av. Universitaria)", "lat": BASE_PUCP[0], "lon": BASE_PUCP[1]},
        "hospitales": hospitales,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(rsu)} RSU elegidas:")
    for r in rsu:
        print(f"  RSU {r['rsu_id']:>2}  {r['interseccion_id']:24} rutas={r['rutas_que_pasan']:2}  "
              f"{r['centro']['lat']:.5f},{r['centro']['lon']:.5f}  {r['nombre']}")

    reg = cargar_registro(p_reg)
    print("\nVerificación (planificar_ruta desde la base):")
    for h in hospitales:
        plan = rutas_mod.planificar_ruta(G, reg, BASE_PUCP, (h["lat"], h["lon"]))
        print(f"  {h['nombre'][:42]:42} {plan.longitud_total_m:6.0f} m  RSU {[p.rsu_id for p in plan.paradas]}")

    if not args.sin_assets:
        ASSETS_APP.mkdir(parents=True, exist_ok=True)
        shutil.copy(p_hos, ASSETS_APP / p_hos.name)
        shutil.copy(p_reg, ASSETS_APP / p_reg.name)
        print(f"\nCopiados a {ASSETS_APP} (la app los usa SOLO para dibujar; el registro vive en el servidor).")


if __name__ == "__main__":
    main()
