"""Vista de la mision en la arquitectura centralizada, armada SOLO con lo que
la consola observa en el broker (mqtt_cliente.py) -- no decide nada ni
publica nada:

  obu/{obu_id}/mision      MI / MF   (OBU -> servidor)
  obu/{obu_id}/posicion    MP        (OBU -> servidor)
  obu/{obu_id}/ruta        MR        (servidor -> OBU)
  obu/{obu_id}/estado      ME        (servidor -> OBU)
  rsu/{rsu_id}/solicitudes M1 / M3   (servidor -> RSU)
  servidor/+/respuestas    M2        (RSU -> servidor)

Formatos en docs/CONTRATO_OBU.md y servidor/gestor_mision.py.

Estado de la solicitud por RSU (el que muestra el panel): el de la parada en
el ultimo ME del servidor (pendiente | solicitada | en_cola | concedida |
en_espera | rechazada | cancelada), adelantado por M1/M2/M3 cuando llegan
antes que el ME siguiente. "liberada" no existe en el contrato: es como la
consola muestra una parada "cancelada" cuyo M3 llevo motivo "cruce" (el
vehiculo ya cruzo y la RSU solto la prioridad); con cualquier otro motivo
(desvio, conflicto, boton, destino, tiempo_maximo) se muestra "cancelada"
con su motivo."""

from __future__ import annotations

import threading
import time
from collections import deque

from consola.backend.bus import BUS

_DESDE_M2 = {"recibida": "solicitada", "en_cola": "en_cola", "concedida": "concedida",
             "rechazada": "rechazada", "cancelada": "cancelada"}
_MAX_LINEA_TIEMPO = 500


class SeguidorMision:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.mision: dict | None = None      # la ultima mision armada (MI)
        self.ruta: dict | None = None        # ultimo MR de esa mision
        self.posicion: dict | None = None    # ultimo MP
        self.prioridad: dict[str, dict] = {}  # rsu_id -> estado de la solicitud
        self.linea_tiempo: deque[dict] = deque(maxlen=_MAX_LINEA_TIEMPO)
        self._m1_vistos: dict[str, int] = {}  # id_solicitud -> renovaciones

    # --- entrada --------------------------------------------------------

    def procesar(self, tema: str, datos: dict, t: float) -> None:
        if not isinstance(datos, dict):
            return
        partes = tema.split("/")
        tipo = datos.get("tipo")
        with self._lock:
            if partes[0] == "obu" and len(partes) == 3:
                obu_id, canal = partes[1], partes[2]
                if canal == "mision" and tipo == "MI":
                    self._mi(obu_id, datos, t)
                elif canal == "mision" and tipo == "MF":
                    self._mf(obu_id, datos, t)
                elif canal == "posicion":
                    self._mp(obu_id, datos, t)
                elif canal == "ruta" and tipo == "MR":
                    self._mr(obu_id, datos, t)
                elif canal == "estado" and tipo == "ME":
                    self._me(obu_id, datos, t)
            elif partes[0] == "rsu" and len(partes) == 3 and partes[2] == "solicitudes":
                if tipo == "M1":
                    self._m1(partes[1], datos, t)
                elif tipo == "M3":
                    self._m3(partes[1], datos, t)
            elif partes[0] == "servidor" and len(partes) == 3 and partes[2] == "respuestas" and tipo == "M2":
                self._m2(datos, t)

    # --- mensajes de la OBU / servidor ----------------------------------

    def _de_esta_mision(self, obu_id: str) -> bool:
        return self.mision is not None and self.mision["obu_id"] == obu_id

    def _mi(self, obu_id: str, d: dict, t: float) -> None:
        self._nueva_mision(obu_id, d, t)
        self._publicar_mision()  # antes del evento: el navegador limpia la linea de tiempo al ver una mision nueva
        self._evento(t, "MI", None, f"OBU {obu_id} arma la misión (clase {d.get('clase')})")

    def _nueva_mision(self, obu_id: str, d: dict, t: float) -> None:
        self.mision = {"obu_id": obu_id, "mision_id": None, "clase": d.get("clase"),
                       "destino": d.get("destino"), "origen": d.get("origen"),
                       "activa": True, "t_inicio": t, "t_fin": None, "motivo_fin": None}
        self.ruta = None
        self.posicion = None
        self.prioridad = {}
        self._m1_vistos = {}
        self.linea_tiempo.clear()

    def _mf(self, obu_id: str, d: dict, t: float) -> None:
        if not self._de_esta_mision(obu_id):
            return
        self.mision["activa"] = False
        self.mision["t_fin"] = t
        self.mision["motivo_fin"] = d.get("motivo")
        self._evento(t, "MF", None, f"OBU {obu_id} desarma la misión (motivo {d.get('motivo', '?')})")
        self._publicar_mision()

    def _mp(self, obu_id: str, d: dict, t: float) -> None:
        if not self._de_esta_mision(obu_id):
            return
        try:
            self.posicion = {"lat": float(d["lat"]), "lon": float(d["lon"]),
                             "velocidad_kmh": d.get("velocidad_kmh"), "rumbo_deg": d.get("rumbo_deg"),
                             "seq": d.get("seq"), "t": t}
        except (KeyError, TypeError, ValueError):
            return
        BUS.publicar("mision_pos", self.posicion)

    def _mr(self, obu_id: str, d: dict, t: float) -> None:
        if not self._de_esta_mision(obu_id):
            if self.mision is not None and self.mision["activa"]:
                return  # otra OBU con mision activa: la consola sigue a la primera
            # La consola arranco con la mision ya armada (no vio el MI).
            self._nueva_mision(obu_id, {}, t)
            self._evento(t, "MI", None, f"OBU {obu_id}: misión ya armada antes de abrir la consola")
        primera = self.ruta is None or self.ruta.get("mision_id") != d.get("mision_id")
        self.mision["mision_id"] = d.get("mision_id")
        self.ruta = {"mision_id": d.get("mision_id"), "version": d.get("version"),
                     "longitud_total_m": d.get("longitud_total_m"),
                     "geometria": d.get("geometria") or [], "paradas": d.get("paradas") or []}
        en_ruta = {str(p["rsu_id"]) for p in self.ruta["paradas"]}
        for orden, p in enumerate(self.ruta["paradas"], start=1):
            rsu_id = str(p["rsu_id"])
            previo = self.prioridad.get(rsu_id)
            self.prioridad[rsu_id] = {
                **(previo or {"estado": "pendiente", "desde": t, "ultimo_m2": None, "motivo": None,
                              "id_solicitud": None, "eta_s": None, "renovaciones": 0}),
                "rsu_id": rsu_id, "interseccion_id": p.get("interseccion_id"),
                "acceso_id": p.get("acceso_id"), "orden": orden,
            }
        for rsu_id in list(self.prioridad):
            if rsu_id not in en_ruta:
                self.prioridad.pop(rsu_id)
        paradas = " → ".join(f"RSU {p['rsu_id']}/{p.get('acceso_id')}" for p in self.ruta["paradas"]) or "sin RSU"
        verbo = "calcula la ruta" if primera else f"recalcula la ruta (v{d.get('version')})"
        self._evento(t, "MR", None, f"servidor {verbo}: {d.get('longitud_total_m')} m, {paradas}")
        self._publicar_mision()
        for rsu_id in self.prioridad:
            self._publicar_prioridad(rsu_id)

    def _me(self, obu_id: str, d: dict, t: float) -> None:
        if not self._de_esta_mision(obu_id):
            return
        for p in d.get("paradas") or []:
            rsu_id = str(p.get("rsu_id"))
            if rsu_id not in self.prioridad:
                continue
            self.prioridad[rsu_id]["eta_s"] = p.get("eta_s")
            self._cambiar(rsu_id, p.get("estado"), t)
            self._publicar_prioridad(rsu_id)

    # --- mensajes servidor <-> RSU --------------------------------------

    def _m1(self, rsu_id: str, d: dict, t: float) -> None:
        if self.mision is None or d.get("mision_id") != self.mision.get("mision_id"):
            return
        id_sol = d.get("id_solicitud")
        p = self.prioridad.get(rsu_id)
        if p is None:
            return
        p["id_solicitud"] = id_sol
        if id_sol not in self._m1_vistos:
            self._m1_vistos[id_sol] = 0
            self._evento(t, "M1", rsu_id, f"servidor → RSU {rsu_id}: solicita prioridad, acceso {d.get('acceso')}, "
                                          f"t_servicio {d.get('t_servicio')} s")
            if p["estado"] in ("pendiente", "en_espera"):
                self._cambiar(rsu_id, "solicitada", t)
        else:
            self._m1_vistos[id_sol] += 1
            p["renovaciones"] = self._m1_vistos[id_sol]
        self._publicar_prioridad(rsu_id)

    def _m2(self, d: dict, t: float) -> None:
        rsu_id = str(d.get("rsu_id"))
        p = self.prioridad.get(rsu_id)
        if p is None or (p.get("id_solicitud") and d.get("id_solicitud") != p["id_solicitud"]):
            return
        anterior = (p.get("ultimo_m2") or {}).get("estado")
        p["ultimo_m2"] = {"estado": d.get("estado"), "fase": d.get("fase"), "motivo": d.get("motivo"), "t": t}
        if d.get("estado") != anterior:
            # Solo cambios: la RSU responde con M2 a cada renovacion M1 (1 Hz).
            extra = f", motivo {d['motivo']}" if d.get("motivo") else ""
            self._evento(t, "M2", rsu_id, f"RSU {rsu_id} → servidor: {d.get('estado')} (fase {d.get('fase')}{extra})")
        if d.get("motivo") and d["motivo"] != "m3" and not p.get("motivo"):
            p["motivo"] = d["motivo"]  # p. ej. caducidad (watchdog de la RSU), sin M3 del servidor
        nuevo = _DESDE_M2.get(d.get("estado"))
        if nuevo:
            self._cambiar(rsu_id, nuevo, t)
        self._publicar_prioridad(rsu_id)

    def _m3(self, rsu_id: str, d: dict, t: float) -> None:
        p = self.prioridad.get(rsu_id)
        if p is None or (p.get("id_solicitud") and d.get("id_solicitud") != p["id_solicitud"]):
            return
        p["motivo"] = d.get("motivo")
        self._evento(t, "M3", rsu_id, f"servidor → RSU {rsu_id}: cancela la solicitud (motivo {d.get('motivo', '?')})")
        self._cambiar(rsu_id, "cancelada", t)
        self._publicar_prioridad(rsu_id)

    # --- estado por RSU -------------------------------------------------

    def _cambiar(self, rsu_id: str, estado: str | None, t: float) -> None:
        p = self.prioridad.get(rsu_id)
        if p is None or not estado:
            return
        if estado == "cancelada" and p.get("motivo") == "cruce":
            estado = "liberada"
        if estado != p["estado"]:
            p["estado"] = estado
            p["desde"] = t

    def _evento(self, t: float, tipo: str, rsu_id: str | None, texto: str) -> None:
        e = {"t": t, "tipo": tipo, "rsu_id": rsu_id, "texto": texto}
        self.linea_tiempo.append(e)
        BUS.publicar("mision_evento", e)

    def _publicar_mision(self) -> None:
        BUS.publicar("mision", {"mision": self.mision, "ruta": self.ruta})

    def _publicar_prioridad(self, rsu_id: str) -> None:
        BUS.publicar("rsu_prioridad", dict(self.prioridad[rsu_id]))

    # --- foto para GET /api/mision --------------------------------------

    def foto(self) -> dict:
        with self._lock:
            return {"mision": self.mision, "ruta": self.ruta, "posicion": self.posicion,
                    "prioridad": {k: dict(v) for k, v in self.prioridad.items()},
                    "linea_tiempo": list(self.linea_tiempo), "ahora": time.time()}


SEGUIDOR = SeguidorMision()
