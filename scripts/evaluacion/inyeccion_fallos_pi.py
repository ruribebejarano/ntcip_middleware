#!/usr/bin/env python3
"""OE1/OE4 (Fase 4, prueba 1) con la RSU FÍSICA (Raspberry Pi por 4G).

Casos (--caso):
  rsu       se mata el proceso del agente con SIGKILL
            (sudo systemctl kill -s KILL rsu-agent.service); systemd lo
            reinicia a los 2 s (Restart=on-failure, RestartSec=2).
            Automático.
  enlace4g  el AUTOR desconecta el módem cuando el script lo indica y lo
            vuelve a conectar 20 s después. Interactivo; ver
            docs/PROCEDIMIENTO_PRUEBAS_FISICAS.md antes de correrlo (la Pi
            no debe tener otra ruta de salida, p. ej. Wi-Fi, durante la prueba).

Por repetición: este script (en la laptop) lanza el servidor y la OBU
emulada del escenario `lazo` contra el broker TLS de la campaña (8883), al
que ya está conectado el agente de la Pi; arranca en la Pi el observador
(scripts/evaluacion/observador_rsu.py) y, cuando el servidor recibe el M2
"concedida", espera 3 a 8 s e inyecta la falla. Al terminar, trae de la Pi
el CSV del observador, los eventos de la RSU y el journal del agente.

Todas las métricas se calculan con el reloj de la Pi:
  t_lib_m1  último M1 recibido por la RSU antes de la falla -> el
            controlador deja de tener la prioridad (observador)
  T_rec     rsu: muerte del proceso (journal) -> "Conectado al broker MQTT"
            del proceso reiniciado (journal);
            enlace4g: la interfaz del módem vuelve a estar "up"
            (observador) -> "Conectado al broker MQTT" (journal)
  retenida  prioridad activa al final de la repetición
Además, una sonda desde la laptop (M1 de prueba con la identidad del
servidor, como en inyeccion_fallos.py) confirma que la RSU responde.

Uso: .venv/Scripts/python.exe scripts/evaluacion/inyeccion_fallos_pi.py --caso rsu --repeticiones 10
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.campanas.lazo_centralizado import (  # noqa: E402
    ESCENARIOS, FIXTURES, _correr_obus, _detener, _lanzar_servidor, _trayectoria_con_ruido)
from scripts.evaluacion import inyeccion_fallos as base  # noqa: E402

HOST = "rsu"
DIR_PI = "~/ntcip_middleware"
PY_PI = "~/rsu-env/bin/python"
DURACION_CORTE_S = 20.0
NS = 1e9


def ssh(cmd: str, timeout: float = 60) -> str:
    r = subprocess.run(["ssh", HOST, cmd], capture_output=True, text=True, timeout=timeout)
    return r.stdout


def ssh_reintentar(cmd: str, limite_s: float = 300) -> str:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", HOST, cmd], capture_output=True, text=True,
                               timeout=60)
            if r.returncode == 0:
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    raise SystemExit(f"la Pi no respondió por SSH en {limite_s:.0f} s")


def esperar_concedida(rep: Path, limite_s: float = 150) -> bool:
    fin = time.monotonic() + limite_s
    f = rep / "eventos_servidor.csv"
    while time.monotonic() < fin:
        if f.exists() and '""estado"":""concedida""' in f.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(0.1)
    return False


def journal_ts(texto: str, patron: str, desde_ns: int) -> int | None:
    """Primera línea del journal (short-unix) que contiene `patron` después de desde_ns."""
    for ln in texto.splitlines():
        partes = ln.split(" ", 1)
        try:
            ts = int(float(partes[0]) * NS)
        except (ValueError, IndexError):
            continue
        if ts > desde_ns and patron in ln:
            return ts
    return None


# Estados de /sys/class/net/<if>/operstate que indican que el enlace cayó.
# El módem USB (usb0) informa "unknown" mientras funciona normalmente (no
# reporta el estado de su portadora), así que "no estar up" no basta: el
# corte se reconoce cuando la interfaz desaparece ("ausente", el cable USB
# desconectado) o queda explícitamente abajo.
ESTADOS_CAIDA = {"ausente", "down", "lowerlayerdown", "notpresent"}
CABECERA_EVENTOS = "ts_ns,nodo,tipo_evento,id_solicitud,extra_json"


def metricas(caso: str, texto_obs: str, eventos: str, journal: str, t_ini_pi: int) -> dict:
    """Métricas de una repetición a partir de los archivos traídos de la Pi."""
    obs = [r for r in csv.DictReader(texto_obs.splitlines())]
    # eventos_rsu_pi.csv es un `tail` del registro de la RSU: si el archivo
    # completo es más largo, la cabecera queda fuera y hay que reponerla.
    lineas_ev = eventos.splitlines()
    if lineas_ev and not lineas_ev[0].startswith("ts_ns,"):
        lineas_ev.insert(0, CABECERA_EVENTOS)
    ev = [r for r in csv.DictReader(lineas_ev) if (r.get("ts_ns") or "").isdigit()]
    m1 = [int(r["ts_ns"]) for r in ev
          if r.get("tipo_evento") == "M1_rx" and int(r["ts_ns"]) > t_ini_pi
          and not r["id_solicitud"].startswith("sonda")]
    # Cualquier M1 recibido (incluida la sonda de la laptop) prueba que la RSU
    # volvió a estar conectada al broker: el cliente MQTT reconecta solo y no
    # siempre deja una línea en el journal.
    m1_todos = [int(r["ts_ns"]) for r in ev if r.get("tipo_evento") == "M1_rx" and int(r["ts_ns"]) > t_ini_pi]
    if caso == "rsu":
        t_falla = journal_ts(journal, "killed", t_ini_pi) or journal_ts(journal, "Main process exited", t_ini_pi)
        t_up = t_falla
    else:
        caidas = [int(r["ts_ns"]) for r in obs if r["interfaz"] in ESTADOS_CAIDA]
        t_falla = caidas[0] if caidas else None
        t_up = next((int(r["ts_ns"]) for r in obs if t_falla and int(r["ts_ns"]) > caidas[-1]
                     and r["interfaz"] not in ESTADOS_CAIDA), None)
    res: dict = {"t_falla_ns": t_falla, "t_up_ns": t_up}
    if not t_falla:
        res["error"] = "sin corte detectado"
        return res
    lib = next((int(r["ts_ns"]) for r in obs if int(r["ts_ns"]) > t_falla and r["prioridad_activa"] == "0"), None)
    m1_antes = [t for t in m1 if t <= t_falla]
    con = journal_ts(journal, "Conectado al broker MQTT", t_up or t_falla)
    if caso == "enlace4g":
        con = next((t for t in m1_todos if t > (t_up or t_falla)), con)
    prio_al_fallo = next((r["prioridad_activa"] for r in reversed(obs) if int(r["ts_ns"]) <= t_falla), None)
    res.update(prioridad_al_fallo=prio_al_fallo == "1",
               t_lib_m1_s=(lib - max(m1_antes)) / NS if lib and m1_antes else None,
               t_lib_falla_s=(lib - t_falla) / NS if lib else None,
               T_rec_s=(con - (t_up or t_falla)) / NS if con else None,
               retenida=bool(obs) and obs[-1]["prioridad_activa"] == "1")
    if caso == "enlace4g" and t_up:
        res.update(_descomponer_trec(obs, ev, t_falla, t_up, con))
    return res


def _descomponer_trec(obs: list, ev: list, t_falla: int, t_up: int, t_m1: int | None) -> dict:
    """Separa T_rec en tramos, si la Pi corre la versión instrumentada
    (columna ipv4 del observador, eventos mqtt_* del middleware); con datos
    anteriores devuelve los campos en None.
      modem      usb0 reaparece -> usb0 tiene IPv4. Es la IP de la LAN USB del
                 propio módem (192.168.0.x), no de la red celular: mide el
                 enlace USB, NO el re-registro en la red de Claro.
      mqtt       IPv4 -> CONNACK del broker: re-registro celular + túnel +
                 reintentos y handshake TLS del cliente MQTT, sin separar
      primer_m1  CONNACK -> primer M1 recibido (resuscripción + periodo de la sonda)
    deteccion: corte -> el cliente da la conexión por perdida (puede ocurrir
    después de reconectado el módem, o nunca, si el corte fue más corto)."""
    def ev_tras(tipo: str, desde: int) -> list[int]:
        return [int(r["ts_ns"]) for r in ev if r.get("tipo_evento") == tipo and int(r["ts_ns"]) > desde]
    t_ip = next((int(r["ts_ns"]) for r in obs if int(r["ts_ns"]) >= t_up and r.get("ipv4")), None)
    t_desc = next(iter(ev_tras("mqtt_desconectado", t_falla)), None)
    t_con = next(iter(ev_tras("mqtt_conectado", t_up)), None)
    intentos = [t for t in ev_tras("mqtt_intento", t_falla) if not t_con or t <= t_con]
    fallidos = [t for t in ev_tras("mqtt_intento_fallido", t_falla) if not t_con or t <= t_con]
    s = lambda a, b: (b - a) / NS if a and b and b >= a else None  # noqa: E731
    return {"t_ip_ns": t_ip, "t_mqtt_desconectado_ns": t_desc, "t_mqtt_conectado_ns": t_con,
            "trec_modem_s": s(t_up, t_ip), "trec_mqtt_s": s(t_ip, t_con), "trec_primer_m1_s": s(t_con, t_m1),
            "deteccion_s": s(t_falla, t_desc), "intentos_mqtt": len(intentos),
            "intentos_tras_ip": sum(1 for t in intentos if t_ip and t >= t_ip),
            "intentos_fallidos": len(fallidos)}


def recalcular(corrida: Path, caso: str) -> None:
    """Recalcula fallo.json y resultados.json de una corrida ya hecha, con los
    archivos guardados por repetición. El instante de inicio en la Pi no se
    guardó: se toma 5 s antes de la primera muestra del observador, que se
    lanza justo después de leerlo."""
    filas = []
    for rep in sorted(corrida.glob("rep_*")):
        previo = json.loads((rep / "fallo.json").read_text(encoding="utf-8"))
        texto_obs = (rep / "observador_pi.csv").read_text(encoding="utf-8")
        primera = next(csv.DictReader(texto_obs.splitlines()), None)
        t_ini_pi = int(primera["ts_ns"]) - int(5 * NS) if primera else 0
        res = {k: previo[k] for k in ("rep", "caso", "sonda") if k in previo}
        res.update(metricas(caso, texto_obs, (rep / "eventos_rsu_pi.csv").read_text(encoding="utf-8"),
                            (rep / "journal_agente.txt").read_text(encoding="utf-8"), t_ini_pi))
        (rep / "fallo.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        filas.append(res)
        print(f"[{caso} {res.get('rep', 0):02d}] t_lib(M1)={res.get('t_lib_m1_s')} "
              f"t_lib(falla)={res.get('t_lib_falla_s')} T_rec={res.get('T_rec_s')} "
              f"retenida={res.get('retenida')} {res.get('error', '')}", flush=True)
    (corrida / "resultados.json").write_text(json.dumps({"caso": caso, "reps": filas}, indent=1, default=str),
                                             encoding="utf-8")


# Contadores de la interfaz de Tailscale de la Pi: a diferencia de usb0 (que
# desaparece y se reinicia a cero en cada corte), tailscale0 acumula desde que
# arrancó tailscaled. Todo el tráfico de la prueba (MQTT, SSH, descargas)
# pasa por ella; no cuenta el tráfico propio de la Pi fuera del túnel.
CMD_BYTES_TS = ("cat /sys/class/net/tailscale0/statistics/rx_bytes "
                "/sys/class/net/tailscale0/statistics/tx_bytes 2>/dev/null")


def _bytes_ts(texto: str) -> int | None:
    try:
        rx, tx = (int(x) for x in texto.split()[:2])
        return rx + tx
    except ValueError:
        return None


def _guardar(corrida: Path, caso: str, filas: list) -> None:
    """Se reescribe tras cada repetición: si la corrida se interrumpe, lo
    hecho hasta ahí queda utilizable por fallos_resumen.py."""
    (corrida / "resultados.json").write_text(json.dumps({"caso": caso, "reps": filas}, indent=1, default=str),
                                             encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caso", required=True, choices=["rsu", "enlace4g"])
    ap.add_argument("--repeticiones", type=int, default=10)
    ap.add_argument("--semilla-base", type=int, default=700)
    ap.add_argument("--recalcular", type=Path, help="corrida ya hecha: solo recalcula sus métricas")
    args = ap.parse_args()
    if args.recalcular:
        recalcular(args.recalcular, args.caso)
        return
    if args.caso == "enlace4g":
        # Con el Wi-Fi activo, al desconectar el módem el tráfico sigue por el
        # Wi-Fi y el "corte" no corta nada. Se exige que la única salida sea el módem.
        wifi = ssh("cat /sys/class/net/wlan0/operstate 2>/dev/null || echo ausente").strip()
        if wifi == "up":
            raise SystemExit("wlan0 está activo en la Pi: el corte del módem no cortaría el enlace. "
                             "Ejecute antes 'bash scripts/pi.sh red modo-campana rsu --sin-wifi' y verifique "
                             "que la Pi siga respondiendo.")
    base.PUERTO_BROKER = 8883  # broker de la campaña, al que se conecta el agente de la Pi
    corrida = RAIZ / "resultados" / "evaluacion" / f"{datetime.now():%Y%m%d-%H%M%S}_fallos_pi_{args.caso}"
    corrida.mkdir(parents=True)
    esc = ESCENARIOS["lazo"]
    filas = []
    for i in range(1, args.repeticiones + 1):
        rep = corrida / f"rep_{i:02d}"
        rep.mkdir()
        semilla = args.semilla_base + i
        obu_id = f"obu-fpi-{args.caso}-r{i:02d}"
        tray = rep / f"trayectoria_{obu_id}.csv"
        _trayectoria_con_ruido(FIXTURES / esc["obus"][0][1], tray, semilla, 5.0)
        ini = ssh_reintentar("date +%s%N; " + CMD_BYTES_TS).split(None, 1)
        t_ini_pi = int(ini[0])
        bytes_ini = _bytes_ts(ini[1]) if len(ini) > 1 else None
        obs_pi = f"/tmp/obs_fallo_{i:02d}.csv"
        # El cliente SSH de Windows no suelta la sesión si el proceso remoto
        # queda en segundo plano: se deja el SSH corriendo aparte (Popen, sin
        # esperarlo) y el observador en su propia sesión (setsid + nohup), para
        # que sobreviva si el corte del enlace tumba la conexión SSH.
        ssh_obs = subprocess.Popen(
            ["ssh", "-n", HOST, f"cd {DIR_PI} && setsid nohup {PY_PI} scripts/evaluacion/observador_rsu.py "
                                f"--salida {obs_pi} --duracion 220 > /dev/null 2>&1 < /dev/null"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)
        servidor = _lanzar_servidor(rep, esc["grafo"], FIXTURES / esc["registro"], "127.0.0.1", 8883,
                                    base.TLS_DIR)
        time.sleep(random.Random(semilla + 10_000).uniform(0, 21))
        hilo = threading.Thread(target=_correr_obus, args=(rep, [(obu_id, "")], [tray], "127.0.0.1", 8883, 1.0,
                                                          base.TLS_DIR), daemon=True)
        hilo.start()
        res = {"rep": i, "caso": args.caso}
        if not esperar_concedida(rep):
            res["error"] = "sin M2 concedida"
        else:
            time.sleep(random.Random(semilla + 20_000).uniform(3.0, 8.0))
            if args.caso == "rsu":
                ssh("sudo systemctl kill -s KILL rsu-agent.service")
            else:
                print("\a\n" + "=" * 60 + "\n   DESCONECTE EL MÓDEM AHORA\n" + "=" * 60, flush=True)
                time.sleep(DURACION_CORTE_S)
                print("\a\n" + "=" * 60 + "\n   VUELVA A CONECTAR EL MÓDEM AHORA\n" + "=" * 60, flush=True)
            res["sonda"] = base._sonda(time.time_ns(), limite_s=240)
        hilo.join(timeout=240)
        time.sleep(3)
        _detener(servidor)
        # --- datos de la Pi (reloj de la Pi) -----------------------------------
        ssh_obs.kill()  # el observador sigue solo hasta --duracion; aquí solo se suelta el SSH
        try:
            texto_obs = ssh_reintentar(f"sleep 1; cat {obs_pi}")
            (rep / "observador_pi.csv").write_text(texto_obs, encoding="utf-8")
            # Sin sudo: el usuario de la Pi está en el grupo adm, que lee el
            # journal. Con sudo, la lectura dependería de que el autor hubiera
            # escrito su contraseña en la Pi en los últimos minutos, y si no,
            # la corrida quedaría esperando.
            journal = ssh_reintentar(f"journalctl -u rsu-agent.service -o short-unix --no-pager "
                                     f"--since @{t_ini_pi // 10**9}")
            (rep / "journal_agente.txt").write_text(journal, encoding="utf-8")
            eventos = ssh_reintentar(f"cd {DIR_PI} && tail -n 4000 resultados/eventos/eventos_rsu_1.csv")
            (rep / "eventos_rsu_pi.csv").write_text(eventos, encoding="utf-8")
            bytes_fin = _bytes_ts(ssh_reintentar(CMD_BYTES_TS))
        except SystemExit as e:
            # La Pi no volvió (p. ej., el 4G no se restableció): se guarda lo
            # hecho y se detiene la corrida en vez de perderla entera.
            res["error"] = f"sin datos de la Pi: {e}"
            (rep / "fallo.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            filas.append(res)
            _guardar(corrida, args.caso, filas)
            print(f"[{args.caso} {i:02d}] {res['error']} -- corrida detenida; salida en {corrida}", flush=True)
            return
        res.update(metricas(args.caso, texto_obs, eventos, journal, t_ini_pi))
        if bytes_ini is not None and bytes_fin is not None and bytes_fin >= bytes_ini:
            res["bytes_tailscale"] = bytes_fin - bytes_ini
        (rep / "fallo.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        filas.append(res)
        _guardar(corrida, args.caso, filas)
        print(f"[{args.caso} {i:02d}] t_lib(M1)={res.get('t_lib_m1_s')} T_rec={res.get('T_rec_s')} "
              f"retenida={res.get('retenida')} sonda={res.get('sonda', {}).get('intentos')} "
              f"datos={res.get('bytes_tailscale', 0) / 1e6:.2f} MB "
              f"[módem={res.get('trec_modem_s')} mqtt={res.get('trec_mqtt_s')} "
              f"intentos={res.get('intentos_mqtt')}] {res.get('error', '')}",
              flush=True)
    _guardar(corrida, args.caso, filas)
    total = sum(x.get("bytes_tailscale", 0) for x in filas)
    print(f"Datos por el túnel en toda la corrida: {total / 1e6:.1f} MB")
    print(f"Salida en {corrida}")


if __name__ == "__main__":
    main()
