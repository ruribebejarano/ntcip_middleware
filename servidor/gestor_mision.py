"""Gestor de misión: el corazón de la arquitectura centralizada (ver
E:\\Tesis\\prompt_arquitectura_centralizada.md, sección 1.1, "Servidor
central"). Un objeto `GestorMision` por proceso servidor (servidor/main.py
lo instancia una vez); NO tiene estado de red: recibe datos ya parseados
(MI/MP/MF/M2) y llama callbacks `enviar_*` para publicar (MR/ME/M1/M3). Eso
hace que se pueda probar sin MQTT (ver tests/test_gestor_mision.py).

Ciclo de vida de una misión (RF nuevos, ver inventario de redacción):
1. armar_mision()  -- MI: calcula la ruta (servidor/rutas.py) cruzada con el
   registro de RSU, publica MR.
2. procesar_mp()   -- MP (1 Hz, solo con misión activa): actualiza el
   progreso sobre la ruta, dispara la solicitud ANTICIPADA por ETA (antes
   de entrar a la geocerca) y, además, reutiliza
   `gateway.geometria.SeguidorAcceso` TAL CUAL (ahora alimentado con la
   posición MP en vez de la posición local de la OBU) para la verificación
   final de geocerca: confirma que la posición real coincide con el acceso
   esperado, renueva la solicitud a 1 Hz mientras siga dentro, y genera la
   cancelación (M3) al cruzar, salir del radio o divergir de rumbo -- las
   MISMAS tres condiciones de ssec:emision, evaluadas aquí en vez de en la
   OBU.
3. procesar_m2()   -- M2 de la RSU: actualiza el estado de la parada y
   reenvía ME a la OBU.
4. desarmar_mision() -- MF, tiempo máximo, o desvío irrecuperable: cancela
   (M3) todo lo pendiente/activo.

Arbitraje de conflictos: antes de solicitar por primera vez un acceso de
una RSU, se consulta servidor/conflictos.py con todas las misiones que ya
tienen un acceso pendiente/activo en esa misma RSU. Si la misión pierde,
su parada queda "en_espera" (sin M1) hasta que se libere el conflicto
(se promueve automáticamente cuando el ganador cruza, se desvía o se
desarma).

*** PARÁMETROS PROVISIONALES [REVISAR con asesor] ***
Ver las constantes al inicio del módulo: ninguna está calibrada con datos
de campo.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from gateway.geometria import (
    ACTUALIZAR_M1,
    EMITIR_M1,
    EMITIR_M3,
    NINGUNA,
    Decision,
    Interseccion,
    ParametrosGeometria,
    SeguidorAcceso,
)
from servidor import conflictos as conflictos_mod
from servidor import rutas as rutas_mod
from servidor.rutas import ParadaRsu, Ruta

try:
    from common.events import (
        EVT_CONFLICTO_ARBITRADO,
        EVT_M1_TX,
        EVT_M2_RX,
        EVT_M3_TX,
        EVT_MISION_ARMADA,
        EVT_MISION_DESARMADA,
        EVT_MP_RX,
        EVT_RUTA_CALCULADA,
        EVT_RUTA_RECALCULADA,
        EventLogger,
    )
except ImportError:  # pragma: no cover - solo para uso aislado en pruebas
    EventLogger = None  # type: ignore[assignment,misc]

# --- Parámetros provisionales, sin calibrar con datos de campo ------------
UMBRAL_DESVIO_M = 60.0            # distancia perpendicular a la ruta que dispara recálculo [REVISAR con asesor]
TIEMPO_MAXIMO_MISION_S = 1800.0   # 30 min: límite de seguridad de una misión armada [REVISAR con asesor]
ANTICIPACION_MINIMA_S = 8.0       # margen mínimo servidor->RSU + transición de fase (RF8) [REVISAR con asesor]
VELOCIDAD_RESPALDO_KMH = 30.0     # si no hay velocidad OBD-II/GPS válida (MP sin "velocidad_kmh" útil) [REVISAR con asesor]
MARGEN_CRUCE_M = 20.0             # cuanto puede "pasarse" la distancia acumulada antes de considerar la parada cruzada

ESTADO_PENDIENTE = "pendiente"
ESTADO_SOLICITADA = "solicitada"
ESTADO_EN_COLA = "en_cola"
ESTADO_CONCEDIDA = "concedida"
ESTADO_CANCELADA = "cancelada"
ESTADO_RECHAZADA = "rechazada"
ESTADO_EN_ESPERA = "en_espera"  # por conflicto (servidor/conflictos.py)

_ESTADO_DESDE_M2 = {
    "recibida": ESTADO_SOLICITADA,
    "en_cola": ESTADO_EN_COLA,
    "concedida": ESTADO_CONCEDIDA,
    "rechazada": ESTADO_RECHAZADA,
    "cancelada": ESTADO_CANCELADA,
}


@dataclass
class EstadoParada:
    parada: ParadaRsu
    estado: str = ESTADO_PENDIENTE
    id_solicitud: Optional[str] = None
    seq: int = 0
    fase: Optional[str] = None
    eta_s: Optional[float] = None


@dataclass
class Mision:
    mision_id: str
    obu_id: str
    clase: int
    destino: tuple[float, float]
    ruta: Ruta
    seguidor: SeguidorAcceso
    paradas: dict[str, EstadoParada]  # por interseccion_id, en el orden de la ruta
    orden: list[str]                  # interseccion_id en orden de la ruta
    activa: bool = True
    t_armado: float = field(default_factory=time.time)
    distancia_recorrida_m: float = 0.0
    ultima_velocidad_kmh: float = VELOCIDAD_RESPALDO_KMH

    def siguiente_parada_pendiente(self) -> Optional[EstadoParada]:
        for iid in self.orden:
            ep = self.paradas[iid]
            if ep.estado == ESTADO_PENDIENTE:
                return ep
        return None


class GestorMision:
    def __init__(
        self,
        grafo,
        registro: list[Interseccion],
        *,
        enviar_m1: Callable[[str, dict], None],
        enviar_m3: Callable[[str, dict], None],
        enviar_mr: Callable[[str, dict], None],
        enviar_me: Callable[[str, dict], None],
        eventos: Optional["EventLogger"] = None,
        arbitro: Optional[conflictos_mod.ArbitroConflictos] = None,
        ahora: Callable[[], float] = time.time,
        parametros_geocerca: Optional[ParametrosGeometria] = None,
        umbral_desvio_m: float = UMBRAL_DESVIO_M,
        tiempo_maximo_s: float = TIEMPO_MAXIMO_MISION_S,
        anticipacion_min_s: float = ANTICIPACION_MINIMA_S,
        velocidad_respaldo_kmh: float = VELOCIDAD_RESPALDO_KMH,
    ) -> None:
        self.grafo = grafo
        self.registro = registro
        self.enviar_m1 = enviar_m1
        self.enviar_m3 = enviar_m3
        self.enviar_mr = enviar_mr
        self.enviar_me = enviar_me
        self.eventos = eventos
        self.arbitro = arbitro or conflictos_mod.ArbitroConflictos()
        self.ahora = ahora
        self.parametros_geocerca = parametros_geocerca or ParametrosGeometria()
        self.umbral_desvio_m = umbral_desvio_m
        self.tiempo_maximo_s = tiempo_maximo_s
        self.anticipacion_min_s = anticipacion_min_s
        self.velocidad_respaldo_kmh = velocidad_respaldo_kmh

        self.misiones: dict[str, Mision] = {}  # por obu_id
        # id_solicitud -> (obu_id, interseccion_id), para resolver M2 y las
        # promociones de "en_espera" sin tener que recorrer todas las misiones.
        self._solicitud_a_parada: dict[str, tuple[str, str]] = {}

    # --- Log auxiliar -------------------------------------------------

    def _log(self, tipo: str, id_ref: str, **extra) -> None:
        if self.eventos is not None:
            self.eventos.log(tipo, id_ref, **extra)

    # --- MI / armado ----------------------------------------------------

    def armar_mision(
        self, obu_id: str, clase: int, origen: tuple[float, float], destino: tuple[float, float],
    ) -> Mision:
        ruta = rutas_mod.planificar_ruta(self.grafo, self.registro, origen, destino)
        registro_mision = [i for i in self.registro if i.interseccion_id in {p.interseccion_id for p in ruta.paradas}]
        seguidor = SeguidorAcceso(registro_mision, self.parametros_geocerca)

        mision_id = f"mis-{uuid.uuid4().hex[:8]}"
        orden = [p.interseccion_id for p in ruta.paradas]
        paradas = {p.interseccion_id: EstadoParada(p) for p in ruta.paradas}
        mision = Mision(
            mision_id=mision_id, obu_id=obu_id, clase=clase, destino=destino,
            ruta=ruta, seguidor=seguidor, paradas=paradas, orden=orden,
        )
        self.misiones[obu_id] = mision
        self._log(EVT_MISION_ARMADA, mision_id, obu_id=obu_id, clase=clase,
                  destino_lat=destino[0], destino_lon=destino[1])
        self._log(EVT_RUTA_CALCULADA, mision_id, n_paradas=len(ruta.paradas),
                  longitud_m=round(ruta.longitud_total_m, 1))
        self.enviar_mr(obu_id, self._cuerpo_mr(mision))
        return mision

    def _cuerpo_mr(self, mision: Mision) -> dict:
        return {
            "tipo": "MR",
            "mision_id": mision.mision_id,
            "version": 1,
            "longitud_total_m": round(mision.ruta.longitud_total_m, 1),
            "geometria": [[n.lat, n.lon] for n in mision.ruta.geometria],
            "paradas": [
                {"rsu_id": p.rsu_id, "interseccion_id": p.interseccion_id, "acceso_id": p.acceso_id,
                 "distancia_llegada_m": round(p.distancia_llegada_m, 1)}
                for p in mision.ruta.paradas
            ],
            "ts_ms": int(self.ahora() * 1000),
        }

    # --- MP / posición ----------------------------------------------------

    def procesar_mp(self, obu_id: str, lat: float, lon: float, velocidad_kmh: float, rumbo_deg: float) -> None:
        mision = self.misiones.get(obu_id)
        if mision is None or not mision.activa:
            return  # sin misión activa no hay procesamiento (ssec:minimizacion)

        self._log(EVT_MP_RX, mision.mision_id, lat=lat, lon=lon,
                  velocidad_kmh=velocidad_kmh, rumbo_deg=rumbo_deg)

        progreso = rutas_mod.proyectar_sobre_ruta(mision.ruta, lat, lon)
        if progreso.distancia_perpendicular_m > self.umbral_desvio_m:
            self._recalcular_por_desvio(mision, (lat, lon))
            return

        mision.distancia_recorrida_m = progreso.distancia_acumulada_m
        mision.ultima_velocidad_kmh = velocidad_kmh if velocidad_kmh and velocidad_kmh > 1.0 else self.velocidad_respaldo_kmh

        # 1) Anticipación por ETA: la primera parada pendiente, si ya está
        #    dentro del margen de anticipación mínima, se solicita AUNQUE la
        #    geocerca todavía no la haya detectado (RF8).
        siguiente = mision.siguiente_parada_pendiente()
        if siguiente is not None:
            distancia_restante = siguiente.parada.distancia_llegada_m - mision.distancia_recorrida_m
            eta_s = self._eta(distancia_restante, mision.ultima_velocidad_kmh)
            siguiente.eta_s = eta_s
            if eta_s is not None and eta_s <= self.anticipacion_min_s:
                self._intentar_solicitar(mision, siguiente, eta_s)

        # 2) Geocerca (gateway.geometria.SeguidorAcceso), igual que antes
        #    pero alimentada con la posición MP del servidor: confirma el
        #    acceso, renueva a 1 Hz, y cancela al cruzar/salir/divergir.
        for dec in mision.seguidor.actualizar(lat, lon, rumbo_deg):
            self._aplicar_decision_geocerca(mision, dec)

        self._revisar_tiempo_maximo(mision)
        self.enviar_me(obu_id, self._cuerpo_me(mision))

    def _eta(self, distancia_restante_m: float, velocidad_kmh: float) -> Optional[float]:
        if distancia_restante_m <= 0:
            return 0.0
        velocidad_m_s = max(velocidad_kmh, 1.0) / 3.6
        return distancia_restante_m / velocidad_m_s

    def _aplicar_decision_geocerca(self, mision: Mision, dec: Decision) -> None:
        if dec.accion == NINGUNA or dec.asignacion is None:
            return
        ep = mision.paradas.get(dec.asignacion.interseccion_id)
        if ep is None:
            return
        if dec.accion in (EMITIR_M1, ACTUALIZAR_M1):
            if ep.estado == ESTADO_PENDIENTE:
                self._intentar_solicitar(mision, ep, self.anticipacion_min_s)
            elif ep.estado not in (ESTADO_EN_ESPERA, ESTADO_CANCELADA, ESTADO_RECHAZADA):
                self._renovar(mision, ep)
        elif dec.accion == EMITIR_M3:
            self._cancelar_parada(mision, ep, motivo=dec.motivo or "cruce")

    # --- Solicitud / renovación / cancelación de una parada ---------------

    def _solicitantes_activos_en(self, rsu_id: str, excluir_obu: Optional[str] = None) -> list[conflictos_mod.Solicitante]:
        salida = []
        for obu_id, m in self.misiones.items():
            if not m.activa or obu_id == excluir_obu:
                continue
            for iid in m.orden:
                ep = m.paradas[iid]
                if ep.parada.rsu_id != rsu_id:
                    continue
                if ep.estado in (ESTADO_SOLICITADA, ESTADO_EN_COLA, ESTADO_CONCEDIDA):
                    grupo = self._grupo_semaforico(ep.parada)
                    salida.append(conflictos_mod.Solicitante(
                        mision_id=m.mision_id, acceso_id=ep.parada.acceso_id,
                        grupo_semaforico=grupo, clase=m.clase, eta_s=ep.eta_s or 0.0,
                    ))
        return salida

    def _grupo_semaforico(self, parada: ParadaRsu) -> int:
        for inter in self.registro:
            if inter.interseccion_id == parada.interseccion_id:
                for a in inter.accesos:
                    if a.acceso_id == parada.acceso_id:
                        return a.grupo_semaforico
        return -1

    def _intentar_solicitar(self, mision: Mision, ep: EstadoParada, eta_s: float) -> None:
        if ep.estado != ESTADO_PENDIENTE:
            return
        rsu_id = ep.parada.rsu_id
        propio = conflictos_mod.Solicitante(
            mision_id=mision.mision_id, acceso_id=ep.parada.acceso_id,
            grupo_semaforico=self._grupo_semaforico(ep.parada), clase=mision.clase, eta_s=eta_s,
        )
        otros = self._solicitantes_activos_en(rsu_id, excluir_obu=mision.obu_id)
        resultado = self.arbitro.evaluar(rsu_id, otros + [propio])
        if resultado.hubo_conflicto:
            self._log(EVT_CONFLICTO_ARBITRADO, mision.mision_id, rsu_id=rsu_id,
                      atendidos=[s.mision_id for s in resultado.atendidos],
                      en_espera=[s.mision_id for s in resultado.en_espera])
        if propio.mision_id not in {s.mision_id for s in resultado.atendidos}:
            ep.estado = ESTADO_EN_ESPERA
            return
        # Los perdedores que estaban atendidos pasan a en_espera: hay que
        # cancelarles la solicitud vigente con M3 motivo="conflicto".
        for perdedor in resultado.en_espera:
            if perdedor.mision_id == propio.mision_id:
                continue
            self._cancelar_por_conflicto(perdedor.mision_id, rsu_id)
        self._solicitar(mision, ep, eta_s)

    def _cancelar_por_conflicto(self, mision_id: str, rsu_id: str) -> None:
        for m in self.misiones.values():
            if m.mision_id != mision_id:
                continue
            for iid in m.orden:
                ep = m.paradas[iid]
                if ep.parada.rsu_id == rsu_id and ep.estado in (ESTADO_SOLICITADA, ESTADO_EN_COLA, ESTADO_CONCEDIDA):
                    self._cancelar_parada(m, ep, motivo="conflicto", pasar_a_en_espera=True)

    def _solicitar(self, mision: Mision, ep: EstadoParada, eta_s: float) -> None:
        ep.id_solicitud = f"{mision.mision_id}-{ep.parada.interseccion_id}"
        ep.seq = 1
        ep.estado = ESTADO_SOLICITADA
        self._solicitud_a_parada[ep.id_solicitud] = (mision.obu_id, ep.parada.interseccion_id)
        cuerpo = self._cuerpo_m1(mision, ep, eta_s)
        self.enviar_m1(ep.parada.rsu_id, cuerpo)
        self._log(EVT_M1_TX, ep.id_solicitud, mision_id=mision.mision_id, rsu_id=ep.parada.rsu_id,
                  interseccion_id=ep.parada.interseccion_id, acceso=ep.parada.acceso_id,
                  t_servicio=round(eta_s, 1), seq=ep.seq, origen="servidor")

    def _renovar(self, mision: Mision, ep: EstadoParada) -> None:
        if ep.id_solicitud is None:
            self._solicitar(mision, ep, ep.eta_s or self.anticipacion_min_s)
            return
        ep.seq += 1
        cuerpo = self._cuerpo_m1(mision, ep, ep.eta_s or 0.0)
        self.enviar_m1(ep.parada.rsu_id, cuerpo)
        self._log(EVT_M1_TX, ep.id_solicitud, mision_id=mision.mision_id, rsu_id=ep.parada.rsu_id,
                  seq=ep.seq, renovacion=True, origen="servidor")

    def _cuerpo_m1(self, mision: Mision, ep: EstadoParada, eta_s: float) -> dict:
        return {
            "tipo": "M1",
            "id_solicitud": ep.id_solicitud,
            "mision_id": mision.mision_id,
            "obu_id": mision.obu_id,
            "clase": mision.clase,
            "acceso": ep.parada.acceso_id,
            "t_servicio": max(1, round(eta_s)),
            "seq": ep.seq,
            "ts_ms": int(self.ahora() * 1000),
            "origen": "servidor",
        }

    def _cancelar_parada(self, mision: Mision, ep: EstadoParada, *, motivo: str, pasar_a_en_espera: bool = False) -> None:
        if ep.estado in (ESTADO_CANCELADA, ESTADO_PENDIENTE):
            return
        if ep.id_solicitud is not None:
            ep.seq += 1
            cuerpo = {
                "tipo": "M3", "id_solicitud": ep.id_solicitud, "seq": ep.seq,
                "motivo": motivo, "ts_ms": int(self.ahora() * 1000),
            }
            self.enviar_m3(ep.parada.rsu_id, cuerpo)
            self._log(EVT_M3_TX, ep.id_solicitud, mision_id=mision.mision_id, motivo=motivo, origen="servidor")
            self._solicitud_a_parada.pop(ep.id_solicitud, None)
        ep.estado = ESTADO_EN_ESPERA if pasar_a_en_espera else ESTADO_CANCELADA
        if not pasar_a_en_espera:
            self._promover_en_espera(ep.parada.rsu_id)

    def _promover_en_espera(self, rsu_id: str) -> None:
        """Al liberarse un conflicto (la parte ganadora cruzó, se desvió o
        se desarmó), la misión que había quedado "en_espera" en esa RSU
        vuelve a intentar pedir."""
        for m in self.misiones.values():
            if not m.activa:
                continue
            for iid in m.orden:
                ep = m.paradas[iid]
                if ep.parada.rsu_id == rsu_id and ep.estado == ESTADO_EN_ESPERA:
                    ep.estado = ESTADO_PENDIENTE
                    self._intentar_solicitar(m, ep, ep.eta_s or self.anticipacion_min_s)

    # --- M2 (respuesta de la RSU) ------------------------------------------

    def procesar_m2(self, body: dict) -> None:
        id_solicitud = body.get("id_solicitud")
        ref = self._solicitud_a_parada.get(id_solicitud) if id_solicitud else None
        if ref is None:
            return  # M2 de una solicitud que ya no se está siguiendo (cancelada, misión desarmada)
        obu_id, interseccion_id = ref
        mision = self.misiones.get(obu_id)
        if mision is None:
            return
        ep = mision.paradas.get(interseccion_id)
        if ep is None:
            return
        estado_m2 = body.get("estado")
        ep.estado = _ESTADO_DESDE_M2.get(estado_m2, ep.estado)
        ep.fase = body.get("fase")
        self._log(EVT_M2_RX, id_solicitud, mision_id=mision.mision_id, estado=estado_m2, fase=ep.fase)
        if ep.estado in (ESTADO_CANCELADA, ESTADO_RECHAZADA):
            self._solicitud_a_parada.pop(id_solicitud, None)
            self._promover_en_espera(ep.parada.rsu_id)
        self.enviar_me(obu_id, self._cuerpo_me(mision))

    # --- ME ------------------------------------------------------------

    def _cuerpo_me(self, mision: Mision) -> dict:
        paradas = []
        proximo = None
        for iid in mision.orden:
            ep = mision.paradas[iid]
            item = {
                "interseccion_id": iid, "rsu_id": ep.parada.rsu_id, "acceso_id": ep.parada.acceso_id,
                "estado": ep.estado, "eta_s": None if ep.eta_s is None else round(ep.eta_s, 1),
                "fase": ep.fase,
            }
            paradas.append(item)
            if proximo is None and ep.estado not in (ESTADO_CANCELADA, ESTADO_RECHAZADA):
                proximo = item
        return {
            "tipo": "ME", "mision_id": mision.mision_id, "paradas": paradas, "proximo": proximo,
            "conflicto": any(ep.estado == ESTADO_EN_ESPERA for ep in mision.paradas.values()),
            "ts_ms": int(self.ahora() * 1000),
        }

    # --- Desvío / recálculo ------------------------------------------------

    def _recalcular_por_desvio(self, mision: Mision, posicion_actual: tuple[float, float]) -> None:
        paradas_antes = len(mision.ruta.paradas)
        nueva_ruta = rutas_mod.planificar_ruta(self.grafo, self.registro, posicion_actual, mision.destino)
        # Cancela lo que ya no está en la nueva ruta.
        nuevos_iid = {p.interseccion_id for p in nueva_ruta.paradas}
        for iid in list(mision.orden):
            ep = mision.paradas[iid]
            if iid not in nuevos_iid and ep.estado not in (ESTADO_CANCELADA, ESTADO_PENDIENTE):
                self._cancelar_parada(mision, ep, motivo="desvio")

        registro_mision = [i for i in self.registro if i.interseccion_id in nuevos_iid]
        mision.ruta = nueva_ruta
        mision.seguidor = SeguidorAcceso(registro_mision, self.parametros_geocerca)
        mision.orden = [p.interseccion_id for p in nueva_ruta.paradas]
        mision.distancia_recorrida_m = 0.0
        for p in nueva_ruta.paradas:
            if p.interseccion_id not in mision.paradas:
                mision.paradas[p.interseccion_id] = EstadoParada(p)

        self._log(EVT_RUTA_RECALCULADA, mision.mision_id, motivo="desvio",
                  n_paradas_antes=paradas_antes, n_paradas_despues=len(nueva_ruta.paradas))
        self.enviar_mr(mision.obu_id, self._cuerpo_mr(mision))

    def _revisar_tiempo_maximo(self, mision: Mision) -> None:
        if self.ahora() - mision.t_armado > self.tiempo_maximo_s:
            self.desarmar_mision(mision.obu_id, motivo="tiempo_maximo")

    # --- MF / desarme -------------------------------------------------

    def desarmar_mision(self, obu_id: str, motivo: str) -> None:
        mision = self.misiones.get(obu_id)
        if mision is None or not mision.activa:
            return
        for iid in list(mision.orden):
            ep = mision.paradas[iid]
            if ep.estado in (ESTADO_PENDIENTE, ESTADO_EN_ESPERA):
                # Nunca se llegó a enviar M1 (o se había retirado por un
                # conflicto): no hay nada que cancelar en la RSU, solo se
                # cierra la parada para que ME deje de mostrarla.
                ep.estado = ESTADO_CANCELADA
            elif ep.estado not in (ESTADO_CANCELADA, ESTADO_RECHAZADA):
                self._cancelar_parada(mision, ep, motivo=motivo)
        mision.activa = False
        self._log(EVT_MISION_DESARMADA, mision.mision_id, motivo=motivo)
        self.enviar_me(obu_id, self._cuerpo_me(mision))
        for iid in mision.orden:
            self._promover_en_espera(mision.paradas[iid].parada.rsu_id)
