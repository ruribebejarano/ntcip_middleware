#!/usr/bin/env python3
"""Diagrama de secuencia de UNA solicitud del lazo de priorizacion, dibujado
a partir de los eventos reales registrados (common/events.py, RF-10).

Una figura PNG por solicitud, con el tiempo en el eje horizontal (segundos
desde el primer M1) y cuatro carriles:

    OBU          M1 (azul), M3 (naranja) salen de aqui; M2 (aqua) llega aqui
    Broker       los mensajes lo atraviesan (no se instrumenta: Mosquitto sin modificar)
    RSU          recepcion de M1/M3, escritura NTCIP 1211 hacia el controlador (violeta)
    Controlador  banda con la fase real en cada instante (verde / ambar / todo rojo / rojo)

Es la "linea de tiempo de un ensayo representativo" del Capitulo IV.

*** Relojes ***: los eventos de la OBU usan el reloj de la laptop; los de la
RSU y del controlador, el de la Raspberry Pi. Las flechas OBU<->RSU heredan
el desfase entre ambos (medirlo con scripts/pi.sh clock y declararlo en el
pie de figura). Las latencias de milisegundos no se ven a escala de
segundos: van escritas en la figura.

Uso:
    scripts/pi.sh fetch      # trae los eventos de la RSU y del controlador
    python3 scripts/analisis/secuencia_recorrido.py --dir resultados/eventos --dir resultados/rsu/eventos
    python3 scripts/analisis/secuencia_recorrido.py --dir resultados/lazo_emulado/<corrida> \\
        --dir resultados/rsu/eventos --todas
    python3 scripts/analisis/secuencia_recorrido.py ... --id ses-48c80b-5b7c4493

Requiere matplotlib (pip install matplotlib).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
from lazo_emulado import cargar  # noqa: E402

# Colores: categoricos para los tipos de mensaje (identidad), y los de la
# fase del semaforo con su significado real. Todo va ademas rotulado con
# texto: el color nunca es la unica pista.
C_M1 = "#2a78d6"
C_M2 = "#1baf7a"
C_M3 = "#eb6834"
C_NTCIP = "#6250d6"
C_FASE = {"verde": "#0ca30c", "amarillo": "#fab219", "todo_rojo": "#d03b3b", "rojo_general": "#e8a3a3"}
NOMBRE_FASE = {"verde": "verde", "amarillo": "\u00e1mbar", "todo_rojo": "todo rojo", "rojo_general": "rojo"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

Y_OBU, Y_BROKER, Y_RSU, Y_CTRL = 3.0, 2.0, 1.0, 0.0


def _solicitudes(eventos: list[dict]) -> list[str]:
    ids = []
    for e in eventos:
        if e["tipo_evento"] == "M1_tx" and "seq" in e["extra"] and e["id_solicitud"] not in ids:
            ids.append(e["id_solicitud"])
    return ids


def dibujar(eventos: list[dict], id_sol: str, salida: Path) -> str:
    propios = [e for e in eventos if e["id_solicitud"] == id_sol]
    m1_tx = [e for e in propios if e["tipo_evento"] == "M1_tx"]
    t0 = m1_tx[0]["ts_ns"]
    rsu_id = m1_tx[0]["extra"].get("rsu_id", "1")
    t_fin = max(e["ts_ns"] for e in propios)
    ini_ns, fin_ns = t0 - 4e9, t_fin + 4e9

    def s(ts):  # segundos desde el primer M1
        return (ts - t0) / 1e9

    def de(tipo, nodo_prefijo=None):
        return [e for e in propios if e["tipo_evento"] == tipo
                and (nodo_prefijo is None or e["nodo"].startswith(nodo_prefijo))]

    # Fases del controlador de ESTA RSU en la ventana (todas, no solo las de la solicitud)
    ctrl = sorted((e for e in eventos if e["nodo"] == f"ctrl_{rsu_id}"
                   and e["tipo_evento"] == "ctrl_fase_cambio"), key=lambda e: e["ts_ns"])
    previas = [e for e in ctrl if e["ts_ns"] <= ini_ns]
    tramos = []
    fase_actual = previas[-1]["extra"].get("fase") if previas else None
    t_actual = ini_ns
    for e in ctrl:
        if ini_ns < e["ts_ns"] <= fin_ns:
            tramos.append((t_actual, e["ts_ns"], fase_actual))
            t_actual, fase_actual = e["ts_ns"], e["extra"].get("fase")
    tramos.append((t_actual, fin_ns, fase_actual))

    fig, ax = plt.subplots(figsize=(13, 5.6), dpi=150)
    fig.patch.set_facecolor(SURF)
    ax.set_facecolor(SURF)

    # Carriles
    for y, nombre in ((Y_OBU, "OBU\n(laptop)"), (Y_BROKER, "Broker MQTT\n(laptop)"),
                      (Y_RSU, f"RSU {rsu_id}\n(Raspberry Pi)"), (Y_CTRL, "Controlador\n(fase)")):
        if y != Y_CTRL:
            ax.axhline(y, color=GRID, lw=1, zorder=0)
        ax.text(s(ini_ns) - 0.4, y, nombre, ha="right", va="center", fontsize=9.5, color=INK)

    # Banda de fases del controlador
    for a, b, fase in tramos:
        if fase is None:
            continue
        ax.add_patch(plt.Rectangle((s(a), Y_CTRL - 0.22), s(b) - s(a), 0.44,
                                   color=C_FASE.get(fase, GRID), lw=0, zorder=1))
        if s(b) - s(a) > 1.6:
            ax.text((s(a) + s(b)) / 2, Y_CTRL, NOMBRE_FASE.get(fase, fase), ha="center", va="center",
                    fontsize=8.5, color=INK if fase in ("amarillo", "rojo_general") else "white", zorder=2)

    # M1 (actualizaciones finas, la primera gruesa) y M1_rx
    rx = {e["extra"].get("seq"): e for e in de("M1_rx")}
    for e in m1_tx:
        seq = e["extra"].get("seq")
        r = rx.get(seq)
        if r is None:
            continue
        primera = seq == 1
        ax.annotate("", xy=(s(r["ts_ns"]), Y_RSU + 0.06), xytext=(s(e["ts_ns"]), Y_OBU - 0.06),
                    arrowprops=dict(arrowstyle="-|>", color=C_M1, lw=2.0 if primera else 0.8,
                                    alpha=1 if primera else 0.45, shrinkA=0, shrinkB=0), zorder=3)

    # M3
    for e in de("M3_tx"):
        r = next((x for x in de("M3_rx")), None)
        if r is not None:
            ax.annotate("", xy=(s(r["ts_ns"]), Y_RSU + 0.06), xytext=(s(e["ts_ns"]), Y_OBU - 0.06),
                        arrowprops=dict(arrowstyle="-|>", color=C_M3, lw=2.0, shrinkA=0, shrinkB=0), zorder=3)

    # M2: solo los que cambian de estado (los demas, finos)
    m2_tx = de("M2_tx")
    m2_rx = de("M2_rx")
    ultimo = None
    cambios = []
    for e in m2_rx:
        est = e["extra"].get("estado")
        tx = min((x for x in m2_tx if x["extra"].get("estado") == est and x["ts_ns"] <= e["ts_ns"] + 50e6),
                 key=lambda x: abs(x["ts_ns"] - e["ts_ns"]), default=None)
        cambio = est != ultimo
        ultimo = est
        if tx is not None:
            ax.annotate("", xy=(s(e["ts_ns"]), Y_OBU - 0.06), xytext=(s(tx["ts_ns"]), Y_RSU + 0.06),
                        arrowprops=dict(arrowstyle="-|>", color=C_M2, lw=1.6 if cambio else 0.7,
                                        ls="--", alpha=1 if cambio else 0.4, shrinkA=0, shrinkB=0), zorder=3)
        if cambio:
            cambios.append((e, est))

    # Escrituras NTCIP hacia el controlador
    textos_set = {"request_priority": "NTCIP 1211:\nsolicitud", "en_cola_despeje": "en cola\n(RF-06)",
                  "activar_cola_rf06": "fin del despeje:\nsolicitud", "clear_priority_m3": "liberaci\u00f3n",
                  "rechazada": "rechazada\n(RF-05)"}
    for e in de("snmp_set_tx"):
        acc = e["extra"].get("accion")
        x = s(e["ts_ns"])
        if acc in ("request_priority", "activar_cola_rf06", "clear_priority_m3"):
            ax.annotate("", xy=(x, Y_CTRL + 0.24), xytext=(x, Y_RSU - 0.06),
                        arrowprops=dict(arrowstyle="-|>", color=C_NTCIP, lw=1.6, shrinkA=0, shrinkB=0), zorder=3)
        if acc in textos_set:
            ax.text(x + 0.15, Y_RSU - 0.42, textos_set[acc], fontsize=8, color=INK2, va="center", zorder=4)
    for e in de("caducidad"):
        ax.text(s(e["ts_ns"]) + 0.15, Y_RSU - 0.42, "caducidad\n(RF-09)", fontsize=8, color=INK2, va="center")

    # Rotulos en la OBU
    x1 = m1_tx[0]["extra"]
    ax.text(0, Y_OBU + 0.28, f"M1 #1  {x1.get('interseccion_id')}/{x1.get('acceso')} a {x1.get('distancia_m')} m",
            fontsize=8.5, color=C_M1, ha="left")
    ultimo_x, nivel = None, 0
    for e, est in cambios:
        rtt = e["extra"].get("rtt_ms")
        etiqueta = f"M2 {est}" + (f"\n{rtt:.1f} ms" if rtt is not None else "\n(aviso de la RSU)")
        x = s(e["ts_ns"])
        # Rotulos a menos de ~3 s se escalonan para no encimarse
        nivel = (nivel + 1) % 2 if (ultimo_x is not None and x - ultimo_x < 3.0) else 0
        ultimo_x = x
        ax.text(x, Y_OBU + 0.52 + 0.5 * nivel, etiqueta, fontsize=8, color=INK, ha="center", va="bottom")
    for e in de("M3_tx"):
        ax.text(s(e["ts_ns"]), Y_OBU + 0.28, f"M3 ({e['extra'].get('motivo')})", fontsize=8.5, color=C_M3, ha="center")

    # Titulo: el hallazgo de esta solicitud
    concedida = next((e for e, est in cambios if est == "concedida"), None)
    rechazada = next((e for e, est in cambios if est == "rechazada"), None)
    en_cola = any(e["extra"].get("accion") == "en_cola_despeje" for e in de("snmp_set_tx"))
    if rechazada is not None:
        titulo = "Solicitud rechazada: clase de veh\u00edculo no reconocida (RF-05); el controlador no se toca"
    elif concedida is not None:
        t_c = s(concedida["ts_ns"])
        motivo = "esper\u00f3 el fin del despeje (RF-06)" if en_cola else "el controlador pas\u00f3 a verde de inmediato"
        titulo = f"Verde concedido {t_c:.1f} s despu\u00e9s del primer M1: {motivo}"
    else:
        titulo = "Solicitud sin verde concedido"
    rtts = [e["extra"]["rtt_ms"] for e in m2_rx if e["extra"].get("rtt_ms") is not None]
    rtt_txt = f"RTT M1/M2 mediano {sorted(rtts)[len(rtts) // 2]:.1f} ms (n={len(rtts)})" if rtts else "sin RTT"
    ax.set_title(titulo, loc="left", fontsize=12.5, color=INK, pad=28, fontweight="bold")
    ax.text(0, 1.02, f"{id_sol}  ·  {x1.get('trayectoria', '')}  ·  {len(m1_tx)} M1 a 1 Hz  ·  {rtt_txt}  ·  "
            f"relojes: OBU = laptop, RSU y controlador = Raspberry Pi",
            transform=ax.transAxes, fontsize=8.5, color=INK2)

    ax.set_xlim(s(ini_ns) - 0.2, s(fin_ns))
    ax.set_ylim(-0.6, 4.5)
    ax.set_yticks([])
    ax.set_xlabel("tiempo desde el primer M1 (s)", fontsize=9.5, color=INK2)
    ax.tick_params(axis="x", colors=INK2, labelsize=9)
    ax.grid(axis="x", color=GRID, lw=0.6, zorder=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    leyenda = [Line2D([0], [0], color=C_M1, lw=2, label="M1 solicitud (fina: actualizaci\u00f3n)"),
               Line2D([0], [0], color=C_M2, lw=2, ls="--", label="M2 estado"),
               Line2D([0], [0], color=C_M3, lw=2, label="M3 cancelaci\u00f3n"),
               Line2D([0], [0], color=C_NTCIP, lw=2, label="RSU -> controlador"),
               Patch(color=C_FASE["verde"], label="verde"), Patch(color=C_FASE["amarillo"], label="\u00e1mbar"),
               Patch(color=C_FASE["todo_rojo"], label="todo rojo"), Patch(color=C_FASE["rojo_general"], label="rojo")]
    ax.legend(handles=leyenda, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=8, frameon=False,
              fontsize=8.5, labelcolor=INK2)

    fig.tight_layout()
    salida.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(salida, facecolor=SURF)
    plt.close(fig)
    return titulo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True, help="carpeta con eventos_*.csv (repetible)")
    ap.add_argument("--id", default=None, help="id_solicitud a dibujar (por defecto, la ultima)")
    ap.add_argument("--todas", action="store_true", help="una figura por cada solicitud")
    ap.add_argument("--salida", default=str(RAIZ / "evidencia" / "secuencias"))
    args = ap.parse_args()

    eventos = cargar([Path(d) for d in args.dir])
    ids = _solicitudes(eventos)
    if not ids:
        print("No hay solicitudes de la OBU emulada (M1_tx con seq) en esas carpetas.", file=sys.stderr)
        raise SystemExit(1)
    elegidos = ids if args.todas else ([args.id] if args.id else [ids[-1]])
    for id_sol in elegidos:
        if id_sol not in ids:
            print(f"No existe la solicitud {id_sol}. Disponibles: {', '.join(ids[-10:])}", file=sys.stderr)
            raise SystemExit(1)
        ruta = Path(args.salida) / f"secuencia_{id_sol}.png"
        titulo = dibujar(eventos, id_sol, ruta)
        print(f"{ruta}\n    {titulo}")


if __name__ == "__main__":
    main()
