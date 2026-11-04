#!/usr/bin/env python3
"""Corre N repeticiones de la OBU emulada, con ruido GNSS y una pausa aleatoria.

La pausa hace que la solicitud llegue en otra fase del ciclo del controlador.
Lo lanza evaluar.ps1 cuando las RSU y el servidor ya están corriendo.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway.geometria import desplazar  # noqa: E402


def con_ruido(base: Path, destino: Path, semilla: int, sigma_m: float) -> None:
    """Copia la trayectoria con ruido de posición, salvo en las filas detenidas."""
    rnd = random.Random(semilla)
    with base.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        for f in filas:
            if float(f["velocidad_kmh"]) > 0 and sigma_m > 0:
                lat, lon = desplazar(float(f["lat"]), float(f["lon"]), rnd.uniform(0, 360), abs(rnd.gauss(0, sigma_m)))
                f["lat"], f["lon"] = f"{lat:.7f}", f"{lon:.7f}"
            w.writerow(f)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trayectoria", type=Path, required=True)
    ap.add_argument("--dir", type=Path, required=True, help="carpeta de la evaluación")
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--factor", type=float, default=1.0, help="1 = tiempo real; otro valor no sirve para medir")
    ap.add_argument("--sigma-pos", type=float, default=5.0, help="ruido GNSS en metros (1 sigma)")
    ap.add_argument("--pausa-max", type=float, default=25.0, help="pausa aleatoria máxima entre repeticiones, en s")
    ap.add_argument("--semilla", type=int, default=1)
    ap.add_argument("--broker-host", default="127.0.0.1")
    ap.add_argument("--broker-port", type=int, default=8883)
    ap.add_argument("--pki", type=Path, default=None, help="carpeta de la PKI; sin ella, conexión sin TLS")
    args = ap.parse_args()

    rnd = random.Random(args.semilla)
    fallos = 0
    for n in range(1, args.repeticiones + 1):
        rep = args.dir / "obu" / f"rep_{n:02d}"
        rep.mkdir(parents=True, exist_ok=True)
        tray = rep / "trayectoria.csv"
        con_ruido(args.trayectoria, tray, args.semilla + n, args.sigma_pos)
        obu_id = f"obu-eval-r{n:02d}"
        cmd = [sys.executable, str(RAIZ / "gateway" / "obu_emulada.py"), "--broker-host", args.broker_host,
               "--broker-port", str(args.broker_port), "--obu-id", obu_id, "--trayectoria", str(tray),
               "--factor", str(args.factor)]
        if args.pki:
            salida = subprocess.run([sys.executable, str(Path(__file__).with_name("cert_cliente.py")), "--pki",
                                     str(args.pki.resolve()), "--tipo", "obu", "--id", obu_id],
                                    check=True, capture_output=True, text=True).stdout
            ca, crt, key = salida.splitlines()
            cmd += ["--tls-ca", str(ca), "--tls-cert", str(crt), "--tls-key", str(key)]
        if n > 1:
            pausa = rnd.uniform(0, args.pausa_max)
            print(f"Pausa de {pausa:.1f} s antes de la repetición {n}...")
            time.sleep(pausa)
        print(f"=== Repetición {n} de {args.repeticiones} ({obu_id}) ===")
        entorno = {**os.environ, "RSU_EVENTOS_DIR": str(rep), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        with (rep / "obu.log").open("w", encoding="utf-8") as log:
            r = subprocess.run(cmd, cwd=RAIZ, env=entorno, stdout=log, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            fallos += 1
            print(f"*** La repetición {n} terminó con error; revisa {rep / 'obu.log'}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
