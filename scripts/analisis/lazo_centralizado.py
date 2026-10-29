#!/usr/bin/env python3
"""Análisis del lazo con la ARQUITECTURA CENTRALIZADA (2026-10-22), sobre
las corridas de scripts/campanas/lazo_centralizado.py. Reemplaza, para este
propósito, a scripts/analisis/lazo_emulado.py (ver su docstring: quedó
obsoleto junto con scripts/campanas/lazo_emulado.py). Definiciones
completas en docs/MEDICION_LATENCIA.md, sección 8.

Dos niveles de agrupación (el servidor ya no recibe M1 de la OBU: la OBU
solo emite MI/MP/MF; es servidor/gestor_mision.py quien decide y emite
M1/M3 a la RSU):

  misión   (mision_id, p. ej. "mis-0716b5ef"): una OBU, un recorrido.
            Mide t_OBU→srv (OBU → servidor) y la anticipación real.
  parada   (id_solicitud = "{mision_id}-{interseccion_id}", p. ej.
            "mis-0716b5ef-C"): una RSU dentro de esa misión. Mide
            t_srv, t_srv→RSU, t_RSU, RTT_srv, L, T_desp y el resultado.

Métricas (ver docs/MEDICION_LATENCIA.md sección 8 para la tabla completa
de fórmula/reloj/confiabilidad):

  t_OBU_srv   MP_rx(servidor, mismo seq) - MP_tx(OBU)              [dos relojes]
  t_srv       M1_tx(seq 1) - MP_rx mas reciente de esa mision      [un reloj: servidor]
  t_srv_RSU   M1_rx(seq 1) - M1_tx(seq 1)                          [dos relojes]
  t_RSU       primer snmp_set_tx (decision) - M1_rx(seq 1)         [un reloj: RSU]
  RTT_srv     M2_rx(seq_ref=1) - M1_tx(seq 1)                      [un reloj: servidor]
  L           primer snmp_set_tx (decision) - M1_tx(seq 1)         [dos relojes] (= t_srv_RSU + t_RSU)
  t_verde     ctrl_fase_cambio(fase=verde, misma parada) - M1_tx(seq 1)  [dos relojes]
  T_desp      activar_cola_rf06 - en_cola_despeje                  [un reloj: RSU]
  anticipacion_real  ctrl_fase_cambio(verde, esa parada) -> M3_tx(motivo=cruce, esa parada)
                     (tiempo entre el verde y el cruce; frente a ANTICIPACION_MINIMA_S, RF8)
                                                                     [dos relojes: servidor y controlador]

*** Relojes ***: t_OBU_srv, t_srv_RSU, L, t_verde y anticipacion_real
cruzan dos máquinas cuando config != "local" (ver config.json de la
corrida) -- se reportan SIEMPRE que haya datos, con una cota de error de
reloj adjunta (ver cota_reloj_pi_ms(), NOTA_RELOJ más abajo), nunca
excluidas por un umbral binario (eso era un error de método, corregido
el 2026-10-28). t_srv, t_RSU, T_desp y RTT_srv usan un solo reloj
siempre y no llevan esa cota: son las métricas de referencia para
config=pi-lan/pi-4g precisamente porque no dependen de sincronizar dos
relojes.

Uso:
    python scripts/analisis/lazo_centralizado.py --dir resultados/campana/<corrida>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.events import (  # noqa: E402
    EVT_CONFLICTO_ARBITRADO,
    EVT_CTRL_FASE_CAMBIO,
    EVT_M1_RX,
    EVT_M1_TX,
    EVT_M2_RX,
    EVT_M3_TX,
    EVT_MISION_ARMADA,
    EVT_MP_RX,
    EVT_MP_TX,
    EVT_SNMP_SET_TX,
    iter_eventos,
)
from servidor.conflictos import Solicitante as _SolicitanteConflicto  # noqa: E402
from servidor.conflictos import arbitrar as _arbitrar_conflicto  # noqa: E402

MS = 1_000_000.0
NS = 1_000_000_000.0
UMBRAL_L_MS = 1000.0  # RNF-01
ANTICIPACION_MINIMA_S = 8.0  # RF8, ver servidor/gestor_mision.py
ACCIONES_DECISION = ("request_priority", "en_cola_despeje")


def percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    k = max(0, min(len(v) - 1, math.ceil(q / 100.0 * len(v)) - 1))
    return v[k]


def resumen(valores: list[float]) -> dict:
    if not valores:
        return {"n": 0}
    return {"n": len(valores), "media": sum(valores) / len(valores), "mediana": percentil(valores, 50),
            "p95": percentil(valores, 95), "max": max(valores), "min": min(valores)}


def cargar(directorios: list[Path]) -> list[dict]:
    eventos = []
    for d in directorios:
        for sub in [d, *[p for p in d.rglob("*") if p.is_dir()]]:
            eventos.extend(iter_eventos(sub))
    vistos, unicos = set(), []
    for e in sorted(eventos, key=lambda e: e["ts_ns"]):
        clave = (e["ts_ns"], e["nodo"], e["tipo_evento"], e["id_solicitud"])
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(e)
    return unicos


NOTA_RELOJ = (
    "Cota de error de reloj (lado Pi, chrony): preferentemente "
    "Root dispersion + Root delay/2 de 'chronyc tracking' (la distancia de "
    "sincronización NTP estándar); si la corrida es anterior a que "
    "scripts/pi.sh clock capturara 'tracking', se usa el campo 'estimated "
    "error' (+/- zzzz) de 'chronyc sources -v' para esa referencia -- "
    "AMBOS son cotas declaradas por chrony, no un offset puntual exacto. "
    "La laptop sincroniza por w32time, cuya precisión NO está "
    "caracterizada: esta cota cubre SOLO el lado de la Pi. "
    "[REVISAR con asesor]."
)


def cota_reloj_pi_ms(texto_reloj: str | None) -> float | None:
    """Cota de error de reloj del lado de la Pi, en ms, a partir del texto
    de `scripts/pi.sh clock` (ver NOTA_RELOJ). Antes de esta versión se
    comparaba el OFFSET PUNTUAL de chrony contra un umbral fijo de 10 ms
    para decidir si "confiar" o "excluir" una métrica de dos relojes por
    completo -- eso es un error de método: el offset puntual (p. ej.
    "-8608us") es un estimado, no una cota, y 10 ms no tiene relación con
    la cota real que chrony declara (~20-50 ms es normal contra NTP
    público). Ahora se reporta la cota en vez de usarla como corte
    binario (ver docs/MEDICION_LATENCIA.md 8.4 y
    docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md)."""
    if not texto_reloj:
        return None
    m_disp = re.search(r"Root dispersion\s*:\s*([\d.]+)\s*seconds", texto_reloj)
    m_delay = re.search(r"Root delay\s*:\s*([\d.]+)\s*seconds", texto_reloj)
    if m_disp and m_delay:
        return (float(m_disp.group(1)) + float(m_delay.group(1)) / 2) * 1000.0
    m = re.search(r"\+/-\s*([\d.]+)\s*(us|ms|s)\b", texto_reloj)
    if not m:
        return None
    factor_a_ms = {"us": 0.001, "ms": 1.0, "s": 1000.0}[m.group(2)]
    return float(m.group(1)) * factor_a_ms


def cota_reloj_pi_ms_de_dirs(dirs: list[Path]) -> float | None:
    """Cota de error de reloj del lado de la Pi para TODA la corrida
    (o corridas, si --dir se repite): 0.0 si todas son config=local
    (mismo reloj, sin tramo entre máquinas); si no, el máximo entre
    'reloj_pi_inicio'/'reloj_pi_fin' de cada config.json -- el más
    conservador. None si algún config.json no-local no tiene el dato o
    no se pudo interpretar (no se asume una cota que no se pudo leer)."""
    cotas: list[float] = []
    todas_local = True
    for d in dirs:
        cfg_path = d / "config.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if cfg.get("config") == "local":
            continue
        todas_local = False
        for campo in ("reloj_pi_inicio", "reloj_pi_fin"):
            c = cota_reloj_pi_ms(cfg.get(campo))
            if c is None:
                return None
            cotas.append(c)
    if todas_local:
        return 0.0
    return max(cotas) if cotas else None


def analizar(eventos: list[dict], cota_reloj_ms: float | None = None) -> tuple[list[dict], list[dict], dict]:
    # --- Nivel misión: obu_id y ts de armado, para emparejar MP_tx/MP_rx ---
    armadas: dict[str, dict] = {}  # mision_id -> {obu_id, ts_ns}
    for e in eventos:
        if e["tipo_evento"] == EVT_MISION_ARMADA:
            armadas[e["id_solicitud"]] = {"obu_id": e["extra"].get("obu_id"), "ts_ns": e["ts_ns"]}

    mp_tx_por_obu: dict[tuple[str, int], int] = {}  # (obu_id, seq) -> ts_ns
    for e in eventos:
        if e["tipo_evento"] == EVT_MP_TX and "seq" in e["extra"]:
            mp_tx_por_obu[(e["nodo"], int(e["extra"]["seq"]))] = e["ts_ns"]

    mp_rx_por_mision: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] == EVT_MP_RX:
            mp_rx_por_mision[e["id_solicitud"]].append(e)

    filas_mision = []
    t_obu_srv_todos = []
    for mision_id, info in armadas.items():
        obu_id = info["obu_id"]
        emparejados = []
        for mp_rx in mp_rx_por_mision.get(mision_id, []):
            seq = mp_rx["extra"].get("seq")
            if seq is None:
                continue
            t_tx = mp_tx_por_obu.get((obu_id, int(seq)))
            if t_tx is not None:
                emparejados.append((mp_rx["ts_ns"] - t_tx) / MS)
        t_obu_srv_todos.extend(emparejados)
        filas_mision.append({
            "mision_id": mision_id, "obu_id": obu_id,
            "n_mp": len(mp_rx_por_mision.get(mision_id, [])),
            "t_OBU_srv_mediana_ms": percentil(emparejados, 50) if emparejados else None,
        })

    # --- Nivel parada: por id_solicitud = "<mision_id>-<interseccion_id>" ---
    por_parada: dict[str, list[dict]] = defaultdict(list)
    for e in eventos:
        if e["tipo_evento"] in (EVT_M1_TX, EVT_M1_RX, EVT_SNMP_SET_TX, EVT_CTRL_FASE_CAMBIO,
                                EVT_M2_RX, EVT_M3_TX):
            por_parada[e["id_solicitud"]].append(e)

    filas_parada = []
    rtt_srv_todos, l_todos, t_rsu_todos, anticipacion_todos = [], [], [], []
    exito = {"concedida": 0, "rechazada": 0, "sin_verde": 0, "sin_respuesta": 0, "total": 0}
    n_cola_despeje = 0
    for id_sol, evs in por_parada.items():
        m1 = sorted((e for e in evs if e["tipo_evento"] == EVT_M1_TX and "seq" in e["extra"]),
                   key=lambda e: e["ts_ns"])
        if not m1:
            continue
        m1_1 = m1[0]
        mision_id = m1_1["extra"].get("mision_id", id_sol.rsplit("-", 1)[0])
        rx1 = next((e for e in evs if e["tipo_evento"] == EVT_M1_RX and e["extra"].get("seq") == 1), None)
        sets = sorted((e for e in evs if e["tipo_evento"] == EVT_SNMP_SET_TX), key=lambda e: e["ts_ns"])
        decision = next((e for e in sets if e["extra"].get("accion") in ACCIONES_DECISION), None)
        cola = next((e for e in sets if e["extra"].get("accion") == "en_cola_despeje"), None)
        activacion = next((e for e in sets if e["extra"].get("accion") == "activar_cola_rf06"), None)
        m2s = sorted((e for e in evs if e["tipo_evento"] == EVT_M2_RX), key=lambda e: e["ts_ns"])
        m2_seq1 = next((e for e in m2s if e["extra"].get("seq_ref") == 1), None)
        m3s_todos = sorted((e for e in evs if e["tipo_evento"] == EVT_M3_TX), key=lambda e: e["ts_ns"])
        m3_cruce = next((e for e in m3s_todos if e["extra"].get("motivo") == "cruce"), None)
        ultimo_m3_motivo = m3s_todos[-1]["extra"].get("motivo") if m3s_todos else None
        verde = sorted((e for e in evs if e["tipo_evento"] == EVT_CTRL_FASE_CAMBIO
                       and e["extra"].get("fase") == "verde"), key=lambda e: e["ts_ns"])

        mp_prev = max((e for e in mp_rx_por_mision.get(mision_id, []) if e["ts_ns"] <= m1_1["ts_ns"]),
                     key=lambda e: e["ts_ns"], default=None)

        t_srv = (m1_1["ts_ns"] - mp_prev["ts_ns"]) / MS if mp_prev else None
        t_srv_rsu = (rx1["ts_ns"] - m1_1["ts_ns"]) / MS if rx1 else None
        t_rsu = (decision["ts_ns"] - rx1["ts_ns"]) / MS if (decision and rx1) else None
        rtt_srv = (m2_seq1["ts_ns"] - m1_1["ts_ns"]) / MS if m2_seq1 else None
        l_ms = (decision["ts_ns"] - m1_1["ts_ns"]) / MS if decision else None
        t_verde = ((verde[0]["ts_ns"] - m1_1["ts_ns"]) / MS) if verde else None
        t_desp = (activacion["ts_ns"] - cola["ts_ns"]) / MS if (activacion and cola) else None
        anticipacion_s = None
        if m3_cruce and verde:
            verde_previo = max((v for v in verde if v["ts_ns"] <= m3_cruce["ts_ns"]),
                              key=lambda v: v["ts_ns"], default=None)
            if verde_previo:
                anticipacion_s = (m3_cruce["ts_ns"] - verde_previo["ts_ns"]) / NS

        concedida = any(e["extra"].get("estado") == "concedida" for e in m2s)
        rechazada = any(e["extra"].get("estado") == "rechazada" for e in m2s)
        resultado = "rechazada" if rechazada else "concedida" if concedida else "sin_verde" if m2s else "sin_respuesta"
        exito[resultado] += 1
        exito["total"] += 1
        if cola:
            n_cola_despeje += 1

        # RNF-01 (L) y las demas metricas de latencia se reportan SOLO
        # sobre solicitudes completadas (llego algun M2) -- un
        # 'sin_respuesta' no tiene una latencia que reportar, tiene una
        # falla de entrega; mezclarlo en el p95 subestimaria la cola de
        # latencia real y a la vez ocultaria la falla. [REVISAR con
        # asesor]: el criterio de exclusion en si (en vez de, p. ej.,
        # contarlo como el peor caso) es una decision de metodo.
        if resultado != "sin_respuesta":
            if rtt_srv is not None:
                rtt_srv_todos.append(rtt_srv)
            if l_ms is not None:
                l_todos.append(l_ms)
            if t_rsu is not None:
                t_rsu_todos.append(t_rsu)
            if anticipacion_s is not None:
                anticipacion_todos.append(anticipacion_s)

        etapa_alcanzada = None
        if resultado == "sin_respuesta":
            # Diagnostico de DONDE se detuvo, no de POR QUE (la causa se
            # investiga en los logs de agent/servidor de esa repeticion,
            # no se asume -- ver docs/bitacora).
            if decision:
                etapa_alcanzada = "decision_sin_m2"  # la RSU decidio pero el M2 nunca llego/se vio
            elif rx1:
                etapa_alcanzada = "m1_rx_sin_decision"  # la RSU recibio el M1 pero no se vio snmp_set_tx
            else:
                etapa_alcanzada = "m1_tx_sin_m1_rx"  # el servidor publico M1 pero no se vio M1_rx en la RSU

        filas_parada.append({
            "id_solicitud": id_sol, "mision_id": mision_id, "rsu_id": m1_1["extra"].get("rsu_id"),
            "resultado": resultado, "etapa_alcanzada": etapa_alcanzada, "cola_despeje": bool(cola),
            "t_srv_ms": t_srv, "t_srv_RSU_ms": t_srv_rsu, "t_RSU_ms": t_rsu, "RTT_srv_ms": rtt_srv,
            "L_ms": l_ms, "t_verde_ms": t_verde, "T_desp_ms": t_desp, "anticipacion_real_s": anticipacion_s,
            "obtuvo_verde": bool(verde), "ultimo_m3_motivo": ultimo_m3_motivo,
        })

    sin_respuesta_por_etapa: dict[str, int] = defaultdict(int)
    for f in filas_parada:
        if f["resultado"] == "sin_respuesta":
            sin_respuesta_por_etapa[f["etapa_alcanzada"]] += 1

    global_ = {
        "cota_reloj_pi_ms": cota_reloj_ms,
        "nota_reloj": NOTA_RELOJ if cota_reloj_ms else None,
        "n_misiones": len(filas_mision), "n_paradas": exito["total"],
        "resultados": {k: v for k, v in exito.items() if k != "total"},
        "sin_respuesta_por_etapa": dict(sin_respuesta_por_etapa),
        "cola_despeje": n_cola_despeje,
        "t_OBU_srv_ms": resumen(t_obu_srv_todos),
        "t_RSU_ms": resumen(t_rsu_todos),
        "RTT_srv_ms": resumen(rtt_srv_todos),
        "L_ms": resumen(l_todos),
        "anticipacion_real_s": resumen(anticipacion_todos),
        "anticipacion_minima_s_rf8": ANTICIPACION_MINIMA_S,
    }
    l_p95 = global_["L_ms"].get("p95")
    global_["rnf01_cumple_p95"] = (l_p95 is not None and l_p95 <= UMBRAL_L_MS)
    # Formulación de peor caso (RNF-01, pedida el 2026-10-28): L sigue
    # siendo el valor medido, pero la conclusión de cumplimiento se da
    # sumando la cota de error de reloj declarada (lado Pi) al p95 medido
    # -- "L < X ms incluso en el peor caso de error de reloj", no un
    # valor puntual exacto que ignore la incertidumbre de sincronización.
    if l_p95 is not None and cota_reloj_ms is not None:
        global_["l_p95_peor_caso_ms"] = l_p95 + cota_reloj_ms
        global_["rnf01_cumple_p95_peor_caso"] = global_["l_p95_peor_caso_ms"] <= UMBRAL_L_MS
    else:
        global_["l_p95_peor_caso_ms"] = None
        global_["rnf01_cumple_p95_peor_caso"] = None
    return filas_mision, filas_parada, global_


def _verificar_ganador(candidatos: list[dict] | None, atendidos_log: list[str]) -> bool | None:
    """Reconstruye los Solicitante logueados (clase/eta_s por mision_id,
    agregado en servidor/gestor_mision.py junto con EVT_CONFLICTO_ARBITRADO)
    y vuelve a correr la MISMA función de política
    (servidor/conflictos.py::arbitrar) para confirmar que lo que el
    servidor decidió en vivo es consistente con sus propios criterios
    (clase y, si empatan, ETA). None si la corrida es anterior a que este
    análisis empezara a pedir 'candidatos' (no se puede verificar)."""
    if not candidatos:
        return None
    # grupo_semaforico distinto para cada candidato: por construcción del
    # escenario 'conflicto' (accesos incompatibles de la misma RSU), ya
    # sabemos que este evento implicó incompatibilidad entre ellos -- no
    # se logueó el grupo_semaforico real, pero para esta verificación basta
    # con forzar la misma incompatibilidad que efectivamente ocurrió.
    solicitantes = [
        _SolicitanteConflicto(mision_id=c["mision_id"], acceso_id=f"acc-{i}",
                              grupo_semaforico=i, clase=c["clase"], eta_s=c["eta_s"])
        for i, c in enumerate(candidatos)
    ]
    resultado = _arbitrar_conflicto("rsu-verificacion-analisis", solicitantes)
    return {s.mision_id for s in resultado.atendidos} == set(atendidos_log)


def analizar_conflicto(eventos: list[dict], filas_parada: list[dict]) -> dict:
    """Métricas propias del escenario 'conflicto'
    (docs/MEDICION_LATENCIA.md sección 8.6 [REVISAR con asesor]): que la
    misión perdedora quede en espera es el comportamiento CORRECTO del
    arbitraje (servidor/conflictos.py), no un fallo. La 'tasa de éxito' de
    este escenario NO es concedidas/total -- es que (a) el servidor haya
    elegido al ganador correcto según su política, (b) el ganador haya
    obtenido verde, y (c) el perdedor se haya atendido después o se haya
    cancelado correctamente al cruzar (en vez de quedar sin resolver).

    *** FUERA DE ALCANCE de la campaña oficial y del Capítulo 4 desde el
    2026-10-28 (decisión del autor; ver docs/CRONOGRAMA.md decisión de
    alcance #2 y docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md).
    Esta función se conserva (igual que el escenario 'conflicto' del
    runner) porque no se borra código verificado -- main() solo la llama
    si --dir apunta a una corrida con escenario='conflicto' en su
    config.json, lo que no debería ocurrir en una campaña nueva."""
    arbitrajes = sorted((e for e in eventos if e["tipo_evento"] == EVT_CONFLICTO_ARBITRADO),
                        key=lambda e: e["ts_ns"])
    rol: dict[str, str] = {}
    eventos_detalle = []
    for ev in arbitrajes:
        atendidos = ev["extra"].get("atendidos", [])
        en_espera = ev["extra"].get("en_espera", [])
        candidatos = ev["extra"].get("candidatos")
        consistente = _verificar_ganador(candidatos, atendidos)
        for mid in atendidos:
            rol[mid] = "ganador"
        for mid in en_espera:
            rol[mid] = "perdedor"
        eventos_detalle.append({
            "rsu_id": ev["extra"].get("rsu_id"), "candidatos": candidatos,
            "atendidos": atendidos, "en_espera": en_espera,
            "consistente_con_politica": consistente,
        })

    ganadores_total = ganadores_con_verde = 0
    perdedores_total = perdedores_atendidos_despues = 0
    perdedores_cancelados_al_cruzar = perdedores_sin_resolver = 0
    sin_conflicto_detectado = 0

    for fila in filas_parada:
        r = rol.get(fila["mision_id"])
        if r is None:
            sin_conflicto_detectado += 1
            continue
        if r == "ganador":
            ganadores_total += 1
            if fila["obtuvo_verde"]:
                ganadores_con_verde += 1
        else:
            perdedores_total += 1
            if fila["resultado"] == "concedida":
                perdedores_atendidos_despues += 1
            elif fila["ultimo_m3_motivo"] == "cruce":
                perdedores_cancelados_al_cruzar += 1
            else:
                perdedores_sin_resolver += 1

    eventos_consistentes = sum(1 for e in eventos_detalle if e["consistente_con_politica"])
    eventos_verificables = sum(1 for e in eventos_detalle if e["consistente_con_politica"] is not None)

    return {
        "eventos_arbitraje": eventos_detalle,
        "arbitraje_consistente_con_politica": f"{eventos_consistentes}/{eventos_verificables}"
                                               if eventos_verificables else "sin datos verificables",
        "ganadores": {"total": ganadores_total, "obtuvieron_verde": ganadores_con_verde},
        "perdedores": {
            "total": perdedores_total,
            "atendidos_despues_de_esperar": perdedores_atendidos_despues,
            "cancelados_correctamente_al_cruzar": perdedores_cancelados_al_cruzar,
            "sin_resolver_al_cierre_de_la_corrida": perdedores_sin_resolver,
        },
        "sin_conflicto_detectado": sin_conflicto_detectado,
        "tasa_exito_arbitraje": (
            (ganadores_con_verde + perdedores_atendidos_despues + perdedores_cancelados_al_cruzar)
            / (ganadores_total + perdedores_total)
            if (ganadores_total + perdedores_total) else None
        ),
    }


def _escenario_de(dirs: list[Path]) -> str | None:
    escenarios = set()
    for d in dirs:
        cfg_path = d / "config.json"
        if cfg_path.exists():
            escenarios.add(json.loads(cfg_path.read_text(encoding="utf-8")).get("escenario"))
    if len(escenarios) > 1:
        print(f"[análisis] AVISO: --dir mezcla escenarios distintos {escenarios}; "
              f"se omite el resumen propio de 'conflicto'.", file=sys.stderr)
        return None
    return escenarios.pop() if escenarios else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    dirs = [Path(d) for d in args.dir]
    cota_reloj_ms = cota_reloj_pi_ms_de_dirs(dirs)
    eventos = cargar(dirs)
    filas_mision, filas_parada, g = analizar(eventos, cota_reloj_ms)
    if not filas_parada:
        print("No hay paradas (M1_tx del servidor con seq) en esas carpetas.", file=sys.stderr)
        raise SystemExit(1)

    if _escenario_de(dirs) == "conflicto":
        g["conflicto"] = analizar_conflicto(eventos, filas_parada)

    salida = Path(args.salida) if args.salida else dirs[0]
    salida.mkdir(parents=True, exist_ok=True)
    with (salida / "lazo_por_mision.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas_mision[0].keys()))
        w.writeheader()
        w.writerows(filas_mision)
    with (salida / "lazo_por_parada.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas_parada[0].keys()))
        w.writeheader()
        w.writerows(filas_parada)
    (salida / "lazo_resumen.json").write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")

    # cota_reloj_ms es None solo cuando hay al menos una corrida no-local
    # cuyo config.json no se pudo interpretar (ver cota_reloj_pi_ms_de_dirs);
    # 0.0 significa "todas local, sin tramo entre máquinas".
    if cota_reloj_ms is None:
        print("*** AVISO: no se pudo determinar la cota de error de reloj (lado Pi) ***")
        print("    t_OBU_srv, t_srv_RSU, L, t_verde y anticipacion_real se reportan SIN cota declarada:")
        print("    tratarlos como orientativos, no como una medición con incertidumbre conocida.\n")
    elif cota_reloj_ms:
        print(f"Cota de error de reloj (lado Pi, chrony): ± {cota_reloj_ms:.2f} ms -- "
              f"la laptop (w32time) no está caracterizada, ver NOTA_RELOJ.\n")

    r = g["resultados"]
    print(f"Misiones: {g['n_misiones']}  Paradas: {g['n_paradas']} "
          f"(concedidas {r['concedida']}, sin verde {r['sin_verde']}, rechazadas {r['rechazada']}, "
          f"sin respuesta {r['sin_respuesta']}; en cola de despeje: {g['cola_despeje']})")
    if r["sin_respuesta"]:
        print(f"    sin_respuesta por etapa alcanzada: {g['sin_respuesta_por_etapa']} "
              f"-- revisar logs de esa(s) repetición(es) antes de atribuir una causa.")

    if "conflicto" in g:
        c = g["conflicto"]
        print(f"\n*** Escenario 'conflicto': la mision perdedora en espera es el comportamiento "
              f"CORRECTO del arbitraje, no una falla -- ver docs/MEDICION_LATENCIA.md sección 8 ***")
        print(f"Arbitraje consistente con la política (servidor/conflictos.py): "
              f"{c['arbitraje_consistente_con_politica']}")
        print(f"Ganadores: {c['ganadores']['total']} (obtuvieron verde: {c['ganadores']['obtuvieron_verde']})")
        p = c["perdedores"]
        print(f"Perdedores: {p['total']} (atendidos después de esperar: {p['atendidos_despues_de_esperar']}, "
              f"cancelados correctamente al cruzar: {p['cancelados_correctamente_al_cruzar']}, "
              f"sin resolver al cierre de la corrida: {p['sin_resolver_al_cierre_de_la_corrida']})")
        if c["sin_conflicto_detectado"]:
            print(f"Paradas sin conflicto detectado (no coincidieron): {c['sin_conflicto_detectado']}")
        if c["tasa_exito_arbitraje"] is not None:
            print(f"Tasa de éxito del arbitraje (NO es concedidas/total): {c['tasa_exito_arbitraje']:.2%}")

    def _fmt(res: dict) -> str:
        if not res.get("n"):
            return "sin datos"
        return f"n={res['n']}, mediana={res['mediana']:.2f}, p95={res['p95']:.2f}, max={res['max']:.2f}"

    print(f"RTT_srv (ms, un reloj):     {_fmt(g['RTT_srv_ms'])}")
    print(f"t_RSU (ms, un reloj):       {_fmt(g['t_RSU_ms'])}")
    l = g["L_ms"]
    if l.get("n"):
        if g["l_p95_peor_caso_ms"] is not None:
            veredicto = "CUMPLE" if g["rnf01_cumple_p95_peor_caso"] else "NO CUMPLE"
            print(f"L -- RNF-01 (ms):           {_fmt(l)}  "
                  f"[peor caso p95+cota={g['l_p95_peor_caso_ms']:.2f} ms vs {UMBRAL_L_MS:.0f} ms -> {veredicto}]")
        else:
            veredicto = "CUMPLE" if g["rnf01_cumple_p95"] else "NO CUMPLE"
            print(f"L -- RNF-01 (ms):           {_fmt(l)}  "
                  f"[p95 vs {UMBRAL_L_MS:.0f} ms -> {veredicto}; SIN cota de reloj -- ver AVISO]")
    print(f"t_OBU_srv (ms):             {_fmt(g['t_OBU_srv_ms'])}")
    a = g["anticipacion_real_s"]
    if a.get("n"):
        print(f"Anticipacion real (s, RF8={ANTICIPACION_MINIMA_S} s): {_fmt(a)}")
    print(f"\nDetalle: {salida / 'lazo_por_parada.csv'}, {salida / 'lazo_por_mision.csv'}")
    print(f"Resumen: {salida / 'lazo_resumen.json'}")


if __name__ == "__main__":
    main()
