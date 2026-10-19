"""Asignacion de intersecciones y accesos en la OBU (RF-11), segun la
seccion ssec:zonas de main.tex ("interseccion por delante y sector de
rumbo"), y criterio de emision/cancelacion de ssec:emision (RF-03, RF-04).

Modulo puro: sin red, sin MQTT, sin reloj. Lo usan gateway/obu_emulada.py y
las pruebas de tests/test_geometria.py.

Un vehiculo con posicion (lat, lon) y rumbo psi_v se asigna al acceso `a` de
la interseccion `i` si se cumplen a la vez (ssec:zonas):

  1. Dentro del radio:          d_i = sqrt(x^2 + y^2) <= R_i
  2. Interseccion por delante:  dpsi(psi_v, beta_i) <= theta,
                                beta_i = atan2(-x, -y) mod 360
  3. Rumbo del acceso:          dpsi(psi_v, psi_a) <= psi_tol
  4. La mas cercana:            menor d_i entre las parejas que cumplen 1-3

con (x, y) la proyeccion plana local de la ecuacion eq:proyeccion_local y
dpsi la diferencia angular de eq:deltapsi.

*** PARAMETROS PROVISIONALES ***
R_i, theta, psi_tol, R_g y la histeresis (N muestras, margen) NO estan
calibrados: main.tex los deja como TODO (ssec:zonas y ssec:emision) a fijar
con la precision GNSS observada en campo. Los valores por defecto de
ParametrosGeometria son solo los del banco de pruebas emulado y deben
declararse asi en el Capitulo IV.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

RADIO_TIERRA_M = 6_371_000.0


@dataclass(frozen=True)
class ParametrosGeometria:
    """Parametros de ssec:zonas y ssec:emision. Valores PROVISIONALES."""

    r_i_m: float = 300.0          # radio de candidatura de la interseccion (condicion 1)
    theta_deg: float = 45.0       # semiangulo del cono "interseccion por delante" (condicion 2)
    psi_tol_deg: float = 30.0     # tolerancia de rumbo respecto del acceso (condicion 3)
    r_g_m: float = 150.0          # radio de la geocerca de emision de M1 (RF-03), R_g < R_i
    n_histeresis: int = 3         # muestras consecutivas fuera del acceso para darlo por abandonado
    margen_histeresis_m: float = 50.0  # margen de distancia adicional mas alla de R_i


@dataclass(frozen=True)
class Acceso:
    acceso_id: str
    rumbo_llegada_deg: float
    grupo_semaforico: int


@dataclass(frozen=True)
class Interseccion:
    rsu_id: str
    interseccion_id: str
    lat: float
    lon: float
    accesos: tuple[Acceso, ...]
    codigo_mml: Optional[str] = None


@dataclass(frozen=True)
class Asignacion:
    rsu_id: str
    interseccion_id: str
    acceso_id: str
    distancia_m: float


# ---------------------------------------------------------------------------
# Geometria basica (ecuaciones de ssec:zonas)
# ---------------------------------------------------------------------------


def proyeccion_local(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """eq:proyeccion_local: (x, y) en metros, este/norte, centradas en (lat0, lon0)."""
    x = RADIO_TIERRA_M * math.radians(lon - lon0) * math.cos(math.radians(lat0))
    y = RADIO_TIERRA_M * math.radians(lat - lat0)
    return x, y


def delta_psi(a_deg: float, b_deg: float) -> float:
    """eq:deltapsi: diferencia angular en [0, 180], sin el salto 359 -> 0."""
    return 180.0 - abs(abs((a_deg % 360.0) - (b_deg % 360.0)) - 180.0)


def rumbo_entre(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumbo (grados desde el norte, sentido horario) del punto 1 al punto 2,
    en el plano local del punto 1."""
    x, y = proyeccion_local(lat2, lon2, lat1, lon1)
    return math.degrees(math.atan2(x, y)) % 360.0


def desplazar(lat: float, lon: float, rumbo_deg: float, distancia_m: float) -> tuple[float, float]:
    """Punto a `distancia_m` de (lat, lon) en direccion `rumbo_deg` (plano local)."""
    dx = distancia_m * math.sin(math.radians(rumbo_deg))
    dy = distancia_m * math.cos(math.radians(rumbo_deg))
    dlat = math.degrees(dy / RADIO_TIERRA_M)
    dlon = math.degrees(dx / (RADIO_TIERRA_M * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


# ---------------------------------------------------------------------------
# Condiciones de asignacion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evaluacion:
    """Resultado de evaluar las condiciones 1-3 para una interseccion."""

    distancia_m: float
    beta_deg: float
    dentro_radio: bool
    por_delante: bool


def evaluar_interseccion(
    inter: Interseccion, lat: float, lon: float, rumbo_v: float, p: ParametrosGeometria,
    radio_m: Optional[float] = None,
) -> Evaluacion:
    x, y = proyeccion_local(lat, lon, inter.lat, inter.lon)
    d = math.hypot(x, y)
    beta = math.degrees(math.atan2(-x, -y)) % 360.0
    radio = p.r_i_m if radio_m is None else radio_m
    return Evaluacion(
        distancia_m=d,
        beta_deg=beta,
        dentro_radio=d <= radio,
        por_delante=delta_psi(rumbo_v, beta) <= p.theta_deg,
    )


def acceso_por_rumbo(inter: Interseccion, rumbo_v: float, p: ParametrosGeometria) -> Optional[Acceso]:
    """Condicion 3: el acceso cuyo rumbo de llegada esta dentro de psi_tol
    (el mas parecido si hubiera mas de uno)."""
    candidatos = [
        (delta_psi(rumbo_v, a.rumbo_llegada_deg), a)
        for a in inter.accesos
        if delta_psi(rumbo_v, a.rumbo_llegada_deg) <= p.psi_tol_deg
    ]
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]


def asignar(
    registro: list[Interseccion], lat: float, lon: float, rumbo_v: float, p: ParametrosGeometria
) -> Optional[Asignacion]:
    """Condiciones 1 a 4 de ssec:zonas. None si ninguna pareja las cumple."""
    mejores: list[Asignacion] = []
    for inter in registro:
        ev = evaluar_interseccion(inter, lat, lon, rumbo_v, p)
        if not (ev.dentro_radio and ev.por_delante):
            continue
        acceso = acceso_por_rumbo(inter, rumbo_v, p)
        if acceso is None:
            continue
        mejores.append(Asignacion(inter.rsu_id, inter.interseccion_id, acceso.acceso_id, ev.distancia_m))
    if not mejores:
        return None
    return min(mejores, key=lambda a: a.distancia_m)


# ---------------------------------------------------------------------------
# Seguimiento con histeresis + criterio de emision/cancelacion
# ---------------------------------------------------------------------------

# Acciones que devuelve SeguidorAcceso.actualizar()
EMITIR_M1 = "emitir_m1"            # entra en la geocerca R_g: nueva solicitud (RF-03)
ACTUALIZAR_M1 = "actualizar_m1"    # solicitud vigente: M1 con seq+1 (RNF-02, 1 Hz)
EMITIR_M3 = "emitir_m3"            # cancelacion (RF-04)
NINGUNA = "ninguna"

# Motivos de M3 (ssec:emision, tres condiciones)
MOTIVO_CRUCE = "cruce"                      # la interseccion quedo detras (condicion 2 deja de cumplirse)
MOTIVO_SALIDA = "salida_acceso"             # fuera del radio + margen, o N muestras fuera
MOTIVO_RUMBO = "rumbo_divergente"           # rumbo fuera de psi_tol de forma sostenida


@dataclass
class Decision:
    accion: str
    asignacion: Optional[Asignacion] = None
    motivo: Optional[str] = None


@dataclass
class SeguidorAcceso:
    """Mantiene la asignacion actual de la OBU entre muestras y decide cuando
    emitir, actualizar o cancelar la solicitud (RF-03, RF-04, RF-11).

    Una muestra por llamada a actualizar() (1 Hz en la OBU, RNF-02)."""

    registro: list[Interseccion]
    p: ParametrosGeometria = field(default_factory=ParametrosGeometria)
    actual: Optional[Asignacion] = None
    solicitud_vigente: bool = False
    _fuera: int = 0
    _rumbo_fuera: int = 0
    # Interseccion recien cruzada: no se vuelve a asignar hasta que el
    # vehiculo salga de su radio + margen. Evita que el ruido GNSS junto al
    # centro la haga aparecer "por delante" otra vez y reabra la solicitud.
    _excluida: Optional[str] = None

    def _inter(self, interseccion_id: str) -> Interseccion:
        return next(i for i in self.registro if i.interseccion_id == interseccion_id)

    def _candidatas(self, lat: float, lon: float) -> list[Interseccion]:
        if self._excluida is not None:
            inter = self._inter(self._excluida)
            x, y = proyeccion_local(lat, lon, inter.lat, inter.lon)
            if math.hypot(x, y) > self.p.r_i_m + self.p.margen_histeresis_m:
                self._excluida = None
        return [i for i in self.registro if i.interseccion_id != self._excluida]

    def actualizar(self, lat: float, lon: float, rumbo_v: float) -> list[Decision]:
        decisiones: list[Decision] = []

        if self.actual is not None:
            inter = self._inter(self.actual.interseccion_id)
            acceso = next(a for a in inter.accesos if a.acceso_id == self.actual.acceso_id)
            ev = evaluar_interseccion(
                inter, lat, lon, rumbo_v, self.p, radio_m=self.p.r_i_m + self.p.margen_histeresis_m
            )
            rumbo_ok = delta_psi(rumbo_v, acceso.rumbo_llegada_deg) <= self.p.psi_tol_deg
            dentro_estricto = ev.distancia_m <= self.p.r_i_m

            motivo = None
            if not ev.por_delante:
                motivo = MOTIVO_CRUCE
            elif not ev.dentro_radio:
                motivo = MOTIVO_SALIDA
            else:
                self._fuera = self._fuera + 1 if not dentro_estricto else 0
                self._rumbo_fuera = self._rumbo_fuera + 1 if not rumbo_ok else 0
                if self._fuera >= self.p.n_histeresis:
                    motivo = MOTIVO_SALIDA
                elif self._rumbo_fuera >= self.p.n_histeresis:
                    motivo = MOTIVO_RUMBO

            if motivo is not None:
                if self.solicitud_vigente:
                    decisiones.append(Decision(EMITIR_M3, self.actual, motivo))
                if motivo == MOTIVO_CRUCE:
                    self._excluida = self.actual.interseccion_id
                self.actual = None
                self.solicitud_vigente = False
                self._fuera = self._rumbo_fuera = 0
            else:
                self.actual = Asignacion(
                    self.actual.rsu_id, self.actual.interseccion_id, self.actual.acceso_id, ev.distancia_m
                )

        if self.actual is None:
            self.actual = asignar(self._candidatas(lat, lon), lat, lon, rumbo_v, self.p)
            self._fuera = self._rumbo_fuera = 0

        if self.actual is not None:
            if self.solicitud_vigente:
                decisiones.append(Decision(ACTUALIZAR_M1, self.actual))
            elif self.actual.distancia_m <= self.p.r_g_m:
                self.solicitud_vigente = True
                decisiones.append(Decision(EMITIR_M1, self.actual))

        return decisiones or [Decision(NINGUNA, self.actual)]


# ---------------------------------------------------------------------------
# Registro de RSU (copia local estatica, esquema E4, ssec:registro)
# ---------------------------------------------------------------------------


def cargar_registro(ruta: Path | str) -> list[Interseccion]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    registro = []
    for r in datos["rsu"]:
        registro.append(
            Interseccion(
                rsu_id=str(r["rsu_id"]),
                interseccion_id=r["interseccion_id"],
                lat=float(r["centro"]["lat"]),
                lon=float(r["centro"]["lon"]),
                accesos=tuple(
                    Acceso(a["acceso_id"], float(a["rumbo_llegada_deg"]), int(a["grupo_semaforico"]))
                    for a in r["accesos"]
                ),
                codigo_mml=r.get("codigo_mml"),
            )
        )
    return registro
