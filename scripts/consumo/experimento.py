#!/usr/bin/env python3
"""Experimento de consumo de datos de la RSU y de la OBU por el módem 4G.

Se ejecuta en la laptop. Copia lo necesario a la Pi, deja allí un registrador
independiente y, durante la medición, no usa SSH hacia la Pi: así los contadores
no incluyen tráfico de control. Guía: docs/EXPERIMENTO_CONSUMO.md.

Uso:
    python scripts/consumo/experimento.py --solo-verificar
    python scripts/consumo/experimento.py
"""

from __future__ import annotations

import argparse
import io
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "evaluacion"))
from correr_emulada import con_ruido  # noqa: E402

PY = sys.executable
FIXTURES = RAIZ / "scripts" / "campanas" / "fixtures"
TRAYECTORIA = FIXTURES / "trayectoria_lazo_base.csv"
REGISTRO = FIXTURES / "registro_rsu_1.json"
PKI = RAIZ / "deploy" / "pki"
OBU_RSU = "obu-rsu-consumo"
OBU_PI = "obu-pi-consumo"
CTRL_PORT, SNMP_PORT = 9000, 1161

PLAN_COMPLETO = {"fondo": 1800, "reposo": 1800, "misiones": 2100, "reposo2": 1800, "obu": 1500}
PLAN_PRUEBA = {"fondo": 60, "reposo": 60, "misiones": 300, "reposo2": 60, "obu": 300}


def ssh(host: str, comando: str, entrada: bytes | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, comando],
                          input=entrada, capture_output=True, timeout=timeout)


def texto_ssh(host: str, comando: str) -> str:
    r = ssh(host, comando)
    return (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def interfaz_por_defecto(rutas: str) -> str | None:
    candidatas = re.findall(r"^default via \S+ dev (\S+).*?metric (\d+)", rutas, re.M)
    return min(candidatas, key=lambda c: int(c[1]))[0] if candidatas else None


def verificar(args) -> list[str]:
    fallas: list[str] = []
    salida = subprocess.run(["netstat", "-an"], capture_output=True, text=True, errors="replace").stdout
    if not re.search(r"[:.]8883\s.*LISTEN", salida):
        fallas.append("No hay broker TLS en 8883. Abre deploy\\pki\\mosquitto_laptop_tls.conf con mosquitto -v.")
    if ssh(args.host, "true").returncode != 0:
        return fallas + [f"La Pi no responde por SSH ({args.host})."]
    activa = interfaz_por_defecto(texto_ssh(args.host, "ip route show default"))
    if activa != args.iface:
        fallas.append(f"La ruta por defecto usa {activa}, no {args.iface}. Para 4G: "
                      'ssh -t rsu "cd ~/ntcip_middleware && bash scripts/red_4g.sh modo-campana --sin-wifi"')
    if "active" != texto_ssh(args.host, "systemctl is-active rsu-agent"):
        fallas.append("rsu-agent no está activo en la Pi.")
    if "MQTT_BROKER_PORT=8883" not in texto_ssh(args.host, "systemctl show rsu-agent -p Environment"):
        fallas.append("rsu-agent no está configurado para 8883.")
    if args.iface == "usb0" and "via 192.168." in texto_ssh(args.host, f"tailscale ping --c 1 {args.broker_host}"):
        fallas.append("Tailscale va por la LAN: apaga el Wi-Fi de la Pi, o no se mediría el 4G.")
    if not args.sin_detener_agente and ssh(args.host, "sudo -n -l systemctl stop rsu-agent.service").returncode != 0:
        fallas.append("La Pi no permite detener rsu-agent sin contraseña.")
    return fallas


def cert(tipo: str, id_: str | None) -> list[str]:
    cmd = [PY, str(RAIZ / "scripts" / "evaluacion" / "cert_cliente.py"), "--pki", str(PKI), "--tipo", tipo]
    if id_:
        cmd += ["--id", id_]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.splitlines()


def subir(host: str, destino: str, archivos: dict[str, Path | str]) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for nombre, origen in archivos.items():
            datos = origen.encode() if isinstance(origen, str) else origen.read_bytes()
            if nombre.endswith(".sh"):  # git en Windows puede dejar CRLF, que rompe bash
                datos = datos.replace(b"\r\n", b"\n")
            info = tarfile.TarInfo(nombre)
            info.size = len(datos)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(datos))
    r = ssh(host, f"mkdir -p {destino} && tar xzf - -C {destino}", entrada=buf.getvalue(), timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"No se pudo copiar a la Pi: {r.stderr.decode('utf-8', 'replace')}")


def traer(host: str, origen: str, destino: Path) -> None:
    r = ssh(host, f"cd {origen} && tar czf - contadores.csv estado.txt obu.log obu 2>/dev/null", timeout=180)
    destino.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:gz") as tar:
        tar.extractall(destino, filter="data")


def esperar_hasta(t: float) -> None:
    while time.time() < t:
        time.sleep(min(1.0, max(0.0, t - time.time())))


def lanzar(nombre: str, cmd: list[str], corrida: Path, **env) -> subprocess.Popen:
    log = (corrida / f"{nombre}.log").open("w", encoding="utf-8")
    entorno = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "MQTT_BROKER_HOST": "127.0.0.1",
               "MQTT_BROKER_PORT": "8883", **env}
    return subprocess.Popen(cmd, cwd=RAIZ, env=entorno, stdout=log, stderr=subprocess.STDOUT)


def detener(*procesos: subprocess.Popen | None) -> None:
    for p in procesos:
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def rsu_local(corrida: Path) -> tuple[subprocess.Popen, subprocess.Popen]:
    """RSU en la laptop para la fase de la OBU: con el agente de la Pi detenido, sus
    mensajes no pasan por el módem y solo se mide el tráfico de la OBU."""
    ca, crt, key = cert("rsu", "1")
    env = {"RSU_ID": "1", "RSU_EVENTOS_DIR": str(corrida / "rsu_local"), "CONTROLLER_PORT": str(CTRL_PORT),
           "SNMP_PORT": str(SNMP_PORT), "RSU_TLS_CA": ca, "RSU_TLS_CERT": crt, "RSU_TLS_KEY": key}
    ctrl = lanzar("controlador_local", [PY, "-u", "controller/controller_emulator.py", "--port", str(CTRL_PORT)], corrida, **env)
    time.sleep(2)
    return ctrl, lanzar("rsu_local", [PY, "-u", "agent/rsu_middleware.py"], corrida, **env)


def misiones_laptop(corrida: Path, n: int, fin: float, duracion: float, rnd: random.Random) -> int:
    ca, crt, key = cert("obu", OBU_RSU)
    hechas = 0
    for i in range(1, n + 1):
        if time.time() + duracion + 15 >= fin:
            print(f"  Sin tiempo para más misiones; se hicieron {hechas}.", flush=True)
            break
        rep = corrida / "misiones" / f"rep_{i:02d}"
        rep.mkdir(parents=True, exist_ok=True)
        tray = rep / "trayectoria.csv"
        con_ruido(TRAYECTORIA, tray, i, 5.0)
        entorno = {**os.environ, "RSU_EVENTOS_DIR": str(rep), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        with (rep / "obu.log").open("w", encoding="utf-8") as log:
            r = subprocess.run([PY, "gateway/obu_emulada.py", "--broker-host", "127.0.0.1", "--broker-port", "8883",
                                "--obu-id", OBU_RSU, "--trayectoria", str(tray), "--tls-ca", ca, "--tls-cert", crt, "--tls-key", key],
                               cwd=RAIZ, env=entorno, stdout=log, stderr=subprocess.STDOUT)
        hechas += r.returncode == 0
        print(f"  Misión {i} de {n}: rc={r.returncode}", flush=True)
        time.sleep(rnd.uniform(0, 25))
    return hechas


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="rsu")
    ap.add_argument("--iface", default="usb0")
    ap.add_argument("--broker-host", default="100.121.77.97", help="IP Tailscale de la laptop")
    ap.add_argument("--misiones-rsu", type=int, default=18)
    ap.add_argument("--misiones-obu", type=int, default=12)
    ap.add_argument("--limite-mb", type=int, default=300, help="la Pi aborta si la interfaz supera este consumo")
    ap.add_argument("--prueba", action="store_true", help="ensayo corto, no sirve para medir")
    ap.add_argument("--sin-detener-agente", action="store_true", help="solo para ensayos: no detiene rsu-agent")
    ap.add_argument("--solo-verificar", action="store_true")
    args = ap.parse_args()

    fallas = verificar(args)
    for f in fallas:
        print(f"[FALLA] {f}")
    if fallas:
        sys.exit(1)
    print("Verificación correcta.")
    if args.solo_verificar:
        return

    plan = PLAN_PRUEBA if args.prueba else PLAN_COMPLETO
    margen = 15 if args.prueba else 60
    n_rsu, n_obu = (2, 2) if args.prueba else (args.misiones_rsu, args.misiones_obu)
    fecha = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrida = RAIZ / "resultados" / "consumo" / ("_pruebas" if args.prueba else "") / f"{fecha}_{args.iface}"
    corrida.mkdir(parents=True)
    remoto = f"consumo/{fecha}"

    # Copia a la Pi, antes de empezar a medir.
    filas = TRAYECTORIA.read_text(encoding="utf-8").count("\n")
    ca, crt, key = cert("obu", OBU_PI)
    with tempfile.TemporaryDirectory() as tmp:
        archivos: dict[str, Path | str] = {"registrar_en_pi.sh": Path(__file__).with_name("registrar_en_pi.sh"),
                                           "ca.crt": Path(ca), "obu.crt": Path(crt), "obu.key": Path(key),
                                           "broker_host.txt": args.broker_host}
        for i in range(1, n_obu + 1):
            tray = Path(tmp) / f"tray_{i:02d}.csv"
            con_ruido(TRAYECTORIA, tray, 100 + i, 5.0)
            archivos[tray.name] = tray
        subir(args.host, remoto, archivos)

    # Servidor en la laptop, durante todo el experimento.
    (corrida / "servidor").mkdir()
    ca_s, crt_s, key_s = cert("servidor", None)
    servidor = lanzar("servidor", [PY, "-u", "servidor/main.py"], corrida, RSU_EVENTOS_DIR=str(corrida / "servidor"),
                      GRAFO_SINTETICO="recta", REGISTRO_RSU_PATH=str(REGISTRO), SERVIDOR_TLS_CA=ca_s,
                      SERVIDOR_TLS_CERT=crt_s, SERVIDOR_TLS_KEY=key_s)
    time.sleep(10)
    if servidor.poll() is not None:
        raise SystemExit(f"El servidor no arrancó; revisa {corrida / 'servidor.log'}")

    t0 = int(time.time()) + 45
    fases = " ".join(f"{k}:{v}" for k, v in plan.items())
    detener_agente = 0 if args.sin_detener_agente else 1
    # Con ";" solo el registrador pasa a segundo plano, sin retener la salida de SSH.
    try:
        r = ssh(args.host, f"cd {remoto} || exit 1; nohup setsid bash registrar_en_pi.sh {t0} {args.iface} $HOME/{remoto} "
                           f"{args.limite_mb} {detener_agente} {margen} {fases} > registrador.log 2>&1 < /dev/null & echo ok")
    except subprocess.TimeoutExpired:
        detener(servidor)
        raise SystemExit("La Pi no respondió al lanzar el registrador. Revisa con: ssh rsu pgrep -fa registrar_en_pi")
    if b"ok" not in r.stdout:
        detener(servidor)
        raise SystemExit(f"No se pudo lanzar el registrador en la Pi: {r.stderr.decode('utf-8', 'replace')}")

    total = sum(plan.values())
    print(f"Medición de {total / 60:.0f} min desde las {datetime.fromtimestamp(t0):%H:%M:%S}. "
          f"No uses SSH hacia la Pi hasta que termine.\nCarpeta: {corrida}", flush=True)
    rnd = random.Random(1)
    locales: tuple = ()
    hechas = 0
    try:
        inicio = t0
        for fase, seg in plan.items():
            fin = inicio + seg
            print(f"[{datetime.now():%H:%M:%S}] Fase {fase}, {seg / 60:.0f} min", flush=True)
            if fase == "misiones":
                esperar_hasta(inicio + margen)
                hechas = misiones_laptop(corrida, n_rsu, fin, filas, rnd)
            elif fase == "obu" and not args.sin_detener_agente:
                esperar_hasta(inicio + 15)  # la Pi ya detuvo su agente: mismo client_id MQTT
                locales = rsu_local(corrida)
            esperar_hasta(fin)
            inicio = fin
        esperar_hasta(inicio + 30)
    except KeyboardInterrupt:
        print("Interrumpido: se detiene el registrador en la Pi, que reinicia el agente.")
        ssh(args.host, "pkill -f registrar_en_pi.sh")
        raise
    finally:
        detener(*locales, servidor)

    traer(args.host, f"$HOME/{remoto}", corrida / "pi")
    if not (corrida / "pi" / "contadores.csv").exists():
        raise SystemExit("No se pudieron traer los contadores de la Pi.")
    print(f"Misiones de la RSU completadas: {hechas}", flush=True)
    subprocess.run([PY, str(Path(__file__).with_name("analizar.py")), "--dir", str(corrida), "--margen-s", str(margen)], check=False)
    print("Estado de rsu-agent:", texto_ssh(args.host, "systemctl is-active rsu-agent"))
    if args.iface == "usb0":
        print("La Pi sigue en modo 4G. Para volver: ssh -t rsu \"cd ~/ntcip_middleware && bash scripts/red_4g.sh modo-normal\"")


if __name__ == "__main__":
    main()
