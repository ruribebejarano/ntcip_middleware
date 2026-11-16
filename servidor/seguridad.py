"""Seguridad operativa del servidor central: detección de una OBU
comprometida o que satura el broker, y comandos del operador de la central.

Por qué en el servidor. Con la arquitectura centralizada (E3), una OBU no
puede ordenarle nada a una RSU (la ACL solo deja publicar en
rsu/+/solicitudes al servidor). El camino más barato para un atacante es
otro: una OBU con un certificado válido (teléfono robado o clonado) arma
una misión falsa y el servidor pide los verdes por ella. Eso no lo detiene
TLS; lo detienen la plausibilidad de lo que la OBU reporta y, sobre todo,
la verificación humana de que la misión existe (procedimiento de respuesta
en docs/PRUEBA_SEGURIDAD_OPERATIVA.md):

  1. Detección (este módulo, automático)
  2. Notificación (alerta al operador de la central; de ahí, al CCGT)
  3. Verificación humana (la central confirma con el despacho de la
     institución dueña del vehículo)
  4. Contención (comando del operador: suspender la misión o la OBU;
     revocar el certificado; el CCGT puede desactivar la prioridad en una RSU)
  5. Cierre (informe del incidente con los eventos RF-08)

Detecciones (todas configurables por variable de entorno; los valores por
defecto son PARÁMETROS DE PRUEBA del banco, no umbrales normativos):

  salto_posicion   desplazamiento entre dos MP consecutivos mayor que
                   SEG_SALTO_MIN_M y con velocidad implícita mayor que
                   SEG_V_MAX_KMH (el intervalo se toma de ts_ms de la OBU
                   si viene, para no confundir con un salto la ráfaga de MP
                   retenidos que llega tras una reconexión).
  inundacion       más de SEG_TASA_MAX_HZ x SEG_VENTANA_S MP de una OBU en
                   SEG_VENTANA_S segundos (el contrato fija 1 Hz, RNF-02).
  misiones_repetidas  más de SEG_MI_MAX MI de una OBU en 60 s.
  verificacion_despacho  aviso informativo al armar cada misión: la central
                   debe confirmarla con el despacho de la institución.

Respuesta automática (SEG_POLITICA):
  alertar    (por defecto) solo alerta; la contención la decide el operador
  suspender  además, suspende de inmediato la OBU ante una alerta de
             severidad alta (salto_posicion, inundacion)

Confirmación obligatoria (SEG_CONFIRMACION_S > 0): una misión que el
operador no confirma (comando confirmar_mision) en ese plazo se cancela.
Con 0 (por defecto) la confirmación es solo un aviso.

Comandos del operador (tema servidor/central/comandos, identidad
"operador-central" en la ACL), JSON:
  {"accion": "suspender_obu" | "reanudar_obu" | "suspender_mision" |
             "confirmar_mision", "obu_id": "...", "motivo": "..."}
"""

from __future__ import annotations

import math
import os
import time
from collections import deque
from typing import Callable, Optional

from common.events import (
    EVT_ALERTA_SEGURIDAD,
    EVT_COMANDO_OPERADOR,
    EVT_MP_RECHAZADO_SUSPENDIDA,
    EventLogger,
)
from gateway.geometria import proyeccion_local

SEVERIDAD_ALTA = "alta"
SEVERIDAD_MEDIA = "media"
SEVERIDAD_INFO = "info"

ACCIONES = ("suspender_obu", "reanudar_obu", "suspender_mision", "confirmar_mision")


def _env_float(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


class MonitorSeguridad:
    def __init__(
        self,
        eventos: Optional[EventLogger],
        publicar_alerta: Callable[[dict], None],
        suspender_mision: Callable[[str, str], None],
        ahora: Callable[[], float] = time.monotonic,
    ) -> None:
        self.eventos = eventos
        self.publicar_alerta = publicar_alerta
        self.suspender_mision = suspender_mision  # (obu_id, motivo) -> desarma con M3
        self.ahora = ahora
        self.v_max_kmh = _env_float("SEG_V_MAX_KMH", 150.0)
        self.salto_min_m = _env_float("SEG_SALTO_MIN_M", 50.0)
        self.tasa_max_hz = _env_float("SEG_TASA_MAX_HZ", 3.0)
        self.ventana_s = _env_float("SEG_VENTANA_S", 5.0)
        self.mi_max = int(_env_float("SEG_MI_MAX", 3))
        self.confirmacion_s = _env_float("SEG_CONFIRMACION_S", 0.0)
        self.politica = os.environ.get("SEG_POLITICA", "alertar").strip().lower()
        self.suspendidas: set[str] = set()
        self._ignorados: dict[str, int] = {}
        self._ultima_pos: dict[str, tuple[float, float, float, Optional[int]]] = {}
        self._mp_t: dict[str, deque] = {}
        self._mi_t: dict[str, deque] = {}
        self._ultima_alerta: dict[tuple[str, str], float] = {}
        self._pendientes_confirmar: dict[str, tuple[str, float]] = {}  # obu_id -> (mision_id, t_armado)
        self._misiones_vistas: set[str] = set()

    # --- utilidades -----------------------------------------------------

    def _log(self, tipo: str, id_ref: str, **extra) -> None:
        if self.eventos is not None:
            self.eventos.log(tipo, id_ref, **extra)

    def parametros(self) -> dict:
        return {"v_max_kmh": self.v_max_kmh, "salto_min_m": self.salto_min_m,
                "tasa_max_hz": self.tasa_max_hz, "ventana_s": self.ventana_s, "mi_max": self.mi_max,
                "confirmacion_s": self.confirmacion_s, "politica": self.politica}

    def _alertar(self, tipo: str, obu_id: str, severidad: str, repetir_cada_s: float = 10.0, **evidencia) -> bool:
        """Registra y publica una alerta (una por tipo y OBU cada
        `repetir_cada_s`, para no inundar al operador). Devuelve True si se
        emitió."""
        t = self.ahora()
        clave = (tipo, obu_id)
        previa = self._ultima_alerta.get(clave)
        if previa is not None and t - previa < repetir_cada_s:
            return False
        self._ultima_alerta[clave] = t
        alerta = {"tipo": "alerta", "alerta": tipo, "obu_id": obu_id, "severidad": severidad,
                  "evidencia": evidencia, "ts_ms": int(time.time() * 1000)}
        self._log(EVT_ALERTA_SEGURIDAD, obu_id, alerta=tipo, obu_id=obu_id, severidad=severidad, **evidencia)
        print(f"[seguridad] ALERTA {severidad}: {tipo} de '{obu_id}' {evidencia}")
        self.publicar_alerta(alerta)
        if severidad == SEVERIDAD_ALTA and self.politica == "suspender" and obu_id not in self.suspendidas:
            self._suspender_obu(obu_id, motivo=f"automatico_{tipo}", origen="automatico")
        return True

    def _suspender_obu(self, obu_id: str, motivo: str, origen: str) -> None:
        self.suspendidas.add(obu_id)
        self._pendientes_confirmar.pop(obu_id, None)
        self._log(EVT_COMANDO_OPERADOR, obu_id, accion="suspender_obu", obu_id=obu_id, motivo=motivo, origen=origen)
        print(f"[seguridad] OBU '{obu_id}' SUSPENDIDA ({origen}: {motivo}): se cancela su misión y se ignoran sus MI/MP")
        self.suspender_mision(obu_id, f"suspendida_{origen}")

    def _ignorar(self, obu_id: str) -> bool:
        if obu_id not in self.suspendidas:
            return False
        n = self._ignorados.get(obu_id, 0) + 1
        self._ignorados[obu_id] = n
        if n == 1 or n % 50 == 0:
            self._log(EVT_MP_RECHAZADO_SUSPENDIDA, obu_id, obu_id=obu_id, ignorados=n)
        return True

    # --- entradas desde servidor/main.py -------------------------------

    def al_recibir_mi(self, obu_id: str) -> bool:
        """Devuelve False si el MI debe ignorarse (OBU suspendida)."""
        if self._ignorar(obu_id):
            return False
        t = self.ahora()
        cola = self._mi_t.setdefault(obu_id, deque())
        cola.append(t)
        while cola and t - cola[0] > 60.0:
            cola.popleft()
        if len(cola) > self.mi_max:
            self._alertar("misiones_repetidas", obu_id, SEVERIDAD_MEDIA, mi_en_60s=len(cola))
        return True

    def al_armar_mision(self, obu_id: str, mision_id: str) -> None:
        if mision_id in self._misiones_vistas:
            return  # MI repetido de una misión ya armada (no es una misión nueva)
        self._misiones_vistas.add(mision_id)
        self._pendientes_confirmar[obu_id] = (mision_id, self.ahora())
        self._alertar("verificacion_despacho", obu_id, SEVERIDAD_INFO, repetir_cada_s=0.0,
                      mision_id=mision_id, plazo_confirmacion_s=self.confirmacion_s)

    def al_recibir_mp(self, obu_id: str, lat: float, lon: float, ts_ms: Optional[int]) -> bool:
        """Devuelve False si el MP debe ignorarse (OBU suspendida, o recién
        suspendida por esta misma muestra)."""
        if self._ignorar(obu_id):
            return False
        t = self.ahora()
        # Tasa de MP en la ventana
        cola = self._mp_t.setdefault(obu_id, deque())
        cola.append(t)
        while cola and t - cola[0] > self.ventana_s:
            cola.popleft()
        if len(cola) > self.tasa_max_hz * self.ventana_s:
            self._alertar("inundacion", obu_id, SEVERIDAD_ALTA,
                          mp_en_ventana=len(cola), ventana_s=self.ventana_s,
                          tasa_hz=round(len(cola) / self.ventana_s, 1))
        # Salto de posición
        previa = self._ultima_pos.get(obu_id)
        self._ultima_pos[obu_id] = (lat, lon, t, ts_ms)
        if previa is not None:
            lat0, lon0, t0, ts0 = previa
            x, y = proyeccion_local(lat, lon, lat0, lon0)
            dist = math.hypot(x, y)
            dt = (ts_ms - ts0) / 1000.0 if (ts_ms is not None and ts0 is not None and ts_ms > ts0) else (t - t0)
            dt = max(dt, 0.05)
            v_kmh = dist / dt * 3.6
            if dist > self.salto_min_m and v_kmh > self.v_max_kmh:
                self._alertar("salto_posicion", obu_id, SEVERIDAD_ALTA,
                              distancia_m=round(dist, 1), dt_s=round(dt, 2), v_implicita_kmh=round(v_kmh, 1))
        return obu_id not in self.suspendidas

    def revisar_confirmaciones(self) -> None:
        """Con SEG_CONFIRMACION_S > 0, cancela la misión que el operador no
        confirmó a tiempo. Se llama con cada mensaje recibido (los MP de
        cualquier misión llegan a 1 Hz), sin un hilo propio."""
        if self.confirmacion_s <= 0:
            return
        t = self.ahora()
        for obu_id, (mision_id, t_armado) in list(self._pendientes_confirmar.items()):
            if t - t_armado >= self.confirmacion_s:
                self._pendientes_confirmar.pop(obu_id, None)
                self._alertar("mision_no_confirmada", obu_id, SEVERIDAD_MEDIA, repetir_cada_s=0.0,
                              mision_id=mision_id, plazo_s=self.confirmacion_s)
                self._log(EVT_COMANDO_OPERADOR, obu_id, accion="suspender_mision", obu_id=obu_id,
                          motivo="sin_confirmacion_despacho", origen="automatico")
                self.suspender_mision(obu_id, "sin_confirmacion_despacho")

    def comando(self, data: dict) -> Optional[str]:
        """Aplica un comando del operador. Devuelve un texto de error o None."""
        accion = data.get("accion")
        obu_id = data.get("obu_id")
        motivo = str(data.get("motivo", "operador"))
        if accion not in ACCIONES or not obu_id:
            return f"comando inválido: {data!r}"
        if accion == "suspender_obu":
            if obu_id not in self.suspendidas:
                self._suspender_obu(obu_id, motivo, origen="operador")
            return None
        self._log(EVT_COMANDO_OPERADOR, obu_id, accion=accion, obu_id=obu_id, motivo=motivo, origen="operador")
        if accion == "reanudar_obu":
            self.suspendidas.discard(obu_id)
            self._ultima_pos.pop(obu_id, None)
            self._mp_t.pop(obu_id, None)
            print(f"[seguridad] OBU '{obu_id}' reanudada por el operador")
        elif accion == "suspender_mision":
            self._pendientes_confirmar.pop(obu_id, None)
            print(f"[seguridad] misión de '{obu_id}' cancelada por el operador ({motivo})")
            self.suspender_mision(obu_id, "cancelada_operador")
        elif accion == "confirmar_mision":
            self._pendientes_confirmar.pop(obu_id, None)
            print(f"[seguridad] misión de '{obu_id}' confirmada por el operador")
        return None
