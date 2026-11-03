#!/usr/bin/env python3
"""Consumo de datos del módem 4G de la RSU por corrida de campaña.

Fuente: los contadores de la interfaz usb0 (módem SIM7670G) que
`scripts/pi.sh red estado` imprime con `ip -s link show usb0`, y que
scripts/campanas/lazo_centralizado.py guarda en config.json al inicio
(`estado_red_inicio`) y al fin (`estado_red_fin`) de cada corrida
pi-4g/pi-lan. Consumo = (RX + TX al fin) - (RX + TX al inicio).

Qué cuenta y qué no:
  - Cuenta TODO lo que pasó por usb0 en esa ventana: MQTT/TLS de la RSU,
    Tailscale (incluido el relevo DERP), SSH de la laptop (pi.sh clock,
    red estado, fetch-eventos), NTP y cualquier otro tráfico del sistema
    operativo. Es lo que se acerca a lo que factura el operador.
  - Son bytes de capa IP/Ethernet vistos por el kernel; el operador puede
    medir algo distinto (cabeceras de su red, redondeo por sesión). Para
    contrastar, anotar el saldo del plan antes y después.
  - Si el módem se reconectó durante la corrida, el contador puede
    reiniciarse: un delta negativo se reporta como "contador reiniciado"
    en vez de un consumo.
  - En pi-lan el tráfico va por wlan0, así que usb0 casi no se mueve:
    este script solo tiene sentido para pi-4g.

Uso:
    python scripts/analisis/consumo_datos.py --dir resultados/campana/<corrida1> [--dir ...]
Escribe consumo_datos.json en cada carpeta e imprime un resumen.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MB = 1_000_000  # MB decimales, como los cuentan los planes de datos


def contadores_usb0(texto: str | None) -> tuple[int, int] | None:
    """(rx_bytes, tx_bytes) de la sección 'contadores usb0' de `ip -s link
    show usb0`: la línea siguiente a la cabecera 'RX:' / 'TX:' empieza por
    los bytes. None si el texto no los trae (usb0 inexistente u otro
    formato)."""
    if not texto:
        return None
    seccion = texto.split("=== contadores usb0 ===", 1)
    bloque = seccion[1] if len(seccion) == 2 else texto
    rx = re.search(r"RX:[^\n]*\n\s*(\d+)", bloque)
    tx = re.search(r"TX:[^\n]*\n\s*(\d+)", bloque)
    if not rx or not tx:
        return None
    return int(rx.group(1)), int(tx.group(1))


def consumo_corrida(cfg: dict) -> dict:
    ini = contadores_usb0(cfg.get("estado_red_inicio"))
    fin = contadores_usb0(cfg.get("estado_red_fin"))
    reps = len(cfg.get("chrony_sincronizado_por_repeticion") or {}) or None
    res = {"config": cfg.get("config"), "escenario": cfg.get("escenario"),
           "fecha_inicio": cfg.get("fecha_inicio"), "fecha_fin": cfg.get("fecha_fin"),
           "repeticiones": reps}
    if ini is None or fin is None:
        res["estado"] = "sin contadores de usb0 al inicio o al fin"
        return res
    rx, tx = fin[0] - ini[0], fin[1] - ini[1]
    if rx < 0 or tx < 0:
        res["estado"] = "contador reiniciado (el módem se reconectó durante la corrida)"
        return res
    res.update(estado="ok", rx_bytes=rx, tx_bytes=tx, total_bytes=rx + tx,
               total_mb=round((rx + tx) / MB, 3))
    if reps:
        res["mb_por_repeticion"] = round((rx + tx) / MB / reps, 3)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    args = ap.parse_args()

    total = 0
    for d in map(Path, args.dir):
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        res = consumo_corrida(cfg)
        (d / "consumo_datos.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        if res["estado"] == "ok":
            total += res["total_bytes"]
            por_rep = f", {res['mb_por_repeticion']:.2f} MB/repetición" if "mb_por_repeticion" in res else ""
            print(f"{d.name}: {res['total_mb']:.2f} MB (RX {res['rx_bytes']/MB:.2f} / "
                  f"TX {res['tx_bytes']/MB:.2f}){por_rep}")
        else:
            print(f"{d.name}: {res['estado']}")
    print(f"Total usb0: {total/MB:.2f} MB")


if __name__ == "__main__":
    main()
