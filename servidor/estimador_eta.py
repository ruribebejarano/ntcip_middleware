"""Estimador de ETA del servidor central, como componente reemplazable.

El criterio de emisión de servidor/gestor_mision.py solo consume, para cada
RSU pendiente de la ruta, un ETA en segundos; no depende de cómo se obtiene.
Este módulo aísla ese cálculo detrás de una interfaz fija (EstimadorETA):

  EstimadorVelocidadConstante  el del prototipo: distancia restante por la
                               ruta dividida por la velocidad suavizada
                               (mediana, ver gestor_mision). Sin tráfico:
                               no anticipa aceleraciones, frenadas ni colas.
  EstimadorServicioExterno     adaptador para un servicio de rutas con
                               tráfico en tiempo real (p. ej. Google Maps o
                               Waze). La consulta al servicio la provee quien
                               lo integre (requiere clave y contrato, fuera
                               del alcance del prototipo); si falla o no hay
                               posición, cae al estimador de respaldo.

Cambiar de estimador no cambia los mensajes (M1/M2/M3, MR/ME) ni la RSU; lo
único que se recalibra es el margen T_m, con el error del nuevo estimador
(tesis, ssec:rnf y sec:ajustes). Un servicio externo a 1 Hz por misión
probablemente necesite caché o una consulta menos frecuente: decidirlo al
integrarlo, según los límites de su API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

Punto = tuple[float, float]  # (lat, lon)


@dataclass(frozen=True)
class ContextoETA:
    distancia_restante_m: float        # por la ruta, hasta la intersección
    velocidad_kmh: float               # la que usa el servidor (suavizada o de respaldo)
    posicion: Optional[Punto] = None   # última posición aceptada de la OBU
    interseccion: Optional[Punto] = None  # centro de la intersección (registro de RSU)


class EstimadorETA(Protocol):
    def estimar(self, ctx: ContextoETA) -> Optional[float]:
        """ETA en segundos, o None si no puede estimarse."""


class EstimadorVelocidadConstante:
    """ETA = distancia / velocidad (la velocidad se acota abajo en 1 km/h)."""

    def estimar(self, ctx: ContextoETA) -> Optional[float]:
        if ctx.distancia_restante_m <= 0:
            return 0.0
        return ctx.distancia_restante_m / (max(ctx.velocidad_kmh, 1.0) / 3.6)


class EstimadorServicioExterno:
    """Adaptador a un servicio de rutas con tráfico en tiempo real.

    `consultar(origen, destino)` devuelve el tiempo de viaje en segundos, o
    None si no hay respuesta; cualquier excepción se trata como None."""

    def __init__(self, consultar: Callable[[Punto, Punto], Optional[float]],
                 respaldo: Optional[EstimadorETA] = None) -> None:
        self.consultar = consultar
        self.respaldo = respaldo or EstimadorVelocidadConstante()

    def estimar(self, ctx: ContextoETA) -> Optional[float]:
        if ctx.distancia_restante_m <= 0:
            return 0.0
        if ctx.posicion is not None and ctx.interseccion is not None:
            try:
                segundos = self.consultar(ctx.posicion, ctx.interseccion)
            except Exception:
                segundos = None
            if segundos is not None:
                return float(segundos)
        return self.respaldo.estimar(ctx)
