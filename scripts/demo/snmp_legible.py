#!/usr/bin/env python3
"""Traduce la salida de `software_gestion.py walk` sobre NTCIP 1202 a una
tabla legible: nombre del objeto, valor y su significado.

    python centro_control/software_gestion.py walk ... 1.3.6.1.4.1.1206.4.2.1 2>&1 \\
        | python scripts/demo/snmp_legible.py
"""

from __future__ import annotations

import re
import sys

BASE = "1.3.6.1.4.1.1206.4.2.1"
OBJETOS = {
    ".1.1.0": ("maxPhases", "fases del controlador", None),
    ".1.2.1.1.1": ("phaseNumber (fase 1)", "numero de la fase", None),
    ".1.2.1.4.1": ("phaseMinimumGreen", "verde minimo", lambda v: f"{v} s"),
    ".1.2.1.8.1": ("phaseYellowChange", "ambar", lambda v: f"{int(v) / 10:.1f} s"),
    ".1.2.1.9.1": ("phaseRedClear", "todo rojo", lambda v: f"{int(v) / 10:.1f} s"),
    ".1.3.0": ("maxPhaseGroups", "grupos de estado", None),
    ".1.4.1.1.1": ("phaseStatusGroupNumber", "grupo de estado", None),
    ".1.4.1.2.1": ("phaseStatusGroupReds", "luz ROJA encendida", lambda v: "SI" if v == "1" else "no"),
    ".1.4.1.3.1": ("phaseStatusGroupYellows", "luz AMBAR encendida", lambda v: "SI" if v == "1" else "no"),
    ".1.4.1.4.1": ("phaseStatusGroupGreens", "luz VERDE encendida", lambda v: "SI" if v == "1" else "no"),
}

patron = re.compile(r"(\d+(?:\.\d+)+)\s*=\s*(.*)$")
vistos = 0
fase = None
print(f"  {'Objeto NTCIP 1202':<26} {'Significado':<24} {'Valor':>8}")
print(f"  {'-' * 26} {'-' * 24} {'-' * 8}")
for linea in sys.stdin:
    m = patron.search(linea.strip())
    if not m:
        if "error" in linea.lower() or "timeout" in linea.lower():
            print("  ! " + linea.strip())
        continue
    oid, valor = m.group(1), m.group(2).strip()
    sufijo = oid[len(BASE):] if oid.startswith(BASE) else oid
    nombre, significado, fmt = OBJETOS.get(sufijo, (oid, "", None))
    texto = fmt(valor) if fmt else valor
    print(f"  {nombre:<26} {significado:<24} {texto:>8}")
    vistos += 1
    if sufijo.startswith(".1.4.1.") and valor == "1" and sufijo != ".1.4.1.1.1":
        fase = {".1.4.1.2.1": "ROJO", ".1.4.1.3.1": "AMBAR", ".1.4.1.4.1": "VERDE"}[sufijo]
if vistos == 0:
    print("  (sin respuesta del agente SNMP: revisar que rsu-agent este activo y el puerto 1161)")
    sys.exit(1)
if fase:
    print(f"\n  => En este instante el semaforo de la RSU esta en {fase}.")
