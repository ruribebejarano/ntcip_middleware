"""RSU que muestra la consola en modo multi-RSU: cruza el registro de RSU
(intersecciones y accesos, gateway/geometria.py::cargar_registro) con el
estado.json que escribe scripts/demo/lanzar_rsus.ps1 (puerto SNMP de cada
RSU levantada en esta maquina).

Una RSU del registro que no aparezca en el estado de la demo se sondea en
SNMP_HOST/SNMP_PORT de consola/.env solo si su rsu_id es RSU_ID (la Pi);
si no, queda sin destino SNMP y la consola la muestra "sin conexion" en vez
de inventar un puerto."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from gateway.geometria import cargar_registro

from consola.backend import config


def _leer_json(ruta: Path) -> dict | None:
    try:
        # utf-8-sig: tolera el BOM si el archivo se edito a mano en PowerShell.
        return json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def estado_demo() -> dict | None:
    if not config.CONSOLA_ESTADO_DEMO:
        return None
    return _leer_json(Path(config.CONSOLA_ESTADO_DEMO))


def ruta_registro() -> Path:
    if config.CONSOLA_REGISTRO_RSU:
        return Path(config.CONSOLA_REGISTRO_RSU)
    e = estado_demo()
    if e and e.get("registro"):
        return Path(e["registro"])
    return config.REGISTRO_RSU


@lru_cache(maxsize=1)
def rsus() -> tuple[dict, ...]:
    """Lista fija para toda la sesion de la consola (el lanzador no cambia
    puertos de una RSU ya levantada; si se relanza la demo, reiniciar la
    consola)."""
    puertos = {str(r["rsu_id"]): r for r in (estado_demo() or {}).get("rsu", [])}
    salida = []
    for inter in cargar_registro(ruta_registro()):
        lanzada = puertos.get(inter.rsu_id)
        if lanzada:
            host, port, fuente = lanzada.get("snmp_host", "127.0.0.1"), int(lanzada["snmp_port"]), "lanzador"
        elif inter.rsu_id == config.RSU_ID:
            host, port, fuente = config.SNMP_HOST, config.SNMP_PORT, "consola/.env"
        else:
            host, port, fuente = None, None, "sin puerto SNMP conocido"
        salida.append({
            "rsu_id": inter.rsu_id, "interseccion_id": inter.interseccion_id,
            "lat": inter.lat, "lon": inter.lon,
            "snmp_host": host, "snmp_port": port, "fuente_snmp": fuente,
        })
    return tuple(salida)


def resumen() -> dict:
    e = estado_demo()
    return {
        "modo_multi_rsu": config.MODO_MULTI_RSU,
        "registro": str(ruta_registro()),
        "estado_demo": config.CONSOLA_ESTADO_DEMO or None,
        "demo_dir": (e or {}).get("dir"),
        "rsus": list(rsus()) if config.MODO_MULTI_RSU else [],
    }
