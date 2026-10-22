"""Política de arbitraje de conflictos entre misiones (sección 1.3 del
prompt de arquitectura centralizada / nueva ssec:conflictos propuesta en el
inventario de redacción).

*** POLÍTICA PROVISIONAL -- cada criterio va marcado [REVISAR con asesor] ***

Regla, en orden:
1. Dos misiones que piden accesos COMPATIBLES de la misma RSU (mismo
   grupo_semaforico, es decir pueden tener verde al mismo tiempo): se
   atienden ambas, no hay conflicto.
2. Accesos INCOMPATIBLES (distinto grupo_semaforico): gana la clase de
   vehículo de MAYOR prioridad. `clase` sigue la convención ya usada en
   RF-05 / agent/rsu_middleware.py: un número MENOR es una prioridad MAYOR
   (clase_tipo=1 = "máxima precedencia"). [REVISAR con asesor]: la tabla de
   clases real depende del D.S. N.º 016-2009-MTC, que no se tiene a mano
   para verificar el orden completo -- ver [CITAR] en
   docs/CONTRATO_OBU.md.
2. Si empatan en clase, gana la de MENOR ETA (llega primero).
3. Si también empatan en ETA (dentro de un margen), se desempata de forma
   determinista por `mision_id` (orden lexicográfico) solo para que el
   resultado sea reproducible en una prueba -- no tiene ninguna
   justificación de tránsito. [REVISAR con asesor]: un criterio real
   (orden de llegada de la solicitud, por ejemplo) debería decidir esto.

Todo conflicto se registra como evento (EVT_CONFLICTO_ARBITRADO en
common/events.py), lo resuelva o no una comparación de clase/ETA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Margen de ETA dentro del cual dos solicitudes se consideran "empatadas"
# (y se pasa al desempate por mision_id). PROVISIONAL [REVISAR con asesor]:
# depende de la incertidumbre real del cálculo de ETA (ssec:ruta_servidor).
MARGEN_ETA_EMPATE_S = 1.0


@dataclass(frozen=True)
class Solicitante:
    """Una misión que quiere un acceso de una RSU, en el momento de
    evaluar el conflicto."""

    mision_id: str
    acceso_id: str
    grupo_semaforico: int
    clase: int
    eta_s: float


@dataclass(frozen=True)
class ResultadoArbitraje:
    rsu_id: str
    atendidos: tuple[Solicitante, ...]
    en_espera: tuple[Solicitante, ...]
    hubo_conflicto: bool


def _compatibles(a: Solicitante, b: Solicitante) -> bool:
    """Regla 1: mismo grupo semafórico = compatibles (ssec:conflictos).
    PROVISIONAL [REVISAR con asesor]: asume que un único grupo_semaforico
    agota la noción de "accesos compatibles" -- no modela fases con más de
    un grupo simultáneo ni giros protegidos."""
    return a.grupo_semaforico == b.grupo_semaforico


def _gana(a: Solicitante, b: Solicitante) -> bool:
    """True si `a` gana sobre `b` (reglas 2-3 del docstring del módulo)."""
    if a.clase != b.clase:
        return a.clase < b.clase
    if abs(a.eta_s - b.eta_s) > MARGEN_ETA_EMPATE_S:
        return a.eta_s < b.eta_s
    return a.mision_id <= b.mision_id


def arbitrar(rsu_id: str, solicitantes: list[Solicitante]) -> ResultadoArbitraje:
    """Evalúa TODOS los solicitantes activos/pendientes de una RSU a la vez
    (no solo un par) y separa en atendidos / en espera. Dos solicitantes
    compatibles entre sí nunca se excluyen uno a otro, aunque alguno de
    ellos sea incompatible con un tercero."""
    atendidos: list[Solicitante] = []
    en_espera: list[Solicitante] = []
    hubo_conflicto = False

    for s in solicitantes:
        incompatibles_ya_atendidos = [a for a in atendidos if not _compatibles(a, s)]
        if not incompatibles_ya_atendidos:
            atendidos.append(s)
            continue
        hubo_conflicto = True
        # ¿`s` le gana a TODOS los incompatibles ya atendidos? Si es así,
        # esos pierden su lugar (pasan a en_espera) y `s` entra.
        if all(_gana(s, a) for a in incompatibles_ya_atendidos):
            for a in incompatibles_ya_atendidos:
                atendidos.remove(a)
                en_espera.append(a)
            atendidos.append(s)
        else:
            en_espera.append(s)

    return ResultadoArbitraje(
        rsu_id=rsu_id,
        atendidos=tuple(atendidos),
        en_espera=tuple(en_espera),
        hubo_conflicto=hubo_conflicto,
    )


class ArbitroConflictos:
    """Envoltorio con memoria mínima: quién está atendido hoy en cada RSU,
    para que gestor_mision.py pueda preguntar "¿puedo pedir esto?" sin tener
    que recalcular desde cero el estado de todas las misiones activas en
    cada muestra MP. El propio gestor sigue siendo la fuente de verdad de
    las misiones; esta clase solo cachea el último resultado por RSU."""

    def __init__(self) -> None:
        self._ultimo: dict[str, ResultadoArbitraje] = {}

    def evaluar(self, rsu_id: str, solicitantes: list[Solicitante]) -> ResultadoArbitraje:
        resultado = arbitrar(rsu_id, solicitantes)
        self._ultimo[rsu_id] = resultado
        return resultado

    def ultimo_resultado(self, rsu_id: str) -> Optional[ResultadoArbitraje]:
        return self._ultimo.get(rsu_id)
