#!/usr/bin/env python3
"""M4 (prompt_figuras_cap4.md, OE3): validación del middleware NTCIP --
traducción y rechazo correctos.

Parte A (traducción correcta): sobre las 4 campañas válidas (y,
opcionalmente, la corrida de M1), por cada M1 inicial (seq=1) recibido por
la RSU, ¿hubo un snmp_set_tx de decisión (NTCIP 1211: request_priority o
en_cola_despeje, según la fase)? Y de esos, ¿el controlador quedó en un
estado consistente con la prioridad (ctrl_fase_cambio motivo=solicitud_prioridad,
o ya estaba en verde -- ver llegadas_verde_contrafactual.py)? Por cada M3
recibido, ¿hubo un snmp_set_tx de cancelación (accion=clear_priority_m3)?
Además, cuando los eventos lo permiten: tiempo M1 recibido -> SET NTCIP
(= t_RSU, ya definido en lazo_centralizado.py) y SET -> cambio de fase real
(ctrl_fase_cambio correspondiente - snmp_set_tx), como columnas aparte.

Parte B (rechazo correcto): NO duplica pruebas. Corre con pytest las que ya
verifican RF-06 (límites/cola de despeje), RF-09 (caducidad 3s) y mensajes
inválidos/duplicados (tests/test_ntcip1211.py, tests/test_controller_emulator.py,
tests/test_modo_seguro.py, tests/test_rsu_middleware_validacion.py -- este
último se agregó en esta misma sesión porque "M1 repetido"/"M1 inválido" no
tenían prueba a nivel de la lógica de rechazo, solo del texto de consola)
y arma una tabla caso -> resultado esperado -> obtenido a partir de su
propio resultado (pass/fail), leyendo el docstring/nombre de cada test como
"caso" y "resultado esperado".

Salidas en --salida:
  tabla_ntcip_traduccion.tex
  tabla_ntcip_rechazo.tex

Uso:
    python scripts/analisis/validacion_ntcip.py \\
        --dir resultados/campana/<corrida1> --dir resultados/campana/<corrida2> ... \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import cargar, percentil  # noqa: E402
from common.events import EVT_CTRL_FASE_CAMBIO, EVT_M1_RX, EVT_M3_RX, EVT_M2_TX  # noqa: E402

NS = 1_000_000_000.0
MS = 1_000_000.0
ACCIONES_DECISION = ("request_priority", "en_cola_despeje")
ACCION_CANCELACION = "clear_priority_m3"

TESTS_RECHAZO = [
    ("tests/test_ntcip1211.py::TestRF05ClaseNoReconocida::test_clase_reconocida_se_acepta",
     "M1 con clase reconocida (CLASES_EMERGENCIA_RECONOCIDAS)", "se acepta (RF-05)"),
    ("tests/test_ntcip1211.py::TestRF05ClaseNoReconocida::test_clase_no_reconocida_se_rechaza",
     "M1 con clase NO reconocida", "se rechaza (RF-05)"),
    ("tests/test_ntcip1211.py::TestRF06LimitesOperacionales::test_se_encola_durante_amarillo",
     "M1 durante amarillo (fase no interrumpible)", "se encola, no se rechaza directo (RF-06)"),
    ("tests/test_ntcip1211.py::TestRF06LimitesOperacionales::test_se_encola_durante_todo_rojo",
     "M1 durante todo_rojo (fase no interrumpible)", "se encola, no se rechaza directo (RF-06)"),
    ("tests/test_ntcip1211.py::TestRF06LimitesOperacionales::test_se_acepta_durante_verde_o_rojo_general",
     "M1 durante verde o rojo_general (fase interrumpible)", "se activa de inmediato (RF-06)"),
    ("tests/test_ntcip1211.py::TestRF06LimitesOperacionales::test_se_activa_al_terminar_el_despeje_dentro_del_ttl",
     "M1 encolado, despeje termina dentro del TTL", "se activa al terminar el despeje (RF-06)"),
    ("tests/test_ntcip1211.py::TestRF06LimitesOperacionales::test_caduca_en_cola_si_el_despeje_tarda_mas_que_el_ttl",
     "M1 encolado, despeje tarda más que el TTL", "caduca en cola, no se activa (RF-06/RF-09)"),
    ("tests/test_ntcip1211.py::TestRF09Caducidad::test_no_caduca_si_se_refresca_a_tiempo",
     "Solicitud activa renovada antes de T_CAD=3s", "no caduca (RF-09)"),
    ("tests/test_ntcip1211.py::TestRF09Caducidad::test_caduca_pasado_t_cad_sin_actualizar",
     "Solicitud activa sin renovar, pasado T_CAD=3s", "caduca sola (RF-09/RNF-03)"),
    ("tests/test_ntcip1211.py::TestRF09Caducidad::test_verificar_caducidad_es_no_op_sin_solicitud_activa",
     "Verificación de caducidad sin ninguna solicitud activa", "no-op, no falla (RF-09)"),
    ("tests/test_ntcip1211.py::TestRF04CancelacionM3::test_cancela_solicitud_activa",
     "M3 sobre una solicitud activa (en verde forzado)", "se cancela (RF-04)"),
    ("tests/test_ntcip1211.py::TestRF04CancelacionM3::test_cancela_solicitud_en_cola",
     "M3 sobre una solicitud encolada (RF-06)", "se cancela, sale de la cola (RF-04)"),
    ("tests/test_ntcip1211.py::TestCodecOER::test_rechaza_longitud_distinta_de_29_al_decodificar",
     "OCTET STRING NTCIP 1211 con longitud != 29 bytes", "se rechaza al decodificar (mensaje inválido)"),
    ("tests/test_ntcip1211.py::TestCodecOER::test_rechaza_campo_fuera_de_rango_al_codificar",
     "Campo del codec OER fuera de rango", "se rechaza al codificar (mensaje inválido)"),
    ("tests/test_ntcip1211.py::TestCodecOER::test_rechaza_vehiculo_id_demasiado_largo",
     "vehiculo_id más largo que el campo OER", "se rechaza al codificar (mensaje inválido)"),
    ("tests/test_controller_emulator.py::test_prioridad_deja_el_ciclo_de_fondo_coherente_al_liberar",
     "Reloj de fondo del controlador tras liberar una prioridad", "queda coherente con el ciclo real, no se reinicia"),
    ("tests/test_modo_seguro.py::TestModoSeguroSinRenovacionDelServidor::test_solicitud_activa_caduca_sola_sin_mas_m1",
     "Solicitud activa sin más M1 del servidor (modo seguro)", "caduca sola, no se sostiene indefinida (RNF-03)"),
    ("tests/test_modo_seguro.py::TestModoSeguroSinRenovacionDelServidor::test_no_hay_reactivacion_automatica_tras_caducar",
     "Tras caducar, sin M1 nuevo", "no hay reactivación automática (RNF-03)"),
    ("tests/test_rsu_middleware_validacion.py::test_m1_repetido_mismo_seq_se_rechaza",
     "M1 repetido (mismo seq que el último visto) -- AGREGADO en esta sesión, sin prueba previa",
     "se descarta como duplicado (replay)"),
    ("tests/test_rsu_middleware_validacion.py::test_m1_repetido_seq_menor_se_rechaza",
     "M1 con seq menor al último visto (reenvío desordenado) -- AGREGADO en esta sesión",
     "se descarta como duplicado (replay)"),
    ("tests/test_rsu_middleware_validacion.py::test_m1_invalido_sin_id_solicitud_no_lanza_excepcion",
     "M1 sin campo id_solicitud (mensaje inválido) -- AGREGADO en esta sesión, sin prueba previa",
     "se descarta (log 'M1 invalido'), no interrumpe el proceso"),
    ("tests/test_rsu_middleware_validacion.py::test_m1_invalido_seq_no_numerico_no_lanza_excepcion",
     "M1 con seq no numérico (mensaje inválido) -- AGREGADO en esta sesión",
     "se descarta (log 'M1 invalido'), no interrumpe el proceso"),
]


def correr_tests_rechazo() -> dict[str, bool]:
    """Corre los tests de TESTS_RECHAZO con pytest (--junit-xml) y devuelve
    {nodeid: paso (bool)}. No duplica la lógica de los tests: solo lee su
    resultado real."""
    ids = sorted({t[0] for t in TESTS_RECHAZO})
    xml_path = RAIZ / "scripts" / "analisis" / "_tmp_ntcip_rechazo.xml"
    subprocess.run([sys.executable, "-m", "pytest", *ids, "-q", f"--junit-xml={xml_path}"],
                   cwd=RAIZ, capture_output=True, text=True)
    resultados: dict[str, bool] = {}
    if xml_path.exists():
        tree = ET.parse(xml_path)
        for case in tree.iter("testcase"):
            nodeid = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name')}"
            # classname viene como tests.test_x.Clase o tests.test_x -- normalizar a tests/test_x.py::...
            partes = case.get("classname", "").split(".")
            archivo = "tests/" + partes[1] + ".py" if len(partes) > 1 else ""
            resto = "::".join(partes[2:] + [case.get("name")]) if len(partes) > 2 else case.get("name")
            nodeid_norm = f"{archivo}::{resto}"
            paso = not case.find("failure") is not None and not case.find("error") is not None
            resultados[nodeid_norm] = paso
        xml_path.unlink()
    return resultados


def tabla_rechazo_latex(resultados: dict[str, bool], salida: Path) -> None:
    lineas = [
        "\\begin{table}[H]", "\\centering",
        "\\caption{Casos de rechazo/aceptación correctos del middleware NTCIP (OE3), a partir del "
        "resultado real de las pruebas automatizadas existentes (no se repite su lógica, solo se "
        "recoge pass/fail). Los últimos cuatro casos se agregaron en esta sesión "
        "(tests/test\\_rsu\\_middleware\\_validacion.py) porque no tenían prueba a nivel de la lógica "
        "de rechazo.}",
        "\\label{tab:ntcip_rechazo}", "\\small",
        "\\begin{tabular}{p{5.2cm}p{4.5cm}p{1.6cm}}", "\\toprule",
        "\\textbf{Caso} & \\textbf{Resultado esperado} & \\textbf{Obtenido} \\\\", "\\midrule",
    ]
    for nodeid, caso, esperado in TESTS_RECHAZO:
        obtenido = resultados.get(nodeid)
        obtenido_txt = "PASA" if obtenido else ("FALLA" if obtenido is False else "sin dato")
        caso_esc = caso.replace("_", "\\_")
        esperado_esc = esperado.replace("_", "\\_")
        lineas.append(f"{caso_esc} & {esperado_esc} & {obtenido_txt} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_ntcip_rechazo.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def analizar_traduccion(dirs: list[Path]) -> dict:
    eventos = cargar(dirs)
    por_parada: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        por_parada[e["id_solicitud"]].append(e)

    n_m1_iniciales = n_set_ok = n_ctrl_consistente = 0
    n_m3 = n_m3_cancelado_ok = 0
    t_m1_set, t_set_fase = [], []

    for id_sol, evs in por_parada.items():
        m1_1 = next((e for e in evs if e["tipo_evento"] == EVT_M1_RX and e["extra"].get("seq") == 1), None)
        if m1_1 is not None:
            n_m1_iniciales += 1
            sets = sorted((e for e in evs if e["tipo_evento"] == "snmp_set_tx"), key=lambda e: e["ts_ns"])
            decision = next((e for e in sets if e["extra"].get("accion") in ACCIONES_DECISION), None)
            if decision is not None:
                n_set_ok += 1
                t_m1_set.append((decision["ts_ns"] - m1_1["ts_ns"]) / MS)
                ctrl_sol = next((e for e in evs if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO
                                 and e["extra"].get("motivo") == "solicitud_prioridad"), None)
                if ctrl_sol is not None:
                    n_ctrl_consistente += 1
                    t_set_fase.append((ctrl_sol["ts_ns"] - decision["ts_ns"]) / MS)
                elif decision["extra"].get("fase") == "verde":
                    n_ctrl_consistente += 1  # ya estaba en verde, consistente sin cambio (ver M2)
                    t_set_fase.append(0.0)

        m3 = next((e for e in evs if e["tipo_evento"] == EVT_M3_RX), None)
        if m3 is not None:
            n_m3 += 1
            cancel = next((e for e in evs if e["tipo_evento"] == "snmp_set_tx"
                           and e["extra"].get("accion") == ACCION_CANCELACION and e["ts_ns"] >= m3["ts_ns"]), None)
            if cancel is not None:
                n_m3_cancelado_ok += 1

    return {
        "n_m1_iniciales": n_m1_iniciales, "n_set_ok": n_set_ok, "n_ctrl_consistente": n_ctrl_consistente,
        "n_m3": n_m3, "n_m3_cancelado_ok": n_m3_cancelado_ok,
        "t_m1_set_ms": t_m1_set, "t_set_fase_ms": t_set_fase,
    }


def tabla_traduccion_latex(r: dict, salida: Path) -> None:
    def pct(a, b):
        return f"{100.0 * a / b:.1f}\\%" if b else "--"

    def stats(vals):
        if not vals:
            return "--", "--"
        return f"{percentil(vals, 50):.2f}", f"{percentil(vals, 95):.2f}"

    med_m1set, p95_m1set = stats(r["t_m1_set_ms"])
    med_setfase, p95_setfase = stats(r["t_set_fase_ms"])

    lineas = [
        "\\begin{table}[H]", "\\centering",
        "\\caption{Traducción correcta del middleware NTCIP (OE3), sobre las 4 campañas válidas del "
        "29/10 más la corrida multi-RSU del 2026-11-02 (ver M1). "
        "`M1 → SET' cuenta cada M1 inicial (seq=1) recibido por la RSU frente a si se tradujo en una "
        "escritura NTCIP 1211 (request\\_priority o en\\_cola\\_despeje); `SET → fase' cuenta, de esos, "
        "si el controlador quedó en un estado consistente con la prioridad (cambio de fase logueado, o "
        "ya estaba en verde); `M3 → cancelación' cuenta cada M3 recibido frente a si se tradujo en "
        "clear\\_priority\\_m3.}",
        "\\label{tab:ntcip_traduccion}", "\\small",
        "\\begin{tabular}{lrrrr}", "\\toprule",
        "\\textbf{Métrica} & \\textbf{n} & \\textbf{\\% correcto} & "
        "\\textbf{Mediana (ms)} & \\textbf{p95 (ms)} \\\\", "\\midrule",
        f"M1 recibido $\\to$ SET NTCIP & {r['n_m1_iniciales']} & {pct(r['n_set_ok'], r['n_m1_iniciales'])} & "
        f"{med_m1set} & {p95_m1set} \\\\",
        f"SET $\\to$ cambio de fase consistente & {r['n_set_ok']} & "
        f"{pct(r['n_ctrl_consistente'], r['n_set_ok'])} & {med_setfase} & {p95_setfase} \\\\",
        f"M3 recibido $\\to$ cancelación NTCIP & {r['n_m3']} & {pct(r['n_m3_cancelado_ok'], r['n_m3'])} & -- & -- \\\\",
    ]
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_ntcip_traduccion.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    r = analizar_traduccion([Path(d) for d in args.dir])
    tabla_traduccion_latex(r, salida)
    print(f"Traducción: M1->SET {r['n_set_ok']}/{r['n_m1_iniciales']}, "
         f"SET->fase {r['n_ctrl_consistente']}/{r['n_set_ok']}, "
         f"M3->cancelación {r['n_m3_cancelado_ok']}/{r['n_m3']}")

    resultados_tests = correr_tests_rechazo()
    tabla_rechazo_latex(resultados_tests, salida)
    n_pasa = sum(1 for v in resultados_tests.values() if v)
    print(f"Rechazo: {n_pasa}/{len(resultados_tests)} pruebas en verde "
         f"(de {len(TESTS_RECHAZO)} casos listados)")
    print(f"Tablas en {salida}: tabla_ntcip_traduccion.tex, tabla_ntcip_rechazo.tex")


if __name__ == "__main__":
    main()
