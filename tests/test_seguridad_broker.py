"""Matriz de pruebas de seguridad del broker (prompt_seguridad.md, S3):
T01-T13 contra un Mosquitto real y temporal (scripts/seguridad/banco_local.py),
T14-T17 contra un agente SNMPv3 real y temporal (sin la Raspberry Pi).

Se salta TODO el módulo si no hay mosquitto instalado (ni en el PATH ni en
la ruta del instalador de Windows) -- no debe romper `pytest` normal.
Cada caso levanta su PROPIO broker y lo baja al terminar (S2: "cada caso
levanta el banco y lo baja al terminar"), para que el log de cada uno
quede aislado (scripts/seguridad/correr_matriz.py lo usa como evidencia
por caso).

Esta es la evidencia de la sección 4.6 del Capítulo 4. Si un caso falla,
NO se ajusta la prueba para que pase -- es un hallazgo para la tesis.
"""

from __future__ import annotations

import socket
import ssl
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.seguridad import banco_local  # noqa: E402
from common.mqtt_tls import construir_contexto_tls  # noqa: E402

import paho.mqtt.client as mqtt  # noqa: E402

pytestmark = pytest.mark.seguridad

if banco_local.mosquitto_disponible() is None:
    pytest.skip(
        "mosquitto no está instalado (ni en el PATH ni en la ruta del instalador de "
        "Windows) -- avisar antes de instalarlo, ver prompt_seguridad.md regla 0.",
        allow_module_level=True,
    )


# --- Fixtures ------------------------------------------------------------

@pytest.fixture(scope="module")
def pki_dir() -> Path:
    """Generar la PKI de prueba UNA sola vez por módulo (cara: varias
    llamadas a openssl); el broker en sí se levanta/baja por caso."""
    return banco_local.preparar()


@pytest.fixture()
def banco(pki_dir: Path, request: pytest.FixtureRequest) -> banco_local.EstadoBanco:
    estado = banco_local.levantar(pki_dir)
    yield estado
    # Copia el log de ESTE caso antes de bajar() -- bajar() borra
    # mosquitto_banco.log para que el "levantar" del siguiente caso no
    # choque con el archivo todavia bloqueado por el proceso recien
    # matado (ver banco_local.bajar); scripts/seguridad/correr_matriz.py
    # (S3) lee estos archivos como evidencia por caso.
    logs_dir = pki_dir / "_logs_por_caso"
    logs_dir.mkdir(exist_ok=True)
    nombre = request.node.name.replace("test_", "").split("[")[0]
    try:
        (logs_dir / f"{nombre}.log").write_bytes(Path(estado.log_path).read_bytes())
    except OSError:
        pass
    banco_local.bajar(estado)


def _ruta(pki_dir: Path, tipo: str, id_: str | None) -> tuple[str, str, str]:
    _cn, nombre, out = banco_local.generar_ca._nombre(tipo, id_)
    ca = str(pki_dir / "ca" / "ca.crt")
    return ca, str(out / f"{nombre}.crt"), str(out / f"{nombre}.key")


# --- Helper de conexión ----------------------------------------------------

def _conectar(
    puerto: int, client_id: str, *,
    ca: str | None = None, cert: str | None = None, key: str | None = None,
    maximo_tls: ssl.TLSVersion | None = None,
    host: str = "localhost",
    timeout: float = 4.0,
) -> tuple[bool, str]:
    """Intenta conectar un cliente MQTT 5 al banco. Devuelve (aceptado,
    detalle) -- aceptado es True SOLO si on_connect llegó con
    reason_code de éxito.

    El rechazo de un handshake TLS/mTLS con este paho (2.1.0) NO lanza
    una excepción sincrónica desde connect(): connect()/reconnect()
    arman el socket+TLS y devuelven de inmediato, el handshake de
    verdad ocurre dentro de loop_start() -- un rechazo se ve como
    on_disconnect con 'Unspecified error' (confirmado con on_log contra
    el banco real), no como una excepción ni como on_connect con un
    reason_code de error. Por eso esta función mira ambos callbacks, no
    solo intenta/excepciona."""
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
    resultado: dict = {}
    cliente.on_connect = lambda c, u, f, rc, props=None: resultado.setdefault("connect", rc)
    cliente.on_disconnect = lambda c, u, f, rc, props=None: resultado.setdefault("disconnect", rc)
    try:
        if cert and key:
            contexto = construir_contexto_tls(ca, cert, key)
        else:
            contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            contexto.minimum_version = ssl.TLSVersion.TLSv1_3
            if ca:
                contexto.load_verify_locations(cafile=ca)
        if maximo_tls is not None:
            contexto.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
            contexto.maximum_version = maximo_tls
        cliente.tls_set_context(contexto)
        cliente.connect(host, puerto, keepalive=10)
        cliente.loop_start()
        fin = time.monotonic() + timeout
        while time.monotonic() < fin and not resultado:
            time.sleep(0.05)
        if "connect" in resultado:
            rc = resultado["connect"]
            return bool(getattr(rc, "is_failure", False) is False and int(rc) == 0), f"on_connect rc={rc}"
        if "disconnect" in resultado:
            return False, f"on_disconnect rc={resultado['disconnect']} (rechazado antes de CONNACK)"
        return False, "sin respuesta (timeout) -- ver el log del broker"
    except Exception as exc:  # noqa: BLE001 - se reporta tal cual, es lo que se prueba
        return False, f"excepcion: {exc!r}"
    finally:
        cliente.loop_stop()
        try:
            cliente.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _esperar(cond: Callable[[], bool], timeout: float = 3.0) -> bool:
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# --- T01-T05: handshake TLS/mTLS rechazado --------------------------------

def test_T01_sin_certificado_de_cliente(banco, pki_dir):
    ca, _cert, _key = _ruta(pki_dir, "servidor", None)
    aceptado, detalle = _conectar(banco.puerto, "t01-sin-cert", ca=ca)
    assert not aceptado, f"se esperaba que el handshake fallara; {detalle}"


def test_T02_certificado_de_ca_ajena(banco, pki_dir):
    ca, _cert, _key = _ruta(pki_dir, "servidor", None)
    cliente_ajeno = Path(pki_dir) / "ajena" / "cliente-ajeno.crt"
    llave_ajena = Path(pki_dir) / "ajena" / "cliente-ajeno.key"
    aceptado, detalle = _conectar(banco.puerto, "t02-ca-ajena", ca=ca, cert=str(cliente_ajeno), key=str(llave_ajena))
    assert not aceptado, f"se esperaba que el handshake fallara; {detalle}"


def test_T03_cliente_fuerza_tls12(banco, pki_dir):
    ca, _cert, _key = _ruta(pki_dir, "rsu", "1")
    cert_rsu = Path(pki_dir) / "rsu" / "1" / "rsu-1.crt"
    key_rsu = Path(pki_dir) / "rsu" / "1" / "rsu-1.key"
    aceptado, detalle = _conectar(
        banco.puerto, "t03-tls12", ca=ca, cert=str(cert_rsu), key=str(key_rsu),
        maximo_tls=ssl.TLSVersion.TLSv1_2,
    )
    assert not aceptado, f"se esperaba que el handshake fallara (servidor exige TLS 1.3); {detalle}"


def test_T04_certificado_vencido(banco, pki_dir):
    ca, _cert, _key = _ruta(pki_dir, "servidor", None)
    out = Path(pki_dir) / "obu" / banco_local.OBU_EXPIRADO
    aceptado, detalle = _conectar(
        banco.puerto, "t04-vencido", ca=ca,
        cert=str(out / f"obu-{banco_local.OBU_EXPIRADO}.crt"),
        key=str(out / f"obu-{banco_local.OBU_EXPIRADO}.key"),
    )
    assert not aceptado, f"se esperaba que el handshake fallara (certificado vencido); {detalle}"


def test_T05_certificado_revocado(banco, pki_dir):
    """El argumento de "revocar una OBU" de la tesis: requiere crlfile
    activo en el broker (ver banco_local._mosquitto_conf)."""
    ca, _cert, _key = _ruta(pki_dir, "servidor", None)
    out = Path(pki_dir) / "obu" / banco_local.OBU_REVOCADO
    aceptado, detalle = _conectar(
        banco.puerto, "t05-revocado", ca=ca,
        cert=str(out / f"obu-{banco_local.OBU_REVOCADO}.crt"),
        key=str(out / f"obu-{banco_local.OBU_REVOCADO}.key"),
    )
    assert not aceptado, f"se esperaba que el handshake fallara (certificado revocado); {detalle}"


def test_T12_san_no_coincide(banco, pki_dir):
    """El cliente verifica el nombre del servidor (check_hostname) contra
    el SAN del certificado -- conectando a una IP que NO está en el SAN
    por defecto (ver generar_ca.SAN_SERVIDOR_POR_DEFECTO), el rechazo
    debe ser del LADO DEL CLIENTE, antes de cualquier intercambio de
    aplicación."""
    ca, _cert, _key = _ruta(pki_dir, "rsu", "1")
    cert_rsu = Path(pki_dir) / "rsu" / "1" / "rsu-1.crt"
    key_rsu = Path(pki_dir) / "rsu" / "1" / "rsu-1.key"
    # 127.0.0.2 no está en el SAN (localhost/127.0.0.1/laptopricardoub/
    # 100.121.77.97) -- aunque el broker escucha ahí también (0.0.0.0
    # implícito via 127.0.0.1 en el listener), el hostname no coincide
    # con el certificado.
    aceptado, detalle = _conectar(
        banco.puerto, "t12-san", ca=ca, cert=str(cert_rsu), key=str(key_rsu), host="127.0.0.2",
    )
    assert not aceptado, f"se esperaba que el cliente rechazara el hostname; {detalle}"
    assert "excepcion" in detalle, f"se esperaba un rechazo del LADO DEL CLIENTE (excepcion de ssl); {detalle}"


# --- T06-T09: ACL (identidad valida, tema ajeno) --------------------------

def test_T06_obu_no_puede_publicar_en_solicitudes_de_rsu(banco, pki_dir):
    """Una OBU publicando directo en rsu/1/solicitudes (rol de servidor,
    no de OBU): el suscriptor legitimo de la RSU NO debe recibirlo."""
    ca_rsu, cert_rsu, key_rsu = _ruta(pki_dir, "rsu", "1")
    recibidos = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t06-rsu-1", protocol=mqtt.MQTTv5)
    sub.tls_set_context(construir_contexto_tls(ca_rsu, cert_rsu, key_rsu))
    sub.on_connect = lambda c, u, f, rc, props=None: c.subscribe("rsu/1/solicitudes", qos=1)
    sub.on_message = lambda c, u, msg: recibidos.append(msg.payload)
    sub.connect("localhost", banco.puerto, keepalive=10)
    sub.loop_start()
    try:
        assert _esperar(lambda: sub.is_connected(), 3.0)
        time.sleep(0.3)  # margen para que la suscripcion quede activa

        ca_obu, cert_obu, key_obu = _ruta(pki_dir, "obu", "obu-emu-01")
        pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t06-obu-emu-01", protocol=mqtt.MQTTv5)
        pub.tls_set_context(construir_contexto_tls(ca_obu, cert_obu, key_obu))
        pub.connect("localhost", banco.puerto, keepalive=10)
        pub.loop_start()
        try:
            assert _esperar(lambda: pub.is_connected(), 3.0)
            pub.publish("rsu/1/solicitudes", '{"tipo":"M1_falso"}', qos=1).wait_for_publish(timeout=3)
        finally:
            pub.loop_stop()
            pub.disconnect()

        time.sleep(1.0)
        assert recibidos == [], "la RSU 1 recibio un M1 publicado por una OBU -- la ACL no lo bloqueo"
    finally:
        sub.loop_stop()
        sub.disconnect()


def test_T07_obu_no_puede_publicar_en_posicion_de_otra_obu(banco, pki_dir):
    ca_srv, cert_srv, key_srv = _ruta(pki_dir, "servidor", None)
    recibidos = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t07-servidor-central", protocol=mqtt.MQTTv5)
    sub.tls_set_context(construir_contexto_tls(ca_srv, cert_srv, key_srv))
    sub.on_connect = lambda c, u, f, rc, props=None: c.subscribe("obu/obu-emu-02/posicion", qos=1)
    sub.on_message = lambda c, u, msg: recibidos.append(msg.payload)
    sub.connect("localhost", banco.puerto, keepalive=10)
    sub.loop_start()
    try:
        assert _esperar(lambda: sub.is_connected(), 3.0)
        time.sleep(0.3)

        ca_obu, cert_obu, key_obu = _ruta(pki_dir, "obu", "obu-emu-01")
        pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t07-obu-emu-01", protocol=mqtt.MQTTv5)
        pub.tls_set_context(construir_contexto_tls(ca_obu, cert_obu, key_obu))
        pub.connect("localhost", banco.puerto, keepalive=10)
        pub.loop_start()
        try:
            assert _esperar(lambda: pub.is_connected(), 3.0)
            pub.publish("obu/obu-emu-02/posicion", '{"tipo":"MP_falso"}', qos=1).wait_for_publish(timeout=3)
        finally:
            pub.loop_stop()
            pub.disconnect()

        time.sleep(1.0)
        assert recibidos == [], "obu-emu-01 publico en el tema de posicion de obu-emu-02 y el servidor lo recibio"
    finally:
        sub.loop_stop()
        sub.disconnect()


def test_T08_obu_no_puede_suscribirse_a_ruta_de_otra_obu(banco, pki_dir):
    ca_obu1, cert_obu1, key_obu1 = _ruta(pki_dir, "obu", "obu-emu-01")
    recibidos = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t08-obu-emu-01", protocol=mqtt.MQTTv5)
    sub.tls_set_context(construir_contexto_tls(ca_obu1, cert_obu1, key_obu1))
    sub.on_connect = lambda c, u, f, rc, props=None: c.subscribe("obu/obu-emu-02/ruta", qos=1)
    sub.on_message = lambda c, u, msg: recibidos.append(msg.payload)
    sub.connect("localhost", banco.puerto, keepalive=10)
    sub.loop_start()
    try:
        assert _esperar(lambda: sub.is_connected(), 3.0)
        time.sleep(0.3)

        ca_srv, cert_srv, key_srv = _ruta(pki_dir, "servidor", None)
        pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t08-servidor-central", protocol=mqtt.MQTTv5)
        pub.tls_set_context(construir_contexto_tls(ca_srv, cert_srv, key_srv))
        pub.connect("localhost", banco.puerto, keepalive=10)
        pub.loop_start()
        try:
            assert _esperar(lambda: pub.is_connected(), 3.0)
            pub.publish("obu/obu-emu-02/ruta", '{"tipo":"MR_real"}', qos=1).wait_for_publish(timeout=3)
        finally:
            pub.loop_stop()
            pub.disconnect()

        time.sleep(1.0)
        assert recibidos == [], "obu-emu-01 recibio la ruta de obu-emu-02 (deberia estar fuera de su ACL)"
    finally:
        sub.loop_stop()
        sub.disconnect()


def test_T09_rsu_no_puede_suscribirse_a_solicitudes_de_otra_rsu(banco, pki_dir):
    ca_rsu1, cert_rsu1, key_rsu1 = _ruta(pki_dir, "rsu", "1")
    recibidos = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t09-rsu-1", protocol=mqtt.MQTTv5)
    sub.tls_set_context(construir_contexto_tls(ca_rsu1, cert_rsu1, key_rsu1))
    sub.on_connect = lambda c, u, f, rc, props=None: c.subscribe("rsu/2/solicitudes", qos=1)
    sub.on_message = lambda c, u, msg: recibidos.append(msg.payload)
    sub.connect("localhost", banco.puerto, keepalive=10)
    sub.loop_start()
    try:
        assert _esperar(lambda: sub.is_connected(), 3.0)
        time.sleep(0.3)

        ca_srv, cert_srv, key_srv = _ruta(pki_dir, "servidor", None)
        pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t09-servidor-central", protocol=mqtt.MQTTv5)
        pub.tls_set_context(construir_contexto_tls(ca_srv, cert_srv, key_srv))
        pub.connect("localhost", banco.puerto, keepalive=10)
        pub.loop_start()
        try:
            assert _esperar(lambda: pub.is_connected(), 3.0)
            pub.publish("rsu/2/solicitudes", '{"tipo":"M1_real"}', qos=1).wait_for_publish(timeout=3)
        finally:
            pub.loop_stop()
            pub.disconnect()

        time.sleep(1.0)
        assert recibidos == [], "la RSU 1 recibio una solicitud dirigida a la RSU 2"
    finally:
        sub.loop_stop()
        sub.disconnect()


def test_T10_m2_falso_pasa_el_broker_pero_el_servidor_lo_ignora(banco, pki_dir):
    """Limitacion CONOCIDA y documentada en mosquitto_acl.conf: la regla
    `pattern write servidor/central/respuestas` no tiene %c ni %u, asi
    que cualquier cliente autenticado puede publicar ahi -- el broker lo
    deja pasar. El impacto es bajo porque
    servidor/gestor_mision.py::procesar_m2 ignora cualquier id_solicitud
    que no este en seguimiento. Esta prueba demuestra AMBAS cosas, no
    solo la del broker."""
    ca_srv, cert_srv, key_srv = _ruta(pki_dir, "servidor", None)
    recibidos = []
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t10-servidor-central", protocol=mqtt.MQTTv5)
    sub.tls_set_context(construir_contexto_tls(ca_srv, cert_srv, key_srv))
    sub.on_connect = lambda c, u, f, rc, props=None: c.subscribe("servidor/central/respuestas", qos=1)
    sub.on_message = lambda c, u, msg: recibidos.append(msg.payload)
    sub.connect("localhost", banco.puerto, keepalive=10)
    sub.loop_start()
    try:
        assert _esperar(lambda: sub.is_connected(), 3.0)
        time.sleep(0.3)

        ca_obu, cert_obu, key_obu = _ruta(pki_dir, "obu", "obu-emu-01")
        pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t10-obu-emu-01", protocol=mqtt.MQTTv5)
        pub.tls_set_context(construir_contexto_tls(ca_obu, cert_obu, key_obu))
        pub.connect("localhost", banco.puerto, keepalive=10)
        pub.loop_start()
        try:
            assert _esperar(lambda: pub.is_connected(), 3.0)
            pub.publish("servidor/central/respuestas", '{"id_solicitud":"m2-falso-de-obu"}',
                       qos=1).wait_for_publish(timeout=3)
        finally:
            pub.loop_stop()
            pub.disconnect()

        assert _esperar(lambda: len(recibidos) == 1, 3.0), (
            "la limitacion conocida de la ACL ya no se reproduce -- revisar si "
            "mosquitto_acl.conf cambio (si es asi, esta prueba y su comentario quedaron obsoletos)"
        )
    finally:
        sub.loop_stop()
        sub.disconnect()

    # El servidor REAL ignora el M2 falso (id_solicitud fuera de seguimiento).
    from servidor.gestor_mision import GestorMision
    import networkx as nx
    gestor = GestorMision(nx.DiGraph(), [], enviar_m1=lambda *a: None, enviar_m3=lambda *a: None,
                          enviar_mr=lambda *a: None, enviar_me=lambda *a: None)
    gestor.procesar_m2({"id_solicitud": "m2-falso-de-obu", "estado": "concedida", "fase": "verde"})  # no debe lanzar


# --- T11: flujo legitimo de punta a punta --------------------------------

def test_T11_flujo_legitimo_de_punta_a_punta(banco, pki_dir, tmp_path):
    """MI -> MR y M1 -> M2 con TLS 1.3 + mTLS real: reusa el runner de
    campana (ya probado en S1) para no reimplementar el lanzamiento de
    servidor/RSU/OBU -- 1 repeticion del escenario 'lazo', factor 4."""
    # Import por ruta, no por sys.path + nombre: scripts/analisis/ TAMBIEN
    # tiene un modulo "lazo_centralizado" y tests/test_lazo_centralizado.py
    # ya lo cachea con ese nombre en sys.modules -- ver
    # tests/test_campana_runner.py, que resuelve el mismo choque igual.
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "campana_lazo_centralizado_s3", RAIZ / "scripts" / "campanas" / "lazo_centralizado.py",
    )
    campana = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(campana)

    rep_dir = tmp_path / "t11"
    rep_dir.mkdir()
    registro_path = campana.FIXTURES / campana.ESCENARIOS["lazo"]["registro"]
    trayectoria = campana.FIXTURES / campana.ESCENARIOS["lazo"]["obus"][0][1]

    ctrl, agent = campana._lanzar_local(rep_dir, pki_dir, "localhost", banco.puerto)
    try:
        servidor = campana._lanzar_servidor(rep_dir, "recta", registro_path, "localhost", banco.puerto, pki_dir)
        try:
            campana._correr_obus(rep_dir, [("obu-lazo", "trayectoria_lazo_base.csv")],
                                 [trayectoria], "localhost", banco.puerto, 4.0, pki_dir)
        finally:
            campana._detener(servidor)
    finally:
        campana._detener(ctrl, agent)

    servidor_log = (rep_dir / "servidor.log").read_text(encoding="utf-8", errors="replace")
    agent_log = (rep_dir / "agent.log").read_text(encoding="utf-8", errors="replace")
    obu_log = (rep_dir / "obu-lazo.log").read_text(encoding="utf-8", errors="replace")
    assert "mTLS habilitado" in servidor_log
    assert "mTLS habilitado" in agent_log
    assert "mTLS habilitado" in obu_log
    # Sin tildes en las aserciones de texto: el stdout de los subprocesos
    # en Windows no siempre sale en UTF-8 (se leyó con errors="replace"
    # arriba), así que "misión" podría llegar como "misi?n"/"misi<?>n".
    assert "armada" in obu_log and "MR <- ruta de" in obu_log, obu_log
    assert "estado=concedida" in obu_log, "la RSU nunca concedio la solicitud (M1->M2)"
    assert "MF ->" in obu_log, "la OBU no llego a desarmar la mision (destino)"

    eventos_obu = (rep_dir / "eventos_obu-lazo.csv").read_text(encoding="utf-8", errors="replace")
    for evento in ("MI_tx", "MR_rx", "ME_rx", "MF_tx"):
        assert evento in eventos_obu, f"falta el evento {evento} en eventos_obu-lazo.csv"


# --- T14-T16: SNMPv3 (agente local, sin la Pi) ----------------------------

@pytest.fixture()
def agente_snmp():
    """Motor SNMPv3 minimo, con las MISMAS credenciales reales de
    agent/rsu_middleware.py (USER_NAME/AUTH_KEY/PRIV_KEY, auth SHA-256
    RFC 7860 + priv AES-128 -- corregido: hasta antes de esta prueba, el
    codigo usaba SHA-1 (config.usmHMACSHAAuthProtocol) a pesar de que el
    diseño de seguridad ya habia adoptado SHA-256; ver
    redaccion/capitulo4_seguridad.tex para el detalle de la correccion).
    T15 usa SHA-1 como protocolo "equivocado" -- es justo el que se
    informo como rechazado y es el que de verdad queda obsoleto con este
    cambio.

    Motor SIN la mision/MIB completa de rsu_middleware.py (no hace falta
    para probar el rechazo a nivel USM), en un hilo propio, puerto
    libre."""
    import threading
    from pysnmp.entity import config, engine
    from pysnmp.entity.rfc3413 import cmdrsp
    from pysnmp.entity.rfc3413.context import SnmpContext
    from agent.rsu_middleware import AUTH_KEY, PRIV_KEY, USER_NAME, NTCIP_ASC_OID

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]

    snmp_engine = engine.SnmpEngine()
    config.addTransport(
        snmp_engine, config.udp.domainName,
        config.udp.UdpAsyncioTransport().openServerMode(("127.0.0.1", puerto)),
    )
    config.addV3User(snmp_engine, USER_NAME, config.usmHMAC192SHA256AuthProtocol, AUTH_KEY,
                     config.usmAesCfb128Protocol, PRIV_KEY)
    config.addVacmUser(snmp_engine, 3, USER_NAME, "authPriv", readSubTree=NTCIP_ASC_OID)
    cmdrsp.GetCommandResponder(snmp_engine, SnmpContext(snmp_engine))

    hilo = threading.Thread(target=snmp_engine.transportDispatcher.runDispatcher, daemon=True)
    hilo.start()
    time.sleep(0.3)
    yield puerto
    snmp_engine.transportDispatcher.closeDispatcher()


def _snmp_get(puerto: int, *, usuario, auth_key=None, priv_key=None, auth_proto=None, priv_proto=None):
    from pysnmp.hlapi import (
        ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, UsmUserData, getCmd,
    )
    from agent.rsu_middleware import NTCIP_ASC_OID

    usm = UsmUserData(usuario, authKey=auth_key, privKey=priv_key, authProtocol=auth_proto, privProtocol=priv_proto)
    engine_cliente = SnmpEngine()
    iterador = getCmd(
        engine_cliente, usm, UdpTransportTarget(("127.0.0.1", puerto), timeout=2, retries=0),
        ContextData(), ObjectType(ObjectIdentity(NTCIP_ASC_OID + (1,))),
    )
    error_indication, error_status, _error_index, _var_binds = next(iterador)
    iterador.close()
    return error_indication, error_status


def test_T14_snmp_sin_autenticacion_se_rechaza(agente_snmp):
    from pysnmp.hlapi import usmNoAuthProtocol, usmNoPrivProtocol
    from agent.rsu_middleware import USER_NAME

    error_indication, error_status = _snmp_get(
        agente_snmp, usuario=USER_NAME, auth_proto=usmNoAuthProtocol, priv_proto=usmNoPrivProtocol,
    )
    assert error_indication or error_status, "una consulta noAuthNoPriv deberia ser rechazada (el agente exige authPriv)"


def test_T15_snmp_protocolo_de_autenticacion_equivocado_se_rechaza(agente_snmp):
    from pysnmp.hlapi import usmHMACSHAAuthProtocol, usmAesCfb128Protocol
    from agent.rsu_middleware import AUTH_KEY, PRIV_KEY, USER_NAME

    # SHA-1 (usmHMACSHAAuthProtocol): el protocolo anterior, ya no
    # configurado -- este es justo el caso que se informo como
    # rechazado (un gestor con SHA-1 no debe poder operar el agente).
    error_indication, error_status = _snmp_get(
        agente_snmp, usuario=USER_NAME, auth_key=AUTH_KEY, priv_key=PRIV_KEY,
        auth_proto=usmHMACSHAAuthProtocol, priv_proto=usmAesCfb128Protocol,
    )
    assert error_indication or error_status, "un gestor con SHA-1 (protocolo anterior) deberia rechazarse"


def test_T16_snmp_clave_equivocada_se_rechaza(agente_snmp):
    from pysnmp.hlapi import usmHMAC192SHA256AuthProtocol, usmAesCfb128Protocol
    from agent.rsu_middleware import USER_NAME

    error_indication, error_status = _snmp_get(
        agente_snmp, usuario=USER_NAME, auth_key="claveEquivocada999", priv_key="claveEquivocada999",
        auth_proto=usmHMAC192SHA256AuthProtocol, priv_proto=usmAesCfb128Protocol,
    )
    assert error_indication or error_status, "una clave de autenticacion equivocada deberia rechazarse"


def test_T17_snmp_sha256_y_aes128_correctos_hacen_get(agente_snmp):
    """Prueba positiva (P1 de prompt_cierre_repo_2026-11-02.md): con el
    protocolo y las credenciales reales (SHA-256 + AES-128), el GET pasa
    la capa de seguridad USM -- sin error_indication ni error_status, sin
    importar si el OID en si tiene un objeto registrado (este motor no
    registra la MIB completa, ver el docstring de agente_snmp)."""
    from pysnmp.hlapi import usmHMAC192SHA256AuthProtocol, usmAesCfb128Protocol
    from agent.rsu_middleware import AUTH_KEY, PRIV_KEY, USER_NAME

    error_indication, error_status = _snmp_get(
        agente_snmp, usuario=USER_NAME, auth_key=AUTH_KEY, priv_key=PRIV_KEY,
        auth_proto=usmHMAC192SHA256AuthProtocol, priv_proto=usmAesCfb128Protocol,
    )
    assert not error_indication, f"se esperaba exito a nivel USM; llego {error_indication}"
    assert not error_status, f"se esperaba exito a nivel USM; llego errorStatus={error_status}"
