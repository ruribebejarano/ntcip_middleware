#!/usr/bin/env python3
"""Calcula el consumo de datos de un experimento de scripts/consumo/experimento.py.

Reposo: MB/hora de cada fase sin misiones. Por misión: bytes de la ventana de
misiones, menos lo que habría consumido el reposo en ese tiempo, entre el número
de misiones. Los contadores incluyen TLS y la sobrecarga de Tailscale.

Uso:
    python scripts/consumo/analizar.py --dir resultados/consumo/<corrida> [--misiones-dia N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import median

OBU_RSU = "obu-rsu-consumo"  # OBU en la laptop: mide el consumo de la RSU
OBU_PI = "obu-pi-consumo"    # OBU en la Pi: mide el consumo de la OBU
HORAS_MES = 720.0


def leer_contadores(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8") as fh:
        return [{"ts": float(f["ts"]), "fase": f["fase"], "bytes": int(f["rx_bytes"]) + int(f["tx_bytes"]),
                 "rx": int(f["rx_bytes"]), "tx": int(f["tx_bytes"])} for f in csv.DictReader(fh)]


def bytes_en(muestras: list[dict], t: float, campo: str = "bytes") -> float:
    """Contador en el instante t, interpolando entre muestras."""
    if t <= muestras[0]["ts"]:
        return float(muestras[0][campo])
    for a, b in zip(muestras, muestras[1:]):
        if a["ts"] <= t <= b["ts"]:
            return a[campo] + (b[campo] - a[campo]) * (t - a["ts"]) / ((b["ts"] - a["ts"]) or 1.0)
    return float(muestras[-1][campo])


def tasa_fase(muestras: list[dict], fase: str, margen_s: float) -> dict | None:
    """Bytes/s de una fase, sin sus primeros margen_s: ahí se conecta o desconecta el agente."""
    filas = [m for m in muestras if m["fase"] == fase]
    if len(filas) < 2:
        return None
    desde = filas[0]["ts"] + margen_s
    utiles = [m for m in filas if m["ts"] >= desde]
    if len(utiles) < 2:
        return None
    dt = utiles[-1]["ts"] - utiles[0]["ts"]
    if dt <= 0:
        return None
    deltas = [b["bytes"] - a["bytes"] for a, b in zip(utiles, utiles[1:])]
    mediana = median(deltas)
    return {"bytes_s": (utiles[-1]["bytes"] - utiles[0]["bytes"]) / dt, "duracion_s": dt,
            "pico_bytes": max(deltas), "picos": sum(1 for d in deltas if d > max(10 * mediana, 50_000))}


def ventanas_mision(ruta_eventos: Path) -> dict[str, dict]:
    """Primer armado, último desarmado y misiones completas de cada OBU, según el servidor."""
    salida: dict[str, dict] = {}
    obu_de: dict[str, str] = {}
    with ruta_eventos.open(newline="", encoding="utf-8") as fh:
        for f in csv.DictReader(fh):
            extra = json.loads(f.get("extra_json") or "{}")
            t = int(f["ts_ns"]) / 1e9
            if f["tipo_evento"] == "mision_armada":
                obu = extra.get("obu_id")
                obu_de[f["id_solicitud"]] = obu
                v = salida.setdefault(obu, {"inicio": t, "fin": t, "n": 0})
                v["inicio"] = min(v["inicio"], t)
            elif f["tipo_evento"] == "mision_desarmada" and f["id_solicitud"] in obu_de:
                v = salida[obu_de[f["id_solicitud"]]]
                v["fin"] = max(v["fin"], t)
                v["n"] += 1
    return salida


def por_mision(muestras: list[dict], ventana: dict | None, base_bytes_s: float | None) -> dict | None:
    if not ventana or not ventana["n"] or base_bytes_s is None:
        return None
    inicio, fin = ventana["inicio"], ventana["fin"]
    total = bytes_en(muestras, fin) - bytes_en(muestras, inicio)
    neto = total - base_bytes_s * (fin - inicio)
    return {"misiones": ventana["n"], "ventana_s": fin - inicio, "total_bytes": total, "neto_bytes": neto,
            "bytes_por_mision": neto / ventana["n"]}


def calcular(muestras: list[dict], ventanas: dict[str, dict], margen_s: float) -> dict:
    fases = {f: tasa_fase(muestras, f, margen_s) for f in ("fondo", "reposo", "reposo2")}
    tasas = [fases[f]["bytes_s"] for f in ("reposo", "reposo2") if fases[f]]
    reposo = sum(tasas) / len(tasas) if tasas else None
    fondo = fases["fondo"]["bytes_s"] if fases["fondo"] else None
    return {
        "fases": fases,
        "reposo_bytes_s": reposo,
        "fondo_bytes_s": fondo,
        "deriva_reposo": abs(tasas[0] - tasas[1]) / max(tasas) if len(tasas) == 2 and max(tasas) else None,
        "rsu": por_mision(muestras, ventanas.get(OBU_RSU), reposo),
        "obu": por_mision(muestras, ventanas.get(OBU_PI), fondo),
        "total_bytes": muestras[-1]["bytes"] - muestras[0]["bytes"],
    }


def mb(b: float) -> float:
    return b / 1e6


def texto(r: dict, misiones_dia: float | None) -> str:
    l = [f"Consumo total de la interfaz en el experimento: {mb(r['total_bytes']):.2f} MB", ""]
    for nombre, fase in (("Fondo, sin agente", "fondo"), ("Reposo, con agente (inicio)", "reposo"), ("Reposo, con agente (final)", "reposo2")):
        d = r["fases"].get(fase)
        if d:
            l.append(f"{nombre}: {mb(d['bytes_s']) * 3600:.3f} MB/hora; {d['picos']} picos; máx. {d['pico_bytes'] / 1000:.0f} KB en 10 s")
    if r["deriva_reposo"] is not None:
        l.append(f"Diferencia entre los dos reposos: {100 * r['deriva_reposo']:.0f} %")
        if r["deriva_reposo"] > 0.2:
            l.append("AVISO: los reposos difieren más de 20 %; revisa los picos antes de usar estas cifras.")
    l.append("")
    for nombre, clave in (("RSU", "rsu"), ("OBU", "obu")):
        d = r[clave]
        if d:
            l.append(f"{nombre} por misión: {mb(d['bytes_por_mision']):.3f} MB ({d['misiones']} misiones; "
                     f"{mb(d['total_bytes']):.2f} MB en {d['ventana_s'] / 60:.1f} min, menos el reposo)")
        else:
            l.append(f"{nombre} por misión: sin datos")
    if r["reposo_bytes_s"] is not None:
        mes = mb(r["reposo_bytes_s"]) * 3600 * HORAS_MES
        l += ["", f"RSU siempre conectada, sin misiones: {mes:.0f} MB en 30 días"]
        if misiones_dia is not None and r["rsu"]:
            con = mes + mb(r["rsu"]["bytes_por_mision"]) * misiones_dia * 30
            l.append(f"Con {misiones_dia:g} misiones al día (supuesto): {con:.0f} MB en 30 días")
    return "\n".join(l) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--margen-s", type=float, default=60.0)
    ap.add_argument("--misiones-dia", type=float, default=None, help="supuesto para la proyección mensual")
    args = ap.parse_args()
    muestras = leer_contadores(args.dir / "pi" / "contadores.csv")
    ventanas = ventanas_mision(args.dir / "servidor" / "eventos_servidor.csv")
    r = calcular(muestras, ventanas, args.margen_s)
    (args.dir / "consumo.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    t = texto(r, args.misiones_dia)
    estado = args.dir / "pi" / "estado.txt"
    if estado.exists():
        t = f"Estado en la Pi: {estado.read_text(encoding='utf-8').strip()}\n\n" + t
    (args.dir / "resumen.txt").write_text(t, encoding="utf-8")
    print(t)


if __name__ == "__main__":
    main()
