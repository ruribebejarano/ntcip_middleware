#!/usr/bin/env python3
"""OBU EMULADA: reproduce una trayectoria sintetica y ejecuta el lado OBU
del lazo de priorizacion (OE4), sin vehiculo, sin telefono y sin OBD-II.

*** EMULACION CON DATOS FICTICIOS ***
La posicion, el rumbo y la velocidad salen de un CSV generado por
scripts/trayectorias/generar.py, no de un receptor GNSS ni de un lector
OBD-II (RF-01, RF-02 quedan fuera de esta emulacion). Lo que SI es real es
todo lo que pasa a partir de la muestra: la identificacion de la
interseccion y del acceso (RF-11, gateway/geometria.py), el criterio de
emision y cancelacion (RF-03, RF-04), y los mensajes M1/M3 que viajan por el
broker MQTT hasta la RSU, que los traduce a NTCIP 1211 hacia el controlador.

Mensajes (tab:mensajes de main.tex), JSON sobre MQTT 5:
  M1  -> rsu/{rsu_id}/solicitudes  {tipo, id_solicitud, vehiculo_id, interseccion_id,
                                    acceso, clase, velocidad_kmh, ts_ms, seq}
  M3  -> rsu/{rsu_id}/solicitudes  {tipo, id_solicitud, ts_ms, seq, motivo}
  M2  <- veh/{vehiculo_id}/respuestas (Response Topic de M1/M3; Correlation
         Data = "<id_solicitud>:<seq>", lo que permite medir el RTT del par
         M1/M2 con el reloj de la propia OBU, ssec:metricas)

La posicion NO viaja en M1 (ssec:minimizacion): solo interseccion y acceso.
vehiculo_id es un seudonimo de sesion ("ses-xxxxxx"), no la placa.

Eventos (common/events.py, RF-10): M1_tx, M3_tx, M2_rx (con rtt_ms). M1_tx
lleva ademas la verdad de terreno de la muestra, para la tasa de acierto de
acceso.

Estado local para el panel (--estado-local): en cada muestra la OBU escribe
su posicion, su asignacion y el estado de su solicitud en un archivo JSON de
la propia laptop, que lee la pagina "Lazo V2I en vivo" del panel. La
posicion NO se publica por MQTT (ssec:minimizacion): ese archivo es solo una
vista local para la demo, equivalente a mirar la pantalla del telefono.

Uso (broker en la RSU o broker central; sin TLS en esta etapa):
    python3 gateway/obu_emulada.py --broker-host 192.168.18.175 \\
        --trayectoria resultados/trayectorias/avenida_ab_s1.csv
    # mas rapido que tiempo real (las muestras salen a 2 Hz):
    python3 gateway/obu_emulada.py --broker-host rsu-01 --factor 2 --trayectoria ...
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import EVT_M1_TX, EVT_M2_RX, EVT_M3_TX, EVT_MUESTRA, EventLogger  # noqa: E402
from gateway.geometria import (  # noqa: E402
    ACTUALIZAR_M1,
    EMITIR_M1,
    EMITIR_M3,
    ParametrosGeometria,
    SeguidorAcceso,
    cargar_registro,
)


class ObuEmulada:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.vehiculo_id = args.vehiculo_id or f"ses-{uuid.uuid4().hex[:6]}"
        self.topic_respuestas = f"veh/{self.vehiculo_id}/respuestas"
        self.eventos = EventLogger(args.obu_id)
        self.registro = cargar_registro(args.registro)
        self.p = ParametrosGeometria(r_g_m=args.r_g, r_i_m=args.r_i)
        self.seguidor = SeguidorAcceso(self.registro, self.p)
        self._enviados: dict[bytes, int] = {}       # correlation -> monotonic_ns del envio
        self._lock = threading.Lock()
        self.id_actual: str | None = None
        self.seq = 0
        self.rsu_actual: str | None = None
        self.contadores = {"M1": 0, "M3": 0, "M2": 0}
        self.ultimo_estado: dict[str, str] = {}
        # RF-05 es un rechazo definitivo (clase no reconocida): tras un M2
        # "rechazada" la OBU deja de actualizar esa solicitud.
        self.rechazadas: set[str] = set()
        self.ultimo_m2: dict = {}

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"obu-{self.vehiculo_id}", protocol=mqtt.MQTTv5)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # --- MQTT ----------------------------------------------------------

    def _on_connect(self, client, _u, _f, reason_code, _p=None):
        client.subscribe(self.topic_respuestas, qos=1)

    def _on_message(self, _c, _u, msg):
        t_rx = time.monotonic_ns()
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        corr = getattr(msg.properties, "CorrelationData", None) if msg.properties else None
        with self._lock:
            t_tx = self._enviados.pop(corr, None) if corr else None
            self.contadores["M2"] += 1
        rtt_ms = (t_rx - t_tx) / 1e6 if t_tx is not None else None
        id_sol = data.get("id_solicitud", "-")
        estado = data.get("estado")
        if estado == "rechazada":
            self.rechazadas.add(id_sol)
        self.ultimo_m2 = {"id_solicitud": id_sol, "estado": estado, "fase": data.get("fase"),
                          "rtt_ms": rtt_ms, "ts": time.time()}
        if self.ultimo_estado.get(id_sol) != estado:
            print(f"  M2 <- {id_sol} estado={estado} fase={data.get('fase')}"
                  + (f" rtt={rtt_ms:.1f} ms" if rtt_ms is not None else ""))
            self.ultimo_estado[id_sol] = estado
        self.eventos.log(EVT_M2_RX, id_sol, estado=estado, fase=data.get("fase"),
                         seq_ref=data.get("seq_ref"), rtt_ms=rtt_ms, motivo=data.get("motivo"))

    def _publicar(self, rsu_id: str, cuerpo: dict) -> None:
        corr = f"{cuerpo['id_solicitud']}:{cuerpo['seq']}".encode()
        props = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        props.ResponseTopic = self.topic_respuestas
        props.CorrelationData = corr
        with self._lock:
            self._enviados[corr] = time.monotonic_ns()
        self.client.publish(f"rsu/{rsu_id}/solicitudes", json.dumps(cuerpo), qos=1, properties=props)

    # --- Lazo ----------------------------------------------------------

    def _m1(self, dec, fila: dict) -> None:
        a = dec.asignacion
        if dec.accion == EMITIR_M1:
            self.id_actual = f"{self.vehiculo_id}-{uuid.uuid4().hex[:8]}"
            self.seq = 0
            self.rsu_actual = a.rsu_id
            print(f"[t={fila['t_s']:>6}s] M1 nueva -> rsu/{a.rsu_id} {a.interseccion_id}/{a.acceso_id} "
                  f"a {a.distancia_m:.0f} m ({self.id_actual})")
        self.seq += 1
        cuerpo = {
            "tipo": "M1", "id_solicitud": self.id_actual, "vehiculo_id": self.vehiculo_id,
            "interseccion_id": a.interseccion_id, "acceso": a.acceso_id, "clase": self.args.clase_tipo,
            "velocidad_kmh": float(fila["velocidad_kmh"]), "ts_ms": int(time.time() * 1000), "seq": self.seq,
        }
        self._publicar(a.rsu_id, cuerpo)
        self.contadores["M1"] += 1
        self.eventos.log(EVT_M1_TX, self.id_actual, seq=self.seq, rsu_id=a.rsu_id,
                         interseccion_id=a.interseccion_id, acceso=a.acceso_id,
                         distancia_m=round(a.distancia_m, 1), t_tray_s=float(fila["t_s"]),
                         verdad_interseccion=fila.get("interseccion_verdad") or None,
                         verdad_acceso=fila.get("acceso_verdad") or None,
                         clase=self.args.clase_tipo, trayectoria=Path(self.args.trayectoria).name)

    def _m3(self, dec, fila: dict) -> None:
        self.seq += 1
        cuerpo = {"tipo": "M3", "id_solicitud": self.id_actual, "ts_ms": int(time.time() * 1000),
                  "seq": self.seq, "motivo": dec.motivo}
        self._publicar(dec.asignacion.rsu_id, cuerpo)
        self.contadores["M3"] += 1
        self.eventos.log(EVT_M3_TX, self.id_actual, seq=self.seq, motivo=dec.motivo,
                         rsu_id=dec.asignacion.rsu_id, t_tray_s=float(fila["t_s"]))
        print(f"[t={fila['t_s']:>6}s] M3 -> rsu/{dec.asignacion.rsu_id} ({dec.motivo}) {self.id_actual}")
        self.id_actual = None

    def _escribir_estado(self, fila: dict, n: int, total: int) -> None:
        """Vista local para el panel (ver docstring del modulo). Escritura
        atomica: el panel nunca lee un JSON a medio escribir."""
        if not self.args.estado_local:
            return
        a = self.seguidor.actual
        estado = {
            "ts": time.time(), "vehiculo_id": self.vehiculo_id,
            "trayectoria": str(Path(self.args.trayectoria).resolve()),
            "muestra": n, "muestras": total, "t_s": float(fila["t_s"]),
            "lat": float(fila["lat"]), "lon": float(fila["lon"]),
            "rumbo_deg": float(fila["rumbo_deg"]), "velocidad_kmh": float(fila["velocidad_kmh"]),
            "asignacion": None if a is None else {
                "rsu_id": a.rsu_id, "interseccion_id": a.interseccion_id,
                "acceso": a.acceso_id, "distancia_m": round(a.distancia_m, 1)},
            "solicitud": self.id_actual, "seq": self.seq if self.id_actual else None,
            "rechazada": self.id_actual in self.rechazadas if self.id_actual else False,
            "ultimo_m2": self.ultimo_m2,
            "r_g_m": self.p.r_g_m, "r_i_m": self.p.r_i_m,
            "registro": str(Path(self.args.registro).resolve()),
            "terminado": n >= total,
        }
        ruta = Path(self.args.estado_local)
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_suffix(".tmp")
            tmp.write_text(json.dumps(estado), encoding="utf-8")
            os.replace(tmp, ruta)
        except OSError:
            pass  # el panel puede tener el archivo abierto un instante (Windows): se reintenta en la proxima muestra

    def correr(self) -> None:
        self.client.connect(self.args.broker_host, self.args.broker_port, keepalive=30)
        self.client.loop_start()
        time.sleep(0.5)  # que la suscripcion a las respuestas quede activa antes del primer M1

        with open(self.args.trayectoria, newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        print(f"OBU emulada {self.vehiculo_id}: {len(filas)} muestras de {self.args.trayectoria} "
              f"a x{self.args.factor} (R_g={self.p.r_g_m:.0f} m, R_i={self.p.r_i_m:.0f} m)")

        t0_mono = time.monotonic()
        t0_tray = float(filas[0]["t_s"])
        for n, fila in enumerate(filas, 1):
            objetivo = t0_mono + (float(fila["t_s"]) - t0_tray) / self.args.factor
            espera = objetivo - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            # t_OBU (de la muestra al envio del M1, ssec:metricas): se
            # registra ANTES de la decision de geometria, para que
            # scripts/analisis/lazo_emulado.py pueda emparejar esta fila con
            # el M1_tx (o ACTUALIZAR_M1) que dispare, si alguno, por t_tray_s
            # (ver docstring de EVT_MUESTRA en common/events.py). Con el
            # reloj de la propia OBU: no depende de sincronizar relojes.
            self.eventos.log(EVT_MUESTRA, "-", t_tray_s=float(fila["t_s"]))
            for dec in self.seguidor.actualizar(float(fila["lat"]), float(fila["lon"]),
                                                float(fila["rumbo_deg"])):
                if self.id_actual in self.rechazadas and dec.accion in (ACTUALIZAR_M1, EMITIR_M3):
                    if dec.accion == EMITIR_M3:
                        self.id_actual = None
                    continue
                if dec.accion in (EMITIR_M1, ACTUALIZAR_M1):
                    self._m1(dec, fila)
                elif dec.accion == EMITIR_M3:
                    self._m3(dec, fila)
            self._escribir_estado(fila, n, len(filas))

        time.sleep(self.args.espera_final)
        self.client.loop_stop()
        self.client.disconnect()
        c = self.contadores
        print(f"Fin: M1 enviados={c['M1']}, M3 enviados={c['M3']}, M2 recibidos={c['M2']} "
              f"(eventos en {self.eventos.path})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker-host", required=True, help="broker MQTT (IP de la RSU, rsu-01 por Tailscale, o el broker central)")
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--trayectoria", required=True, help="CSV de scripts/trayectorias/generar.py")
    ap.add_argument("--registro", default=str(RAIZ / "config" / "registro_rsu.json"))
    ap.add_argument("--vehiculo-id", default=None, help="seudonimo de sesion (por defecto ses-<aleatorio>)")
    ap.add_argument("--clase-tipo", type=int, default=1,
                    help="clase NTCIP 1211 (1 = emergencia reconocida; otro valor para probar RF-05)")
    ap.add_argument("--factor", type=float, default=1.0, help="velocidad de reproduccion (1 = tiempo real)")
    ap.add_argument("--r-g", type=float, default=ParametrosGeometria.r_g_m, help="radio de la geocerca R_g, m")
    ap.add_argument("--r-i", type=float, default=ParametrosGeometria.r_i_m, help="radio de candidatura R_i, m")
    ap.add_argument("--espera-final", type=float, default=2.0, help="s a esperar M2 pendientes al terminar")
    ap.add_argument("--obu-id", default="obu", help="nodo del registro de eventos (eventos_<obu-id>.csv)")
    ap.add_argument("--estado-local", default=str(RAIZ / "resultados" / "obu_vivo" / "estado.json"),
                    help="JSON local que lee el panel en vivo ('' para no escribirlo)")
    ObuEmulada(ap.parse_args()).correr()


if __name__ == "__main__":
    main()
