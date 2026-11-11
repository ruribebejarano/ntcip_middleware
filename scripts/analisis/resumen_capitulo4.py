#!/usr/bin/env python3
"""Resumen complementario del Capítulo 4 (B6, 2026-11-01), sobre las
corridas de scripts/campanas/lazo_centralizado.py. NO repite las métricas
de scripts/analisis/lazo_centralizado.py (RTT_srv, t_RSU, L, anticipación
real: ya están en tabla_latencia.tex / tabla_condicion.tex de cada
carpeta `_figuras_*`) -- calcula lo que falta para el Capítulo 4:

  1. Renovación de solicitudes (RNF-02, 1 Hz) y caducidad (RNF-03, RF-07):
     cuenta M1_tx (primeras vs. renovaciones, por el campo "renovacion"
     de servidor/gestor_mision.py::_renovar) y eventos "caducidad"
     (EVT_CADUCIDAD, agent/rsu_middleware.py) por repetición -- si la
     renovación a 1 Hz funciona, debe haber cero caducidades a velocidad
     real (factor=1).
  2. Tamaño de muestra real por escenario/config (repeticiones, misiones,
     paradas), para la metodología del Capítulo 4, leído de config.json y
     de los eventos, no tecleado a mano.

Uso:
    python scripts/analisis/resumen_capitulo4.py \\
        --dir resultados/campana/20261029-005510_lazo_local \\
        --dir resultados/campana/20261029-012758_desvio_local \\
        --dir resultados/campana/20261029-020001_lazo_pi-lan \\
        --dir resultados/campana/20261029-023433_desvio_pi-lan \\
        --salida resultados/campana/_figuras_2026-10-29_local_vs_pi-lan
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import cargar  # noqa: E402


def _config_json(directorio: Path) -> dict:
    ruta = directorio / "config.json"
    if not ruta.exists():
        raise SystemExit(f"{ruta} no existe -- ¿es una carpeta de corrida de "
                          f"scripts/campanas/lazo_centralizado.py?")
    return json.loads(ruta.read_text(encoding="utf-8"))


def _resumen_renovacion(directorio: Path) -> dict:
    cfg = _config_json(directorio)
    eventos = cargar([directorio])

    m1 = [e for e in eventos if e["tipo_evento"] == "M1_tx" and e["nodo"] == "servidor"]
    primeras = [e for e in m1 if not e["extra"].get("renovacion")]
    renovaciones = [e for e in m1 if e["extra"].get("renovacion")]
    caducidades = [e for e in eventos if e["tipo_evento"] == "caducidad"]

    n_reps = len(sorted(directorio.glob("rep_*")))
    return {
        "escenario": cfg["escenario"],
        "config": cfg["config"],
        "factor": cfg["factor"],
        "n_repeticiones": n_reps,
        "n_solicitudes_primeras": len(primeras),
        "n_renovaciones": len(renovaciones),
        "n_caducidades": len(caducidades),
    }


def _fila_latex(r: dict) -> str:
    veredicto = "Sin caducidad" if r["n_caducidades"] == 0 else f"{r['n_caducidades']} CADUCIDAD(ES)"
    return (
        f"{r['escenario']} & {r['config']} & {r['n_repeticiones']} & "
        f"{r['n_solicitudes_primeras']} & {r['n_renovaciones']} & {veredicto} \\\\"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True,
                     help="una carpeta de corrida por --dir (config.json + rep_NN/)")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    resumenes = [_resumen_renovacion(Path(d)) for d in args.dir]

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "resumen_renovacion.json").write_text(
        json.dumps(resumenes, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    filas = "\n".join(_fila_latex(r) for r in resumenes)
    factores = {r["factor"] for r in resumenes}
    nota_factor = (
        "a velocidad real (factor=1)" if factores == {1.0} or factores == {1}
        else f"[REVISAR: hay corridas con factor != 1 mezcladas: {sorted(factores)}]"
    )
    tex = f"""\\begin{{table}}[H]
\\centering
\\caption{{Renovación de solicitudes (RNF-02) y caducidad (RNF-03, RF-07), {nota_factor}.}}
\\label{{tab:renovacion_campana}}
\\small
\\begin{{tabular}}{{llrrrl}}
\\toprule
\\textbf{{Escenario}} & \\textbf{{Config.}} & \\textbf{{Repet.}} & \\textbf{{Solicitudes}} & \\textbf{{Renovaciones}} & \\textbf{{Caducidad (RF-07)}} \\\\
\\midrule
{filas}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""
    (salida / "tabla_renovacion.tex").write_text(tex, encoding="utf-8")

    total_caducidades = sum(r["n_caducidades"] for r in resumenes)
    print(f"Tabla: {salida / 'tabla_renovacion.tex'}")
    print(f"Total caducidades en {len(resumenes)} corridas: {total_caducidades}")
    for r in resumenes:
        print(f"  {r['escenario']}/{r['config']}: {r['n_repeticiones']} rep., "
              f"{r['n_solicitudes_primeras']} solicitudes, {r['n_renovaciones']} renovaciones, "
              f"{r['n_caducidades']} caducidades")


if __name__ == "__main__":
    main()
