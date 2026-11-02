#!/usr/bin/env python3
"""Corre la matriz de pruebas de seguridad (prompt_seguridad.md, S3:
tests/test_seguridad_broker.py) y escribe la evidencia de la sección 4.6
del Capítulo 4 en evidencia/<fecha>_seguridad/:

    resultados.csv      ID, caso, esperado, obtenido, ✔/✘, extracto de log
    <ID>.log            log completo del broker/agente de ese caso
    tabla_seguridad.tex  tabla LaTeX lista para pegar (ver redaccion/)

Si un caso FALLA, este script no lo oculta ni lo reintenta: lo reporta
igual, con ✘, para que sea un hallazgo documentado, no una prueba
ajustada para que pase.

Uso:
    python scripts/seguridad/correr_matriz.py
    python scripts/seguridad/correr_matriz.py --salida evidencia/2026-11-05_seguridad
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
PY = sys.executable

# Descripción de cada caso (ver prompt_seguridad.md, S3) -- estática: no
# se calcula de los datos, es lo que la prueba dice que verifica.
MATRIZ = {
    "T01": ("Cliente sin certificado", "Handshake rechazado"),
    "T02": ("Certificado de una CA ajena", "Handshake rechazado"),
    "T03": ("Cliente que fuerza TLS 1.2", "Handshake rechazado"),
    "T04": ("Certificado vencido", "Handshake rechazado"),
    "T05": ("Certificado revocado (CRL)", "Handshake rechazado -- argumento de revocar una OBU"),
    "T06": ("La OBU publica un M1 en rsu/1/solicitudes", "El suscriptor RSU 1 NO lo recibe"),
    "T07": ("obu-emu-01 publica en obu/obu-emu-02/posicion", "El servidor NO lo recibe"),
    "T08": ("obu-emu-01 se suscribe a obu/obu-emu-02/ruta", "No recibe nada"),
    "T09": ("La RSU 1 se suscribe a rsu/2/solicitudes", "No recibe nada"),
    "T10": ("Una OBU publica un M2 falso en servidor/central/respuestas",
            "El broker LO DEJA PASAR (limitación conocida) y el servidor LO IGNORA"),
    "T11": ("Un cliente legítimo (servidor, RSU 1 y OBU)", "Conecta y el flujo MI->MR y M1->M2 funciona"),
    "T12": ("El cliente verifica el SAN del servidor contra un host que no coincide", "Rechazado del lado del cliente"),
    "T13": ("Repetición de un MP capturado (mismo seq)", "Descartado por el servidor (B2)"),
    "T14": ("SNMPv3 sin autenticación (noAuthNoPriv)", "Rechazado"),
    "T15": ("SNMPv3 con protocolo de autenticación equivocado", "Rechazado"),
    "T16": ("SNMPv3 con clave de autenticación equivocada", "Rechazado"),
}


_RE_ID = re.compile(r"test_(t\d{2})_", re.IGNORECASE)

# T13 ya está cubierto, con esos datos: no se reimplementa aquí, se
# referencia -- "repetición de un MP capturado (mismo seq) descartada"
# es exactamente test_mp_fuera_de_orden_se_descarta (item 2a.2 de
# prompt_integracion_app_obu.md, anterior a este prompt_seguridad.md).
REFERENCIADOS = {
    "test_mp_fuera_de_orden_se_descarta": "T13",
}


def _id_de(nombre_test: str) -> str | None:
    if nombre_test in REFERENCIADOS:
        return REFERENCIADOS[nombre_test]
    m = _RE_ID.match(nombre_test)
    if not m:
        return None
    id_ = m.group(1).upper()
    return id_ if id_ in MATRIZ else None


def _correr_pytest(xml_path: Path) -> None:
    print("Corriendo tests/test_seguridad_broker.py (T13 referenciado en test_gestor_mision.py) ...")
    objetivos = [str(RAIZ / "tests" / "test_seguridad_broker.py")] + [
        f"{RAIZ / 'tests' / 'test_gestor_mision.py'}::{nombre}" for nombre in REFERENCIADOS
    ]
    subprocess.run([PY, "-m", "pytest", *objetivos, "-v", f"--junit-xml={xml_path}"], cwd=RAIZ)
    # No se revisa el returncode: un caso en rojo es un resultado valido
    # de la matriz, no un error de este script.


def _leer_resultados(xml_path: Path) -> dict[str, dict]:
    if not xml_path.exists():
        raise SystemExit(f"{xml_path} no se generó -- ¿pytest no corrió? (revisar si mosquitto está instalado)")
    raiz = ET.parse(xml_path).getroot()
    resultados: dict[str, dict] = {}
    for caso in raiz.iter("testcase"):
        id_ = _id_de(caso.get("name", ""))
        if id_ is None:
            continue
        fallo = caso.find("failure")
        error = caso.find("error")
        omitido = caso.find("skipped")
        if omitido is not None:
            resultados[id_] = {"estado": "omitido", "detalle": omitido.get("message", "")}
        elif fallo is not None:
            resultados[id_] = {"estado": "FALLO", "detalle": (fallo.text or "").strip().splitlines()[-1][:300]}
        elif error is not None:
            resultados[id_] = {"estado": "ERROR", "detalle": (error.text or "").strip().splitlines()[-1][:300]}
        else:
            resultados[id_] = {"estado": "ok", "detalle": ""}
    return resultados


def _nombre_archivo_log(id_: str) -> str:
    # Debe coincidir con tests/test_seguridad_broker.py::banco (nombre del
    # test sin "test_" ni params) -- se busca por substring porque el
    # nombre completo de la funcion incluye una descripcion despues del ID.
    logs_dir = RAIZ / "deploy" / "pki_banco" / "_logs_por_caso"
    if not logs_dir.exists():
        return ""
    for archivo in logs_dir.glob(f"{id_.lower()}_*.log"):
        return archivo.name
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", default=None, help=f"default: evidencia/{date.today():%Y-%m-%d}_seguridad")
    args = ap.parse_args()

    salida = Path(args.salida) if args.salida else RAIZ / "evidencia" / f"{date.today():%Y-%m-%d}_seguridad"
    salida.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "resultados.xml"
        _correr_pytest(xml_path)
        resultados = _leer_resultados(xml_path)

    logs_dir = RAIZ / "deploy" / "pki_banco" / "_logs_por_caso"
    filas_tex = []
    with (salida / "resultados.csv").open("w", newline="", encoding="utf-8") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(["ID", "caso", "esperado", "obtenido", "resultado", "log"])
        for id_, (caso, esperado) in MATRIZ.items():
            r = resultados.get(id_, {"estado": "no corrido", "detalle": ""})
            marca = "✔" if r["estado"] == "ok" else ("-" if r["estado"] == "omitido" else "✘")
            obtenido = r["estado"] if not r["detalle"] else f"{r['estado']}: {r['detalle']}"
            nombre_log = _nombre_archivo_log(id_)
            if nombre_log:
                # .txt, no .log: el .gitignore del proyecto ignora *.log en
                # todo el repo (ningún .log se comitea nunca, ver la regla
                # de "Logs") -- la copia de evidencia necesita otra
                # extensión para no perderse en silencio al comitear.
                shutil.copy(logs_dir / nombre_log, salida / f"{id_}.txt")
                log_rel = f"{id_}.txt"
            else:
                log_rel = ""
            escritor.writerow([id_, caso, esperado, obtenido, marca, log_rel])
            filas_tex.append(f"{id_} & {caso} & {esperado} & {marca} \\\\")

    tex = f"""\\begin{{table}}[H]
\\centering
\\caption{{Matriz de pruebas de seguridad del broker y del agente SNMPv3 ({date.today():%Y-%m-%d}).}}
\\label{{tab:seguridad_matriz}}
\\small
\\begin{{tabular}}{{lp{{5cm}}p{{4cm}}c}}
\\toprule
\\textbf{{ID}} & \\textbf{{Caso}} & \\textbf{{Resultado esperado}} & \\textbf{{OK}} \\\\
\\midrule
{chr(10).join(filas_tex)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""
    (salida / "tabla_seguridad.tex").write_text(tex, encoding="utf-8")

    n_ok = sum(1 for r in resultados.values() if r["estado"] == "ok")
    n_mal = sum(1 for r in resultados.values() if r["estado"] in ("FALLO", "ERROR"))
    print(f"\n{n_ok}/{len(MATRIZ)} casos en verde, {n_mal} en rojo.")
    if n_mal:
        print("*** HAY CASOS EN ROJO -- revisar resultados.csv antes de usar esta evidencia. "
              "No se ajustan las pruebas para que pasen. ***")
    print(f"Evidencia en {salida}")


if __name__ == "__main__":
    main()
