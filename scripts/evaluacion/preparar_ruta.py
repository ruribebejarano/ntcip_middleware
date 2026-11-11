#!/usr/bin/env python3
"""Genera el registro de RSU y la trayectoria de una ruta de rutas.json.

Calcula la ruta con servidor/rutas.py (la misma que usará el servidor), elige
las intersecciones semaforizadas de OSM que hay sobre ella (o las que lista
"rsu_manual" en rutas.json) y escribe en resultados/evaluacion/rutas/:

    registro_rsu_<ruta>.json   RSU emuladas que levanta evaluar.ps1
    trayectoria_<ruta>.csv     recorrido a 1 Hz para la OBU emulada

Uso:
    python scripts/evaluacion/preparar_ruta.py --ruta pucp_mariano_cornejo
    python scripts/evaluacion/preparar_ruta.py --listar
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "app_obu" / "pruebas"))

import generar_escenario_casa as casa  # noqa: E402
from gateway.geometria import ParametrosGeometria, cargar_registro  # noqa: E402
from servidor import rutas as rutas_mod  # noqa: E402

RUTAS_JSON = Path(__file__).resolve().parent / "rutas.json"
SALIDA = RAIZ / "resultados" / "evaluacion" / "rutas"


def cargar_rutas(ruta_json: Path = RUTAS_JSON) -> dict:
    return json.loads(ruta_json.read_text(encoding="utf-8"))


def elegir_separadas(candidatas: list[dict], maximo: int, separacion_m: float) -> list[dict]:
    """Primeras candidatas por la ruta, separadas al menos separacion_m."""
    elegidas: list[dict] = []
    for c in candidatas:
        if len(elegidas) >= maximo:
            break
        acum = c["nodo"].distancia_acumulada_m
        if not elegidas or acum - elegidas[-1]["nodo"].distancia_acumulada_m >= separacion_m:
            elegidas.append(c)
    return elegidas


RADIO_MANUAL_M = 40.0   # distancia máxima entre un punto de "rsu_manual" y el nodo de la ruta


def candidatas_manuales(ruta, puntos: list, radio_m: float = RADIO_MANUAL_M) -> list[dict]:
    """RSU puestas a mano: cada punto [lat, lon] se asocia al nodo de la ruta más
    cercano (sin contar el origen). Los puntos lejos de la ruta se omiten con aviso.
    Devuelve las candidatas en el orden de la ruta, sin repetir nodos."""
    geo = ruta.geometria
    elegidas: dict[int, dict] = {}
    for k, punto in enumerate(puntos, start=1):
        lat, lon = (punto["lat"], punto["lon"]) if isinstance(punto, dict) else (punto[0], punto[1])
        indice = min(range(1, len(geo)), key=lambda i: casa._dist(lat, lon, geo[i].lat, geo[i].lon))
        d = casa._dist(lat, lon, geo[indice].lat, geo[indice].lon)
        if d > radio_m:
            print(f"  Se omite el punto {k} ({lat},{lon}): queda a {d:.0f} m de la ruta (máximo {radio_m:.0f} m).")
            continue
        if indice in elegidas:
            print(f"  Se omite el punto {k} ({lat},{lon}): cae en el mismo nodo que otro punto.")
            continue
        elegidas[indice] = {"indice": indice, "nodo": geo[indice], "distancia_m": d}
    return [elegidas[i] for i in sorted(elegidas)]


def fuera_de_radio_inicial(candidatas: list[dict], origen: tuple[float, float]) -> list[dict]:
    """Quita las RSU demasiado cerca del origen en línea recta. Si la misión empieza
    dentro de R_i + margen, el seguidor de acceso da la RSU por cruzada casi de inmediato."""
    p = ParametrosGeometria()
    minimo = p.r_i_m + p.margen_histeresis_m
    utiles = []
    for c in candidatas:
        d = casa._dist(origen[0], origen[1], c["nodo"].lat, c["nodo"].lon)
        if d > minimo:
            utiles.append(c)
        else:
            print(f"  Se omite el nodo {c['nodo'].nodo_id}: está a {d:.0f} m del origen en línea recta "
                  f"(debe superar {minimo:.0f} m).")
    return utiles


def armar_registro(nombre: str, conf: dict, G, ruta, elegidas: list[dict]) -> dict:
    primero = int(conf.get("primer_rsu_id", 50))
    return {
        "version": f"evaluacion-{nombre}",
        "descripcion": f"Registro generado por scripts/evaluacion/preparar_ruta.py para la ruta '{nombre}'. "
                       "RSU y controladores emulados; grupo_semaforico es un valor de relleno.",
        "origen": {
            "origen": {"lat": conf["origen"][0], "lon": conf["origen"][1]},
            "destino": {"lat": conf["destino"][0], "lon": conf["destino"][1]},
            "longitud_m": round(ruta.longitud_total_m, 1),
        },
        "rsu": [{
            "rsu_id": str(primero + i),
            "interseccion_id": f"OSM-{c['nodo'].nodo_id}",
            "codigo_mml": None,
            "centro": {"lat": round(c["nodo"].lat, 7), "lon": round(c["nodo"].lon, 7)},
            "accesos": casa.construir_accesos(G, ruta, c["indice"]),
        } for i, c in enumerate(elegidas)],
    }


MARGEN_GRAFO_DEG = 0.006   # margen de la caja sugerida para un grafo propio (~650 m)


def ruta_grafo(conf: dict) -> Path:
    """Grafo vial de la ruta: el campo opcional "grafo" de rutas.json (ruta
    relativa a la raíz del repo) o, sin él, el grafo de siempre. Una zona
    alejada usa su propio grafo para no volver a descargar ni agrandar el
    compartido, que es el de las campañas ya medidas."""
    return RAIZ / conf["grafo"] if conf.get("grafo") else rutas_mod.GRAFO_REAL_DEFAULT


def comando_grafo_propio(conf: dict, destino: Path) -> str:
    """Comando para descargar un grafo que cubra origen, destino y RSU a mano."""
    puntos = [conf["origen"], conf["destino"], *conf.get("rsu_manual", [])]
    lats = [p[0] for p in puntos]
    lons = [p[1] for p in puntos]
    m = MARGEN_GRAFO_DEG
    rel = destino.relative_to(RAIZ).as_posix() if destino.is_relative_to(RAIZ) else str(destino)
    return (f"python scripts/datos/regenerar_grafo.py --norte {max(lats) + m:.5f} --sur {min(lats) - m:.5f} "
            f"--este {max(lons) + m:.5f} --oeste {min(lons) - m:.5f} --salida {rel}")


def preparar(nombre: str, conf: dict, salida: Path = SALIDA) -> int:
    origen, destino = tuple(conf["origen"]), tuple(conf["destino"])
    archivo_grafo = ruta_grafo(conf)
    if not archivo_grafo.exists():
        print(f"No existe el grafo '{conf['grafo']}' de esta ruta. Para descargarlo (requiere osmnx e internet):")
        print(f"    {comando_grafo_propio(conf, archivo_grafo)}")
        return 2
    print(f"Grafo: {archivo_grafo.relative_to(RAIZ).as_posix()}")
    G = rutas_mod.cargar_grafo(archivo_grafo)
    if not casa.verificar_cobertura(G, {"origen": origen, "destino": destino}):
        if not conf.get("grafo"):
            print()
            print("Si la zona está lejos de las otras rutas, conviene un grafo propio en vez de agrandar el"
                  " compartido (el de las campañas ya medidas). Agrega a la ruta en rutas.json:")
            print(f'    "grafo": "data/grafo_{nombre}.graphml"')
            print("y descárgalo con:")
            print(f"    {comando_grafo_propio(conf, RAIZ / 'data' / f'grafo_{nombre}.graphml')}")
        print("La ruta queda fuera del grafo vial. Ejecuta uno de los comandos indicados arriba y vuelve a preparar.")
        return 2

    ruta = rutas_mod.calcular_ruta(G, origen, destino)
    velocidad = float(conf.get("velocidad_emulada_kmh", 36))
    print(f"Ruta '{nombre}': {ruta.longitud_total_m:.0f} m, "
          f"unos {ruta.longitud_total_m / (velocidad / 3.6) / 60:.1f} min a {velocidad:g} km/h")

    if conf.get("rsu_manual"):
        print(f"RSU a mano: {len(conf['rsu_manual'])} puntos (se ignoran max_rsu y separacion_min_m)")
        elegidas = fuera_de_radio_inicial(candidatas_manuales(ruta, conf["rsu_manual"]), origen)
    else:
        candidatas = casa.candidatas_semaforo(G, ruta, float(conf.get("min_desde_origen_m", 200)))
        candidatas = fuera_de_radio_inicial(candidatas, origen)
        elegidas = elegir_separadas(candidatas, int(conf.get("max_rsu", 3)), float(conf.get("separacion_min_m", 300)))
    if not elegidas:
        print("No hay RSU sobre esta ruta. Cambia origen o destino, revisa rsu_manual o baja min_desde_origen_m.")
        return 3

    salida.mkdir(parents=True, exist_ok=True)
    registro = armar_registro(nombre, conf, G, ruta, elegidas)
    ruta_registro = salida / f"registro_rsu_{nombre}.json"
    ruta_registro.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    plan = rutas_mod.planificar_ruta(G, cargar_registro(ruta_registro), origen, destino)
    detectadas = {str(p.rsu_id) for p in plan.paradas}
    for r, c in zip(registro["rsu"], elegidas):
        marca = "" if r["rsu_id"] in detectadas else "  (AVISO: el servidor no la detecta en la ruta)"
        print(f"  RSU {r['rsu_id']}: nodo {c['nodo'].nodo_id}, a {c['nodo'].distancia_acumulada_m:.0f} m "
              f"del origen, {r['centro']['lat']},{r['centro']['lon']}{marca}")
    if not detectadas:
        print("El servidor no detecta ninguna RSU en la ruta. Prueba con otro origen o destino.")
        return 4

    filas = casa.muestrear_trayectoria(ruta, velocidad)
    ruta_tray = salida / f"trayectoria_{nombre}.csv"
    with ruta_tray.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"Listo: {ruta_registro.relative_to(RAIZ)} y {ruta_tray.relative_to(RAIZ)}")
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruta", help="nombre de la ruta en rutas.json")
    ap.add_argument("--listar", action="store_true", help="muestra las rutas disponibles")
    args = ap.parse_args()
    rutas = cargar_rutas()
    if args.listar or not args.ruta:
        for nombre, conf in rutas.items():
            print(f"{nombre}: {conf.get('descripcion', '')}")
            print(f"    origen {conf['origen'][0]},{conf['origen'][1]}  destino {conf['destino'][0]},{conf['destino'][1]}")
        return
    if args.ruta not in rutas:
        sys.exit(f"No existe la ruta '{args.ruta}' en {RUTAS_JSON.name}. Disponibles: {', '.join(rutas)}")
    sys.exit(preparar(args.ruta, rutas[args.ruta]))


if __name__ == "__main__":
    main()
