#!/usr/bin/env python3
"""OE3/OE4 (Fase 4, prueba 5): bytes por mensaje con y sin TLS, y consumo de
datos de una RSU en reposo y por misión.

Un proxy TCP (este mismo proceso) se interpone entre cada cliente y el
broker, con un puerto por rol (OBU 8891, servidor 8892, RSU 8893), y cuenta
los bytes de cada sentido al nivel de la carga TCP (sin encabezados IP/TCP):
  - sin TLS: lee los paquetes MQTT (tipo, tema y, en PUBLISH, el campo
    "tipo" del JSON: MI, MF, MP, MR, ME, M1, M2, M3) y suma sus bytes;
  - con TLS: lee los encabezados de registro TLS (5 bytes en claro) y cuenta
    registros y bytes; el tamaño de cada registro de datos de aplicación es
    el del paquete MQTT más 22 bytes (encabezado 5 + tipo de contenido 1 +
    etiqueta AES-GCM 16), lo que el script verifica.
Cada repetición es el escenario `lazo` de la campaña (una misión que cruza
la RSU). Al final se deja a la RSU conectada y en reposo --reposo-s
segundos para medir el keepalive (PINGREQ/PINGRESP cada 30 s).

Salida: resultados/evaluacion/<AAAAMMDD-HHMMSS>_bytes_<tls|sin-tls>/ con
paquetes.csv (un paquete o registro por fila) y resumen.json.

Uso:
  .venv/Scripts/python.exe scripts/evaluacion/bytes_mensaje.py --tls          (broker en 8883)
  .venv/Scripts/python.exe scripts/evaluacion/bytes_mensaje.py                 (broker en 1883)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.campanas.lazo_centralizado import (  # noqa: E402
    CONTROLLER_PORT, ESCENARIOS, FIXTURES, SNMP_PORT, _correr_obus, _detener, _esperar_puertos_libres,
    _lanzar_local, _lanzar_servidor, _trayectoria_con_ruido)

TLS_DIR = RAIZ / "deploy" / "pki"
PUERTOS = {"obu": 8891, "servidor": 8892, "rsu": 8893}
TIPOS_MQTT = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 8: "SUBSCRIBE", 9: "SUBACK",
              12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}
SOBRECARGA_TLS13 = 22


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    mult, valor = 1, 0
    while True:
        b = buf[i]
        valor += (b & 0x7F) * mult
        i += 1
        if not b & 0x80:
            return valor, i
        mult *= 128


class Contador:
    def __init__(self, tls: bool) -> None:
        self.tls = tls
        self.filas: list[tuple] = []  # (ts_ns, rol, sentido, clase, bytes, conexion)
        self.lock = threading.Lock()

    def registrar(self, rol, sentido, clase, n, con):
        with self.lock:
            self.filas.append((time.time_ns(), rol, sentido, clase, n, con))


class Flujo:
    """Separa un sentido de una conexión en paquetes MQTT o registros TLS."""

    def __init__(self, cont: Contador, rol: str, sentido: str, con: int) -> None:
        self.c, self.rol, self.sentido, self.con, self.buf = cont, rol, sentido, con, b""

    def alimentar(self, datos: bytes) -> None:
        self.buf += datos
        while True:
            if self.c.tls:
                if len(self.buf) < 5:
                    return
                largo = int.from_bytes(self.buf[3:5], "big")
                total = 5 + largo
                if len(self.buf) < total:
                    return
                clase = {20: "TLS_ccs", 21: "TLS_alerta", 22: "TLS_handshake", 23: "TLS_datos"}.get(
                    self.buf[0], f"TLS_{self.buf[0]}")
            else:
                if len(self.buf) < 2:
                    return
                try:
                    largo, ini = _varint(self.buf, 1)
                except IndexError:
                    return
                total = ini + largo
                if len(self.buf) < total:
                    return
                tipo = self.buf[0] >> 4
                clase = TIPOS_MQTT.get(tipo, f"MQTT_{tipo}")
                if tipo == 3:
                    clase = self._clase_publish(self.buf[:total], ini)
            self.c.registrar(self.rol, self.sentido, clase, total, self.con)
            self.buf = self.buf[total:]

    @staticmethod
    def _clase_publish(p: bytes, i: int) -> str:
        qos = (p[0] >> 1) & 3
        lt = int.from_bytes(p[i:i + 2], "big")
        tema = p[i + 2:i + 2 + lt].decode("utf-8", "replace")
        j = i + 2 + lt + (2 if qos else 0)
        lp, j = _varint(p, j)  # propiedades MQTT 5
        carga = p[j + lp:]
        try:
            return f"PUBLISH_{json.loads(carga).get('tipo') or tema}"
        except ValueError:
            return f"PUBLISH_{tema}"


async def _proxy(rol: str, destino_puerto: int, cont: Contador, listo: threading.Event) -> None:
    contador_con = [0]

    async def manejar(lector, escritor):
        contador_con[0] += 1
        con = contador_con[0]
        r2, w2 = await asyncio.open_connection("127.0.0.1", destino_puerto)

        async def bombear(a, b, sentido):
            flujo = Flujo(cont, rol, sentido, con)
            try:
                while datos := await a.read(65536):
                    flujo.alimentar(datos)
                    b.write(datos)
                    await b.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                b.close()

        await asyncio.gather(bombear(lector, w2, "subida"), bombear(r2, escritor, "bajada"))

    srv = await asyncio.start_server(manejar, "127.0.0.1", PUERTOS[rol])
    listo.set()
    async with srv:
        await srv.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--repeticiones", type=int, default=5)
    ap.add_argument("--reposo-s", type=float, default=300.0)
    args = ap.parse_args()
    broker = 8883 if args.tls else 1883
    tls_dir = TLS_DIR if args.tls else None
    salida = RAIZ / "resultados" / "evaluacion" / (
        f"{datetime.now():%Y%m%d-%H%M%S}_bytes_{'tls' if args.tls else 'sin-tls'}")
    salida.mkdir(parents=True)
    cont = Contador(args.tls)
    bucle = asyncio.new_event_loop()
    listos = [threading.Event() for _ in PUERTOS]
    hilo = threading.Thread(target=lambda: (asyncio.set_event_loop(bucle), bucle.run_until_complete(
        asyncio.gather(*[_proxy(r, broker, cont, e) for r, e in zip(PUERTOS, listos)]))), daemon=True)
    hilo.start()
    for e in listos:
        e.wait(5)

    esc = ESCENARIOS["lazo"]
    ventanas = []
    for i in range(1, args.repeticiones + 1):
        rep = salida / f"rep_{i:02d}"
        rep.mkdir()
        obu_id = f"obu-bytes-r{i:02d}"
        tray = rep / "trayectoria.csv"
        _trayectoria_con_ruido(FIXTURES / esc["obus"][0][1], tray, 900 + i, 5.0)
        t0 = time.time_ns()
        ctrl, agent = _lanzar_local(rep, tls_dir, "127.0.0.1", PUERTOS["rsu"])
        servidor = _lanzar_servidor(rep, esc["grafo"], FIXTURES / esc["registro"], "127.0.0.1",
                                    PUERTOS["servidor"], tls_dir)
        time.sleep(random.Random(900 + i).uniform(0, 21))
        t_mision = time.time_ns()
        _correr_obus(rep, [(obu_id, "")], [tray], "127.0.0.1", PUERTOS["obu"], 1.0, tls_dir)
        time.sleep(3.0)
        t_fin_mision = time.time_ns()
        if i == args.repeticiones and args.reposo_s > 0:
            print(f"reposo de {args.reposo_s:.0f} s con la RSU conectada", flush=True)
            time.sleep(args.reposo_s)
        t_fin = time.time_ns()
        _detener(servidor, ctrl, agent)
        _esperar_puertos_libres([(CONTROLLER_PORT, "tcp"), (SNMP_PORT, "udp")])
        ventanas.append({"rep": i, "t0": t0, "t_mision": t_mision, "t_fin_mision": t_fin_mision, "t_fin": t_fin})
        print(f"rep {i} lista", flush=True)
    time.sleep(1.0)

    with cont.lock:
        filas = list(cont.filas)
    with (salida / "paquetes.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_ns", "rol", "sentido", "clase", "bytes", "conexion"])
        w.writerows(filas)

    # --- resumen -----------------------------------------------------------
    def suma(rol, desde, hasta):
        return sum(n for ts, r, _s, _c, n, _k in filas if r == rol and desde <= ts < hasta)

    por_clase = defaultdict(list)
    for ts, r, s, c, n, _k in filas:
        por_clase[(r, s, c)].append(n)
    resumen = {
        "tls": args.tls, "repeticiones": args.repeticiones,
        "por_clase": {f"{r}|{s}|{c}": {"n": len(v), "bytes_min": min(v), "bytes_max": max(v),
                                       "bytes_mediana": sorted(v)[len(v) // 2]}
                      for (r, s, c), v in sorted(por_clase.items())},
        "por_repeticion": [{"rep": v["rep"], **{f"{rol}_mision": suma(rol, v["t_mision"], v["t_fin_mision"])
                                                for rol in PUERTOS},
                            **{f"{rol}_total": suma(rol, v["t0"], v["t_fin"]) for rol in PUERTOS}}
                           for v in ventanas],
    }
    ult = ventanas[-1]
    if args.reposo_s > 0:
        b = suma("rsu", ult["t_fin_mision"], ult["t_fin"])
        resumen["rsu_reposo"] = {"segundos": (ult["t_fin"] - ult["t_fin_mision"]) / 1e9, "bytes": b,
                                 "bytes_por_hora": b * 3600e9 / (ult["t_fin"] - ult["t_fin_mision"])}
    (salida / "resumen.json").write_text(json.dumps(resumen, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen["por_repeticion"], indent=1))
    print(resumen.get("rsu_reposo"))
    print(f"Salida en {salida}")


if __name__ == "__main__":
    main()
