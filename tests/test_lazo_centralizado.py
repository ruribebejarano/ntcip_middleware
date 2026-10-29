"""Pruebas de scripts/analisis/lazo_centralizado.py sobre eventos REALES
ya existentes (evidencia/2026-10-22_arquitectura-centralizada/, fase 3.8:
los tres escenarios de la arquitectura centralizada corridos localmente),
no sobre datos sintéticos hechos a mano -- así una regresión en el
cálculo de tramos se detecta contra una corrida real conocida.

Esos eventos son ANTERIORES a la instrumentación de `seq` en MP_rx y de
`seq_ref` en M2_rx (commit de la campaña centralizada, 2026-10-28): por
eso t_OBU_srv y RTT_srv deben salir "sin datos" (n=0) sobre esta
evidencia -- no es un bug, es la limitación real de esos datos, y esta
prueba la deja explícita en vez de que pase desapercibida."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))

from lazo_centralizado import analizar, analizar_conflicto, cargar, cota_reloj_pi_ms  # noqa: E402
from common.events import (  # noqa: E402
    EVT_CONFLICTO_ARBITRADO,
    EVT_CTRL_FASE_CAMBIO,
    EVT_M1_RX,
    EVT_M1_TX,
    EVT_M2_RX,
    EVT_M3_TX,
    EVT_MISION_ARMADA,
    EVT_SNMP_SET_TX,
)

EVIDENCIA = RAIZ / "evidencia" / "2026-10-22_arquitectura-centralizada"


def test_evidencia_2026_10_22_produce_paradas_y_misiones():
    eventos = cargar([EVIDENCIA])
    assert eventos, "no se encontraron eventos_*.csv en evidencia/2026-10-22_arquitectura-centralizada/"

    filas_mision, filas_parada, g = analizar(eventos, cota_reloj_ms=0.0)

    assert g["n_misiones"] >= 3  # lazo, conflicto (x2 OBU) y desvio, al menos
    assert g["n_paradas"] >= 3
    assert sum(g["resultados"].values()) == g["n_paradas"]


def test_t_rsu_y_L_se_calculan_con_datos_reales():
    eventos = cargar([EVIDENCIA])
    _, _, g = analizar(eventos, cota_reloj_ms=0.0)

    assert g["t_RSU_ms"]["n"] > 0
    assert g["t_RSU_ms"]["mediana"] >= 0
    assert g["L_ms"]["n"] > 0
    assert g["L_ms"]["mediana"] >= g["t_RSU_ms"]["mediana"] - 1e-6  # L = t_srv_RSU + t_RSU >= t_RSU


def test_rtt_srv_y_t_obu_srv_sin_datos_en_evidencia_anterior_a_seq_ref():
    """Documenta la limitación: esta evidencia no tiene seq_ref (M2_rx) ni
    seq (MP_rx) -- ver docstring del módulo. Si alguna vez se regenera esa
    evidencia con la instrumentación nueva, esta prueba hay que
    actualizarla (dejaría de ser n=0)."""
    eventos = cargar([EVIDENCIA])
    _, _, g = analizar(eventos, cota_reloj_ms=0.0)

    assert g["RTT_srv_ms"]["n"] == 0
    assert g["t_OBU_srv_ms"]["n"] == 0


def test_metricas_de_dos_relojes_ya_no_se_excluyen_por_umbral():
    """Hasta el 2026-10-28, una cota de reloj grande (o no declarada)
    NULEABA L/t_srv_RSU por completo -- eso era un error de método (el
    umbral de 10 ms no tenía relación con la cota real que declara
    chrony, típicamente 20-50 ms contra NTP público). Ahora las métricas
    de dos relojes se calculan SIEMPRE que haya datos; la cota se adjunta
    aparte (cota_reloj_pi_ms en el resumen), no se usa para excluir."""
    eventos = cargar([EVIDENCIA])
    _, filas_parada, g = analizar(eventos, cota_reloj_ms=80.0)  # cota grande, a propósito

    assert g["L_ms"]["n"] > 0
    assert any(f["L_ms"] is not None for f in filas_parada)
    assert g["cota_reloj_pi_ms"] == 80.0
    # t_RSU no lleva cota (un solo reloj): no debe verse afectado.
    assert g["t_RSU_ms"]["n"] > 0


def test_cota_reloj_pi_ms_usa_root_dispersion_y_root_delay_si_hay_tracking():
    """Salida real de 'chronyc tracking' (scripts/pi.sh clock, 2026-10-28):
    Root dispersion 0.0049 s + Root delay/2 0.0194 s =~ 24.3 ms. Se
    prefiere este campo (distancia de sincronización NTP estándar) sobre
    el 'estimated error' de 'chronyc sources -v' cuando está disponible."""
    texto = ("Reference ID    : D8EF2300 (time1.google.com)\n"
             "Root delay      : 0.038743746 seconds\n"
             "Root dispersion : 0.004902852 seconds\n")
    cota = cota_reloj_pi_ms(texto)
    assert cota == pytest.approx(0.004902852 * 1000 + 0.038743746 * 1000 / 2)


def test_cota_reloj_pi_ms_cae_a_estimated_error_de_sources_v_sin_tracking():
    """Corridas anteriores a que scripts/pi.sh clock capturara 'chronyc
    tracking' (todas las del 2026-10-28): solo queda el campo 'estimated
    error' (+/- zzzz) de 'chronyc sources -v' -- una cota declarada por
    chrony, no el offset puntual que le precede."""
    texto = ("MS Name/IP address         Stratum Poll Reach LastRx Last sample\n"
             "^+ time.cloudflare.com           3  10   377     5  -8608us[-8608us] +/-   50ms\n")
    assert cota_reloj_pi_ms(texto) == pytest.approx(50.0)


def test_cota_reloj_pi_ms_sin_texto_es_none():
    assert cota_reloj_pi_ms(None) is None
    assert cota_reloj_pi_ms("texto sin ningun campo reconocible") is None


def test_sin_respuesta_se_excluye_de_L_y_se_cuenta_por_etapa():
    """Una parada que recibio snmp_set_tx (decision) pero NUNCA un M2 es
    'sin_respuesta' -- NO una latencia valida, aunque L se pueda calcular
    con los timestamps disponibles (ver docs/MEDICION_LATENCIA.md 8.3)."""
    eventos = [
        _ev(1_000_000_000, "servidor", EVT_M1_TX, "mis-X-A",
            mision_id="mis-X", rsu_id="rsu-1", seq=1),
        _ev(1_010_000_000, "rsu_1", EVT_M1_RX, "mis-X-A", seq=1),
        _ev(1_020_000_000, "rsu_1", EVT_SNMP_SET_TX, "mis-X-A", accion="request_priority"),
        # ningun M2_rx para esta parada: el M2 se perdio.
    ]
    _, filas_parada, g = analizar(eventos, cota_reloj_ms=0.0)

    assert len(filas_parada) == 1
    fila = filas_parada[0]
    assert fila["resultado"] == "sin_respuesta"
    assert fila["etapa_alcanzada"] == "decision_sin_m2"
    assert fila["L_ms"] is not None  # SI se puede calcular con los timestamps...
    assert g["L_ms"]["n"] == 0        # ...pero NO entra al resumen/p95.
    assert g["sin_respuesta_por_etapa"] == {"decision_sin_m2": 1}


def _ev(ts_ns: int, nodo: str, tipo: str, id_sol: str, **extra) -> dict:
    return {"ts_ns": ts_ns, "nodo": nodo, "tipo_evento": tipo, "id_solicitud": id_sol, "extra": extra}


def _candidato(mision_id: str, clase: int, eta_s: float) -> dict:
    return {"mision_id": mision_id, "clase": clase, "eta_s": eta_s}


def _eventos_conflicto_sintetico() -> list[dict]:
    """Dos conflictos sintéticos en la misma RSU, con los tres desenlaces
    posibles de una perdedora (atendida después, cancelada correctamente
    al cruzar, sin resolver) y un ganador sin verde -- no sale de ninguna
    corrida real, construido a mano para ejercitar
    analizar_conflicto() sin depender de que una campaña real haya
    producido los tres casos a la vez."""
    eventos = []
    # --- Conflicto 1: mis-A gana (menor ETA) con verde; mis-B pierde y
    # se atiende despues de esperar. ---
    eventos += [
        _ev(1_000_000_000, "servidor", EVT_M1_TX, "mis-A-X", mision_id="mis-A", rsu_id="rsu-1", seq=1),
        _ev(1_030_000_000, "servidor", EVT_M2_RX, "mis-A-X", mision_id="mis-A", estado="concedida", seq_ref=1),
        _ev(1_040_000_000, "ctrl_1", EVT_CTRL_FASE_CAMBIO, "mis-A-X", fase="verde"),
        _ev(1_005_000_000, "servidor", EVT_CONFLICTO_ARBITRADO, "mis-B", rsu_id="rsu-1",
            atendidos=["mis-A"], en_espera=["mis-B"],
            candidatos=[_candidato("mis-A", 1, 5.0), _candidato("mis-B", 1, 10.0)]),
        _ev(1_050_000_000, "servidor", EVT_M1_TX, "mis-B-X", mision_id="mis-B", rsu_id="rsu-1", seq=1),
        _ev(1_080_000_000, "servidor", EVT_M2_RX, "mis-B-X", mision_id="mis-B", estado="concedida", seq_ref=1),
    ]
    # --- Conflicto 2: mis-D gana sin verde (todavia no llega su fase);
    # mis-C pierde, estaba solicitada, y se cancela correctamente al cruzar. ---
    eventos += [
        _ev(2_000_000_000, "servidor", EVT_M1_TX, "mis-C-Y", mision_id="mis-C", rsu_id="rsu-1", seq=1, t_servicio=9.0),
        _ev(2_002_000_000, "servidor", EVT_M2_RX, "mis-C-Y", mision_id="mis-C", estado="recibida", seq_ref=1),
        _ev(2_005_000_000, "servidor", EVT_CONFLICTO_ARBITRADO, "mis-D", rsu_id="rsu-1",
            atendidos=["mis-D"], en_espera=["mis-C"],
            candidatos=[_candidato("mis-D", 1, 4.0), _candidato("mis-C", 1, 9.0)]),
        _ev(2_006_000_000, "servidor", EVT_M3_TX, "mis-C-Y", mision_id="mis-C", motivo="conflicto"),
        _ev(2_007_000_000, "servidor", EVT_M2_RX, "mis-C-Y", mision_id="mis-C", estado="cancelada", seq_ref=2),
        _ev(2_050_000_000, "servidor", EVT_M3_TX, "mis-C-Y", mision_id="mis-C", motivo="cruce"),
        _ev(2_006_500_000, "servidor", EVT_M1_TX, "mis-D-Y", mision_id="mis-D", rsu_id="rsu-1", seq=1),
        _ev(2_008_000_000, "servidor", EVT_M2_RX, "mis-D-Y", mision_id="mis-D", estado="concedida", seq_ref=1),
        # mis-D NO tiene ctrl_fase_cambio a verde todavia: ganador sin verde.
    ]
    # --- Conflicto 3: mis-F gana; mis-E pierde y queda sin resolver (ni
    # concedida ni cruce) al cierre de la corrida. ---
    eventos += [
        _ev(3_000_000_000, "servidor", EVT_M1_TX, "mis-E-Z", mision_id="mis-E", rsu_id="rsu-1", seq=1),
        _ev(3_001_000_000, "servidor", EVT_M2_RX, "mis-E-Z", mision_id="mis-E", estado="recibida", seq_ref=1),
        _ev(3_005_000_000, "servidor", EVT_CONFLICTO_ARBITRADO, "mis-F", rsu_id="rsu-1",
            atendidos=["mis-F"], en_espera=["mis-E"],
            candidatos=[_candidato("mis-F", 1, 3.0), _candidato("mis-E", 1, 9.0)]),
        _ev(3_006_000_000, "servidor", EVT_M3_TX, "mis-E-Z", mision_id="mis-E", motivo="conflicto"),
        _ev(3_007_000_000, "servidor", EVT_M2_RX, "mis-E-Z", mision_id="mis-E", estado="cancelada", seq_ref=2),
        _ev(3_006_500_000, "servidor", EVT_M1_TX, "mis-F-Z", mision_id="mis-F", rsu_id="rsu-1", seq=1),
        _ev(3_008_000_000, "servidor", EVT_M2_RX, "mis-F-Z", mision_id="mis-F", estado="concedida", seq_ref=1),
    ]
    return eventos


def test_analizar_conflicto_clasifica_los_tres_desenlaces_de_perdedora():
    eventos = _eventos_conflicto_sintetico()
    _, filas_parada, _ = analizar(eventos, cota_reloj_ms=0.0)
    c = analizar_conflicto(eventos, filas_parada)

    assert c["ganadores"]["total"] == 3  # mis-A, mis-D, mis-F
    assert c["ganadores"]["obtuvieron_verde"] == 1  # solo mis-A
    assert c["perdedores"]["total"] == 3  # mis-B, mis-C, mis-E
    assert c["perdedores"]["atendidos_despues_de_esperar"] == 1  # mis-B
    assert c["perdedores"]["cancelados_correctamente_al_cruzar"] == 1  # mis-C
    assert c["perdedores"]["sin_resolver_al_cierre_de_la_corrida"] == 1  # mis-E
    # Los tres eventos de arbitraje son consistentes con la politica
    # (menor ETA gana, misma clase): esto re-corre
    # servidor/conflictos.py::arbitrar() con los 'candidatos' logueados.
    assert c["arbitraje_consistente_con_politica"] == "3/3"
    assert c["tasa_exito_arbitraje"] == pytest.approx((1 + 1 + 1) / 6)


def test_analizar_conflicto_detecta_arbitraje_inconsistente_con_la_politica():
    """Si el log dice que ganó quien tenía MAYOR ETA (mismo clase), eso es
    inconsistente con servidor/conflictos.py::arbitrar() -- un bug de
    integracion (p. ej. candidatos desactualizados), no algo que deba
    pasar desapercibido como si fuera correcto."""
    eventos = [
        _ev(4_000_000_000, "servidor", EVT_CONFLICTO_ARBITRADO, "mis-H", rsu_id="rsu-1",
            atendidos=["mis-G"], en_espera=["mis-H"],
            candidatos=[_candidato("mis-G", 1, 9.0), _candidato("mis-H", 1, 3.0)]),
    ]
    c = analizar_conflicto(eventos, filas_parada=[])

    assert c["arbitraje_consistente_con_politica"] == "0/1"
    assert c["eventos_arbitraje"][0]["consistente_con_politica"] is False


def test_analizar_conflicto_sin_candidatos_queda_sin_verificar():
    """Corridas anteriores a la instrumentación de 'candidatos'
    (2026-10-28): no se puede verificar la política, y eso debe quedar
    explícito en vez de contarse como correcto o incorrecto."""
    eventos = [
        _ev(5_000_000_000, "servidor", EVT_CONFLICTO_ARBITRADO, "mis-J", rsu_id="rsu-1",
            atendidos=["mis-I"], en_espera=["mis-J"]),
    ]
    c = analizar_conflicto(eventos, filas_parada=[])

    assert c["arbitraje_consistente_con_politica"] == "sin datos verificables"
    assert c["eventos_arbitraje"][0]["consistente_con_politica"] is None
