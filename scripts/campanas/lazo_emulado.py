#!/usr/bin/env python3
"""*** OBSOLETO desde la arquitectura centralizada (2026-10-22, commits
3.2-3.8) *** Usar scripts/campanas/lazo_centralizado.py en su lugar.

Este script asume el esquema ANTERIOR: la OBU decide localmente y emite
M1 directo a la RSU (gateway/obu_emulada.py de esa etapa). Desde la
migracion, la OBU solo emite MI/MP/MF y es servidor/main.py quien decide
y emite M1/M3 hacia la RSU -- este runner no levanta el servidor central
en absoluto, asi que el analisis que espera (M1_tx de la OBU) no
encuentra nada util contra el gateway/obu_emulada.py actual. Se deja el
archivo (no se borra, es evidencia de la etapa anterior -- ver
docs/bitacora/2026-10-19_lazo-obu-emulada.md) pero no se actualiza mas.

Docstring original, valido solo para esa etapa anterior:

Campana del lazo con OBU EMULADA: genera trayectorias sinteticas, las
reproduce una por una contra el broker y deja todo listo para el analisis.

*** TRAYECTORIAS FICTICIAS (ver scripts/trayectorias/generar.py) ***

Cada corrida queda en resultados/lazo_emulado/<AAAAMMDD-HHMMSS>/:
    config.json          commit, parametros, broker, escenarios y semillas
    trayectorias/*.csv   las trayectorias exactas que se reprodujeron
    eventos_obu.csv      eventos del lado OBU (M1_tx, M2_rx, M3_tx)
    obu_*.log            consola de cada recorrido

Los eventos de la RSU y del controlador quedan en la maquina donde corren:
- Banco local (todo en la laptop): se escriben en la misma carpeta si se
  arrancan con RSU_EVENTOS_DIR apuntando a ella (ver docs/LAZO_EMULADO.md).
- Raspberry Pi: traerlos con `scripts/pi.sh fetch` y pasarlos al analisis
  con un segundo --dir.

Uso:
    python3 scripts/campanas/lazo_emulado.py --broker-host 192.168.18.175 --repeticiones 5
    python3 scripts/campanas/lazo_emulado.py --broker-host rsu-01 --escenarios avenida_ab --repeticiones 10
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import ParametrosGeometria  # noqa: E402
from scripts.trayectorias.generar import ESCENARIOS  # noqa: E402


def _commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, text=True).strip()
        sucio = subprocess.call(["git", "diff", "--quiet"], cwd=RAIZ) != 0
        return sha + ("-con-cambios-sin-commit" if sucio else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker-host", required=True)
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--escenarios", nargs="*", default=["avenida_ab", "avenida_ba", "transversal_a"],
                    choices=ESCENARIOS)
    ap.add_argument("--repeticiones", type=int, default=3, help="semillas por escenario")
    ap.add_argument("--factor", type=float, default=1.0, help="1 = tiempo real (recomendado para medir)")
    ap.add_argument("--clase-tipo", type=int, default=1)
    ap.add_argument("--pausa-max", type=float, default=15.0,
                    help="pausa aleatoria (0..s) entre recorridos, para no llegar siempre en la misma fase del ciclo")
    ap.add_argument("--sigma-pos", type=float, default=5.0)
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "lazo_emulado"))
    args = ap.parse_args()

    corrida = Path(args.salida) / datetime.now().strftime("%Y%m%d-%H%M%S")
    tray_dir = corrida / "trayectorias"
    tray_dir.mkdir(parents=True, exist_ok=True)

    semillas = list(range(1, args.repeticiones + 1))
    for s in semillas:
        subprocess.check_call([sys.executable, str(RAIZ / "scripts" / "trayectorias" / "generar.py"),
                               "--salida", str(tray_dir), "--sigma-pos", str(args.sigma_pos),
                               "--escenarios", *args.escenarios, "--semilla", str(s)],
                              stdout=subprocess.DEVNULL)

    p = ParametrosGeometria()
    config = {
        "fecha_inicio": datetime.now().isoformat(timespec="seconds"),
        "commit": _commit(),
        "broker": f"{args.broker_host}:{args.broker_port}",
        "tls": False,
        "escenarios": args.escenarios,
        "semillas": semillas,
        "factor": args.factor,
        "clase_tipo": args.clase_tipo,
        "sigma_pos_m": args.sigma_pos,
        "parametros_geometria": p.__dict__,
        "advertencia": "trayectorias sinteticas; parametros geometricos provisionales (sin calibrar)",
    }
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    rnd = random.Random(2026)
    entorno = dict(os.environ, RSU_EVENTOS_DIR=str(corrida))
    recorridos = sorted(tray_dir.glob("*.csv"))
    print(f"Corrida {corrida.name}: {len(recorridos)} recorridos contra {config['broker']} (x{args.factor})")
    for i, tray in enumerate(recorridos, 1):
        print(f"[{i}/{len(recorridos)}] {tray.name}")
        with (corrida / f"obu_{tray.stem}.log").open("w", encoding="utf-8") as log:
            subprocess.call([sys.executable, str(RAIZ / "gateway" / "obu_emulada.py"),
                             "--broker-host", args.broker_host, "--broker-port", str(args.broker_port),
                             "--trayectoria", str(tray), "--factor", str(args.factor),
                             "--clase-tipo", str(args.clase_tipo)],
                            stdout=log, stderr=subprocess.STDOUT, env=entorno, cwd=RAIZ)
        if i < len(recorridos):
            time.sleep(rnd.uniform(0, args.pausa_max))

    config["fecha_fin"] = datetime.now().isoformat(timespec="seconds")
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nListo: {corrida}")
    print("Analisis (si la RSU corre en otra maquina, traer antes sus eventos con scripts/pi.sh fetch):")
    print(f"  python3 scripts/analisis/lazo_emulado.py --dir {corrida} [--dir resultados/rsu/eventos]")


if __name__ == "__main__":
    main()
