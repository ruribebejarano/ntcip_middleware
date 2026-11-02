"""Pruebas de common/mqtt_tls.py (prompt_seguridad.md, S1) que no
requieren un broker real: construccion del contexto, puerto 8883 sin
rutas, rutas incompletas, rutas inexistentes. Las pruebas que sí
necesitan un mosquitto real (TLS 1.3 efectivo, verificacion de SAN,
rechazo de certificados invalidos) estan en test_seguridad_broker.py."""

from __future__ import annotations

import ssl
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from common.mqtt_tls import PUERTO_TLS_POR_CONVENCION, aplicar_tls, construir_contexto_tls  # noqa: E402


@pytest.fixture(scope="module")
def certs_prueba(tmp_path_factory) -> tuple[Path, Path, Path]:
    """CA + certificado de cliente mínimos, generados una vez por módulo
    con openssl (igual que scripts/seguridad/generar_ca.py), para probar
    construir_contexto_tls() sin depender de deploy/pki/ ni de la CA
    real del proyecto."""
    if subprocess.run(["openssl", "version"], capture_output=True).returncode != 0:
        pytest.skip("openssl no esta en el PATH")
    d = tmp_path_factory.mktemp("pki_mqtt_tls")
    ca_key, ca_crt = d / "ca.key", d / "ca.crt"
    cli_key, cli_crt, cli_csr = d / "cli.key", d / "cli.crt", d / "cli.csr"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                    "-out", str(ca_key)], check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-new", "-x509", "-days", "1", "-key", str(ca_key),
                    "-out", str(ca_crt), "-subj", "/CN=ca-prueba"], check=True, capture_output=True)
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                    "-out", str(cli_key)], check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-new", "-key", str(cli_key), "-out", str(cli_csr),
                    "-subj", "/CN=cliente-prueba"], check=True, capture_output=True)
    subprocess.run(["openssl", "x509", "-req", "-in", str(cli_csr), "-CA", str(ca_crt),
                    "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1", "-out", str(cli_crt)],
                   check=True, capture_output=True)
    return ca_crt, cli_crt, cli_key


def test_construir_contexto_tls_fija_tls13_minimo(certs_prueba):
    ca_crt, cli_crt, cli_key = certs_prueba
    contexto = construir_contexto_tls(str(ca_crt), str(cli_crt), str(cli_key))
    assert contexto.minimum_version == ssl.TLSVersion.TLSv1_3
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True


def test_construir_contexto_tls_falla_si_falta_un_archivo(tmp_path):
    with pytest.raises(SystemExit, match="no se encontr"):
        construir_contexto_tls(str(tmp_path / "ca.crt"), str(tmp_path / "c.crt"), str(tmp_path / "c.key"))


def test_aplicar_tls_sin_rutas_no_toca_el_cliente_en_puerto_normal():
    cliente = MagicMock()
    assert aplicar_tls(cliente, None, None, None, puerto=1883) is False
    cliente.tls_set_context.assert_not_called()


def test_aplicar_tls_sin_rutas_en_puerto_tls_falla_explicito():
    cliente = MagicMock()
    with pytest.raises(SystemExit, match="no se conecta en claro"):
        aplicar_tls(cliente, None, None, None, puerto=PUERTO_TLS_POR_CONVENCION)
    cliente.tls_set_context.assert_not_called()


def test_aplicar_tls_con_rutas_parciales_falla_explicito():
    cliente = MagicMock()
    with pytest.raises(SystemExit, match="TLS incompleto"):
        aplicar_tls(cliente, "ca.crt", None, None)
    cliente.tls_set_context.assert_not_called()


def test_aplicar_tls_con_las_tres_rutas_aplica_el_contexto(certs_prueba):
    ca_crt, cli_crt, cli_key = certs_prueba
    cliente = MagicMock()
    assert aplicar_tls(cliente, str(ca_crt), str(cli_crt), str(cli_key), puerto=PUERTO_TLS_POR_CONVENCION) is True
    cliente.tls_set_context.assert_called_once()
    contexto_usado = cliente.tls_set_context.call_args[0][0]
    assert contexto_usado.minimum_version == ssl.TLSVersion.TLSv1_3
