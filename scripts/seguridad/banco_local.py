#!/usr/bin/env python3
"""Banco de seguridad local, reproducible (prompt_seguridad.md, S2).

Todo en la laptop, sin Raspberry Pi ni tablet: genera una PKI de prueba
(con casos positivos Y negativos) y levanta/baja un Mosquitto temporal
en un puerto libre, para que tests/test_seguridad_broker.py (S3) pueda
probar TLS 1.3 + mTLS + ACL contra un broker real sin tocar
deploy/pki/ ni el Mosquitto de desarrollo de la laptop (allow_anonymous
en 1883).

Subcomandos (también importables como funciones, ver más abajo):
    preparar   genera deploy/pki_banco/ (ignorada por git, ver .gitignore)
    levantar   escribe un mosquitto.conf temporal y arranca Mosquitto
    bajar      detiene el broker (usa el estado que dejó 'levantar')

Identidades de deploy/pki_banco/ (todas firmadas por la CA propia del
banco, deploy/pki_banco/ca/, salvo que se diga lo contrario):
    servidor-central           sin casos negativos
    rsu 1, rsu 2                "
    obu obu-emu-01, obu-emu-02  "
    obu obu-expirado-01        vencido (openssl ca -startdate/-enddate
                                en el pasado, NO simulado con fechas de
                                sistema falsas)
    obu obu-revocado-01        revocado (generar_ca.revocar(); CRL
                                regenerada en ca/ca.crl)
    (carpeta aparte) ajena/    una CA AJENA (no la del banco) y un
                                cliente firmado por ella con CN=obu-emu-01
                                -- mismo "nombre" que un cliente legítimo,
                                pero de un emisor que el broker no confía
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.seguridad import generar_ca  # noqa: E402

PKI_BANCO = RAIZ / "deploy" / "pki_banco"
MOSQUITTO_EXE = r"C:\Program Files (x86)\Mosquitto\mosquitto.exe"
ACL_FILE = RAIZ / "scripts" / "seguridad" / "mosquitto_acl.conf"
ESTADO_JSON = PKI_BANCO / "_banco_estado.json"

RSU_IDS = ["1", "2"]
OBU_IDS = ["obu-emu-01", "obu-emu-02"]
OBU_EXPIRADO = "obu-expirado-01"
OBU_REVOCADO = "obu-revocado-01"
CN_CLIENTE_AJENO = "obu-emu-01"  # a propósito: el mismo CN que un cliente legítimo


def _openssl(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def preparar(pki_dir: Path = PKI_BANCO) -> Path:
    """Genera la PKI de prueba completa (casos positivos y negativos) en
    `pki_dir`. Es reentrante: si ya existe, no la regenera (igual que
    generar_ca.init_ca()) -- borrar la carpeta a mano para empezar de
    nuevo (p. ej. tras cambiar los SAN por defecto)."""
    generar_ca.PKI = pki_dir
    generar_ca.CA_DIR = pki_dir / "ca"
    pki_dir.mkdir(parents=True, exist_ok=True)

    generar_ca.init_ca()
    generar_ca.emitir("servidor", None)
    for rsu_id in RSU_IDS:
        generar_ca.emitir("rsu", rsu_id)
    for obu_id in OBU_IDS:
        generar_ca.emitir("obu", obu_id)

    _emitir_vencido(pki_dir)
    _emitir_y_revocar(pki_dir)
    _emitir_ca_ajena(pki_dir)

    # CRL con al menos una entrada (OBU_REVOCADO) -- mosquitto necesita
    # que el archivo exista y sea un CRL válido para poder activar
    # `crlfile`; sin esto, levantar() no podría probarlo.
    if not (generar_ca.CA_DIR / "ca.crl").exists():
        _openssl(["openssl", "ca", "-config", str(generar_ca.CA_DIR / "openssl.cnf"),
                  "-gencrl", "-out", str(generar_ca.CA_DIR / "ca.crl")])
    print(f"Banco de seguridad preparado en {pki_dir}")
    return pki_dir


def _emitir_vencido(pki_dir: Path) -> None:
    """Certificado YA vencido de verdad (openssl ca -startdate/-enddate
    en el pasado), no una fecha de sistema falsificada: T04 de S3 debe
    probar el rechazo real de TLS ante un certificado expirado."""
    out = pki_dir / "obu" / OBU_EXPIRADO
    crt = out / f"obu-{OBU_EXPIRADO}.crt"
    if crt.exists():
        return
    out.mkdir(parents=True, exist_ok=True)
    key = out / f"obu-{OBU_EXPIRADO}.key"
    csr = out / f"obu-{OBU_EXPIRADO}.csr"
    _openssl(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key)])
    _openssl(["openssl", "req", "-new", "-key", str(key), "-out", str(csr),
              "-subj", f"/O=ntcip_middleware (tesis PUCP)/CN={OBU_EXPIRADO}"])
    # Vigencia de un solo día, hace dos años: vencido con margen de sobra.
    _openssl([
        "openssl", "ca", "-config", str(generar_ca.CA_DIR / "openssl.cnf"), "-batch",
        "-startdate", "230101000000Z", "-enddate", "230102000000Z",
        "-in", str(csr), "-out", str(crt),
    ])
    csr.unlink(missing_ok=True)


def _emitir_y_revocar(pki_dir: Path) -> None:
    """Certificado normal, revocado de inmediato -- T05: el argumento de
    "revocar una OBU" de la tesis. emitir() + revocar() siempre van
    juntos aquí, así que basta con que el .crt ya exista para saber que
    ambos pasos ya se hicieron (reentrancia, igual que init_ca())."""
    crt = pki_dir / "obu" / OBU_REVOCADO / f"obu-{OBU_REVOCADO}.crt"
    if crt.exists():
        return
    generar_ca.emitir("obu", OBU_REVOCADO)
    generar_ca.revocar("obu", OBU_REVOCADO)


def _emitir_ca_ajena(pki_dir: Path) -> None:
    """Una CA totalmente distinta de la del banco, y un cliente firmado
    por ella con el MISMO CN que un cliente legítimo (obu-emu-01) -- T02:
    el broker debe rechazarlo por el EMISOR, no solo por el nombre."""
    ajena = pki_dir / "ajena"
    ca_crt = ajena / "ca-ajena.crt"
    if ca_crt.exists():
        return
    ajena.mkdir(parents=True, exist_ok=True)
    ca_key = ajena / "ca-ajena.key"
    _openssl(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(ca_key)])
    _openssl([
        "openssl", "req", "-new", "-x509", "-days", "3650", "-key", str(ca_key), "-out", str(ca_crt),
        "-subj", "/O=CA ajena (prueba T02)/CN=CA-ajena-LABORATORIO",
    ])
    cli_key = ajena / "cliente-ajeno.key"
    cli_csr = ajena / "cliente-ajeno.csr"
    cli_crt = ajena / "cliente-ajeno.crt"
    _openssl(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(cli_key)])
    _openssl(["openssl", "req", "-new", "-key", str(cli_key), "-out", str(cli_csr),
              "-subj", f"/O=ntcip_middleware (tesis PUCP)/CN={CN_CLIENTE_AJENO}"])
    _openssl([
        "openssl", "x509", "-req", "-in", str(cli_csr), "-CA", str(ca_crt), "-CAkey", str(ca_key),
        "-CAcreateserial", "-days", "825", "-out", str(cli_crt),
    ])
    cli_csr.unlink(missing_ok=True)


# --- levantar / bajar --------------------------------------------------

@dataclasses.dataclass
class EstadoBanco:
    puerto: int
    pid: int
    conf_path: str
    log_path: str
    pki_dir: str


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _mosquitto_conf(pki_dir: Path, puerto: int, log_path: Path) -> str:
    """Basado en mosquitto_tls.conf/mosquitto_acl.conf, con rutas LOCALES
    a pki_dir en vez de /etc/mosquitto/pki/ (S2: 'levantar... basado en
    mosquitto_tls.conf y mosquitto_acl.conf, con crlfile activo').

    log_dest file (NO stdout): con stdout redirigido a un archivo desde
    Python, mosquitto.exe en Windows deja el log en su buffer interno y
    nunca lo vacía si se lo mata con taskkill /F -- el archivo queda en
    0 bytes aunque el broker haya corrido y logueado de verdad.
    log_dest file escribe directo, sin pasar por ese buffer."""
    ca = pki_dir / "ca"
    servidor = pki_dir / "servidor"
    return f"""\
listener {puerto} 127.0.0.1
cafile {ca / 'ca.crt'}
certfile {servidor / 'servidor-central.crt'}
keyfile {servidor / 'servidor-central.key'}
tls_version tlsv1.3
require_certificate true
use_identity_as_username true
crlfile {ca / 'ca.crl'}

allow_anonymous false
acl_file {ACL_FILE}

persistence false
log_dest file {log_path}
log_type all
"""


def levantar(pki_dir: Path = PKI_BANCO, puerto: int | None = None) -> EstadoBanco:
    if not (pki_dir / "ca" / "ca.crt").exists():
        raise SystemExit(f"{pki_dir}: no hay PKI todavía -- correr 'preparar' primero.")
    puerto = puerto or _puerto_libre()
    log_path = pki_dir / "mosquitto_banco.log"
    log_path.unlink(missing_ok=True)  # mosquitto hace append; que no mezcle con una corrida anterior
    conf_path = pki_dir / "mosquitto_banco.conf"
    conf_path.write_text(_mosquitto_conf(pki_dir, puerto, log_path), encoding="utf-8")
    proceso = subprocess.Popen([MOSQUITTO_EXE, "-c", str(conf_path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    fin = time.monotonic() + 5.0
    listo = False
    while time.monotonic() < fin:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                listo = True
                break
        time.sleep(0.1)
    if not listo:
        proceso.terminate()
        raise SystemExit(f"Mosquitto no abrió el puerto {puerto} en 5 s -- ver {log_path}")

    estado = EstadoBanco(puerto=puerto, pid=proceso.pid, conf_path=str(conf_path),
                         log_path=str(log_path), pki_dir=str(pki_dir))
    ESTADO_JSON.write_text(json.dumps(dataclasses.asdict(estado)), encoding="utf-8")
    return estado


def bajar(estado: EstadoBanco | None = None) -> None:
    """Detiene el Mosquitto del banco. Funciona entre procesos distintos
    (lee el pid de ESTADO_JSON si no se pasa `estado`) -- taskkill en vez
    de Popen.terminate() porque el Popen de levantar() puede vivir en un
    proceso de Python que ya terminó (p. ej. el CLI 'levantar' de una
    llamada y 'bajar' de otra)."""
    if estado is None:
        if not ESTADO_JSON.exists():
            return
        estado = EstadoBanco(**json.loads(ESTADO_JSON.read_text(encoding="utf-8")))
    subprocess.run(["taskkill", "/PID", str(estado.pid), "/T", "/F"], capture_output=True)
    ESTADO_JSON.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="accion", required=True)
    sub.add_parser("preparar")
    p_levantar = sub.add_parser("levantar")
    p_levantar.add_argument("--puerto", type=int, default=None)
    sub.add_parser("bajar")
    args = ap.parse_args()

    if args.accion == "preparar":
        preparar()
    elif args.accion == "levantar":
        estado = levantar(puerto=args.puerto)
        print(f"Mosquitto del banco en 127.0.0.1:{estado.puerto} (pid={estado.pid}), log en {estado.log_path}")
    elif args.accion == "bajar":
        bajar()
        print("Banco detenido.")


if __name__ == "__main__":
    main()
