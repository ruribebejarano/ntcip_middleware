#!/usr/bin/env python3
"""Campaña de medición del lazo con la ARQUITECTURA CENTRALIZADA
(2026-10-22): servidor/main.py decide, la RSU solo traduce. Reemplaza a
scripts/campanas/lazo_emulado.py para este propósito (ver su docstring:
quedó obsoleto, era para el esquema anterior donde la OBU emitía M1
directo a la RSU).

Tres escenarios, cada uno con UNA sola RSU física (rsu_id="1", igual al
RSU_ID por defecto de agent/rsu_middleware.py y al que corre hoy en la
Raspberry Pi real vía deploy/systemd/rsu-agent.service -- ver
scripts/campanas/fixtures/):

  lazo       1 OBU, recorrido recto que cruza la RSU (grafo sintético
             "recta", registro_rsu_1.json).
  desvio     1 OBU, mismo recorrido que "lazo" pero con una excursión que
             dispara el recálculo de ruta (servidor/gestor_mision.py,
             UMBRAL_DESVIO_M).
  conflicto  2 OBU casi simultáneas, accesos incompatibles de la MISMA RSU
             (grafo sintético "cruce", registro_rsu_1_conflicto.json).
             *** FUERA DE ALCANCE de la campaña de medición y del
             Capítulo 4 desde el 2026-10-28 (decisión del autor, caso
             demasiado específico para el alcance de la tesis -- ver
             docs/CRONOGRAMA.md, decisión de alcance #2, y
             docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md).
             El arbitraje (servidor/conflictos.py) sigue verificado con
             pruebas unitarias; este runner conserva el escenario (no se
             borra código) pero NO correrlo para la campaña oficial.

Tres configuraciones de dónde corre la RSU, con el MISMO runner y el MISMO
análisis (scripts/analisis/lazo_centralizado.py) para que sean
comparables (OE5, hito S7):

  local      Todo en esta máquina: lanza controller_emulator.py +
             agent/rsu_middleware.py también (como los correr_e2e*.sh de
             evidencia/2026-10-22_arquitectura-centralizada/).
  pi-lan     La RSU real (Raspberry Pi, controller+agent ya corriendo como
             servicios systemd) conectada por Ethernet/LAN. Este runner NO
             lanza nada en la Pi: solo verifica con `scripts/pi.sh status`
             que los servicios estén activos, y lanza servidor + OBU(s)
             aquí.
  pi-4g      Igual que pi-lan, pero la Pi llega por el módem 4G (SIM7670G)
             en vez de LAN. La diferencia para este script es solo
             --broker-host (la dirección por la que se la alcanza); la
             topología de mensajes es idéntica.

*** CORREGIDO 2026-10-28, tras una campaña pi-lan inútil (100 %
sin_respuesta) por este motivo exacto *** El broker Mosquitto vive en
la LAPTOP, no en la Raspberry Pi, en los TRES config -- al revés de lo
que decía esta sección antes. `deploy/systemd/rsu-agent.service.d/broker.conf`
(instalado siguiendo docs/ARRANQUE_BROKER_LAPTOP.md) fija
`MQTT_BROKER_HOST=100.121.77.97` (Tailscale de la laptop) en la unidad
systemd del agente de la Pi: el agente real NUNCA se conecta a
127.0.0.1 ni al Mosquitto propio de la Pi (que sigue instalado y activo,
pero sin uso real -- ver `scripts/pi.sh status mosquitto <host>`). Por
eso `--broker-host` para `pi-lan`/`pi-4g` debe ser la dirección de la
LAPTOP (`127.0.0.1` si este script corre en la misma laptop que aloja el
broker, que es el caso de hoy), NO la de la Pi -- apuntar a la Pi
conecta a un Mosquitto distinto, sin nadie suscrito del lado del agente,
y cada M1 se pierde en silencio (servidor cree que lo mandó, el agente
nunca lo vio: "sin_respuesta" en 100 % de las paradas, ver
docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md).
**[REVISAR con asesor]**: si el diseño final quiere el broker EN cada
RSU (como sugería esta sección antes de corregirse) hay que: (a) quitar
`broker.conf` en la Pi para que el agente vuelva a 127.0.0.1, (b) usar
el Mosquitto de la Pi en vez de desactivarlo. Hoy no es así: queda
documentada la realidad desplegada, no el diseño que se había asumido.

Cada repetición varía la trayectoria (ruido GNSS gaussiano, mismo patrón
que scripts/trayectorias/generar.py) y espera una pausa aleatoria (0..
--pausa-max, por defecto cubre un ciclo completo del controlador emulado:
verde 8 s + ámbar 3 s + todo rojo 2 s + rojo general 8 s = 21 s) antes de
arrancar, para que las solicitudes lleguen en fases distintas del ciclo
(verde, ámbar/todo rojo, rojo) en vez de repetir N veces el mismo caso.

*** CUOTAS ADAPTATIVAS (2026-10-29) *** En vez de un número fijo de
repeticiones, esta corrida sigue lanzando repeticiones hasta que cada una
de las 3 condiciones de llegada (verde / ámbar-todo_rojo / rojo_general --
la fase de la RSU en el momento de decidir, ver
scripts/analisis/lazo_centralizado.py::condicion_de_fase) tenga al menos
`--meta-por-condicion` repeticiones (por defecto 4), con un tope de
`--tope-repeticiones` (por defecto 18) para no quedar colgado si alguna
condición es rara. La pausa aleatoria NO se toca: la estratificación es
por CUOTA (seguir corriendo hasta cubrir las 3), no por apuntar a una fase
objetivo antes de lanzar la OBU -- eso último se descartó a propósito:
entre lanzar la OBU y que la RSU decida pasan varios segundos variables
(más con 4G), así que un objetivo fijado de antemano apuntaría a la fase
equivocada. La condición de cada repetición se clasifica leyendo la
decisión del lado de la RSU (snmp_set_tx, campo "fase") -- NO el M2 del
servidor: ese M2 vuelve a consultar al controlador al publicarse, y si la
concesión fue inmediata (fase "verde" o "rojo_general", ambas fuera de
FASES_NO_INTERRUMPIBLES) ya se llamó request_priority() antes de
publicarlo, así que el M2 siempre reporta "verde" sin importar cuál de
las dos fue la decisión real (bug encontrado y corregido el 2026-10-29,
ver docs/bitacora/2026-10-29_fase-controlador-emulado.md). Con
config=local esos eventos ya están en esta máquina; con config=pi-lan/
pi-4g se hace un fetch incremental (no solo al final de la campaña) para
poder clasificar cada repetición de inmediato. `config.json` registra la
meta pedida, el conteo final por condición y si se llegó al tope.

Cada corrida queda en resultados/campana/<AAAAMMDD-HHMMSS>_<escenario>_<config>/:
    config.json             commit (marca si hay cambios sin commitear),
                            escenario, config, factor, semillas, broker,
                            host de la RSU, reloj (scripts/pi.sh clock) al
                            inicio y al fin (solo si config != local), y
                            -- solo si config es pi-4g/pi-lan -- la salida
                            de "scripts/pi.sh red estado" al inicio y al
                            fin (modo de red, contadores de usb0, señal);
                            la corrida ABORTA si el modo de red no
                            corresponde a la config pedida (ver
                            scripts/red_4g.sh, docs/MODEM_4G.md sección 4)
    rep_01/, rep_02/, ...   eventos_*.csv de todos los nodos de esa
                            repetición, logs de cada proceso lanzado aquí,
                            y las trayectorias CON RUIDO que se
                            reprodujeron (trayectoria_*.csv)

Con config=pi-lan/pi-4g, los eventos de la RSU real (rsu_1, ctrl_1) se
traen UNA vez al final con `scripts/pi.sh fetch` y se reparten entre las
carpetas rep_XX/ por ventana de tiempo (cada repetición registra su propio
inicio/fin en nanosegundos).

*** PRERREQUISITO (no lo hace este script) *** Un broker Mosquitto
corriendo y alcanzable en --broker-host:--broker-port, con
`set_tcp_nodelay true` (ver docs/MEDICION_LATENCIA.md, sección 5) -- en
los TRES config, hoy es el Mosquitto de la laptop
(docs/ARRANQUE_BROKER_LAPTOP.md); para pi-lan/pi-4g --broker-host sigue
siendo la dirección de la LAPTOP (p. ej. `127.0.0.1` si corre en la
misma laptop), no la de la Pi -- ver la nota de más arriba.

Uso:
    # Prueba corta en esta máquina:
    python scripts/campanas/lazo_centralizado.py --escenario lazo --repeticiones 2 --config local

    # Campaña real, RSU por Wi-Fi/LAN (escenarios de la campaña oficial: lazo, desvio).
    # --broker-host es la direccion de la LAPTOP (ver nota de mas arriba), no la de la Pi:
    python scripts/campanas/lazo_centralizado.py --escenario desvio --repeticiones 10 \\
        --config pi-lan --broker-host 127.0.0.1 --host-rsu rsu --factor 1

Análisis, al terminar:
    python scripts/analisis/lazo_centralizado.py --dir <corrida>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from gateway.geometria import desplazar  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Un ciclo completo del controlador emulado por defecto (controller/
# controller_emulator.py): verde 8 s + amarillo 3.0 s + todo-rojo 2.0 s +
# rojo general 8 s = 21 s. Un poco más, para no sesgar hacia el principio
# del ciclo.
PAUSA_MAX_DEFAULT_S = 25.0

CONTROLLER_PORT = 9000
SNMP_PORT = 1161
RSU_ID = "1"

ESCENARIOS = {
    "lazo": {"grafo": "recta", "registro": "registro_rsu_1.json",
             "obus": [("obu-lazo", "trayectoria_lazo_base.csv")]},
    "desvio": {"grafo": "recta", "registro": "registro_rsu_1.json",
               "obus": [("obu-desvio", "trayectoria_desvio_base.csv")]},
    "conflicto": {"grafo": "cruce", "registro": "registro_rsu_1_conflicto.json",
                  "obus": [("obu-conflicto-a", "trayectoria_conflicto_a_base.csv"),
                           ("obu-conflicto-b", "trayectoria_conflicto_b_base.csv")]},
}

# Cuotas adaptativas por condición de llegada (ver docstring del módulo y
# docs/bitacora/2026-10-29_fase-controlador-emulado.md).
META_POR_CONDICION_DEFAULT = 4
TOPE_REPETICIONES_DEFAULT = 18
CONDICIONES_LLEGADA = ("verde", "ambar_todo_rojo", "rojo_general")


def _condicion_de_fase(fase: str | None) -> str | None:
    """Misma política que scripts/analisis/lazo_centralizado.py::condicion_de_fase
    (duplicada, no importada, para no acoplar el runner al módulo de
    análisis): amarillo y todo_rojo son FASES_NO_INTERRUMPIBLES
    (agent/ntcip1211.py) -- la RSU las trata igual, así que cuentan como
    una sola condición."""
    if fase == "verde":
        return "verde"
    if fase in ("amarillo", "todo_rojo"):
        return "ambar_todo_rojo"
    if fase == "rojo_general":
        return "rojo_general"
    return None


def _condicion_de_repeticion(rep_dir: Path, config: str, host_rsu: str,
                             t_ini_ns: int, t_fin_ns: int) -> str | None:
    """Condición de llegada (fase de la RSU al decidir) de la repetición ya
    terminada en `rep_dir`, leída del lado de la RSU (snmp_set_tx, mismo
    campo "fase" y mismo filtro de acción que
    scripts/analisis/lazo_centralizado.py::analizar() usa para `decision`).

    *** CORREGIDO 2026-10-29, el mismo día que se escribió: la primera
    versión leía esto del lado del SERVIDOR (M2_rx.fase) para no depender
    de scripts/pi.sh fetch con config=pi-lan/pi-4g (que solo trae los
    eventos de la RSU real al terminar TODA la campaña) -- pero esa fase
    NO es confiable para la concesión INMEDIATA de prioridad (fase_decision
    "verde" o "rojo_general", ambas fuera de FASES_NO_INTERRUMPIBLES):
    agent/rsu_middleware.py::_publicar_m2() vuelve a consultar
    get_status() al publicar el M2, momento en el que ya se llamó
    request_priority() y el controlador fuerza a reportar "verde" --
    entonces una decisión real en "rojo_general" también se veía como
    "verde" en el M2. Solo el camino en cola (RF-06, fase amarillo/
    todo_rojo) reportaba bien, porque ese M2 se publica ANTES de pedir
    prioridad. Visto en la primera campaña `lazo_local` real (20/20
    "verde"/"ambar_todo_rojo", 0 "rojo_general" reportado en vivo, pero
    8/5/5 real al recalcular desde el lado RSU) -- ver
    docs/bitacora/2026-10-29_fase-controlador-emulado.md.

    Con config=local, eventos_rsu_1.csv ya está en `rep_dir` (misma
    máquina). Con config=pi-lan/pi-4g se hace un fetch incremental (no
    solo al final de la campaña, ver _repartir_eventos_pi) SOLO para
    clasificar esta repetición -- el reparto definitivo a cada rep_XX/
    sigue pasando al final, sin cambios."""
    from common.events import iter_eventos

    if config == "local":
        eventos_rsu = [e for e in iter_eventos(rep_dir) if e["nodo"] == "rsu_1"]
    else:
        _pi_sh("fetch", host_rsu)
        origen = RAIZ / "resultados" / host_rsu / "eventos"
        if not origen.exists():
            return None
        eventos_rsu = [e for e in iter_eventos(origen)
                       if e["nodo"] == "rsu_1" and t_ini_ns <= e["ts_ns"] <= t_fin_ns]

    decision = next(
        (e for e in sorted(eventos_rsu, key=lambda e: e["ts_ns"])
         if e["tipo_evento"] == "snmp_set_tx" and e["extra"].get("accion") in ("request_priority", "en_cola_despeje")),
        None,
    )
    if decision is None:
        return None
    return _condicion_de_fase(decision["extra"].get("fase"))


def _venv_python() -> str:
    """.venv/Scripts/python.exe en Windows, .venv/bin/python en Linux/macOS
    (la Raspberry Pi corre ~/rsu-env, no .venv, pero este script nunca
    ejecuta python EN la Pi -- solo en esta máquina)."""
    if platform.system() == "Windows":
        candidato = RAIZ / ".venv" / "Scripts" / "python.exe"
    else:
        candidato = RAIZ / ".venv" / "bin" / "python"
    return str(candidato) if candidato.exists() else sys.executable


PY = _venv_python()


def _commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, text=True).strip()
        sucio = subprocess.call(["git", "diff", "--quiet"], cwd=RAIZ) != 0
        return sha + ("-con-cambios-sin-commit" if sucio else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def _bash_ejecutable() -> str:
    """En Windows, invocar "bash" sin ruta puede resolver al bash.exe de
    WSL (C:\\Windows\\System32\\bash.exe) en vez del de Git Bash, según el
    orden de PATH que vea ESTE proceso -- no el de una terminal interactiva.
    WSL no ve ~/.ssh/config de Windows ni las rutas de Windows igual
    (necesita /mnt/<letra>/...), así que termina fallando de formas
    confusas: a veces "ssh: Could not resolve hostname" (WSL con su propio
    ~/.ssh ausente), a veces "No such file or directory" directamente
    sobre scripts/pi.sh. Se fuerza la ruta de Git Bash en Windows; en
    otros sistemas "bash" a secas ya es el correcto."""
    if platform.system() == "Windows":
        candidato = Path(r"C:\Program Files\Git\usr\bin\bash.exe")
        if candidato.exists():
            return str(candidato)
    return "bash"


BASH = _bash_ejecutable()


def _pi_sh(*args: str) -> subprocess.CompletedProcess:
    # encoding="utf-8" explícito (no basta text=True): systemctl status
    # imprime "●"/"○" (UTF-8 multibyte) y el locale por defecto de Windows
    # (cp1252) no los puede decodificar -- sin esto, subprocess.run()
    # LANZA UnicodeDecodeError en vez de devolver el texto.
    return subprocess.run([BASH, (RAIZ / "scripts" / "pi.sh").as_posix(), *args],
                          cwd=RAIZ, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _verificar_pi_activa(host: str) -> None:
    for servicio in ("controller", "agent"):
        r = _pi_sh("status", servicio, host)
        salida = r.stdout + r.stderr
        if "Active: active (running)" not in salida:
            raise SystemExit(
                f"[campaña] rsu-{servicio}.service NO está activo en '{host}' "
                f"(scripts/pi.sh status {servicio} {host}):\n{salida}\n"
                f"Desplegar/arrancar antes de seguir: scripts/pi.sh deploy {host} && "
                f"scripts/pi.sh restart {servicio} {host}")
        print(f"[campaña] rsu-{servicio}.service activo en '{host}'")


def _verificar_sin_agente_local_huerfano() -> None:
    """Válido para LOS TRES config: si un agent/rsu_middleware.py o
    controller_emulator.py quedó corriendo en ESTA laptop de una corrida
    anterior, ocupa CONTROLLER_PORT/SNMP_PORT y, en pi-lan/pi-4g, usa el
    MISMO client_id 'rsu-middleware-{RSU_ID}' que el agente REAL de la
    Pi -- el mismo choque que contaminó la campaña del 2026-10-28 (ver
    docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md), aquí
    en sentido inverso (huérfano local contra agente real de la Pi, en
    vez de agente real de la Pi contra agente local)."""
    ocupados = [(p, proto) for p, proto in ((CONTROLLER_PORT, "tcp"), (SNMP_PORT, "udp"))
                if not _puerto_libre(p, proto)]
    if ocupados:
        raise SystemExit(
            f"[campaña] {ocupados} ya está en uso ANTES de arrancar la corrida -- "
            f"probablemente un agente/controlador local huérfano de una corrida anterior "
            f"(controller_emulator.py / rsu_middleware.py) que no se cerró del todo. "
            f"En PowerShell: Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
            f"| Select ProcessId,CommandLine -- identificar y cerrar esos procesos antes "
            f"de reintentar.")


def _verificar_pi_agente_inactivo(host_rsu: str) -> None:
    """Solo para config=local: el agente de la Pi NO debe estar apuntando
    a este mismo broker con el mismo client_id (causa real de la campaña
    contaminada del 2026-10-28)."""
    r = _pi_sh("status", "agent", host_rsu)
    salida = r.stdout + r.stderr
    if "Active: active (running)" in salida:
        raise SystemExit(
            f"[campaña] config=local, pero rsu-agent.service SIGUE ACTIVO en "
            f"'{host_rsu}' (scripts/pi.sh status agent {host_rsu}). Si su broker.conf "
            f"(deploy/systemd/rsu-agent.service.d/broker.conf) apunta al broker de esta "
            f"laptop, usa el MISMO client_id 'rsu-middleware-{{RSU_ID}}' que este runner: "
            f"Mosquitto expulsa a uno de los dos en bucle. Detenerlo antes de seguir: "
            f"scripts/pi.sh stop agent {host_rsu}")
    if "Active:" in salida:
        print(f"[campaña] rsu-agent.service NO está activo en '{host_rsu}' "
              f"(OK, sin riesgo de choque de client_id con el broker local).")
    else:
        print(f"[campaña] AVISO: no se pudo verificar rsu-agent.service en '{host_rsu}' "
              f"(¿Pi apagada o inalcanzable?) -- si esta corrida da 'sin_respuesta' "
              f"inesperados, verificar a mano con scripts/pi.sh status agent {host_rsu}.")


def _verificar_tailscale_directo(host_rsu: str, red_lan_prefijo: str = "192.168.18.") -> None:
    """Solo para config=pi-lan: confirma que la Pi alcanza a la laptop por
    Tailscale con camino DIRECTO por la LAN (no relevado por DERP), para
    que 'pi-lan' describa de verdad un enlace Wi-Fi/LAN y no termine
    midiendo, sin darse cuenta, un camino por internet. Aborta si no se
    puede confirmar -- no se asume."""
    r = _pi_sh("tailscale-ping", host_rsu)
    salida = r.stdout + r.stderr
    if red_lan_prefijo not in salida:
        raise SystemExit(
            f"[campaña] config=pi-lan, pero 'tailscale ping' desde la Pi no muestra un "
            f"camino directo por la LAN ({red_lan_prefijo}x) hacia la laptop "
            f"(scripts/pi.sh tailscale-ping {host_rsu}):\n{salida}\n"
            f"Si está yendo por DERP o por una IP pública, esto no es la configuración "
            f"'Wi-Fi local' que describe pi-lan -- revisar la red antes de seguir.")
    print(f"[campaña] tailscale ping confirma camino directo por la LAN ({red_lan_prefijo}x): OK")


# Descripción explícita del enlace real para cada config -- "pi-lan" es
# solo el nombre genérico del código (ver docstring del módulo); sin esto,
# config.json/figuras/tablas podrían leerse como si "pi-lan" fuera un
# enlace Ethernet cableado, cuando hoy es Wi-Fi vía Tailscale.
# [REVISAR con asesor] limitación: el enlace es inalámbrico en el extremo
# de la RSU (y posiblemente también en el de la laptop, ver
# _enlace_laptop) -- no es una "red de área local" cableada.
DESCRIPCION_ENLACE_RSU = {
    "pi-lan": "Wi-Fi (wlan0 de la Pi) alcanzado por Tailscale -- 'pi-lan' es "
              "el nombre genérico del código, NO una conexión Ethernet cableada",
    "pi-4g": "módem celular 4G SIMCom SIM7670G (usb0 de la Pi) alcanzado por "
             "Tailscale, ver docs/MODEM_4G.md",
}


def _ip_interfaz_de_estado(estado_texto: str, interfaz: str) -> str | None:
    m = re.search(rf"dev {re.escape(interfaz)} proto dhcp src (\S+)", estado_texto)
    return m.group(1) if m else None


def _enlace_laptop() -> str:
    """Mejor esfuerzo: por qué interfaz sale el tráfico por defecto de
    ESTA laptop (Wi-Fi o cable) -- limitación [REVISAR con asesor] que
    conviene registrar, no asumir, porque también afecta el tramo
    laptop<->broker/Pi en pi-lan/pi-4g. Solo implementado para Windows."""
    if platform.system() != "Windows":
        return "desconocido (detección solo implementada para Windows)"
    try:
        ps = ("Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
              "Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty InterfaceAlias")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, text=True, timeout=10)
        alias = r.stdout.strip()
        if not alias:
            return "desconocido (no se pudo determinar la interfaz de ruta por defecto)"
        alias_l = alias.lower()
        if any(s in alias_l for s in ("wi-fi", "wifi", "wireless", "wlan")):
            tipo = "Wi-Fi"
        elif any(s in alias_l for s in ("ethernet", "lan")):
            tipo = "cable (Ethernet)"
        else:
            tipo = "desconocido"
        return f"{tipo} (interfaz '{alias}')"
    except (OSError, subprocess.TimeoutExpired):
        return "desconocido (no se pudo consultar Get-NetRoute)"


def _contar_conexiones_broker(ruta_log: Path) -> int:
    """Cuenta cuántas veces el proceso de ese log imprimió que se conectó
    al broker MQTT ('Conectado al broker'). Más de una vez en una sola
    repetición de config=local (donde el agente/servidor se relanza
    fresco en cada repetición) es la firma de un choque de client_id: algo
    más lo está expulsando y se está reconectando en bucle -- no un
    comportamiento normal a ignorar."""
    try:
        contenido = ruta_log.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    return contenido.count("Conectado al broker")


def _verificar_una_sola_conexion(rep_dir: Path) -> None:
    for nombre in ("agent.log", "servidor.log"):
        ruta = rep_dir / nombre
        conexiones = _contar_conexiones_broker(ruta)
        if conexiones > 1:
            raise SystemExit(
                f"[campaña] {ruta} tiene {conexiones} conexiones al broker en UNA sola "
                f"repetición -- choque de client_id (otro cliente con el mismo ID lo está "
                f"expulsando y se reconecta en bucle; p. ej. rsu-agent.service de la Pi "
                f"apuntando al broker de esta laptop). Verificar con "
                f"'scripts/pi.sh status agent <host>' y detenerlo con "
                f"'scripts/pi.sh stop agent <host>' si corresponde. Ver "
                f"docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md.")


def _reloj_pi(host: str) -> str:
    r = _pi_sh("clock", host)
    return (r.stdout + r.stderr).strip()


# Interfaz de red por la que DEBE llegarse a la Pi en cada config (ver
# scripts/red_4g.sh y docs/MODEM_4G.md, sección 4): la ruta por defecto de
# MENOR métrica es la que el kernel usa realmente.
INTERFAZ_ESPERADA = {"pi-4g": "usb0", "pi-lan": "wlan0"}


def _interfaz_default_activa(estado_texto: str) -> str | None:
    rutas = re.findall(r"^default via \S+ dev (\S+).*?metric (\d+)", estado_texto, re.MULTILINE)
    if not rutas:
        return None
    return min(rutas, key=lambda par: int(par[1]))[0]


def _estado_red_pi(host: str) -> str:
    r = _pi_sh("red", "estado", host)
    return (r.stdout + r.stderr).strip()


def _verificar_modo_red(config: str, estado_texto: str) -> None:
    """Aborta si la ruta por defecto de la Pi (métrica más baja de
    'default via ... dev <if>' en el 'ip route' de 'scripts/pi.sh red
    estado') no corresponde a la config pedida -- p. ej. pi-4g con wlan0
    como ruta por defecto en vez de usb0 (ver docs/MODEM_4G.md, sección 4:
    modo normal vs. modo campaña)."""
    esperada = INTERFAZ_ESPERADA.get(config)
    if esperada is None:
        return
    activa = _interfaz_default_activa(estado_texto)
    if activa != esperada:
        modo = "modo-campana" if config == "pi-4g" else "modo-normal"
        raise SystemExit(
            f"[campaña] modo de red inesperado para --config {config}: la ruta por "
            f"defecto de la Pi usa '{activa}', se esperaba '{esperada}' "
            f"(scripts/pi.sh red estado):\n{estado_texto}\n"
            f"Corregir con 'scripts/pi.sh red {modo} <host>' antes de seguir.")
    print(f"[campaña] modo de red OK para --config {config}: ruta por defecto = '{activa}'")


def _trayectoria_con_ruido(base: Path, destino: Path, semilla: int, sigma_pos_m: float) -> None:
    """Copia `base` a `destino` con ruido gaussiano de posición (mismo
    patrón que scripts/trayectorias/generar.py): no se perturban las
    filas detenidas (velocidad 0), para no inventar un salto de posición
    con el vehículo parado."""
    rnd = random.Random(semilla)
    with base.open(newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "lat", "lon", "rumbo_deg", "velocidad_kmh"])
        for fila in filas:
            lat, lon = float(fila["lat"]), float(fila["lon"])
            if float(fila["velocidad_kmh"]) > 0:
                lat, lon = desplazar(lat, lon, rnd.uniform(0, 360), abs(rnd.gauss(0, sigma_pos_m)))
            w.writerow([fila["t_s"], f"{lat:.7f}", f"{lon:.7f}", fila["rumbo_deg"], fila["velocidad_kmh"]])


def _esperar_en_log(ruta_log: Path, fragmento: str, timeout: float = 8.0, intervalo: float = 0.1) -> bool:
    """Espera hasta `timeout` s a que `fragmento` aparezca en `ruta_log`.
    Los procesos lanzados aquí corren con `-u` (stdout sin búfer), así que
    lo que imprimen ya está en el archivo apenas se ejecuta el print() --
    esto reemplaza los `time.sleep()` fijos de antes (que no confirmaban
    nada, solo esperaban "lo suficiente la mayoría de las veces") por una
    espera de la condición real que cada llamada necesita."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            contenido = ruta_log.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            contenido = ""
        if fragmento in contenido:
            return True
        time.sleep(intervalo)
    return False


def _lanzar_local(rep_dir: Path) -> tuple[subprocess.Popen, subprocess.Popen]:
    """config=local: esta máquina hace también de RSU. Devuelve
    (controller, agent) ya lanzados Y CONFIRMADOS listos (puerto TCP
    escuchando / suscrito al broker MQTT) -- no solo "tras dormir un rato
    que normalmente alcanza". servidor se lanza aparte (función
    _lanzar_servidor), igual en los tres config."""
    entorno = dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir), RSU_ID=RSU_ID,
                   CONTROLLER_PORT=str(CONTROLLER_PORT), SNMP_PORT=str(SNMP_PORT))
    ctrl_log = rep_dir / "controller.log"
    ctrl = subprocess.Popen([PY, "-u", str(RAIZ / "controller" / "controller_emulator.py"),
                             "--port", str(CONTROLLER_PORT)],
                            stdout=ctrl_log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
                            env=entorno, cwd=RAIZ)
    if not _esperar_en_log(ctrl_log, "escuchando en"):
        _detener(ctrl)
        raise SystemExit(
            f"[campaña] controller_emulator.py no reportó estar escuchando en "
            f"{CONTROLLER_PORT} tras 8 s -- ver {ctrl_log}. ¿Puerto ocupado por un proceso "
            f"de una corrida anterior que no se cerró del todo?")
    agent_log = rep_dir / "agent.log"
    agent = subprocess.Popen([PY, "-u", str(RAIZ / "agent" / "rsu_middleware.py")],
                             stdout=agent_log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
                             env=entorno, cwd=RAIZ)
    if not _esperar_en_log(agent_log, "[middleware] Conectado al broker MQTT"):
        _detener(ctrl, agent)
        raise SystemExit(
            f"[campaña] agent/rsu_middleware.py no reportó conexión al broker MQTT tras 8 s -- "
            f"ver {agent_log}. Si el broker no está corriendo, eso explica un 'sin_respuesta' "
            f"(ver docs/ARRANQUE_BROKER_LAPTOP.md), no hay que asumir otra causa sin revisar este log.")
    return ctrl, agent


def _lanzar_servidor(rep_dir: Path, grafo: str, registro: Path, broker_host: str, broker_port: int
                     ) -> subprocess.Popen:
    entorno = dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir), GRAFO_SINTETICO=grafo,
                   REGISTRO_RSU_PATH=str(registro), MQTT_BROKER_HOST=broker_host,
                   MQTT_BROKER_PORT=str(broker_port))
    log = rep_dir / "servidor.log"
    p = subprocess.Popen([PY, "-u", str(RAIZ / "servidor" / "main.py")],
                        stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
                        env=entorno, cwd=RAIZ)
    # Verificación del lado del servidor: si servidor/main.py no llega a
    # conectarse y suscribirse al broker ANTES de que las OBU empiecen a
    # publicar (_correr_obus), el MI/MP inicial de la misión se pierde sin
    # dejar rastro en la RSU -- un "sin_respuesta" que antes se atribuía a
    # otras causas sin haber revisado este log. servidor/main.py imprime
    # "[servidor] Conectado al broker" en su _on_connect justo antes de
    # suscribirse (ver servidor/main.py).
    if not _esperar_en_log(log, "[servidor] Conectado al broker"):
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        raise SystemExit(
            f"[campaña] servidor/main.py no reportó conexión al broker "
            f"({broker_host}:{broker_port}) tras 8 s -- ver {log}. No se lanzan las OBU: "
            f"con el servidor sin conectar se perdería su misión sin ningún rastro en la RSU. "
            f"Verificar que el broker esté corriendo y sea alcanzable "
            f"(docs/ARRANQUE_BROKER_LAPTOP.md / deploy/systemd/README.md).")
    return p


def _correr_obus(rep_dir: Path, obus: list[tuple[str, str]], trayectorias: list[Path],
                 broker_host: str, broker_port: int, factor: float) -> None:
    entorno = dict(os.environ, RSU_EVENTOS_DIR=str(rep_dir))
    procesos = []
    for (obu_id, _nombre), tray in zip(obus, trayectorias):
        log = (rep_dir / f"{obu_id}.log").open("w", encoding="utf-8")
        p = subprocess.Popen([PY, "-u", str(RAIZ / "gateway" / "obu_emulada.py"),
                             "--broker-host", broker_host, "--broker-port", str(broker_port),
                             "--trayectoria", str(tray), "--factor", str(factor), "--obu-id", obu_id],
                            stdout=log, stderr=subprocess.STDOUT, env=entorno, cwd=RAIZ)
        procesos.append(p)
        if len(obus) > 1:
            time.sleep(0.2)  # mismo escalonado que correr_e2e_conflicto.sh
    for p in procesos:
        p.wait()


def _detener(*procesos: subprocess.Popen) -> None:
    """Termina cada proceso y CONFIRMA cómo salió -- no solo que wait() no
    hizo timeout. Si terminate() no bastó y hubo que matarlo con kill(), o
    si el código de salida no es el de una terminación limpia pedida por
    este script, lo reporta: antes esto se asumía en silencio entre
    repeticiones, y un proceso que quedaba a medio morir podía contaminar
    la siguiente (puerto ocupado, conexión MQTT zombie)."""
    for p in procesos:
        if p is None:
            continue
        p.terminate()
    for p in procesos:
        if p is None:
            continue
        forzado = False
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forzado = True
            p.kill()
            p.wait(timeout=5)
        # terminate()/kill() en Windows no tiene señales POSIX: Popen los
        # traduce a TerminateProcess(handle, 1), asi que returncode==1 ES
        # la salida limpia esperada ahi. En POSIX, terminate()/kill() dan
        # returncode negativo (-SIGTERM/-SIGKILL).
        if platform.system() == "Windows":
            limpio = p.returncode == 1
        else:
            limpio = p.returncode in (0, -15, -9)
        if forzado or not limpio:
            print(f"[campaña] AVISO: pid={p.pid}"
                  f"{' no respondió a terminate(), se forzó kill()' if forzado else ''}"
                  f" -- código de salida={p.returncode}. Revisar su log antes de confiar "
                  f"en que la siguiente repetición arranca limpia.")


def _puerto_libre(puerto: int, proto: str) -> bool:
    import socket

    tipo = socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM
    s = socket.socket(socket.AF_INET, tipo)
    try:
        s.bind(("127.0.0.1", puerto))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _esperar_puertos_libres(puertos: list[tuple[int, str]], intentos: int = 20, espera: float = 0.25) -> None:
    """config=local relanza controller/agent en los MISMOS puertos en cada
    repeticion. p.wait() en _detener() ya confirma que el proceso anterior
    salio del todo, pero el SO puede demorar un instante en liberar el
    socket (mas el TCP del controlador que el UDP del agente SNMP) -- esto
    verifica antes de seguir, en vez de asumirlo."""
    for intento in range(intentos):
        libres = {(p, proto): _puerto_libre(p, proto) for p, proto in puertos}
        if all(libres.values()):
            return
        time.sleep(espera)
    ocupados = [k for k, v in libres.items() if not v]
    print(f"[campaña] AVISO: {ocupados} sigue(n) ocupado(s) tras {intentos * espera:.1f} s de espera "
          f"-- el siguiente lanzamiento puede fallar o comportarse de forma rara.")


def _memoria_libre_mb() -> float | None:
    """Memoria disponible en la máquina que corre esta campaña (la laptop,
    en los tres config), en MB. Sin dependencias nuevas: ctypes en Windows
    (GlobalMemoryStatusEx), /proc/meminfo en Linux. Se registra ANTES de
    cada escenario para poder CONFIRMAR o DESCARTAR con un dato real si la
    memoria tiene algo que ver con un 'sin_respuesta' -- no para asumirlo
    sin medirlo."""
    try:
        if platform.system() == "Windows":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            estado = _MemoryStatusEx()
            estado.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
                return None
            return estado.ullAvailPhys / (1024 * 1024)
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for linea in fh:
                if linea.startswith("MemAvailable:"):
                    return float(linea.split()[1]) / 1024  # kB -> MB
        return None
    except (OSError, ValueError):
        return None


def _repartir_eventos_pi(corrida: Path, host: str, ventanas: list[tuple[str, int, int]]) -> None:
    """Después de `scripts/pi.sh fetch <host>` (copia resultados/ de la Pi
    a resultados/<host>/ en esta máquina), reparte las filas de
    resultados/<host>/eventos/eventos_rsu_1.csv y eventos_ctrl_1.csv entre
    las carpetas rep_XX/ de esta corrida, por la ventana de tiempo
    [t_ini, t_fin] en ns que cada repetición anotó en main()."""
    from common.events import FIELDNAMES, iter_eventos  # noqa: E402

    origen = RAIZ / "resultados" / host / "eventos"
    if not origen.exists():
        print(f"[campaña] AVISO: no se encontró '{origen}' tras el fetch -- "
              f"¿RSU_EVENTOS_DIR de la Pi no es el default 'resultados/eventos'?")
        return
    eventos = list(iter_eventos(origen))
    for nombre_dir, t_ini, t_fin in ventanas:
        rep_dir = corrida / nombre_dir
        por_nodo: dict[str, list[dict]] = {}
        for e in eventos:
            if t_ini <= e["ts_ns"] <= t_fin:
                por_nodo.setdefault(e["nodo"], []).append(e)
        for nodo, filas in por_nodo.items():
            with (rep_dir / f"eventos_{nodo}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(FIELDNAMES)
                for e in sorted(filas, key=lambda x: x["ts_ns"]):
                    w.writerow([e["ts_ns"], e["nodo"], e["tipo_evento"], e["id_solicitud"],
                               json.dumps(e["extra"], ensure_ascii=False, separators=(",", ":"))])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escenario", required=True, choices=list(ESCENARIOS))
    ap.add_argument("--meta-por-condicion", type=int, default=META_POR_CONDICION_DEFAULT,
                     help="repeticiones mínimas por condición de llegada (verde/ámbar-todo_rojo/"
                          "rojo_general) antes de parar")
    ap.add_argument("--tope-repeticiones", type=int, default=TOPE_REPETICIONES_DEFAULT,
                     help="máximo de repeticiones aunque no se cubran las 3 cuotas")
    ap.add_argument("--factor", type=float, default=1.0, help="1 = tiempo real (obligatorio para medir)")
    ap.add_argument("--config", required=True, choices=["local", "pi-lan", "pi-4g"])
    ap.add_argument("--host-rsu", default="rsu", help="alias SSH de scripts/pi.sh (ignorado en config=local)")
    ap.add_argument("--broker-host", required=True)
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--semilla-base", type=int, default=1)
    ap.add_argument("--pausa-max", type=float, default=PAUSA_MAX_DEFAULT_S)
    ap.add_argument("--sigma-pos", type=float, default=5.0, help="ruido GNSS, m (1 sigma)")
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "campana"))
    args = ap.parse_args()

    _verificar_sin_agente_local_huerfano()
    if args.config != "local":
        _verificar_pi_activa(args.host_rsu)
        if args.config == "pi-lan":
            _verificar_tailscale_directo(args.host_rsu)
    else:
        _verificar_pi_agente_inactivo(args.host_rsu)

    estado_red_inicio = None
    if args.config in ("pi-4g", "pi-lan"):
        estado_red_inicio = _estado_red_pi(args.host_rsu)
        _verificar_modo_red(args.config, estado_red_inicio)

    esc = ESCENARIOS[args.escenario]
    registro_path = FIXTURES / esc["registro"]

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrida = Path(args.salida) / f"{ts}_{args.escenario}_{args.config}"
    corrida.mkdir(parents=True, exist_ok=True)

    reloj_inicio = _reloj_pi(args.host_rsu) if args.config != "local" else None

    enlace_rsu_descripcion = enlace_rsu_ip = enlace_laptop = limitacion_enlace = None
    if args.config in ("pi-4g", "pi-lan"):
        enlace_rsu_descripcion = DESCRIPCION_ENLACE_RSU.get(args.config)
        interfaz = INTERFAZ_ESPERADA.get(args.config)
        enlace_rsu_ip = _ip_interfaz_de_estado(estado_red_inicio or "", interfaz) if interfaz else None
        enlace_laptop = _enlace_laptop()
        limitacion_enlace = (
            "[REVISAR con asesor] El enlace entre la RSU y el broker es inalámbrico "
            f"({enlace_rsu_descripcion}); si 'enlace_laptop' también es Wi-Fi, ningún "
            "tramo medido en esta corrida es una conexión cableada, pese al nombre "
            f"genérico '{args.config}' del código.")

    config = {
        "fecha_inicio": datetime.now().isoformat(timespec="seconds"),
        "commit": _commit(),
        "escenario": args.escenario,
        "config": args.config,
        "factor": args.factor,
        "broker": f"{args.broker_host}:{args.broker_port}",
        "host_rsu": args.host_rsu if args.config != "local" else None,
        "enlace_rsu_descripcion": enlace_rsu_descripcion,
        "enlace_rsu_ip": enlace_rsu_ip,
        "enlace_laptop": enlace_laptop,
        "limitacion_enlace": limitacion_enlace,
        "meta_por_condicion": args.meta_por_condicion,
        "tope_repeticiones": args.tope_repeticiones,
        "semilla_base": args.semilla_base,
        "pausa_max_s": args.pausa_max,
        "sigma_pos_m": args.sigma_pos,
        "reloj_pi_inicio": reloj_inicio,
        "estado_red_inicio": estado_red_inicio,
        # Memoria libre de la laptop ANTES de correr el escenario (ver
        # _memoria_libre_mb): referencia para confirmar o descartar con un
        # dato real si la memoria tuvo algo que ver con un 'sin_respuesta',
        # en vez de asumirlo.
        "memoria_libre_mb_inicio": _memoria_libre_mb(),
    }
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    ventanas: list[tuple[str, int, int]] = []
    conteo_por_condicion: dict[str, int] = {c: 0 for c in CONDICIONES_LLEGADA}
    condicion_por_repeticion: dict[str, str | None] = {}
    print(f"Corrida {corrida.name}: cuotas por condición={args.meta_por_condicion} "
          f"(tope {args.tope_repeticiones} repeticiones), escenario={args.escenario}, "
          f"config={args.config}, broker={config['broker']}, "
          f"memoria_libre_mb_inicio={config['memoria_libre_mb_inicio']}")

    i = 0
    while i < args.tope_repeticiones and any(
        conteo_por_condicion[c] < args.meta_por_condicion for c in CONDICIONES_LLEGADA
    ):
        i += 1
        rep_nombre = f"rep_{i:02d}"
        rep_dir = corrida / rep_nombre
        rep_dir.mkdir(parents=True, exist_ok=True)
        semilla = args.semilla_base + i

        # obu_id unico por repeticion (sufijo -rNN): varias repeticiones de
        # la misma campana se analizan juntas (--dir <corrida> recorre
        # todas las rep_XX/), y los eventos se correlacionan por seq
        # DENTRO de (obu_id, seq) -- con el mismo obu_id en todas las
        # repeticiones, el seq=1 de rep_02 pisaria al de rep_01.
        obus_rep = [(f"{obu_id}-r{i:02d}", nombre_base) for obu_id, nombre_base in esc["obus"]]

        trayectorias = []
        for obu_id, nombre_base in obus_rep:
            destino = rep_dir / f"trayectoria_{obu_id}.csv"
            _trayectoria_con_ruido(FIXTURES / nombre_base, destino, semilla, args.sigma_pos)
            trayectorias.append(destino)

        pausa = random.Random(semilla + 10_000).uniform(0, args.pausa_max)
        print(f"[{i}, tope={args.tope_repeticiones}] {rep_nombre}: semilla={semilla}, pausa={pausa:.1f} s, "
              f"conteo_por_condicion={conteo_por_condicion}")

        t_ini_ns = time.time_ns()
        ctrl = agent = None
        if args.config == "local":
            # IMPORTANTE: la pausa va DESPUES de lanzar el controlador, no
            # antes. En config=local el controlador se relanza fresco en
            # cada repeticion (ciclo de fases reiniciado desde el mismo
            # estado inicial); si la pausa fuera antes de lanzarlo, el
            # tiempo relativo entre "controlador arranca" y "la OBU
            # dispara la solicitud" seria casi constante entre
            # repeticiones (la trayectoria tarda siempre lo mismo en
            # llegar a la geocerca) y TODAS caerian en la misma fase del
            # ciclo -- justo lo que se queria evitar. Con config=pi-*, el
            # controlador real ya viene corriendo de antes (no se
            # relanza), asi que ahi la pausa cumple su proposito aunque
            # vaya antes.
            ctrl, agent = _lanzar_local(rep_dir)
        else:
            time.sleep(pausa)
        servidor = _lanzar_servidor(rep_dir, esc["grafo"], registro_path, args.broker_host, args.broker_port)
        if args.config == "local":
            time.sleep(pausa)
        try:
            _correr_obus(rep_dir, obus_rep, trayectorias, args.broker_host, args.broker_port, args.factor)
            time.sleep(3.0)  # drenar M2/ME finales, igual que correr_e2e*.sh
        finally:
            _detener(servidor, ctrl, agent)
            if args.config == "local":
                # controller/agent de la SIGUIENTE repeticion se relanzan
                # en los mismos puertos (CONTROLLER_PORT, SNMP_PORT): el
                # SO puede demorar un instante en liberar el socket
                # despues de que el proceso ya salio (_detener ya lo
                # confirmo) -- verificarlo aqui, no asumirlo.
                _esperar_puertos_libres([(CONTROLLER_PORT, "tcp"), (SNMP_PORT, "udp")])
        if args.config == "local":
            _verificar_una_sola_conexion(rep_dir)
        t_fin_ns = time.time_ns()
        ventanas.append((rep_nombre, t_ini_ns, t_fin_ns))

        condicion = _condicion_de_repeticion(rep_dir, args.config, args.host_rsu, t_ini_ns, t_fin_ns)
        condicion_por_repeticion[rep_nombre] = condicion
        if condicion is not None:
            conteo_por_condicion[condicion] += 1
        print(f"    -> condición de llegada: {condicion!r} "
              f"(conteo acumulado: {conteo_por_condicion})")

    tope_alcanzado = i >= args.tope_repeticiones and any(
        conteo_por_condicion[c] < args.meta_por_condicion for c in CONDICIONES_LLEGADA
    )
    config["meta_por_condicion_cubierta"] = not tope_alcanzado
    config["tope_alcanzado"] = tope_alcanzado
    config["repeticiones_corridas"] = i
    config["conteo_por_condicion"] = conteo_por_condicion
    config["condicion_por_repeticion"] = condicion_por_repeticion
    print(f"\nCuotas por condición: {conteo_por_condicion} "
          f"(meta={args.meta_por_condicion} c/u, {'TOPE ALCANZADO sin cubrir las 3' if tope_alcanzado else 'cubiertas'}, "
          f"{i} repeticiones corridas)")

    if args.config != "local":
        print("[campaña] Trayendo eventos de la RSU real (scripts/pi.sh fetch)...")
        r = _pi_sh("fetch", args.host_rsu)
        print(r.stdout, r.stderr)
        _repartir_eventos_pi(corrida, args.host_rsu, ventanas)

    config["fecha_fin"] = datetime.now().isoformat(timespec="seconds")
    config["reloj_pi_fin"] = _reloj_pi(args.host_rsu) if args.config != "local" else None
    config["estado_red_fin"] = (
        _estado_red_pi(args.host_rsu) if args.config in ("pi-4g", "pi-lan") else None
    )
    (corrida / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nListo: {corrida}")
    print(f"Análisis: {PY} scripts/analisis/lazo_centralizado.py --dir {corrida}")


if __name__ == "__main__":
    main()
