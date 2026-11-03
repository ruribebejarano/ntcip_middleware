#!/usr/bin/env python3
"""M1 (prompt_figuras_cap4.md): diagrama espacio-tiempo de la priorización
sucesiva -- el servidor central prioriza cada RSU de la ruta por separado;
no es una coordinación de ola verde entre RSU (fuera del alcance) --, sobre
la corrida multi-RSU de resultados/espacio_tiempo/<AAAA-MM-DD_HHMM>/
(3 RSU del escenario Hospital del Niño, generada porque las 4 campañas del
29/10 tienen una sola RSU por misión y no permiten mostrar varias RSU).

Eje X: tiempo (s) desde el MI (mision_armada en eventos_servidor.csv).
Eje Y: distancia a lo largo de la ruta (m) -- la de cada RSU viene de
config.json (acum_m, calculada en app_obu/pruebas/registro_rsu_hospital_nino.json
a partir de servidor/rutas.py sobre el grafo real); la del vehículo es la
distancia acumulada de su trayectoria (proyección local equirectangular,
gateway.geometria.proyeccion_local, mismo método que el resto del código).

*** Qué se colorea y qué NO (para no fabricar precisión que no existe) ***
El controlador NUNCA pausa su reloj de fondo (ver
controller/controller_emulator.py::_fase_normal_locked), pero solo deja un
rastro en ctrl_fase_cambio cuando algo lo hace re-evaluar la fase Y esta
cambió desde la última vez logueada. En una corrida real (no una campaña
con un proceso de controlador por repetición) eso deja, por RSU, como mucho
estos puntos de referencia:
  - el primer poll tras arrancar (fase arbitraria, no informativa: no se
    sabe cuánto tiempo pasó desde el arranque real del proceso);
  - el instante de la decisión (M1, fase real en ese momento -- si ya es
    "verde" no se loguea una fila nueva, ver snmp_set_tx);
  - el instante de la liberación (M3/cruce, fase real EN ESE INSTANTE,
    medida, no calculada -- ver docstring de
    scripts/analisis/llegadas_verde_contrafactual.py).
No hay una segunda referencia dentro de esa ventana para fijar el offset
exacto del ciclo de fondo, así que este script SOLO colorea en verde el
tramo donde la prioridad estuvo activa (decisión -> liberación, 100%
determinado: ahí el controlador reporta "verde" por construcción) y anota
como texto (no como banda continua) la fase natural medida en la decisión
y en la liberación. El resto de la banda de cada RSU se deja en gris claro
("fase no verificada"), explícitamente, en vez de inventar un ciclo
continuo de ámbar/todo-rojo/rojo general que no está en los datos.

*** Bonus (plan normal sin prioridad): OMITIDO a propósito *** Por la misma
razón de arriba -- no hay cómo fijar el offset del ciclo de fondo de cada
controlador con la precisión necesaria para dibujar una línea continua
"sin prioridad" sobre varios minutos (solo hay 1-2 muestras puntuales por
RSU, no una serie). Dibujar esa línea sería inventar un ciclo que no está
respaldado por los eventos. Se deja como anotación puntual (la fase medida
en la decisión y en la liberación), no como línea.

Salida en --salida: fig_espacio_tiempo.pdf/.png

Uso:
    python scripts/analisis/espacio_tiempo.py \\
        --dir resultados/espacio_tiempo/<AAAA-MM-DD_HHMM> \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import EVT_CTRL_FASE_CAMBIO, EVT_M1_TX, EVT_M3_TX, EVT_MISION_ARMADA, iter_eventos  # noqa: E402
from gateway.geometria import proyeccion_local  # noqa: E402

NS = 1_000_000_000.0
ANCHO_BANDA_M = 40.0  # grosor visual de la banda de cada RSU (no es RADIO_DETECCION_RSU_M real, solo dibujo)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"], "mathtext.fontset": "stix",
    "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 7,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.linewidth": 0.6,
    "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e",
    "ytick.color": "#52514e", "grid.color": "#e4e3df", "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 300,
    "figure.dpi": 150, "lines.linewidth": 1.4,
})
AZUL, INK2 = "#2a78d6", "#52514e"
COLOR_VERDE_FORZADO = "#1baf7a"
COLOR_NO_VERIFICADO = "#e4e3df"
COLOR_FASE = {"verde": "#1baf7a", "amarillo": "#eab308", "todo_rojo": "#eb6834", "rojo_general": "#b91c1c"}
COL2 = 7.16
# Nombres de fase del código -> texto de la figura (la tesis dice "ámbar" y
# "rojo general", no los identificadores internos).
NOMBRE_FASE = {"verde": "verde", "amarillo": "ámbar", "todo_rojo": "todo rojo", "rojo_general": "rojo general"}


def distancia_acumulada(trayectoria: list[dict]) -> list[float]:
    """Distancia acumulada (m) entre muestras consecutivas de la
    trayectoria, vía proyeccion_local (mismo método que gateway/geometria.py
    en el resto del código: equirectangular, no haversine)."""
    dist = [0.0]
    for a, b in zip(trayectoria, trayectoria[1:]):
        x0, y0 = proyeccion_local(a["lat"], a["lon"], a["lat"], a["lon"])
        x1, y1 = proyeccion_local(b["lat"], b["lon"], a["lat"], a["lon"])
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        dist.append(dist[-1] + d)
    return dist


def cargar_trayectoria(ruta: Path) -> tuple[list[float], list[float]]:
    with ruta.open(newline="", encoding="utf-8") as fh:
        filas = [{"t_s": float(r["t_s"]), "lat": float(r["lat"]), "lon": float(r["lon"])}
                 for r in csv.DictReader(fh)]
    return [f["t_s"] for f in filas], distancia_acumulada(filas)


def fase_en_decision_y_liberacion(eventos: list[dict], id_solicitud: str) -> dict:
    """(fase_decision, ts_decision, fase_liberacion, ts_liberacion) para una
    parada -- mismo criterio que llegadas_verde_contrafactual.py: si no se
    logueó un ctrl_fase_cambio de solicitud_prioridad porque la fase ya
    era 'verde', se usa el propio snmp_set_tx como referencia."""
    ctrl = sorted((e for e in eventos if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO
                  and e["id_solicitud"] == id_solicitud), key=lambda e: e["ts_ns"])
    sets = sorted((e for e in eventos if e["tipo_evento"] == "snmp_set_tx" and e["id_solicitud"] == id_solicitud),
                  key=lambda e: e["ts_ns"])
    decision = next((e for e in sets if e["extra"].get("accion") in ("request_priority", "en_cola_despeje")), None)
    sol_prioridad = next((e for e in ctrl if e["extra"].get("motivo") == "solicitud_prioridad"), None)
    liberacion = next((e for e in reversed(ctrl)
                       if e["extra"].get("motivo") in ("liberacion_manual", "caducidad_prioridad")), None)

    ts_decision = decision["ts_ns"] if decision else None
    fase_decision = decision["extra"].get("fase") if decision else None
    ts_verde = sol_prioridad["ts_ns"] if sol_prioridad else ts_decision

    if liberacion is not None:
        fase_lib, ts_lib = liberacion["extra"].get("fase"), liberacion["ts_ns"]
    elif decision is not None:
        fase_lib, ts_lib = "verde", None  # sostenido hasta el cruce, sin cambio detectado (ver docstring)
    else:
        fase_lib, ts_lib = None, None

    return {"ts_decision": ts_decision, "fase_decision": fase_decision, "ts_verde": ts_verde,
            "fase_liberacion": fase_lib, "ts_liberacion": ts_lib}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, help="carpeta de la corrida (con config.json)")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    run_dir = Path(args.dir)
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    eventos = sorted(iter_eventos(run_dir), key=lambda e: e["ts_ns"])

    t0 = next(e["ts_ns"] for e in eventos if e["tipo_evento"] == EVT_MISION_ARMADA)
    mision_id = next(e["id_solicitud"] for e in eventos if e["tipo_evento"] == EVT_MISION_ARMADA)

    tray_path = run_dir / f"trayectoria_{cfg['obu_id']}.csv"
    t_tray, d_tray = cargar_trayectoria(tray_path)

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(COL2, 4.0))
    etiquetas_rsu: list[tuple[float, str]] = []

    for r in cfg["rsus"]:
        rsu_id, interseccion, acum_m = r["rsu_id"], r["interseccion_id"], r["acum_m"]
        id_sol = f"{mision_id}-{interseccion}"
        info = fase_en_decision_y_liberacion(eventos, id_sol)

        # Banda "no verificada" de fondo, en todo el eje X de la figura.
        ax.add_patch(Rectangle((t_tray[0], acum_m - ANCHO_BANDA_M / 2), t_tray[-1] - t_tray[0], ANCHO_BANDA_M,
                               facecolor=COLOR_NO_VERIFICADO, edgecolor="none", zorder=1))

        # Tramo de prioridad activa (decision -> liberacion o cruce): verde forzado, 100% determinado.
        if info["ts_decision"] is not None:
            t_ini = (info["ts_decision"] - t0) / NS
            m3 = next((e for e in eventos if e["tipo_evento"] == EVT_M3_TX and e["id_solicitud"] == id_sol
                      and e["extra"].get("motivo") == "cruce"), None)
            t_fin = ((info["ts_liberacion"] or (m3["ts_ns"] if m3 else info["ts_decision"])) - t0) / NS
            ax.add_patch(Rectangle((t_ini, acum_m - ANCHO_BANDA_M / 2), t_fin - t_ini, ANCHO_BANDA_M,
                                   facecolor=COLOR_VERDE_FORZADO, edgecolor="none", zorder=2))

        # Marcas: M1 enviados, M3 (cruce).
        m1s = [e for e in eventos if e["tipo_evento"] == EVT_M1_TX and e["id_solicitud"] == id_sol]
        for e in m1s:
            ax.plot((e["ts_ns"] - t0) / NS, acum_m - ANCHO_BANDA_M / 2 - 10, marker="^", ms=3.5,
                    color=INK2, zorder=4)
        m3s = [e for e in eventos if e["tipo_evento"] == EVT_M3_TX and e["id_solicitud"] == id_sol]
        for e in m3s:
            ax.plot((e["ts_ns"] - t0) / NS, acum_m + ANCHO_BANDA_M / 2 + 10, marker="x", ms=5,
                    color="#0b0b0b", zorder=4)
        if info["ts_verde"] is not None:
            ax.plot((info["ts_verde"] - t0) / NS, acum_m, marker="o", ms=4, color=COLOR_VERDE_FORZADO,
                    mec="#0b0b0b", mew=0.5, zorder=5)

        # Anotaciones puntuales de fase natural (decision y liberacion) -- NO una linea continua, ver docstring.
        if info["fase_decision"] and info["ts_decision"] is not None:
            fase = NOMBRE_FASE.get(info["fase_decision"], info["fase_decision"])
            ax.annotate(f"decisión: {fase}", ((info["ts_decision"] - t0) / NS, acum_m - ANCHO_BANDA_M / 2 - 40),
                       fontsize=5.5, color=INK2, ha="left", va="top")
        if info["fase_liberacion"] and info["ts_liberacion"] is not None:
            fase = NOMBRE_FASE.get(info["fase_liberacion"], info["fase_liberacion"])
            ax.annotate(f"liberación: {fase}",
                       ((info["ts_liberacion"] - t0) / NS + 3, acum_m + ANCHO_BANDA_M / 2 + 18),
                       fontsize=5.5, color=INK2, ha="left", va="bottom")

        # Anticipacion real (verde -> cruce): como etiqueta del eje derecho,
        # no dentro del gráfico, donde chocaba con las anotaciones de
        # decisión/liberación y con la leyenda.
        if info["ts_verde"] is not None and m3s:
            antic_s = (m3s[0]["ts_ns"] - info["ts_verde"]) / NS
            etiquetas_rsu.append((acum_m, f"RSU {rsu_id} ({interseccion})\nanticipación {antic_s:.2f} s"))

    # Trayectoria del vehiculo, encima de las bandas.
    ax.plot(t_tray, d_tray, color=AZUL, lw=1.6, zorder=6, label="Trayectoria de la OBU")

    # Sin título: lo pone el \caption de la tesis.
    ax.set_xlabel("Tiempo desde el armado de la misión (s)")
    ax.set_ylabel("Distancia a lo largo de la ruta (m)")
    ax.set_xlim(t_tray[0], t_tray[-1])
    ax.set_ylim(0, max(d_tray[-1], max(r["acum_m"] for r in cfg["rsus"]) + 80))
    ax.grid(True, axis="x", alpha=0.5)
    ax_rsu = ax.twinx()
    ax_rsu.set_ylim(ax.get_ylim())
    ax_rsu.set_yticks([y for y, _ in etiquetas_rsu], [txt for _, txt in etiquetas_rsu], fontsize=6.5)
    ax_rsu.tick_params(axis="y", length=0)
    ax_rsu.spines["right"].set_visible(False)

    leyenda = [
        plt.Line2D([0], [0], color=AZUL, lw=1.6, label="Trayectoria de la OBU"),
        Rectangle((0, 0), 1, 1, facecolor=COLOR_VERDE_FORZADO, label="Prioridad activa (verde forzado, medido)"),
        Rectangle((0, 0), 1, 1, facecolor=COLOR_NO_VERIFICADO, label="Fase no verificada (sin evento de referencia)"),
        plt.Line2D([0], [0], marker="^", color=INK2, lw=0, label="M1 enviado"),
        plt.Line2D([0], [0], marker="x", color="#0b0b0b", lw=0, label="M3 (cruce)"),
        plt.Line2D([0], [0], marker="o", color=COLOR_VERDE_FORZADO, mec="#0b0b0b", lw=0, label="Verde concedido"),
    ]
    ax.legend(handles=leyenda, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False, fontsize=6)

    fig.savefig(salida / "fig_espacio_tiempo.pdf", bbox_inches="tight")
    fig.savefig(salida / "fig_espacio_tiempo.png", bbox_inches="tight")
    plt.close(fig)
    print(f"Figura en {salida}: fig_espacio_tiempo (.pdf/.png)")


if __name__ == "__main__":
    main()
