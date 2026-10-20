"""Pantalla "Ensayos y metricas": lista corridas de resultados/lazo_emulado/,
calcula las metricas con scripts/analisis/lazo_emulado.py (analizar/cargar)
y los datos crudos de graficos para los graficos con scripts/analisis/
graficos_campana.py (metricas) -- ambos importados tal cual, sin duplicar
ninguna formula. "Exportar figuras" y "Tabla LaTeX" lanzan el script de
graficos como subproceso (genera PDF/PNG + .tex), igual que se haria a mano."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

from consola.backend import config
from consola.backend.registro_comandos import REGISTRO

RAIZ = config.RAIZ


def _importar(nombre_modulo: str, ruta: Path):
    if nombre_modulo in sys.modules:
        return sys.modules[nombre_modulo]
    spec = importlib.util.spec_from_file_location(nombre_modulo, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre_modulo] = modulo
    spec.loader.exec_module(modulo)
    return modulo


_lazo = _importar("_consola_analisis_lazo_emulado", RAIZ / "scripts" / "analisis" / "lazo_emulado.py")
_graficos = _importar("_consola_analisis_graficos_campana", RAIZ / "scripts" / "analisis" / "graficos_campana.py")

DIR_RSU_FETCHED = RAIZ / "resultados" / "rsu" / "eventos"


def _dirs_para(nombre_corrida: str) -> list[Path]:
    dirs = [config.DIR_LAZO_EMULADO / nombre_corrida]
    if DIR_RSU_FETCHED.is_dir():
        dirs.append(DIR_RSU_FETCHED)
    return dirs


def listar_corridas() -> list[dict]:
    if not config.DIR_LAZO_EMULADO.is_dir():
        return []
    corridas = []
    for carpeta in sorted(config.DIR_LAZO_EMULADO.iterdir(), reverse=True):
        if not carpeta.is_dir():
            continue
        cfg_path = carpeta / "config.json"
        cfg = {}
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cfg = {"error": "config.json invalido"}
        corridas.append({"nombre": carpeta.name, "config": cfg})
    return corridas


def resumen_corrida(nombre_corrida: str) -> dict | None:
    carpeta = config.DIR_LAZO_EMULADO / nombre_corrida
    if not carpeta.is_dir():
        return None
    eventos = _lazo.cargar(_dirs_para(nombre_corrida))
    filas, global_ = _lazo.analizar(eventos)
    m = _graficos.metricas(eventos)
    cfg_path = carpeta / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    return {"nombre": nombre_corrida, "config": cfg, "global": global_, "por_solicitud": filas, "graficos": m}


def comparar_corridas(nombres_y_etiquetas: list[tuple[str, str]]) -> dict:
    """nombres_y_etiquetas: [(nombre_corrida, etiqueta), ...]. Devuelve, por
    condicion: m (datos crudos de graficos_campana.metricas), resumen
    (lazo_emulado.analizar) y el PDR con su intervalo de Wilson al 95%."""
    condiciones = []
    for nombre, etiqueta in nombres_y_etiquetas:
        carpeta = config.DIR_LAZO_EMULADO / nombre
        if not carpeta.is_dir():
            continue
        eventos = _lazo.cargar(_dirs_para(nombre))
        _, global_ = _lazo.analizar(eventos)
        m = _graficos.metricas(eventos)
        pdr_env, pdr_rx = global_["mensajes_enviados"], global_["mensajes_recibidos"]
        condiciones.append({
            "nombre": nombre, "etiqueta": etiqueta, "global": global_, "graficos": m,
            "pdr_wilson": _wilson(pdr_rx, pdr_env),
        })
    return {"condiciones": condiciones}


def _wilson(exitos: int, n: int, z: float = 1.959963984540054) -> dict:
    """Intervalo de confianza de Wilson al 95% para una proporcion (PDR).
    Formula estandar (Wilson, 1927); sin dependencias externas."""
    if n == 0:
        return {"p": None, "inferior": None, "superior": None, "n": 0}
    p = exitos / n
    denom = 1 + z**2 / n
    centro = p + z**2 / (2 * n)
    margen = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    return {"p": p, "inferior": max(0.0, (centro - margen) / denom),
            "superior": min(1.0, (centro + margen) / denom), "n": n}


def exportar_figuras(nombre_corrida: str, nota: str = "") -> tuple[bool, str, str]:
    """Corre scripts/analisis/graficos_campana.py como subproceso (figuras
    PDF/PNG + tabla LaTeX) y devuelve (ok, salida_texto, carpeta_salida)."""
    carpeta = config.DIR_LAZO_EMULADO / nombre_corrida
    if not carpeta.is_dir():
        return False, "corrida no encontrada", ""
    salida = carpeta / "figuras"
    dirs = _dirs_para(nombre_corrida)
    cmd = [sys.executable, "scripts/analisis/graficos_campana.py",
           *[a for d in dirs for a in ("--dir", str(d))],
           "--salida", str(salida), "--nota", nota]
    try:
        r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, timeout=120, text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        REGISTRO.registrar("Consola", "scripts/analisis/graficos_campana.py", "proceso local", cmd, str(exc))
        return False, str(exc), ""
    salida_txt = (r.stdout or "") + (r.stderr or "")
    REGISTRO.registrar("Consola", "scripts/analisis/graficos_campana.py", "proceso local", cmd,
                       {"codigo": r.returncode, "salida": salida_txt[-2000:]})
    return r.returncode == 0, salida_txt, str(salida)
