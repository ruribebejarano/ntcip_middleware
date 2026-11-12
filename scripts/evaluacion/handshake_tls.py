#!/usr/bin/env python3
"""OE3 (Fase 4, prueba 3): costo de establecer la conexión segura con el
broker: duración y bytes del handshake TLS con autenticación mutua.

Corre en el CLIENTE (la RSU, para medir sobre 4G o Wi-Fi) contra el broker
de la laptop. Casos, intercalados en cada ronda para que la variación del
enlace afecte a todos por igual:
  tcp        TCP + CONNECT/CONNACK de MQTT sin TLS (línea base; broker 1883)
  tls13      TLS 1.3 + mTLS, handshake completo (broker 8883)
  tls13_res  TLS 1.3 + mTLS reanudando la sesión (ticket PSK de la
             conexión tls13 anterior de la misma ronda)
  tls12      TLS 1.2 + mTLS, handshake completo (listener temporal 8884,
             tls_version tlsv1.2; solo para esta comparación)
El TLS se hace sobre MemoryBIO: los bytes de cada sentido se cuentan
exactos al nivel de la carga TCP (sin encabezados IP/TCP).

Tiempos (perf_counter del cliente): t_tcp (connect), t_tls (fin del
handshake TLS desde el connect), t_mqtt (CONNACK desde el fin del TLS), y
t_total. Bytes: subida/bajada durante el handshake y durante CONNECT/CONNACK.

Salida: CSV en --salida (por defecto resultados/evaluacion/<ts>_handshake_<etiqueta>/handshake.csv).

Uso (en la Pi, raíz del repo):
  python3 scripts/evaluacion/handshake_tls.py --host 100.121.77.97 --etiqueta 4g --rondas 30 \
      --ca deploy/pki/ca/ca.crt --cert deploy/pki/rsu/rsu-1.crt --key deploy/pki/rsu/rsu-1.key
"""
from __future__ import annotations

import argparse
import csv
import socket
import ssl
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent


def _connect_mqtt5(client_id: str) -> bytes:
    """Paquete CONNECT de MQTT 5 mínimo (clean start, keepalive 30 s)."""
    cid = client_id.encode()
    variable = b"\x00\x04MQTT\x05\x02\x00\x1e\x00"  # nombre, versión 5, flags clean start, keepalive, props=0
    payload = len(cid).to_bytes(2, "big") + cid
    resto = variable + payload
    return b"\x10" + bytes([len(resto)]) + resto


def _leer_connack(recv) -> bytes:
    datos = b""
    while len(datos) < 2 or len(datos) < 2 + datos[1]:
        trozo = recv()
        if not trozo:
            raise ConnectionError("conexión cerrada antes del CONNACK")
        datos += trozo
    if datos[0] >> 4 != 2:
        raise ConnectionError(f"se esperaba CONNACK, llegó {datos[0]:#x}")
    if datos[3] != 0:
        raise ConnectionError(f"CONNACK con código {datos[3]}")
    return datos


def caso_tcp(host, port, cid):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    t1 = time.perf_counter()
    pkt = _connect_mqtt5(cid)
    s.sendall(pkt)
    ack = _leer_connack(lambda: s.recv(4096))
    t3 = time.perf_counter()
    s.sendall(b"\xe0\x00")
    s.close()
    return {"t_tcp_ms": (t1 - t0) * 1e3, "t_tls_ms": 0.0, "t_mqtt_ms": (t3 - t1) * 1e3, "t_total_ms": (t3 - t0) * 1e3,
            "hs_sub": 0, "hs_baj": 0, "mqtt_sub": len(pkt), "mqtt_baj": len(ack), "reanudada": False, "version": "-"}


def caso_tls(host, port, cid, ctx, sesion=None):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    t1 = time.perf_counter()
    entrada, salida = ssl.MemoryBIO(), ssl.MemoryBIO()
    obj = ctx.wrap_bio(entrada, salida, server_hostname=host, session=sesion)
    sub = baj = 0

    def vaciar():
        nonlocal sub
        d = salida.read()
        if d:
            s.sendall(d)
            sub += len(d)

    def recibir():
        nonlocal baj
        d = s.recv(65536)
        baj += len(d)
        entrada.write(d)
        return d

    while True:
        try:
            obj.do_handshake()
            break
        except ssl.SSLWantReadError:
            vaciar()
            if not recibir():
                raise ConnectionError("cerrado durante el handshake")
    vaciar()
    t2 = time.perf_counter()
    hs_sub, hs_baj = sub, baj
    obj.write(_connect_mqtt5(cid))
    vaciar()
    buf = b""
    while True:
        try:
            buf += obj.read(4096)
        except ssl.SSLWantReadError:
            pass
        if len(buf) >= 2 and len(buf) >= 2 + buf[1]:
            break
        vaciar()
        if not recibir():
            raise ConnectionError("cerrado antes del CONNACK")
    _leer_connack(lambda b=buf: b)
    t3 = time.perf_counter()
    # En TLS 1.3 los tickets de sesión llegan tras el handshake: se drena un
    # instante para que obj.session quede utilizable en la reanudación.
    s.settimeout(0.3)
    try:
        while recibir():
            try:
                obj.read(4096)
            except ssl.SSLWantReadError:
                pass
    except (socket.timeout, TimeoutError):
        pass
    res = {"t_tcp_ms": (t1 - t0) * 1e3, "t_tls_ms": (t2 - t1) * 1e3, "t_mqtt_ms": (t3 - t2) * 1e3,
           "t_total_ms": (t3 - t0) * 1e3, "hs_sub": hs_sub, "hs_baj": hs_baj, "mqtt_sub": sub - hs_sub,
           "mqtt_baj": baj - hs_baj, "reanudada": obj.session_reused, "version": obj.version()}
    sesion_nueva = obj.session
    try:
        obj.write(b"\xe0\x00")
        vaciar()
    except ssl.SSLError:
        pass
    s.close()
    return res, sesion_nueva


def contexto(ca, cert, key, version):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ctx.maximum_version = version
    ctx.load_verify_locations(cafile=ca)
    ctx.load_cert_chain(cert, key)
    return ctx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--puerto-tcp", type=int, default=1883)
    ap.add_argument("--puerto-tls13", type=int, default=8883)
    ap.add_argument("--puerto-tls12", type=int, default=8884)
    ap.add_argument("--ca", required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--rondas", type=int, default=30)
    ap.add_argument("--etiqueta", required=True)
    ap.add_argument("--client-id", default="hs-medicion")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = Path(args.salida) if args.salida else (
        RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_handshake_{args.etiqueta}")
    salida.mkdir(parents=True, exist_ok=True)
    c13 = contexto(args.ca, args.cert, args.key, ssl.TLSVersion.TLSv1_3)
    c12 = contexto(args.ca, args.cert, args.key, ssl.TLSVersion.TLSv1_2)
    filas = []
    for r in range(1, args.rondas + 1):
        cid = f"{args.client_id}-{r}"
        intentos = [("tcp", lambda: (caso_tcp(args.host, args.puerto_tcp, cid), None))]
        intentos.append(("tls13", lambda: caso_tls(args.host, args.puerto_tls13, cid, c13)))
        intentos.append(("tls12", lambda: caso_tls(args.host, args.puerto_tls12, cid, c12)))
        sesion13 = None
        for nombre, f in intentos:
            try:
                res, ses = f()
                if nombre == "tls13":
                    sesion13 = ses
                filas.append({"ronda": r, "caso": nombre, **res})
            except (OSError, ssl.SSLError, ConnectionError) as exc:
                filas.append({"ronda": r, "caso": nombre, "error": str(exc)})
            time.sleep(0.5)
        if sesion13 is not None:
            try:
                res, _ = caso_tls(args.host, args.puerto_tls13, cid, c13, sesion=sesion13)
                filas.append({"ronda": r, "caso": "tls13_res", **res})
            except (OSError, ssl.SSLError, ConnectionError) as exc:
                filas.append({"ronda": r, "caso": "tls13_res", "error": str(exc)})
        print(f"ronda {r}: " + ", ".join(f"{f['caso']}={f.get('t_total_ms', float('nan')):.1f} ms"
                                         for f in filas if f["ronda"] == r), flush=True)
        time.sleep(1.0)
    campos = ["ronda", "caso", "t_tcp_ms", "t_tls_ms", "t_mqtt_ms", "t_total_ms", "hs_sub", "hs_baj",
              "mqtt_sub", "mqtt_baj", "reanudada", "version", "error"]
    with (salida / "handshake.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"Salida en {salida}")


if __name__ == "__main__":
    main()
