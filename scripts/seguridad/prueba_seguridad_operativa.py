#!/usr/bin/env python3
"""Pruebas de seguridad operativa: OBU comprometida y saturación del broker,
con la respuesta en capas del servidor y del operador de la central
(servidor/seguridad.py, scripts/seguridad/operador_central.py,
docs/PRUEBA_SEGURIDAD_OPERATIVA.md).

Corre en esta máquina (condición local, TLS 1.3 + mTLS) con un broker
PROPIO en 127.0.0.1:--puerto (por defecto 8884), con la ACL vigente de
scripts/seguridad/mosquitto_acl.conf: no choca con el broker de la laptop
ni con el agente de la Pi.

Escenarios (--escenario):

  mision_falsa  Una OBU con certificado válido arma una misión que no
                existe y recorre una trayectoria plausible (la de `lazo`).
                Técnicamente no se distingue de una real: la detecta la
                verificación con el despacho. Variantes: el operador
                responde tras --retardo-s; o confirmación obligatoria
                (--confirmacion-s > 0) sin operador.
  clon          El mismo certificado en dos lugares: las posiciones
                alternan entre la trayectoria real y un punto a
                --distancia-clon-m. Lo detecta el servidor (salto de
                posición). Variantes: --politica alertar + operador, o
                --politica suspender (automático).
  inundacion    Una misión legítima (`lazo`) mientras otra OBU válida
                publica MP a --hz. Mide cuánto se degrada el lazo legítimo.
                Variantes: sin respuesta (--sin-operador, --politica
                alertar), automático (--politica suspender), o operador.
  base          Solo la misión legítima, sin atacante (referencia).

Cada corrida queda en resultados/seguridad/<AAAAMMDD-HHMMSS>_<escenario>_<etiqueta>/
con rep_XX/ (eventos de todos los nodos y logs) y config.json.
Análisis: python scripts/seguridad/analisis_seguridad_operativa.py --dir <corrida>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import desplazar  # noqa: E402
from scripts.campanas import lazo_centralizado as campana  # noqa: E402

FIXTURES = RAIZ / "scripts" / "campanas" / "fixtures"
BASE_LAZO = FIXTURES / "trayectoria_lazo_base.csv"
REGISTRO = FIXTURES / "registro_rsu_1.json"
PY = sys.executable


def _mosquitto() -> str:
    for cand in (shutil.which("mosquitto"), r"C:\Program Files (x86)\Mosquitto\mosquitto.exe",
                 r"C:\Program Files\Mosquitto\mosquitto.exe", "/usr/sbin/mosquitto"):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("No se encontró mosquitto")


def _lanzar_broker(corrida: Path, puerto: int, tls_dir: Path) -> subprocess.Popen:
    pki = tls_dir.resolve().as_posix()
    conf = corrida / "mosquitto_prueba.conf"
    conf.write_text("\n".join([
        "per_listener_settings false",
        f"listener {puerto} 127.0.0.1",
        f"cafile {pki}/ca/ca.crt",
        f"certfile {pki}/servidor/servidor-central.crt",
        f"keyfile {pki}/servidor/servidor-central.key",
        "tls_version tlsv1.3",
        "require_certificate true",
        "use_identity_as_username true",
        f"crlfile {pki}/ca/ca.crl",
        "allow_anonymous false",
        f"acl_file {(RAIZ / 'scripts' / 'seguridad' / 'mosquitto_acl.conf').as_posix()}",
        "set_tcp_nodelay true",
        "persistence false",
        "log_dest stdout",
        "log_type error", "log_type warning", "log_type notice", "log_type information", ""]), encoding="utf-8")
    log = corrida / "broker.log"
    p = subprocess.Popen([_mosquitto(), "-c", str(conf)], stdout=log.open("w", encoding="utf-8"),
                         stderr=subprocess.STDOUT, cwd=RAIZ)
    time.sleep(1.5)
    if p.poll() is not None:
        raise SystemExit(f"El broker de la prueba no arrancó: ver {log}")
    return p


def _leer(base: Path) -> list[dict]:
    with base.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _escribir(filas: list[dict], destino: Path) -> None:
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh"])
        for i, f in enumerate(filas):
            w.writerow([f"{float(i):.1f}", f["lat"], f["lon"], f["rumbo_deg"], f["velocidad_kmh"]])


def _trayectoria_clon(base: Path, destino: Path, desde_s: int, distancia_m: float) -> None:
    """Desde la muestra `desde_s`, una de cada dos posiciones viene del
    "otro" dispositivo con el mismo certificado, a `distancia_m`."""
    filas = _leer(base)
    out = []
    for i, f in enumerate(filas):
        g = dict(f)
        if i >= desde_s and i % 2 == 1:
            lat, lon = desplazar(float(f["lat"]), float(f["lon"]), 90.0, distancia_m)
            g["lat"], g["lon"] = f"{lat:.7f}", f"{lon:.7f}"
        out.append(g)
    _escribir(out, destino)


def _trayectoria_inundacion(base: Path, destino: Path, n: int) -> None:
    """`n` muestras que van y vuelven sobre los primeros 300 m de la recta
    (lejos de la RSU: la misión del atacante no pide prioridad y no compite
    con la legítima). Sin saltos: pasos de ~10 m."""
    filas = _leer(base)[:30]
    ida_vuelta = filas + filas[-2:0:-1]
    _escribir([ida_vuelta[i % len(ida_vuelta)] for i in range(n)], destino)


def _lanzar_obu(rep_dir: Path, obu_id: str, tray: Path, puerto: int, tls_dir: Path, factor: float) -> subprocess.Popen:
    ca, cert, key = campana._rutas_tls(tls_dir, "obu", obu_id)
    log = (rep_dir / f"{obu_id}.log").open("w", encoding="utf-8")
    return subprocess.Popen([PY, "-u", str(RAIZ / "gateway" / "obu_emulada.py"),
                             "--broker-host", "127.0.0.1", "--broker-port", str(puerto),
                             "--trayectoria", str(tray), "--factor", str(factor), "--obu-id", obu_id,
                             "--tls-ca", ca, "--tls-cert", cert, "--tls-key", key],
                            stdout=log, stderr=subprocess.STDOUT, cwd=RAIZ,
                            env=dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir)))


def _lanzar_operador(rep_dir: Path, puerto: int, tls_dir: Path, retardo: float, confirma: list[str],
                     sin_accion: bool) -> subprocess.Popen:
    cmd = [PY, "-u", str(RAIZ / "scripts" / "seguridad" / "operador_central.py"),
           "--broker-port", str(puerto), "--tls", str(tls_dir), "--retardo-s", str(retardo),
           "--despacho-confirma", ",".join(confirma)]
    if sin_accion:
        cmd.append("--sin-accion")
    log = rep_dir / "operador.log"
    p = subprocess.Popen(cmd, stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT, cwd=RAIZ,
                         env=dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir)))
    if not campana._esperar_en_log(log, "[operador] conectado"):
        campana._detener(p)
        raise SystemExit(f"El operador no se conectó: ver {log}")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escenario", required=True, choices=["mision_falsa", "clon", "inundacion", "base"])
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--puerto", type=int, default=8884)
    ap.add_argument("--tls", default=str(RAIZ / "deploy" / "pki"))
    ap.add_argument("--politica", choices=["alertar", "suspender"], default="alertar")
    ap.add_argument("--retardo-s", type=float, default=30.0, help="respuesta humana emulada del operador")
    ap.add_argument("--sin-operador", action="store_true", help="el operador solo registra las alertas")
    ap.add_argument("--confirmacion-s", type=float, default=0.0, help="SEG_CONFIRMACION_S del servidor")
    ap.add_argument("--hz", type=float, default=50.0, help="tasa de MP del atacante (inundacion)")
    ap.add_argument("--distancia-clon-m", type=float, default=3000.0)
    ap.add_argument("--clon-desde-s", type=int, default=20)
    ap.add_argument("--pausa-max", type=float, default=21.0)
    ap.add_argument("--etiqueta", default="")
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "seguridad"))
    args = ap.parse_args()
    tls_dir = Path(args.tls)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrida = Path(args.salida) / f"{ts}_{args.escenario}{'_' + args.etiqueta if args.etiqueta else ''}"
    corrida.mkdir(parents=True, exist_ok=True)
    config = {"fecha_inicio": datetime.now().isoformat(timespec="seconds"), "commit": campana._commit(),
              **{k: v for k, v in vars(args).items()}}
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    os.environ.update(SEG_POLITICA=args.politica, SEG_CONFIRMACION_S=str(args.confirmacion_s))
    broker = _lanzar_broker(corrida, args.puerto, tls_dir)
    print(f"Corrida {corrida.name}: broker de prueba en 127.0.0.1:{args.puerto}")
    try:
        for i in range(1, args.repeticiones + 1):
            rep_dir = corrida / f"rep_{i:02d}"
            rep_dir.mkdir(parents=True, exist_ok=True)
            semilla = 100 + i
            pausa = random.Random(semilla).uniform(0, args.pausa_max)
            obus: list[tuple[str, Path, float]] = []
            legitimas: list[str] = []
            if args.escenario in ("inundacion", "base"):
                legit = f"obu-legit-r{i:02d}"
                tray = rep_dir / f"trayectoria_{legit}.csv"
                campana._trayectoria_con_ruido(BASE_LAZO, tray, semilla, 5.0)
                obus.append((legit, tray, 1.0))
                legitimas.append(legit)
            if args.escenario == "mision_falsa":
                atac = f"obu-falsa-r{i:02d}"
                tray = rep_dir / f"trayectoria_{atac}.csv"
                campana._trayectoria_con_ruido(BASE_LAZO, tray, semilla, 5.0)
                obus.append((atac, tray, 1.0))
            elif args.escenario == "clon":
                atac = f"obu-clon-r{i:02d}"
                tray = rep_dir / f"trayectoria_{atac}.csv"
                _trayectoria_clon(BASE_LAZO, tray, args.clon_desde_s, args.distancia_clon_m)
                obus.append((atac, tray, 1.0))
            elif args.escenario == "inundacion":
                atac = f"obu-flood-r{i:02d}"
                tray = rep_dir / f"trayectoria_{atac}.csv"
                duracion = len(_leer(BASE_LAZO)) + 5
                _trayectoria_inundacion(BASE_LAZO, tray, int(duracion * args.hz))
                obus.append((atac, tray, args.hz))
            print(f"[{i}/{args.repeticiones}] {rep_dir.name}: pausa {pausa:.1f} s, OBU {[o[0] for o in obus]}")

            ctrl, agent = campana._lanzar_local(rep_dir, tls_dir, "127.0.0.1", args.puerto)
            servidor = operador = None
            procesos: list[subprocess.Popen] = []
            try:
                servidor = campana._lanzar_servidor(rep_dir, "recta", REGISTRO, "127.0.0.1", args.puerto, tls_dir)
                operador = _lanzar_operador(rep_dir, args.puerto, tls_dir, args.retardo_s, legitimas,
                                            args.sin_operador)
                time.sleep(pausa)
                for obu_id, tray, factor in obus:
                    procesos.append(_lanzar_obu(rep_dir, obu_id, tray, args.puerto, tls_dir, factor))
                    time.sleep(0.2)
                for p in procesos:
                    p.wait()
                time.sleep(3.0)
            finally:
                campana._detener(*procesos, operador, servidor, ctrl, agent)
                campana._esperar_puertos_libres([(campana.CONTROLLER_PORT, "tcp"), (campana.SNMP_PORT, "udp")])
    finally:
        campana._detener(broker)
    config["fecha_fin"] = datetime.now().isoformat(timespec="seconds")
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nListo: {corrida}")
    print(f"Análisis: {PY} scripts/seguridad/analisis_seguridad_operativa.py --dir {corrida}")


if __name__ == "__main__":
    main()
