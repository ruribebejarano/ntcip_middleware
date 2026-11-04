#!/usr/bin/env python3
"""Imprime las rutas CA, certificado y llave de un cliente, y lo emite si falta.

Uso:
    python scripts/evaluacion/cert_cliente.py --tipo rsu --id 50
    python scripts/evaluacion/cert_cliente.py --tipo obu --id obu-tab-01
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from scripts.seguridad import generar_ca  # noqa: E402

# El openssl de Strawberry Perl falla con estos comandos; se prefiere el de Git.
OPENSSL_GIT = Path(r"C:\Program Files\Git\usr\bin")


def rutas_cliente(pki: Path, tipo: str, id_: str | None) -> tuple[Path, Path, Path]:
    if OPENSSL_GIT.exists():
        os.environ["PATH"] = f"{OPENSSL_GIT}{os.pathsep}{os.environ.get('PATH', '')}"
    generar_ca.PKI = pki
    generar_ca.CA_DIR = pki / "ca"
    if not (generar_ca.CA_DIR / "ca.crt").exists():
        raise SystemExit(f"No hay una CA en {pki}. Crea una con: python scripts/seguridad/generar_ca.py init")
    _cn, nombre, directorio = generar_ca._nombre(tipo, id_)
    crt = directorio / f"{nombre}.crt"
    if not crt.exists():
        with contextlib.redirect_stdout(sys.stderr):
            generar_ca.emitir(tipo, id_)
    return generar_ca.CA_DIR / "ca.crt", crt, directorio / f"{nombre}.key"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pki", type=Path, default=RAIZ / "deploy" / "pki")
    ap.add_argument("--tipo", required=True, choices=["rsu", "obu", "servidor"])
    ap.add_argument("--id", default=None)
    args = ap.parse_args()
    # openssl hereda estos descriptores: sin consola, no debe esperar entrada ni
    # escribir en un stderr que PowerShell 5 trate como error.
    log = RAIZ / "resultados" / "evaluacion" / "cert_cliente.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    fd_log = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(fd_log, 2)
    # `openssl verify` escribe en stdout; aquí solo deben salir las tres rutas.
    stdout_real = os.dup(1)
    os.dup2(fd_log, 1)
    try:
        rutas = rutas_cliente(args.pki.resolve(), args.tipo, args.id)
    finally:
        os.dup2(stdout_real, 1)
    for ruta in rutas:
        print(ruta)


if __name__ == "__main__":
    main()
