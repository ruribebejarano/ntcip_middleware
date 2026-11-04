#!/usr/bin/env python3
"""M2 (prompt_figuras_cap4.md): llegadas en verde con prioridad y estimación
contrafactual de lo que habría pasado SIN prioridad, sobre las 4 campañas
válidas de la arquitectura centralizada (resultados/campana/2026102*,
excluida _descartadas/) más, opcionalmente, la corrida multi-RSU de M1.

*** Es una ESTIMACIÓN CONTRAFACTUAL sobre un controlador EMULADO de tiempos
fijos (verde 8s + amarillo 3.0s + todo_rojo 2.0s + rojo_general 8s = 21s,
controller/controller_emulator.py, sin --phase-* ni set_timing en estas
campañas -- ver scripts/campanas/lazo_centralizado.py) con trayectorias
REPRODUCIDAS: el vehículo no frena en rojo (la trayectoria es la misma con o
sin prioridad), así que la demora "evitada" es la que el controlador
emulado habría impuesto, no una medida de un vehículo real deteniéndose. ***

Metodología para la fase SIN prioridad en el instante del cruce (NO es una
reconstrucción analítica del ciclo vía offset: el controlador NUNCA pausa su
reloj de fondo, ni siquiera durante una solicitud de prioridad activa --
ver controller/controller_emulator.py::Controller._fase_normal_locked --
así que la fase real que el watchdog mide justo al liberar la prioridad
(motivo='liberacion_manual' o 'caducidad_prioridad' en ctrl_fase_cambio) YA
ES la fase natural en ese instante, medida, no calculada):

  1. Si hay un evento ctrl_fase_cambio con motivo liberacion_manual o
     caducidad_prioridad para esa parada: su campo `fase` es la fase SIN
     prioridad en el instante de la liberación (que ocurre a los pocos ms
     del M3 motivo=cruce -- ver agent/rsu_middleware.py, clear_priority
     inmediato al recibir M3). Fuente directa, no una proyección.
  2. Si NO hay ese evento pero la parada fue 'concedida' (prioridad activa
     sostenida en 'verde' hasta el cruce): la ausencia de una fila nueva en
     ctrl_fase_cambio significa que, al revisar, la fase natural TAMBIÉN
     era 'verde' (si hubiera sido otra, _log_si_cambio_locked habría
     logueado el cambio) -- también medido, por omisión informativa.
  3. Si ninguna de las dos aplica (p. ej. 'rechazada'/'sin_verde': nunca se
     forzó ni liberó prioridad, no hay ningún evento de referencia en esa
     parada): NO se reconstruye nada -- se cuenta aparte como "sin dato".

Para la demora evitada (tiempo hasta el siguiente verde del plan, cuando la
fase sin prioridad en el cruce NO es verde): el método anterior da la
IDENTIDAD de la fase en el cruce, pero no en qué punto de esa fase está (no
hay una segunda referencia dentro de la misma parada para fijarlo exacto --
ver docstring de este módulo y docs/bitacora de esta sesión). Se reporta un
RANGO exacto (mínimo = 0 s restantes de esa fase, máximo = su duración
completa) y un punto central bajo el supuesto de llegada uniforme dentro de
la fase (esperanza = duración/2, igual que el supuesto de Webster para
retardo de semáforos de tiempo fijo) -- el punto central es una ESTIMACIÓN
MODELADA, marcada como tal, no una medición.

Salidas en --salida:
  tabla_contrafactual.tex   N, % verde con prioridad, % verde sin prioridad
                            (estimado), demora evitada (mediana/p95/total)
                            por condición y escenario.
  contrafactual_detalle.csv  una fila por parada con cruce real, con la
                            fase sin prioridad, el método usado y el rango
                            de demora.
  sin_dato_contrafactual.txt  paradas donde no se pudo determinar la fase
                            sin prioridad (rechazada/sin_verde sin evento
                            de referencia), para no omitirlas en silencio.

Uso:
    python scripts/analisis/llegadas_verde_contrafactual.py \\
        --dir resultados/campana/<corrida1> --dir resultados/campana/<corrida2> ... \\
        --salida resultados/campana/_figuras_cap4_2026-11-02
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))
sys.path.insert(0, str(RAIZ))
from lazo_centralizado import analizar, cargar, percentil  # noqa: E402
from common.events import EVT_CTRL_FASE_CAMBIO  # noqa: E402

NS = 1_000_000_000.0

#: duraciones por defecto del controlador emulado (controller/controller_emulator.py,
#: DEFAULT_PHASE_MINIMUM_GREEN_S=8, DEFAULT_PHASE_YELLOW_CHANGE_DS=30 (=3.0s),
#: DEFAULT_PHASE_RED_CLEAR_DS=20 (=2.0s), DEFAULT_ROJO_GENERAL_S=8). Confirmado
#: sin overrides en scripts/campanas/lazo_centralizado.py (no pasa --phase-*
#: ni set_timing).
DURACIONES_S = {"verde": 8.0, "amarillo": 3.0, "todo_rojo": 2.0, "rojo_general": 8.0}
ORDEN_CICLO = ["verde", "amarillo", "todo_rojo", "rojo_general"]
MOTIVOS_LIBERACION = ("liberacion_manual", "caducidad_prioridad")


def demora_hasta_verde_s(fase: str) -> tuple[float, float, float]:
    """(estimado bajo llegada uniforme, mínimo exacto, máximo exacto) de
    espera hasta el próximo verde del plan, partiendo de `fase`. Si
    fase == 'verde', (0, 0, 0): ya estaría en verde, no hay demora que
    evitar (ver fase_natural_en_cruce: ese caso no entra en este cálculo,
    se cuenta en 'verde sin prioridad')."""
    if fase == "verde":
        return 0.0, 0.0, 0.0
    idx = ORDEN_CICLO.index(fase)
    resto = sum(DURACIONES_S[f] for f in ORDEN_CICLO[idx + 1:])
    d = DURACIONES_S[fase]
    return d / 2.0 + resto, resto, d + resto


def fase_natural_en_cruce(eventos_parada: list[dict], resultado: str) -> tuple[str | None, str]:
    """(fase, metodo) -- ver docstring del módulo. metodo in
    ('medido_liberacion', 'medido_sin_cambio', 'sin_dato')."""
    ctrl = sorted((e for e in eventos_parada if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO),
                 key=lambda e: e["ts_ns"])
    liberacion = next((e for e in reversed(ctrl) if e["extra"].get("motivo") in MOTIVOS_LIBERACION), None)
    if liberacion is not None:
        return liberacion["extra"].get("fase"), "medido_liberacion"
    if resultado == "concedida":
        # Prioridad activa sostenida hasta el cruce sin que se detectara (ni
        # se logueara) ningún cambio de fase natural: la fase natural en el
        # cruce también era 'verde' (ver punto 2 del docstring).
        return "verde", "medido_sin_cambio"
    return None, "sin_dato"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    grupos: dict[str, list[dict]] = defaultdict(list)
    sin_dato: list[dict] = []

    for d in args.dir:
        d = Path(d)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        etiqueta = f"{cfg['config']}/{cfg['escenario']}"
        eventos = cargar([d])
        filas_mision, filas_parada, _ = analizar(eventos)

        # Mismo agrupamiento por id_solicitud que lazo_centralizado.analizar(),
        # para encontrar los eventos ctrl_fase_cambio de cada parada.
        por_parada: dict[str, list[dict]] = defaultdict(list)
        for e in eventos:
            por_parada[e["id_solicitud"]].append(e)

        for f in filas_parada:
            if f["ultimo_m3_motivo"] != "cruce":
                continue  # sin cruce real (desvio/conflicto/etc.): fuera de alcance de M2
            fase, metodo = fase_natural_en_cruce(por_parada.get(f["id_solicitud"], []), f["resultado"])
            fila = {
                "etiqueta": etiqueta, "id_solicitud": f["id_solicitud"], "rsu_id": f["rsu_id"],
                "resultado": f["resultado"], "obtuvo_verde": f["obtuvo_verde"],
                "fase_sin_prioridad": fase, "metodo": metodo,
            }
            if metodo == "sin_dato":
                sin_dato.append(fila)
                continue
            esperado, dmin, dmax = demora_hasta_verde_s(fase)
            fila.update(habria_sido_rojo=(fase != "verde"), demora_evitada_estimada_s=esperado,
                       demora_evitada_min_s=dmin, demora_evitada_max_s=dmax)
            grupos[etiqueta].append(fila)

    # --- tabla_contrafactual.tex -------------------------------------------
    lineas = [
        "\\begin{table}[H]", "\\centering",
        "\\caption{Llegadas en verde con prioridad y estimación contrafactual sin prioridad "
        "(controlador emulado de tiempos fijos: verde 8~s, ámbar 3~s, todo rojo 2~s, rojo general 8~s). "
        "La demora evitada es el valor esperado bajo el supuesto de llegada uniforme dentro de la "
        "fase (la mitad de su duración más las fases completas restantes hasta el verde); su mediana, "
        "p95 y total se calculan sobre los cruces que sin prioridad no habrían sido en verde.}",
        "\\label{tab:contrafactual_verde}", "\\small",
        "\\begin{tabular}{l r >{\\raggedleft\\arraybackslash}p{1.9cm} >{\\raggedleft\\arraybackslash}p{1.9cm} "
        ">{\\raggedleft\\arraybackslash}p{2.1cm} r r}", "\\toprule",
        "\\textbf{Condición/ escenario} & \\textbf{N} & \\textbf{\\% verde con prioridad} & "
        "\\textbf{\\% verde sin prioridad (est.)} & \\textbf{Demora evitada, mediana (s)} & "
        "\\textbf{p95 (s)} & \\textbf{Total (s)} \\\\",
        "\\midrule",
    ]
    for etq, filas in grupos.items():
        n = len(filas)
        pct_con = 100.0 * sum(1 for f in filas if f["obtuvo_verde"]) / n if n else float("nan")
        pct_sin = 100.0 * sum(1 for f in filas if not f["habria_sido_rojo"]) / n if n else float("nan")
        demoras = [f["demora_evitada_estimada_s"] for f in filas if f["habria_sido_rojo"]]
        mediana = percentil(demoras, 50) if demoras else None
        p95 = percentil(demoras, 95) if demoras else None
        total = sum(demoras)
        med_txt = f"{mediana:.2f}" if mediana is not None else "--"
        p95_txt = f"{p95:.2f}" if p95 is not None else "--"
        lineas.append(f"{etq} & {n} & {pct_con:.1f} & {pct_sin:.1f} & {med_txt} & {p95_txt} & {total:.2f} \\\\")
    lineas += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    (salida / "tabla_contrafactual.tex").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # --- contrafactual_detalle.csv -----------------------------------------
    import csv as csv_mod
    campos = ["etiqueta", "id_solicitud", "rsu_id", "resultado", "obtuvo_verde", "fase_sin_prioridad",
              "metodo", "habria_sido_rojo", "demora_evitada_estimada_s", "demora_evitada_min_s",
              "demora_evitada_max_s"]
    with (salida / "contrafactual_detalle.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv_mod.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for filas in grupos.values():
            for f in filas:
                w.writerow({k: f.get(k) for k in campos})

    # --- sin_dato_contrafactual.txt -----------------------------------------
    if sin_dato:
        texto = "\n".join(
            f"{f['id_solicitud']} ({f['etiqueta']}, RSU {f['rsu_id']}, resultado={f['resultado']}): "
            "sin evento ctrl_fase_cambio de referencia (nunca se forzó ni liberó prioridad en esta "
            "parada) -- no se reconstruye la fase sin prioridad para no inventarla."
            for f in sin_dato
        )
    else:
        texto = ("Ninguna parada con cruce real quedó sin dato: todas tenían resultado='concedida' "
                 "(con evento de liberación o sin cambio detectado) para determinar la fase sin "
                 "prioridad en el cruce.")
    (salida / "sin_dato_contrafactual.txt").write_text(texto + "\n", encoding="utf-8")

    print(f"Tabla/CSV en {salida}: tabla_contrafactual.tex, contrafactual_detalle.csv, "
         f"sin_dato_contrafactual.txt")
    for etq, filas in grupos.items():
        n = len(filas)
        pct_con = 100.0 * sum(1 for f in filas if f["obtuvo_verde"]) / n if n else float("nan")
        pct_sin = 100.0 * sum(1 for f in filas if not f["habria_sido_rojo"]) / n if n else float("nan")
        print(f"  [{etq}] n={n}, verde con prioridad={pct_con:.1f}%, verde sin prioridad (est.)={pct_sin:.1f}%")
    print(f"  Paradas sin dato para el contrafactual: {len(sin_dato)}")


if __name__ == "__main__":
    main()
