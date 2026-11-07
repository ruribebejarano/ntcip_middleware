#!/usr/bin/env python3
"""ESTIMACIÓN SIN RED (no medición): cuándo habría abierto la geocerca la
solicitud de cada RSU de la ruta completa si el "cruce" solo se declarara
tras haber entrado al radio R_g.

En la campaña medida, el seguidor de la geocerca (gateway/geometria.py)
declara "cruce" y excluye la intersección en cuanto deja de estar por
delante, aunque el vehículo siga lejos (curvas antes de la RSU). Ahí la
solicitud la abre el respaldo por ETA con ETA <= 8 s.

Este script pasa las MISMAS trayectorias, con el MISMO ruido GNSS (misma
función y semilla que el runner), por el seguidor tal cual y por una
variante corregida (aplicada aquí con un parche en memoria, sin tocar
gateway/geometria.py). Para cada RSU calcula el tiempo desde la apertura
por geocerca hasta que el vehículo alcanza la intersección en la
trayectoria base. Es tiempo hasta el centro, no anticipación real: no
incluye la transición del controlador, que solo se mide con la red.

Uso:
    python scripts/analisis/estimacion_geocerca_corregida.py \
        --salida resultados/ruta_completa/analisis/estimacion_geocerca_corregida.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
import gateway.geometria as g  # noqa: E402
from scripts.campanas.lazo_centralizado import _trayectoria_con_ruido  # noqa: E402

FIX = RAIZ / "scripts" / "campanas" / "fixtures"
SIGMA_POS_M = 5.0
SEMILLAS = {"A": [101, 102, 103, 104, 105], "B": [201, 202, 203, 204, 205]}

_original = g.SeguidorAcceso.actualizar


def _corregido(self, lat, lon, rumbo):
    """Si la intersección asignada deja de estar por delante SIN que el
    vehículo haya entrado a R_g (no hay solicitud vigente y sigue fuera de
    R_g), se pierde la asignación sin declarar cruce ni excluirla."""
    if self.actual is not None and not self.solicitud_vigente:
        inter = self._inter(self.actual.interseccion_id)
        ev = g.evaluar_interseccion(inter, lat, lon, rumbo, self.p)
        if not ev.por_delante and ev.distancia_m > self.p.r_g_m:
            self.actual = None
            self._fuera = self._rumbo_fuera = 0
    return _original(self, lat, lon, rumbo)


def _leer(p: Path) -> list[dict]:
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def aperturas(registro, filas, variante) -> dict[str, float]:
    """t_s de la primera EMITIR_M1 de la geocerca por RSU."""
    g.SeguidorAcceso.actualizar = variante
    try:
        s = g.SeguidorAcceso(registro)
        out: dict[str, float] = {}
        for f in filas:
            for d in s.actualizar(float(f["lat"]), float(f["lon"]), float(f["rumbo_deg"])):
                if d.accion == g.EMITIR_M1:
                    out.setdefault(d.asignacion.rsu_id, float(f["t_s"]))
        return out
    finally:
        g.SeguidorAcceso.actualizar = _original


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args()

    registro = g.cargar_registro(FIX / "registro_ruta_hospital_nino.json")
    paradas = json.loads((FIX / "ruta_completa" / "validacion_sin_red.json").read_text(encoding="utf-8"))["paradas"]
    filas_salida = []
    for esc, semillas in SEMILLAS.items():
        for k, semilla in enumerate(semillas, start=1):
            base = FIX / "ruta_completa" / ("trayectoria_A.csv" if esc == "A" else f"trayectoria_B_s{semilla}.csv")
            filas_base = _leer(base)
            with tempfile.TemporaryDirectory() as tmp:
                ruidosa = Path(tmp) / "t.csv"
                _trayectoria_con_ruido(base, ruidosa, semilla, SIGMA_POS_M)
                filas = _leer(ruidosa)
            antes = aperturas(registro, filas, _original)
            despues = aperturas(registro, filas, _corregido)
            for rsu, acum in paradas.items():
                t_llegada = next(float(f["t_s"]) for f in filas_base if float(f["s_m"]) >= acum)
                filas_salida.append({
                    "escenario": esc, "repeticion": f"rep_{k:02d}", "semilla": semilla, "rsu_id": rsu,
                    "geocerca_actual_s_al_centro": round(t_llegada - antes[rsu], 1) if rsu in antes else None,
                    "geocerca_corregida_s_al_centro": round(t_llegada - despues[rsu], 1) if rsu in despues else None,
                })
    afectadas = [f for f in filas_salida if f["geocerca_actual_s_al_centro"] != f["geocerca_corregida_s_al_centro"]]
    resumen = {
        "nota": "ESTIMACIÓN SIN RED con geocerca corregida; no es una medición. Tiempo desde la apertura "
                "por geocerca hasta alcanzar la intersección en la trayectoria base.",
        "casos_que_cambian": afectadas,
        "todas": filas_salida,
    }
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resumen, indent=1, ensure_ascii=False), encoding="utf-8")
    for f in afectadas:
        print(f"{f['escenario']} {f['repeticion']} RSU {f['rsu_id']}: actual {f['geocerca_actual_s_al_centro']} s "
              f"-> corregida {f['geocerca_corregida_s_al_centro']} s")
    print(f"Escrito en {args.salida}")


if __name__ == "__main__":
    main()
