"""Helper TLS 1.3 + mTLS común para los clientes paho-mqtt del proyecto
(prompt_seguridad.md, S1): servidor/main.py, agent/rsu_middleware.py,
gateway/obu_emulada.py y gateway/obu_simulator.py construían cada uno su
propio ssl.SSLContext (o, en el caso del servidor, pasaban
tls_version=ssl.PROTOCOL_TLS_CLIENT a tls_set(), que deja que la
librería negocie hasta TLS 1.2 si el otro lado no ofrece 1.3 -- no fija
un mínimo). Este módulo construye el contexto una sola vez, con:

- TLS 1.3 como versión MÍNIMA (no solo "la más alta disponible").
- Verificación del nombre del servidor (hostname) contra el SAN del
  certificado del broker -- paho usa el host de client.connect() como
  server_hostname (ver Client._ssl_wrap_socket).
- Certificado de cliente obligatorio (mTLS).
- Un error explícito, antes de intentar conectar, si falta alguno de
  los tres archivos.

Sin red ni dependencia del broker: solo construye objetos ssl/paho.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

# Puerto de Mosquitto reservado para TLS en este proyecto
# (scripts/seguridad/mosquitto_tls.conf); conectarse aquí sin TLS sería
# un error de configuración, no un modo válido "sin TLS".
PUERTO_TLS_POR_CONVENCION = 8883


def construir_contexto_tls(ca_cert: str, certfile: str, keyfile: str) -> ssl.SSLContext:
    """Arma un ssl.SSLContext para mTLS de cliente: TLS 1.3 mínimo,
    certificado de cliente cargado, CA del proyecto como única raíz de
    confianza. Lanza SystemExit con un mensaje claro si algún archivo no
    existe -- más legible que la traza de ssl.SSLError al conectar."""
    faltantes = [ruta for ruta in (ca_cert, certfile, keyfile) if not Path(ruta).is_file()]
    if faltantes:
        raise SystemExit(
            "TLS: no se encontró " + ", ".join(faltantes) +
            " -- revisa las rutas de CA/certificado/llave."
        )
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_3
    contexto.load_verify_locations(cafile=ca_cert)
    contexto.load_cert_chain(certfile=certfile, keyfile=keyfile)
    # PROTOCOL_TLS_CLIENT ya deja esto en True/CERT_REQUIRED por defecto;
    # explícito para que no dependa de ese valor por defecto si cambia.
    contexto.check_hostname = True
    contexto.verify_mode = ssl.CERT_REQUIRED
    return contexto


def aplicar_tls(
    client: "mqtt.Client",
    ca_cert: str | None,
    certfile: str | None,
    keyfile: str | None,
    *,
    puerto: int | None = None,
) -> bool:
    """Si las tres rutas están presentes, construye el contexto y lo
    aplica al cliente paho (`client.tls_set_context`) -- devuelve True.

    Si NINGUNA ruta está presente, no toca el cliente (modo sin TLS, el
    broker de desarrollo en 1883) y devuelve False -- salvo que `puerto`
    sea el de TLS por convención (8883): ahí falla explícito, porque
    conectar en claro a ese puerto sería un error de configuración
    silencioso, no un modo soportado (S1.3 de prompt_seguridad.md).

    Si solo ALGUNAS rutas están presentes, es una configuración a medio
    hacer: falla explícito en vez de adivinar.
    """
    rutas = (ca_cert, certfile, keyfile)
    if not any(rutas):
        if puerto == PUERTO_TLS_POR_CONVENCION:
            raise SystemExit(
                f"Puerto {puerto} es el de TLS por convención "
                f"(scripts/seguridad/mosquitto_tls.conf) y no se pasó CA/"
                "certificado/llave -- no se conecta en claro a ese puerto. "
                "Pasa las tres rutas, o usa el puerto sin TLS."
            )
        return False
    if not all(rutas):
        nombres = ("CA", "certificado", "llave")
        faltan = [nombre for nombre, ruta in zip(nombres, rutas) if not ruta]
        raise SystemExit(f"TLS incompleto: falta {', '.join(faltan)} (se dieron las otras rutas).")
    contexto = construir_contexto_tls(*rutas)  # type: ignore[arg-type]
    client.tls_set_context(contexto)
    return True
