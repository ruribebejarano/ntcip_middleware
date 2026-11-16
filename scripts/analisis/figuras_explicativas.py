#!/usr/bin/env python3
"""Figuras explicativas de resultados para la tesis (capítulo IV), pensadas
para un lector no especialista: cada una resume en una imagen lo que hoy
dice una tabla. Lee los resúmenes ya versionados; no mide nada nuevo.

  fig_latencia_condiciones   L p95 por condición de enlace frente al presupuesto
  fig_rf11_indra             A_v por parada con los tiempos del controlador INDRA
  fig_handshake              costo de establecer la conexión segura, 4G y Wi-Fi
  fig_resultados_limites     cada resultado clave como % de su límite
  fig_consumo_mensual        consumo mensual de datos de la RSU y de la OBU

Uso:
    python scripts/analisis/figuras_explicativas.py --salida resultados/_figuras_explicativas
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from espacio_tiempo import AZUL, COL2, INK2  # noqa: E402  (fija rcParams)
from costo_planes_iot import duracion_misiones_s  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
C = RAIZ / "resultados" / "campana"
E = RAIZ / "resultados" / "evaluacion"
VERDE, ROJO, NARANJA, GRIS = "#1baf7a", "#b91c1c", "#eb6834", "#a8a6a0"

RECALCULO_CAMPANA = C / "_figuras_cap4_2026-11-11" / "recalculo_por_mensaje.json"
RECALCULO_NUBE = C / "_campana_nube" / "recalculo_por_mensaje.json"
FASE4 = E / "_figuras_fase4_2026-11-12"
BYTES_TLS = E / "20261112-150406_bytes_tls"
RF11 = [  # (etiqueta, carpeta)
    ("Geocerca 150 m, 36 km/h", "20261115-225721_lazo_local_rf11_indra_v36_geocerca"),
    ("Geocerca 150 m, 60 km/h", "20261115-232554_lazo_local_rf11_indra_v60_geocerca"),
    ("ETA 16,3 s, 36 km/h", "20261115-234726_lazo_local_rf11_indra_v36_eta"),
    ("ETA 16,3 s, 60 km/h", "20261116-001557_lazo_local_rf11_indra_v60_eta"),
]
T_M, A_V_MAX = 2.0, 16.0


def _coma(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _guardar(fig, salida: Path, nombre: str) -> None:
    fig.savefig(salida / f"{nombre}.pdf", bbox_inches="tight")
    fig.savefig(salida / f"{nombre}.png", bbox_inches="tight", dpi=160)
    plt.close(fig)


def latencia_condiciones(salida: Path) -> None:
    camp = json.loads(RECALCULO_CAMPANA.read_text(encoding="utf-8"))
    nube = json.loads(RECALCULO_NUBE.read_text(encoding="utf-8"))
    filas = [("Local\n(banco)", camp["Local"]), ("Wi-Fi", camp["Wi-Fi"]), ("4G\n(broker en laptop)", camp["4G"]),
             ("4G\n(broker en la nube)", nube["Nube, S1 (15-nov)"])]
    fig, ax = plt.subplots(figsize=(COL2 * 0.82, 2.6))
    x = range(len(filas))
    p95 = [f[1]["L_corr_ms"]["p95"] for f in filas]
    ic = [f[1]["L_corr_ms"]["p95_ic"] for f in filas]
    err = [[p - lo for p, (lo, hi) in zip(p95, ic)], [hi - p for p, (lo, hi) in zip(p95, ic)]]
    ax.bar(x, p95, color=[GRIS, GRIS, AZUL, AZUL], width=0.55, yerr=err, capsize=3, ecolor=INK2)
    for i, v in enumerate(p95):
        ax.text(i, v + err[1][i] + 20, f"{_coma(v)} ms", ha="center", va="bottom", fontsize=7.5)
    ax.axhline(1000, color=ROJO, ls="--", lw=1)
    ax.text(len(filas) - 0.6, 1010, "límite de RNF-01: 1000 ms", color=ROJO, ha="right", va="bottom", fontsize=7)
    ax.set_xticks(list(x), [f[0] for f in filas])
    ax.set_ylabel("$L$, percentil 95 (ms)")
    ax.set_ylim(0, 1150)
    _guardar(fig, salida, "fig_latencia_condiciones")


def rf11_indra(salida: Path) -> None:
    fig, ax = plt.subplots(figsize=(COL2 * 0.9, 2.5))
    ax.axvspan(T_M, A_V_MAX, color=VERDE, alpha=0.12, lw=0)
    ax.text((T_M + A_V_MAX) / 2, len(RF11) - 0.35, "zona permitida por RF-11 (de 2 a 16 s)", ha="center",
            fontsize=7, color="#0f6e4f")
    for i, (etq, carpeta) in enumerate(reversed(RF11)):
        with (C / carpeta / "lazo_por_parada.csv").open(encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        av = [float(f["anticipacion_real_s"]) for f in filas if f["anticipacion_real_s"]]
        sin_verde = sum(1 for f in filas if f.get("obtuvo_verde") != "True")
        colores = [VERDE if T_M <= a <= A_V_MAX else NARANJA for a in av]
        ax.scatter(av, [i] * len(av), c=colores, s=16, zorder=3, edgecolors="white", linewidths=0.4)
        if sin_verde:
            ax.scatter([0.6] * sin_verde, [i + 0.12 * k for k in range(sin_verde)], marker="x", c=ROJO, s=26, zorder=3)
            ax.text(1.1, i + 0.05, f"{sin_verde} sin verde", color=ROJO, fontsize=7, va="center")
    ax.set_yticks(range(len(RF11)), [e for e, _ in reversed(RF11)])
    ax.set_xlabel("anticipación $A_v$: segundos de verde antes de que el vehículo cruce")
    ax.set_xlim(0, 20)
    ax.set_ylim(-0.6, len(RF11) - 0.1)
    ax.grid(axis="x")
    _guardar(fig, salida, "fig_rf11_indra")


def handshake(salida: Path) -> None:
    hs = json.loads((FASE4 / "resumen_fase4.json").read_text(encoding="utf-8"))["handshake"]
    casos = [("tcp", "Sin cifrado\n(TCP)"), ("tls13", "TLS 1.3\ncompleto"), ("tls13_res", "TLS 1.3\nreanudado"),
             ("tls12", "TLS 1.2\ncompleto")]
    fig, axs = plt.subplots(1, 2, figsize=(COL2 * 0.95, 2.4), sharey=False)
    for ax, enlace in zip(axs, ("4G", "Wi-Fi")):
        vals = [hs[f"{enlace}|{k}"]["total_med"] for k, _ in casos]
        ax.bar(range(len(casos)), vals, color=[GRIS, AZUL, VERDE, NARANJA], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v * 1.02, f"{v:.0f} ms", ha="center", va="bottom", fontsize=7)
        ax.set_xticks(range(len(casos)), [n for _, n in casos], fontsize=6.8)
        ax.set_title(f"Por {enlace}")
        ax.set_ylim(0, max(vals) * 1.18)
    axs[0].set_ylabel("tiempo de conexión, mediana (ms)")
    _guardar(fig, salida, "fig_handshake")


def resultados_limites(salida: Path) -> None:
    camp = json.loads(RECALCULO_CAMPANA.read_text(encoding="utf-8"))
    nube = json.loads(RECALCULO_NUBE.read_text(encoding="utf-8"))["Nube, S1 (15-nov)"]
    fallos = json.loads((FASE4 / "fallos_resumen.json").read_text(encoding="utf-8"))
    corte_aj = fallos["pi_enlace4g_20261115-011141_fallos_pi_enlace4g"]
    corte_def = fallos["pi_enlace4g"]
    t_lib_caida = max(max(fallos["broker"]["t_lib_m1_s"]), max(fallos["servidor"]["t_lib_m1_s"]))
    filas = [  # (texto, valor, límite, unidad)
        ("Latencia $L$ p95, 4G (broker en laptop)", camp["4G"]["L_corr_ms"]["p95"], 1000, "ms"),
        ("Latencia $L$ p95, 4G (broker en la nube)", nube["L_corr_ms"]["p95"], 1000, "ms"),
        ("Racha sin renovación, máx. (4G, nube)", nube["racha_s"]["max"], 3.0, "s"),
        ("Liberación tras caída de broker o servidor, máx.", t_lib_caida, 4.0, "s"),
        ("Liberación tras corte del 4G, máx.", max(corte_aj["t_lib_m1_s"]), 4.0, "s"),
        ("Recuperación tras corte del 4G, máx. (ajustada)", max(corte_aj["T_rec_s"]), 10.0, "s"),
        ("Recuperación tras corte del 4G, máx. (por defecto)", max(corte_def["T_rec_s"]), 10.0, "s"),
    ]
    fig, ax = plt.subplots(figsize=(COL2 * 0.95, 2.9))
    for i, (txt, v, lim, u) in enumerate(reversed(filas)):
        pct = 100 * v / lim
        color = VERDE if pct <= 100 else ROJO
        ax.barh(i, min(pct, 140), color=color, height=0.55)
        etiqueta = f"{_coma(v, 1 if u == 'ms' else 2)} {u} de {_coma(lim, 0)} {u}"
        if pct > 140:
            # barra recortada: la etiqueta va dentro, en blanco
            ax.text(138, i, etiqueta + f" ({pct:.0f} %)", va="center", ha="right", fontsize=7, color="white")
        else:
            # a la derecha de la línea del límite, para no cruzarla
            ax.text(max(pct, 100) + 3, i, etiqueta, va="center", fontsize=7)
    ax.axvline(100, color=ROJO, ls="--", lw=1)
    ax.text(100, len(filas) - 0.35, "límite del requerimiento", color=ROJO, ha="center", fontsize=7)
    ax.set_yticks(range(len(filas)), [f[0] for f in reversed(filas)])
    ax.set_xlabel("resultado como porcentaje de su límite (%)")
    ax.set_xlim(0, 175)
    ax.set_ylim(-0.6, len(filas) - 0.1)
    _guardar(fig, salida, "fig_resultados_limites")


def consumo_mensual(salida: Path) -> None:
    b = json.loads((FASE4 / "resumen_fase4.json").read_text(encoding="utf-8"))["bytes"]
    mision, total = b["tls"]["rsu_mision"], b["tls"]["rsu_total"]
    conexion = total - mision
    reposo_h = b["reposo_tls_B_h"]
    dias, horas_mes = 30, 720
    misiones = list(range(0, 201, 5))
    rsu = [(reposo_h * horas_mes + conexion * dias + mision * m * dias) / 1e6 for m in misiones]
    durs = duracion_misiones_s(BYTES_TLS)
    tasa_obu = b["tls"]["obu_mision"] / (sum(durs) / len(durs))  # B/s de misión
    horas = [h / 2 for h in range(0, 17)]
    obu = [tasa_obu * 3600 * h * dias / 1e6 for h in horas]
    fig, axs = plt.subplots(1, 2, figsize=(COL2 * 0.95, 2.4))
    axs[0].plot(misiones, rsu, color=AZUL)
    axs[0].fill_between(misiones, 0, [reposo_h * horas_mes / 1e6] * len(misiones), color=GRIS, alpha=0.35, lw=0)
    axs[0].text(100, reposo_h * horas_mes / 1e6 / 2, "solo mantener la conexión (keepalive)", ha="center",
                fontsize=6.8, color=INK2)
    axs[0].set_xlabel("misiones atendidas por día")
    axs[0].set_ylabel("MB al mes")
    axs[0].set_title("RSU")
    axs[0].set_ylim(0, max(rsu) * 1.1)
    axs[1].plot(horas, obu, color=NARANJA)
    axs[1].set_xlabel("horas de misión por día")
    axs[1].set_title("OBU")
    axs[1].set_ylim(0, max(obu) * 1.1)
    for ax in axs:
        ax.grid(True)
    _guardar(fig, salida, "fig_consumo_mensual")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", default=str(RAIZ / "resultados" / "_figuras_explicativas"))
    a = ap.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    latencia_condiciones(salida)
    rf11_indra(salida)
    handshake(salida)
    resultados_limites(salida)
    consumo_mensual(salida)
    print(f"Listo: {salida}")


if __name__ == "__main__":
    main()
