#!/usr/bin/env python3
"""Genera trayectorias SINTETICAS para la OBU emulada (gateway/obu_emulada.py).

*** DATOS FICTICIOS ***
No son recorridos reales de un vehiculo: son rectas a velocidad dada sobre
las intersecciones de config/registro_rsu.json, con ruido gaussiano de
posicion y de rumbo que imita (de forma simplificada) el error de un
receptor GNSS urbano. Sirven para ejercitar el lazo OBU -> broker -> RSU ->
controlador sin vehiculo ni telefono. Declararlo asi en el Capitulo IV.

Cada CSV tiene una fila por muestra (1 Hz por defecto, RNF-02):

    t_s, lat, lon, rumbo_deg, velocidad_kmh,       <- lo que "ve" la OBU (con ruido)
    lat_real, lon_real, rumbo_real_deg,            <- posicion sin ruido
    interseccion_verdad, acceso_verdad             <- verdad de terreno (sin ruido)

La verdad de terreno se calcula con las mismas reglas de gateway/geometria.py
sobre la posicion SIN ruido; sirve para la "tasa de acierto de acceso"
de ssec:metricas.

Escenarios (todos sobre la via que une las dos intersecciones del registro):
  avenida_ab        llega a A por el sur, la cruza y sigue hasta pasar B
  avenida_ba        sentido contrario (llega a B por el norte, luego A)
  transversal_a     cruza A por la transversal (acceso O), sin pasar por B
  detenido_en_cola  llega a A, se detiene 20 s a 80 m (cola) y luego cruza

Uso:
    python3 scripts/trayectorias/generar.py                # los 4 escenarios, semilla 1
    python3 scripts/trayectorias/generar.py --semilla 7 --sigma-pos 8
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import (  # noqa: E402
    ParametrosGeometria,
    asignar,
    cargar_registro,
    desplazar,
    proyeccion_local,
    rumbo_entre,
)

SALIDA_DEFAULT = RAIZ / "resultados" / "trayectorias"


def _tramo(lat0, lon0, rumbo, largo_m, v_ms, dt, t0=0.0):
    """Muestras sobre una recta desde (lat0, lon0), sin incluir el punto final."""
    pasos = int(largo_m / (v_ms * dt))
    for k in range(pasos):
        lat, lon = desplazar(lat0, lon0, rumbo, k * v_ms * dt)
        yield t0 + k * dt, lat, lon, rumbo, v_ms


def escenario(nombre: str, registro, v_kmh: float, dt: float):
    a, b = registro[0], registro[1]
    r_ab = rumbo_entre(a.lat, a.lon, b.lat, b.lon)
    x, y = proyeccion_local(b.lat, b.lon, a.lat, a.lon)
    d_ab = math.hypot(x, y)
    v = v_kmh / 3.6
    if nombre == "avenida_ab":
        ini = desplazar(a.lat, a.lon, (r_ab + 180) % 360, 600)
        largo = 600 + d_ab + 250
        return list(_tramo(*ini, r_ab, largo, v, dt))
    if nombre == "avenida_ba":
        r_ba = (r_ab + 180) % 360
        ini = desplazar(b.lat, b.lon, r_ab, 600)
        largo = 600 + d_ab + 250
        return list(_tramo(*ini, r_ba, largo, v, dt))
    if nombre == "transversal_a":
        r_t = (r_ab + 90) % 360
        ini = desplazar(a.lat, a.lon, (r_t + 180) % 360, 600)
        return list(_tramo(*ini, r_t, 850, v, dt))
    if nombre == "detenido_en_cola":
        ini = desplazar(a.lat, a.lon, (r_ab + 180) % 360, 600)
        m = list(_tramo(*ini, r_ab, 520, v, dt))           # hasta 80 m de A
        t = m[-1][0] + dt
        lat_q, lon_q = desplazar(*ini, r_ab, 520)
        m += [(t + k * dt, lat_q, lon_q, r_ab, 0.0) for k in range(int(20 / dt))]  # 20 s detenido
        t = m[-1][0] + dt
        m += list(_tramo(lat_q, lon_q, r_ab, 330, v, dt, t0=t))
        return m
    raise ValueError(f"escenario desconocido: {nombre}")


ESCENARIOS = ("avenida_ab", "avenida_ba", "transversal_a", "detenido_en_cola")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registro", default=str(RAIZ / "config" / "registro_rsu.json"))
    ap.add_argument("--salida", default=str(SALIDA_DEFAULT))
    ap.add_argument("--escenarios", nargs="*", default=list(ESCENARIOS), choices=ESCENARIOS)
    ap.add_argument("--velocidad-kmh", type=float, default=40.0)
    ap.add_argument("--dt", type=float, default=1.0, help="periodo de muestreo en s (1 Hz, RNF-02)")
    ap.add_argument("--sigma-pos", type=float, default=5.0, help="ruido de posicion, m (1 sigma)")
    ap.add_argument("--sigma-rumbo", type=float, default=5.0, help="ruido de rumbo, grados (1 sigma)")
    ap.add_argument("--semilla", type=int, default=1)
    args = ap.parse_args()

    registro = cargar_registro(args.registro)
    p = ParametrosGeometria()
    rnd = random.Random(args.semilla)
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    for nombre in args.escenarios:
        ruta = salida / f"{nombre}_s{args.semilla}.csv"
        with ruta.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh",
                        "lat_real", "lon_real", "rumbo_real_deg",
                        "interseccion_verdad", "acceso_verdad"])
            for t, lat, lon, rumbo, v in escenario(nombre, registro, args.velocidad_kmh, args.dt):
                verdad = asignar(registro, lat, lon, rumbo, p)
                lat_r, lon_r = desplazar(lat, lon, rnd.uniform(0, 360), abs(rnd.gauss(0, args.sigma_pos)))
                # Detenido: el rumbo GNSS es poco fiable a v ~ 0, se deja el ultimo con ruido
                rumbo_r = (rumbo + rnd.gauss(0, args.sigma_rumbo)) % 360
                v_r = max(0.0, v * 3.6 + rnd.gauss(0, 1.0)) if v > 0 else 0.0
                w.writerow([f"{t:.1f}", f"{lat_r:.7f}", f"{lon_r:.7f}", f"{rumbo_r:.1f}", f"{v_r:.1f}",
                            f"{lat:.7f}", f"{lon:.7f}", f"{rumbo:.1f}",
                            verdad.interseccion_id if verdad else "",
                            verdad.acceso_id if verdad else ""])
        print(f"{ruta}  ({sum(1 for _ in ruta.open()) - 1} muestras)")


if __name__ == "__main__":
    main()
