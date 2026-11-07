#!/usr/bin/env python3
"""Trayectorias SINTÉTICAS sobre la geometría real de una ruta (campaña de
ruta completa, resultados/ruta_completa/). Complementa a
scripts/trayectorias/generar.py, que solo genera rectas entre las dos
intersecciones de config/registro_rsu.json.

*** DATOS FICTICIOS *** El vehículo sigue la polilínea de la ruta del
servidor (servidor/rutas.py) a 1 Hz con un perfil de velocidad definido
aquí; no es un recorrido real ni reacciona a los semáforos. Las filas no
llevan ruido GNSS: lo agrega el runner en cada repetición
(scripts/campanas/lazo_centralizado.py::_trayectoria_con_ruido, que no
perturba las filas con velocidad 0).

Escenarios:
  A  velocidad constante (36 km/h por defecto).
  B  PERFIL SINTÉTICO de velocidad variable: velocidad objetivo al azar entre
     20 y 50 km/h que cambia cada 15-40 s, con aceleración <= 1.5 m/s2 y
     frenado <= 2.5 m/s2, y 3 o 4 detenciones de 5 a 20 s: 2 o 3 en puntos al
     azar de la ruta y 1 dirigida 40 m antes de una RSU cuya solicitud sale
     por ETA (fuera de la geocerca), para ejercitar la suspensión de la
     solicitud con el vehículo detenido (servidor/gestor_mision.py,
     T_DETENIDO_MAX_S). No es tráfico real.
  C  desvío: igual que A hasta un punto de salida, sigue por una calle
     lateral y luego por la ruta que el servidor calcularía desde ahí hasta
     el destino (la trayectoria debe coincidir con la ruta recalculada; si
     no, el servidor recalcularía en cada muestra).

La primera y la última fila van con velocidad 0 (sin ruido): así el origen
y el destino del MI de la OBU emulada (primera y última fila) caen siempre
en el mismo nodo del grafo.

Columnas: t_s, lat, lon, rumbo_deg, velocidad_kmh, s_m (distancia
recorrida sin ruido), detenida (1 si la fila es parte de una detención),
tramo ("ruta" o "desvio").
"""

from __future__ import annotations

import csv
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import proyeccion_local, rumbo_entre  # noqa: E402

COLUMNAS = ["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh", "s_m", "detenida", "tramo"]

ACEL_MAX = 1.5    # m/s2
FRENO_MAX = 2.5   # m/s2


@dataclass
class Polilinea:
    puntos: list[tuple[float, float]]

    def __post_init__(self) -> None:
        self.acum = [0.0]
        for a, b in zip(self.puntos, self.puntos[1:]):
            x, y = proyeccion_local(b[0], b[1], a[0], a[1])
            self.acum.append(self.acum[-1] + math.hypot(x, y))

    @property
    def largo(self) -> float:
        return self.acum[-1]

    def en(self, s: float) -> tuple[float, float, float]:
        """(lat, lon, rumbo) a la distancia s (recortada a [0, largo])."""
        s = max(0.0, min(s, self.largo))
        for i in range(len(self.puntos) - 1):
            if s <= self.acum[i + 1] or i == len(self.puntos) - 2:
                a, b = self.puntos[i], self.puntos[i + 1]
                tramo = self.acum[i + 1] - self.acum[i]
                t = 0.0 if tramo == 0 else (s - self.acum[i]) / tramo
                return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), rumbo_entre(a[0], a[1], b[0], b[1]))
        raise AssertionError


def recorrer(pol: Polilinea, velocidades_ms: list[float], tramo_de=lambda s: "ruta") -> list[dict]:
    """Una fila por segundo. velocidades_ms[k] es la velocidad en el segundo
    k (la posición de la fila k+1 avanza esa velocidad). Primera y última
    fila con velocidad 0."""
    filas = []
    s = 0.0
    lat, lon, rumbo = pol.en(0.0)
    filas.append({"t_s": 0.0, "lat": lat, "lon": lon, "rumbo_deg": rumbo, "velocidad_kmh": 0.0, "s_m": 0.0,
                  "detenida": 0, "tramo": tramo_de(0.0)})
    t = 0
    for v in velocidades_ms:
        t += 1
        s = min(s + v, pol.largo)
        lat, lon, rumbo_seg = pol.en(s)
        if v > 0:
            rumbo = rumbo_seg
        filas.append({"t_s": float(t), "lat": lat, "lon": lon, "rumbo_deg": rumbo, "velocidad_kmh": v * 3.6,
                      "s_m": s, "detenida": int(v == 0), "tramo": tramo_de(s)})
        if s >= pol.largo:
            break
    filas[-1]["velocidad_kmh"] = 0.0
    return filas


def perfil_constante(largo_m: float, v_kmh: float) -> list[float]:
    v = v_kmh / 3.6
    n = math.ceil(largo_m / v) + 1
    return [v] * n


def perfil_variable(largo_m: float, rnd: random.Random, detenciones: list[tuple[float, int]],
                    v_min_kmh: float = 20.0, v_max_kmh: float = 50.0) -> list[float]:
    """detenciones: (posición en m, duración en s), en cualquier orden."""
    pendientes = sorted(detenciones)
    v_min, v_max = v_min_kmh / 3.6, v_max_kmh / 3.6
    v = 0.0
    s = 0.0
    objetivo = rnd.uniform(v_min, v_max)
    cambio_en = rnd.randint(15, 40)
    salida: list[float] = []
    t = 0
    while s < largo_m and t < 5000:
        t += 1
        if t >= cambio_en:
            objetivo = rnd.uniform(v_min, v_max)
            cambio_en = t + rnd.randint(15, 40)
        if pendientes:
            pos, dur = pendientes[0]
            restante = pos - s
            if restante <= max(v * 1.2, 0.5):
                # Llega al punto de detención en este segundo.
                salida.append(max(restante, 0.0))
                s += max(restante, 0.0)
                salida.extend([0.0] * dur)
                t += dur
                pendientes.pop(0)
                v = 0.0
                continue
            v_freno = math.sqrt(2 * FRENO_MAX * 0.8 * restante)
            meta = min(objetivo, v_freno)
        else:
            meta = objetivo
        if meta > v:
            v = min(meta, v + ACEL_MAX)
        else:
            v = max(meta, v - FRENO_MAX)
        v = max(v, 1.0)
        salida.append(v)
        s += v
    return salida


def escribir(filas: list[dict], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        for f in filas:
            w.writerow({"t_s": f"{f['t_s']:.1f}", "lat": f"{f['lat']:.7f}", "lon": f"{f['lon']:.7f}",
                        "rumbo_deg": f"{f['rumbo_deg']:.1f}", "velocidad_kmh": f"{f['velocidad_kmh']:.1f}",
                        "s_m": f"{f['s_m']:.1f}", "detenida": f["detenida"], "tramo": f["tramo"]})
