#!/usr/bin/env python3
"""Cruza los eventos de common/events.py por id_solicitud y calcula la
latencia por tramo, segun la ecuacion del presupuesto de latencia de
ssec:latencia en main.tex:

    L = t_adq + t_OBU + t_V2I + t_RSU + t_NTCIP <= 1 s   (RNF-01)

*** APROXIMACION, NO ES UNA MEDICION DE ESA ECUACION COMPLETA ***
Con los eventos que hoy registran agent/rsu_middleware.py,
controller/controller_emulator.py y gateway/obu_simulator.py (M1_tx,
M1_rx, snmp_set_tx, ctrl_fase_cambio) solo se puede aproximar:

  - t_V2I_aprox = ts(M1_rx) - ts(M1_tx)
    Transporte OBU -> broker -> RSU, de un solo salto medido (no separa
    t_up / t_broker / t_down: eso exigiria instrumentar tambien el broker,
    que hoy es mosquitto sin modificar).
  - t_RSU_aprox = ts(snmp_set_tx) - ts(M1_rx)
    Procesamiento en la RSU (autenticacion, validacion, verificacion de
    limites) antes de escribir hacia el controlador.
  - t_NTCIP_aprox = ts(ctrl_fase_cambio) - ts(snmp_set_tx)
    Escritura hacia el controlador y confirmacion del cambio de fase.
  - L_aprox = t_V2I_aprox + t_RSU_aprox + t_NTCIP_aprox
            = ts(ctrl_fase_cambio) - ts(M1_tx)

NO se mide t_adq (adquisicion OBD-II/GNSS: el simulador toma el ETA por
argumento, no lo adquiere) ni t_OBU por separado (evaluacion del criterio
de activacion + serializacion + proteccion criptografica: el simulador no
marca ese paso con su propio evento). L_aprox es, por lo tanto, una cota
INFERIOR de la L real de RNF-01, no un reemplazo. Esto deja de ser una
aproximacion recien cuando el agente implemente NTCIP 1202/1211 reales
(ver docs/PLAN_IMPLEMENTACION.md, P2/P3) y la OBU real adquiera telemetria
(OE4).

Uso:
    python3 scripts/analisis/latencia_tramos.py --dir resultados/prueba_registro
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.events import (  # noqa: E402
    EVT_CTRL_FASE_CAMBIO,
    EVT_M1_RX,
    EVT_M1_TX,
    EVT_SNMP_SET_TX,
    iter_eventos,
)

NS_POR_MS = 1_000_000.0


def agrupar_por_solicitud(directorio: Path) -> dict[str, dict[str, int]]:
    """Devuelve {id_solicitud: {tipo_evento: ts_ns}}. Si un tipo_evento se
    repite para el mismo id_solicitud (p. ej. varios polls), se queda con
    el PRIMERO en orden cronologico -- es el que corresponde a la
    transicion real, no a un poll posterior que ya no cambia nada."""
    por_solicitud: dict[str, dict[str, int]] = defaultdict(dict)
    eventos = sorted(iter_eventos(directorio), key=lambda e: e["ts_ns"])
    for ev in eventos:
        tramo = por_solicitud[ev["id_solicitud"]]
        tramo.setdefault(ev["tipo_evento"], ev["ts_ns"])
    return por_solicitud


def calcular_latencias(eventos_ts: dict[str, int]) -> dict[str, float] | None:
    """None si faltan eventos para calcular algun tramo (no se inventa un
    valor parcial)."""
    requeridos = (EVT_M1_TX, EVT_M1_RX, EVT_SNMP_SET_TX, EVT_CTRL_FASE_CAMBIO)
    if not all(r in eventos_ts for r in requeridos):
        return None
    t_m1_tx = eventos_ts[EVT_M1_TX]
    t_m1_rx = eventos_ts[EVT_M1_RX]
    t_snmp_set_tx = eventos_ts[EVT_SNMP_SET_TX]
    t_ctrl = eventos_ts[EVT_CTRL_FASE_CAMBIO]
    return {
        "t_V2I_aprox_ms": (t_m1_rx - t_m1_tx) / NS_POR_MS,
        "t_RSU_aprox_ms": (t_snmp_set_tx - t_m1_rx) / NS_POR_MS,
        "t_NTCIP_aprox_ms": (t_ctrl - t_snmp_set_tx) / NS_POR_MS,
        "L_aprox_ms": (t_ctrl - t_m1_tx) / NS_POR_MS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dir", default="resultados/prueba_registro",
        help="Carpeta con los eventos_*.csv de las tres maquinas (ya copiados "
             "ahi, p. ej. con scripts/pi.sh fetch). Default: resultados/prueba_registro",
    )
    parser.add_argument(
        "--salida", default=None,
        help="CSV de salida (default: <dir>/latencia_tramos.csv)",
    )
    args = parser.parse_args()

    directorio = Path(args.dir)
    if not directorio.is_dir():
        print(f"No existe el directorio '{directorio}'.", file=sys.stderr)
        raise SystemExit(1)

    por_solicitud = agrupar_por_solicitud(directorio)
    if not por_solicitud:
        print(f"No se encontro ningun eventos_*.csv en '{directorio}'.", file=sys.stderr)
        raise SystemExit(1)

    filas = []
    incompletas = 0
    for id_solicitud, eventos_ts in por_solicitud.items():
        latencias = calcular_latencias(eventos_ts)
        if latencias is None:
            incompletas += 1
            continue
        filas.append({"id_solicitud": id_solicitud, **latencias})

    salida = Path(args.salida) if args.salida else directorio / "latencia_tramos.csv"
    with salida.open("w", newline="", encoding="utf-8") as fh:
        campos = ["id_solicitud", "t_V2I_aprox_ms", "t_RSU_aprox_ms", "t_NTCIP_aprox_ms", "L_aprox_ms"]
        writer = csv.DictWriter(fh, fieldnames=campos)
        writer.writeheader()
        for fila in filas:
            writer.writerow(fila)

    print(f"{len(filas)} solicitud(es) con los 4 eventos completos "
          f"(M1_tx, M1_rx, snmp_set_tx, ctrl_fase_cambio); "
          f"{incompletas} descartada(s) por eventos incompletos.")
    print(f"Resultado: {salida}\n")
    if filas:
        print(f"{'id_solicitud':<28} {'t_V2I':>10} {'t_RSU':>10} {'t_NTCIP':>10} {'L_aprox':>10}  (ms)")
        for fila in filas:
            print(
                f"{fila['id_solicitud']:<28} "
                f"{fila['t_V2I_aprox_ms']:>10.2f} "
                f"{fila['t_RSU_aprox_ms']:>10.2f} "
                f"{fila['t_NTCIP_aprox_ms']:>10.2f} "
                f"{fila['L_aprox_ms']:>10.2f}"
            )
    print(
        "\nRecordatorio: L_aprox excluye t_adq y no separa t_OBU; es una cota "
        "inferior de L (RNF-01), no la medicion final -- ver el docstring de "
        "este script."
    )


if __name__ == "__main__":
    main()
