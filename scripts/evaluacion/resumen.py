#!/usr/bin/env python3
"""Resume una evaluación: misiones, RSU, latencia, frecuencia y GNSS.

Las RSU y el servidor corren en la misma laptop, así que L usa un solo reloj.
Escribe resumen.txt y paradas.csv en la carpeta de la evaluación.

Uso:
    python scripts/evaluacion/resumen.py --dir resultados/evaluacion/<carpeta>
"""

from __future__ import annotations

import argparse
import csv
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


def texto_resumen(eventos: list[dict]) -> tuple[str, list[dict]]:
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
    return "\n".join(lineas) + "\n", paradas


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True)
    args = ap.parse_args()
    eventos = cargar([args.dir])
    if not eventos:
        sys.exit(f"No hay eventos en {args.dir}.")
    texto, paradas = texto_resumen(eventos)
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
