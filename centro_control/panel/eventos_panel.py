"""Linea de tiempo de eventos + latencia por tramo para el panel.
Reutiliza common/events.py (iter_eventos) y
scripts/analisis/latencia_tramos.py (agrupar_por_solicitud,
calcular_latencias) tal cual, sin reimplementar el cruce por
id_solicitud ni el calculo de latencias.

Los eventos del controlador y de la RSU se generan en la Pi
(resultados/eventos/ ahi); los de la OBU simulada se generan en esta
laptop si se corrio gateway/obu_simulator.py (resultados/eventos/ aqui).
agrupar_por_solicitud() de latencia_tramos.py espera los 3 eventos_*.csv
en UN mismo directorio -- por eso "Traer eventos de la Pi" primero corre
`scripts/pi.sh fetch` (ya existente, no reimplementado) y despues copia
los CSV relevantes a resultados/panel_vivo/ junto con el eventos_obu.csv
local, para poder llamar agrupar_por_solicitud() sobre un solo
directorio sin tocar su firma."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.events import iter_eventos  # noqa: E402
from scripts.analisis.latencia_tramos import (  # noqa: E402
    agrupar_por_solicitud,
    calcular_latencias,
)
from centro_control.panel.demo_acciones import _BASH_EXE  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIR_VIVO = REPO_ROOT / "resultados" / "panel_vivo"
DIR_LOCAL_OBU = REPO_ROOT / "resultados" / "eventos"
DIR_PI_FETCHED = REPO_ROOT / "resultados" / "rsu" / "eventos"


def traer_eventos_de_la_pi(timeout: float = 30.0) -> tuple[bool, str]:
    """Corre scripts/pi.sh fetch (ya probado, no reimplementado) para
    traer resultados/ de la Pi a resultados/rsu/."""
    try:
        r = subprocess.run(
            [_BASH_EXE, "scripts/pi.sh", "fetch"],
            cwd=REPO_ROOT, capture_output=True, timeout=timeout,
        )
        salida = (
            (r.stdout or b"").decode("utf-8", errors="replace")
            + (r.stderr or b"").decode("utf-8", errors="replace")
        )
        return r.returncode == 0, salida.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


def _preparar_directorio_combinado() -> int:
    """Copia los eventos_*.csv disponibles (Pi ya traida + OBU local) a
    resultados/panel_vivo/. Devuelve cuantos archivos copio."""
    DIR_VIVO.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for origen_dir in (DIR_PI_FETCHED, DIR_LOCAL_OBU):
        if not origen_dir.is_dir():
            continue
        for csv_path in origen_dir.glob("eventos_*.csv"):
            shutil.copy2(csv_path, DIR_VIVO / csv_path.name)
            copiados += 1
    return copiados


def linea_de_tiempo_y_latencias(max_filas: int = 25) -> dict:
    """Devuelve {"num_archivos": int, "eventos_recientes": [...],
    "latencias": [...]} -- vacio con un mensaje si todavia no hay datos."""
    num_archivos = _preparar_directorio_combinado()
    if num_archivos == 0:
        return {
            "num_archivos": 0,
            "eventos_recientes": [],
            "latencias": [],
            "aviso": (
                "No hay eventos_*.csv todavia. Usa el boton 'Traer eventos de "
                "la Pi' (corre scripts/pi.sh fetch) y/o corre "
                "gateway/obu_simulator.py en esta laptop para generar "
                "eventos locales de la OBU."
            ),
        }

    eventos = sorted(iter_eventos(DIR_VIVO), key=lambda e: -e["ts_ns"])[:max_filas]

    por_solicitud = agrupar_por_solicitud(DIR_VIVO)
    latencias = []
    for id_solicitud, eventos_ts in por_solicitud.items():
        calc = calcular_latencias(eventos_ts)
        if calc is not None:
            latencias.append({"id_solicitud": id_solicitud, **calc})
    latencias.sort(key=lambda f: -f["L_aprox_ms"])

    return {
        "num_archivos": num_archivos,
        "eventos_recientes": eventos,
        "latencias": latencias,
        "aviso": None,
    }
