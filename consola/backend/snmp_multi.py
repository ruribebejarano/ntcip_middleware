"""Sondeo SNMPv3 de VARIAS RSU para la demo multi-RSU (~1 Hz por RSU, cada
una en su host:puerto, ver consola/backend/demo_rsu.py).

Lee los objetos NTCIP 1202 de estado de fase que ya expone
agent/rsu_middleware.py (phaseStatusGroupReds/Yellows/Greens, grupo 1,
bit 0 = fase 1; mismas constantes que centro_control/panel/ntcip_objetos.py)
en un solo GET de tres varbinds por RSU.

A diferencia de consola/backend/snmp_poller.py (pysnmp sincrono, un GET a
la vez), aqui se usa la API asyncio de pysnmp en UN hilo con su propio
event loop y UNA tarea por RSU: una RSU que no responde solo espera su
propio timeout y queda "sin conexion", sin frenar el sondeo de las demas.
Sigue habiendo un unico hilo tocando pysnmp (ver la nota "pysnmp + asyncio
en Windows" de docs/CONSOLA.md): en modo multi-RSU, consola/backend/api.py
no arranca snmp_poller.py."""

from __future__ import annotations

import asyncio
import threading
import time

from pysnmp.hlapi.asyncio import (
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    getCmd,
    usmAesCfb128Protocol,
    usmHMAC192SHA256AuthProtocol,
)

from centro_control.panel.ntcip_objetos import PHASESTATUSGROUPGREENS, PHASESTATUSGROUPREDS, PHASESTATUSGROUPYELLOWS
from consola.backend import config, demo_rsu
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

OIDS_FASE = (PHASESTATUSGROUPREDS, PHASESTATUSGROUPYELLOWS, PHASESTATUSGROUPGREENS)


def _usm() -> UsmUserData:
    return UsmUserData(config.SNMP_USER, authKey=config.SNMP_AUTH_KEY, privKey=config.SNMP_PRIV_KEY,
                       authProtocol=usmHMAC192SHA256AuthProtocol, privProtocol=usmAesCfb128Protocol)


def _fase(red: bool, yellow: bool, green: bool) -> str:
    # Mismo criterio que consola/static/js/monitoreo.js (aplicarSemaforo).
    return "rojo" if red else "ambar" if yellow else "verde" if green else "?"


async def _leer(engine: SnmpEngine, usm: UsmUserData, destino: UdpTransportTarget) -> dict:
    t0 = time.perf_counter()
    err_ind, err_status, _idx, var_binds = await getCmd(
        engine, usm, destino, ContextData(), *(ObjectType(ObjectIdentity(o)) for o in OIDS_FASE))
    rtt_ms = (time.perf_counter() - t0) * 1000
    if err_ind:
        return {"conectado": False, "error": str(err_ind)}
    if err_status:
        return {"conectado": False, "error": err_status.prettyPrint()}
    try:
        red, yellow, green = (bool(int(v) & 1) for _o, v in var_binds)
    except (TypeError, ValueError):
        return {"conectado": False, "error": "respuesta no numerica: " + ", ".join(v.prettyPrint() for _o, v in var_binds)}
    return {"conectado": True, "error": None, "red": red, "yellow": yellow, "green": green,
            "fase": _fase(red, yellow, green), "rtt_ms": round(rtt_ms, 1)}


async def _sondear_rsu(engine: SnmpEngine, usm: UsmUserData, rsu: dict) -> None:
    rsu_id = rsu["rsu_id"]
    if rsu["snmp_port"] is None:
        estado = {"rsu_id": rsu_id, "conectado": False, "error": rsu["fuente_snmp"], "ts": time.time()}
        ESTADO.set_rsu_fase(rsu_id, estado)
        BUS.publicar("rsu_fase", estado)
        return
    destino = UdpTransportTarget((rsu["snmp_host"], rsu["snmp_port"]),
                                 timeout=config.SNMP_MULTI_TIMEOUT_S, retries=0)
    etiqueta = f"RSU {rsu_id} ({rsu['snmp_host']}:{rsu['snmp_port']})"
    previo = None
    while True:
        t0 = time.time()
        try:
            lectura = await _leer(engine, usm, destino)
        except Exception as exc:  # noqa: BLE001 -- una RSU rota no debe tumbar el hilo de las demas
            lectura = {"conectado": False, "error": f"{type(exc).__name__}: {exc}"}
        estado = {"rsu_id": rsu_id, **lectura, "ts": t0}
        ESTADO.set_rsu_fase(rsu_id, estado)
        BUS.publicar("rsu_fase", estado)
        clave = (lectura.get("conectado"), lectura.get("fase"), lectura.get("error"))
        if clave != previo:
            # Solo cambios (no cada segundo): mismo criterio que snmp_poller.py.
            REGISTRO.registrar("Consola", etiqueta, "SNMPv3", {"accion": "GET", "oids": list(OIDS_FASE)},
                               {k: lectura.get(k) for k in ("conectado", "fase", "error")})
            previo = clave
        await asyncio.sleep(max(0.05, config.SNMP_MULTI_PERIODO_S - (time.time() - t0)))


async def _principal() -> None:
    engine = SnmpEngine()
    usm = _usm()
    await asyncio.gather(*(_sondear_rsu(engine, usm, r) for r in demo_rsu.rsus()))


def _correr() -> None:
    loop = asyncio.SelectorEventLoop() if hasattr(asyncio, "SelectorEventLoop") else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_principal())


def iniciar() -> threading.Thread:
    hilo = threading.Thread(target=_correr, name="snmp-multi", daemon=True)
    hilo.start()
    return hilo
