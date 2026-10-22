#!/usr/bin/env python3
"""CA propia para TLS 1.3 + mTLS (P4, sección 1.4 del prompt de
arquitectura centralizada): emite y revoca certificados para el servidor
central, cada RSU y cada OBU, todos firmados por la misma CA, para que
Mosquitto pueda exigir `require_certificate true` y las ACL de
scripts/seguridad/mosquitto_acl.conf puedan basarse en el Common Name (CN)
del certificado de cada cliente (`use_identity_as_username true`).

*** Estado real en este entorno (ver docs/bitacora/2026-10-22_arquitectura-centralizada.md) ***
Este script SÍ se probó en este entorno (genera la CA y emite certificados
de servidor/RSU/OBU reales con openssl, verificados con
`openssl verify`). Lo que NO se pudo probar aquí es un Mosquitto real
escuchando en 8883 con estos certificados y las ACL aplicadas -- no hay un
broker corriendo en este entorno de desarrollo. Ver
scripts/seguridad/mosquitto_tls.conf y el final de este docstring para los
comandos exactos para que el autor lo verifique en la Raspberry Pi o en su
laptop con Mosquitto instalado.

Subcomandos:
    init                                   crea la CA (una sola vez)
    emitir --tipo servidor                 certificado del servidor central
    emitir --tipo rsu --id 1               certificado de la RSU 1
    emitir --tipo obu --id ses-abc123      certificado de una OBU
    revocar --tipo rsu --id 1              revoca el certificado de la RSU 1 (regenera la CRL)
    listar                                 lista los certificados emitidos y su estado

Todo bajo deploy/pki/ (NO se commitea: deploy/pki/ está en .gitignore --
son credenciales, cada despliegue debe generar las suyas).

Validar un certificado a mano:
    openssl verify -CAfile deploy/pki/ca/ca.crt deploy/pki/rsu/1/rsu-1.crt

Para probar contra un Mosquitto real (Raspberry Pi o laptop, fuera de este
entorno):
    1. Copiar deploy/pki/ca/ca.crt, deploy/pki/servidor/servidor.{crt,key}
       a la máquina del broker (o al servidor mismo si el broker corre ahí).
    2. mosquitto -c scripts/seguridad/mosquitto_tls.conf -v
    3. mosquitto_pub --cafile deploy/pki/ca/ca.crt \\
         --cert deploy/pki/rsu/1/rsu-1.crt --key deploy/pki/rsu/1/rsu-1.key \\
         -h <host> -p 8883 -t rsu/1/solicitudes -m '{"tipo":"M1"}'
       (debe funcionar: el servidor es quien tiene permiso de publicar ahí,
       pero mosquitto_pub con el cert de la RSU prueba al menos el
       handshake TLS/mTLS; para probar la ACL en sí, publicar desde la RSU
       y confirmar que SE RECHAZA, ver docs/CONTRATO_OBU.md).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
PKI = RAIZ / "deploy" / "pki"
CA_DIR = PKI / "ca"
DIAS_CA = 3650   # 10 años: CA de laboratorio, no de producción [REVISAR con asesor]
DIAS_LEAF = 825  # ~27 meses, igual que el límite que exigen los navegadores para TLS de servidor


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _openssl_disponible() -> None:
    try:
        subprocess.run(["openssl", "version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "No se encontró 'openssl' en el PATH. Este script depende del binario de "
            "openssl (no de pyca/cryptography) para no agregar una dependencia pesada "
            "solo para un script de administración -- instalarlo y reintentar."
        )


def init_ca() -> None:
    _openssl_disponible()
    if (CA_DIR / "ca.crt").exists():
        print(f"La CA ya existe en {CA_DIR}, no se regenera (borrar la carpeta a mano si se quiere empezar de nuevo).")
        return
    CA_DIR.mkdir(parents=True, exist_ok=True)
    (CA_DIR / "index.txt").touch()
    (CA_DIR / "serial").write_text("1000\n", encoding="utf-8")
    (CA_DIR / "crlnumber").write_text("1000\n", encoding="utf-8")
    (CA_DIR / "nuevos_certs").mkdir(exist_ok=True)

    cnf = CA_DIR / "openssl.cnf"
    cnf.write_text(_OPENSSL_CNF.format(ca_dir=str(CA_DIR).replace("\\", "/")), encoding="utf-8")

    _run(["openssl", "genrsa", "-out", str(CA_DIR / "ca.key"), "4096"])
    _run([
        "openssl", "req", "-new", "-x509", "-days", str(DIAS_CA),
        "-key", str(CA_DIR / "ca.key"), "-out", str(CA_DIR / "ca.crt"),
        "-subj", "/O=ntcip_middleware (tesis PUCP)/CN=CA-arquitectura-centralizada-LABORATORIO",
    ])
    print(f"CA creada en {CA_DIR} (ca.crt / ca.key). *** SOLO LABORATORIO, no usar en producción ***")


def _nombre(tipo: str, id_: str | None) -> tuple[str, str, Path]:
    """Devuelve (cn, nombre_archivo, directorio). `cn` es el Common Name
    del certificado, que con `use_identity_as_username true` en Mosquitto
    (ver scripts/seguridad/mosquitto_tls.conf) se vuelve el "username" MQTT
    del cliente -- para RSU y OBU se usa el id TAL CUAL (sin prefijo),
    porque scripts/seguridad/mosquitto_acl.conf usa reglas `pattern` con
    `%u` que dependen de que el username coincida exactamente con el
    segmento del tema (RSU_ID de agent/rsu_middleware.py, obu_id de
    gateway/obu_emulada.py). `nombre_archivo` solo es para que los
    archivos en deploy/pki/ sean legibles (sí lleva el prefijo)."""
    if tipo == "servidor":
        return "servidor-central", "servidor-central", PKI / "servidor"
    if tipo == "rsu":
        if not id_:
            raise SystemExit("--id es obligatorio para --tipo rsu (debe ser el mismo RSU_ID de agent/rsu_middleware.py)")
        return id_, f"rsu-{id_}", PKI / "rsu" / id_
    if tipo == "obu":
        if not id_:
            raise SystemExit("--id es obligatorio para --tipo obu (debe ser el mismo obu_id de gateway/obu_emulada.py)")
        return id_, f"obu-{id_}", PKI / "obu" / id_
    raise SystemExit(f"--tipo desconocido: {tipo!r} (servidor|rsu|obu)")


def emitir(tipo: str, id_: str | None) -> None:
    _openssl_disponible()
    if not (CA_DIR / "ca.crt").exists():
        raise SystemExit("No existe la CA todavía -- correr primero: python scripts/seguridad/generar_ca.py init")

    cn, nombre_archivo, out = _nombre(tipo, id_)
    out.mkdir(parents=True, exist_ok=True)
    key = out / f"{nombre_archivo}.key"
    csr = out / f"{nombre_archivo}.csr"
    crt = out / f"{nombre_archivo}.crt"

    _run(["openssl", "genrsa", "-out", str(key), "2048"])
    _run([
        "openssl", "req", "-new", "-key", str(key), "-out", str(csr),
        "-subj", f"/O=ntcip_middleware (tesis PUCP)/CN={cn}",
    ])
    _run([
        "openssl", "ca", "-config", str(CA_DIR / "openssl.cnf"), "-batch",
        "-days", str(DIAS_LEAF), "-in", str(csr), "-out", str(crt),
    ])
    csr.unlink(missing_ok=True)
    print(f"Certificado emitido: {crt} (CN={cn}), firmado por {CA_DIR / 'ca.crt'}")
    print(f"  CA/cert/key para este cliente:")
    print(f"    SERVIDOR_TLS_CA={CA_DIR / 'ca.crt'}" if tipo == "servidor" else "")
    _run(["openssl", "verify", "-CAfile", str(CA_DIR / "ca.crt"), str(crt)])


def revocar(tipo: str, id_: str | None) -> None:
    _openssl_disponible()
    _cn, nombre_archivo, out = _nombre(tipo, id_)
    crt = out / f"{nombre_archivo}.crt"
    if not crt.exists():
        raise SystemExit(f"No existe el certificado {crt}")
    _run(["openssl", "ca", "-config", str(CA_DIR / "openssl.cnf"), "-revoke", str(crt)])
    _run([
        "openssl", "ca", "-config", str(CA_DIR / "openssl.cnf"), "-gencrl",
        "-out", str(CA_DIR / "ca.crl"),
    ])
    print(f"Certificado {crt} revocado. CRL regenerada en {CA_DIR / 'ca.crl'}")
    print("Mosquitto necesita 'crlfile' apuntando a esta CRL para rechazar un cliente revocado "
          "(ver scripts/seguridad/mosquitto_tls.conf) -- sin eso, el certificado revocado sigue "
          "siendo aceptado por TLS (solo mTLS valida la firma de la CA, no la CRL, salvo que se "
          "lo pida explícitamente).")


def listar() -> None:
    index = CA_DIR / "index.txt"
    if not index.exists():
        print("No hay CA inicializada todavía.")
        return
    print(index.read_text(encoding="utf-8") or "(sin certificados emitidos)")


_OPENSSL_CNF = """\
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = {ca_dir}
database        = $dir/index.txt
serial          = $dir/serial
crlnumber       = $dir/crlnumber
new_certs_dir   = $dir/nuevos_certs
certificate     = $dir/ca.crt
private_key     = $dir/ca.key
default_md      = sha256
default_days    = 825
default_crl_days = 30
policy          = policy_laboratorio
copy_extensions = none
unique_subject  = no

[ policy_laboratorio ]
# Laboratorio: no se exige que O/C/ST coincidan con los de la CA, solo que
# haya un CN. [REVISAR con asesor] si se quiere una politica mas estricta
# para un despliegue real.
countryName             = optional
stateOrProvinceName     = optional
organizationName        = optional
commonName              = supplied
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="accion", required=True)
    sub.add_parser("init")
    p_emitir = sub.add_parser("emitir")
    p_emitir.add_argument("--tipo", required=True, choices=["servidor", "rsu", "obu"])
    p_emitir.add_argument("--id", default=None)
    p_revocar = sub.add_parser("revocar")
    p_revocar.add_argument("--tipo", required=True, choices=["servidor", "rsu", "obu"])
    p_revocar.add_argument("--id", default=None)
    sub.add_parser("listar")

    args = ap.parse_args()
    if args.accion == "init":
        init_ca()
    elif args.accion == "emitir":
        emitir(args.tipo, args.id)
    elif args.accion == "revocar":
        revocar(args.tipo, args.id)
    elif args.accion == "listar":
        listar()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Comando de openssl falló (código {exc.returncode}): {' '.join(exc.cmd)}")
