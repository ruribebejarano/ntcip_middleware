#!/usr/bin/env python3
"""OBU EMULADA: cliente delgado de la arquitectura centralizada (2026-10-22).

*** La OBU ya NO decide a qué RSU ni a qué acceso dirigirse. *** Solo:

1. Al arrancar, arma la misión (MI) con la clase de vehículo y el destino
   (el último punto de la trayectoria) -- equivalente al botón "Iniciar
   emergencia" + destino de la app real.
2. Mientras la misión está activa, reproduce la trayectoria publicando la
   posición a 1 Hz (MP) -- el servidor calcula la ruta, la lista ordenada
   de RSU/accesos, el ETA a cada una y decide cuándo pedir prioridad
   (servidor/gestor_mision.py). La OBU no conoce el registro de RSU
   (config/registro_rsu.json): ya no lo descarga (ssec:registro).
3. Recibe la ruta (MR) y los cambios de estado (ME) del servidor, los
   imprime y los registra.
4. Al terminar la trayectoria (o con Ctrl+C), desarma la misión (MF).

*** EMULACIÓN CON DATOS FICTICIOS *** La posición, el rumbo y la velocidad
salen de un CSV generado por scripts/trayectorias/generar.py, no de un
receptor GNSS ni de un lector OBD-II (RF-01, RF-02 quedan fuera de esta
emulación). Lo que SÍ es real es todo lo que pasa a partir de la muestra:
los mensajes MI/MP/MF hacia el servidor central y MR/ME que vuelven de él.

Mensajes (tab:mensajes, servidor/main.py), JSON sobre MQTT 5:
  MI -> obu/{obu_id}/mision    {tipo, obu_id, clase, destino:{lat,lon},
                                 origen:{lat,lon}, ts_ms}
  MP -> obu/{obu_id}/posicion  {tipo, obu_id, lat, lon, velocidad_kmh,
                                 rumbo_deg, fuente_velocidad, ts_ms, seq}
  MF -> obu/{obu_id}/mision    {tipo, obu_id, motivo, ts_ms}
  MR <- obu/{obu_id}/ruta      geometría + lista ordenada de RSU/accesos
  ME <- obu/{obu_id}/estado    estado de cada RSU de la ruta, próximo semáforo, conflicto

La posición SÍ viaja ahora en MP (a diferencia del M1 del esquema anterior,
que solo llevaba intersección/acceso): es indispensable para que el
servidor calcule el progreso sobre la ruta y el ETA a cada RSU. Esto es una
desviación deliberada de ssec:minimizacion tal como estaba escrita para el
esquema anterior -- se publica solo con misión activa (de un vehículo
institucional en servicio), nunca en reposo; ver la nueva ssec:conflictos /
ssec:ruta_servidor propuesta en el inventario de redacción para la
justificación completa y la política de retención [DATO: por definir].

Legado (gateway/obu_simulator.py, consola/backend/obu_local.py): esos dos
módulos implementan el esquema ANTERIOR (OBU decide localmente) y no se
tocaron en esta migración más allá de una nota en su docstring -- ver
sección 3.2 de E:\\Tesis\\prompt_arquitectura_centralizada.md.

Uso (broker del servidor central; sin TLS en esta etapa salvo que se
configure mTLS, ver scripts/seguridad/):
    python3 gateway/obu_emulada.py --broker-host 127.0.0.1 \\
        --trayectoria resultados/trayectorias/avenida_ab_s1.csv
    # mas rapido que tiempo real (las muestras salen a 2 Hz):
    python3 gateway/obu_emulada.py --broker-host servidor-central --factor 2 --trayectoria ...
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from common.events import (  # noqa: E402
    EVT_ME_RX,
    EVT_MF_TX,
    EVT_MI_TX,
    EVT_MP_TX,
    EVT_MR_RX,
    EVT_MUESTRA,
    EventLogger,
)


class ObuEmulada:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.obu_id = args.obu_id or f"ses-{uuid.uuid4().hex[:6]}"
        self.eventos = EventLogger(self.obu_id)
        self.seq = 0
        self.ultima_ruta: dict | None = None
        self.ultimo_estado: dict | None = None

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"obu-{self.obu_id}", protocol=mqtt.MQTTv5)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # --- MQTT ----------------------------------------------------------

    def _on_connect(self, client, _u, _f, reason_code, _p=None):
        client.subscribe([(f"obu/{self.obu_id}/ruta", 1), (f"obu/{self.obu_id}/estado", 1)])

    def _on_message(self, _c, _u, msg) -> None:
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        tipo = data.get("tipo")
        if tipo == "MR":
            self.ultima_ruta = data
            print(f"  MR <- ruta de {len(data.get('paradas', []))} RSU, "
                  f"{data.get('longitud_total_m', '?')} m: "
                  f"{[p['rsu_id'] for p in data.get('paradas', [])]}")
            self.eventos.log(EVT_MR_RX, data.get("mision_id", "-"),
                             n_paradas=len(data.get("paradas", [])),
                             longitud_m=data.get("longitud_total_m"))
        elif tipo == "ME":
            anterior = self.ultimo_estado
            self.ultimo_estado = data
            if anterior is None or anterior.get("paradas") != data.get("paradas"):
                proximo = data.get("proximo")
                print(f"  ME <- proximo={proximo and proximo.get('rsu_id')} "
                      f"estado={proximo and proximo.get('estado')} "
                      f"conflicto={data.get('conflicto')}")
            self.eventos.log(EVT_ME_RX, data.get("mision_id", "-"),
                             proximo=data.get("proximo"), conflicto=data.get("conflicto"))

    def _publicar(self, canal: str, cuerpo: dict) -> None:
        self.client.publish(f"obu/{self.obu_id}/{canal}", json.dumps(cuerpo), qos=1)

    # --- MI / MF ---------------------------------------------------------

    def _armar_mision(self, fila0: dict, fila_final: dict) -> None:
        cuerpo = {
            "tipo": "MI", "obu_id": self.obu_id, "clase": self.args.clase_tipo,
            "origen": {"lat": float(fila0["lat"]), "lon": float(fila0["lon"])},
            "destino": {"lat": float(fila_final["lat"]), "lon": float(fila_final["lon"])},
            "ts_ms": int(time.time() * 1000),
        }
        self._publicar("mision", cuerpo)
        print(f"MI -> misión armada (obu_id={self.obu_id}, clase={self.args.clase_tipo}, "
              f"destino=({cuerpo['destino']['lat']:.5f}, {cuerpo['destino']['lon']:.5f}))")
        self.eventos.log(EVT_MI_TX, "-", clase=self.args.clase_tipo,
                         destino_lat=cuerpo["destino"]["lat"], destino_lon=cuerpo["destino"]["lon"])

    def _desarmar_mision(self, motivo: str) -> None:
        cuerpo = {"tipo": "MF", "obu_id": self.obu_id, "motivo": motivo, "ts_ms": int(time.time() * 1000)}
        self._publicar("mision", cuerpo)
        print(f"MF -> fin de misión ({motivo})")
        self.eventos.log(EVT_MF_TX, "-", motivo=motivo)

    # --- MP --------------------------------------------------------------

    def _mp(self, fila: dict) -> None:
        self.seq += 1
        cuerpo = {
            "tipo": "MP", "obu_id": self.obu_id,
            "lat": float(fila["lat"]), "lon": float(fila["lon"]),
            "velocidad_kmh": float(fila["velocidad_kmh"]), "rumbo_deg": float(fila["rumbo_deg"]),
            "fuente_velocidad": "sintetica", "ts_ms": int(time.time() * 1000), "seq": self.seq,
        }
        self._publicar("posicion", cuerpo)
        self.eventos.log(EVT_MP_TX, "-", seq=self.seq, lat=cuerpo["lat"], lon=cuerpo["lon"],
                         velocidad_kmh=cuerpo["velocidad_kmh"], rumbo_deg=cuerpo["rumbo_deg"],
                         t_tray_s=float(fila["t_s"]))

    # --- Lazo ----------------------------------------------------------

    def correr(self) -> None:
        self.client.connect(self.args.broker_host, self.args.broker_port, keepalive=30)
        self.client.loop_start()

        with open(self.args.trayectoria, newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        if not filas:
            raise SystemExit(f"Trayectoria vacía: {self.args.trayectoria}")
        print(f"OBU emulada {self.obu_id}: {len(filas)} muestras de {self.args.trayectoria} "
              f"a x{self.args.factor}")

        time.sleep(0.5)  # que las suscripciones a ruta/estado queden activas antes del MI
        self._armar_mision(filas[0], filas[-1])
        time.sleep(0.3)  # margen para que el servidor publique la MR antes del primer MP

        t0_mono = time.monotonic()
        t0_tray = float(filas[0]["t_s"])
        try:
            for fila in filas:
                objetivo = t0_mono + (float(fila["t_s"]) - t0_tray) / self.args.factor
                espera = objetivo - time.monotonic()
                if espera > 0:
                    time.sleep(espera)
                self.eventos.log(EVT_MUESTRA, "-", t_tray_s=float(fila["t_s"]))
                self._mp(fila)
        except KeyboardInterrupt:
            print("\n(interrumpido por el usuario)")
            self._desarmar_mision("boton")
            self.client.loop_stop()
            self.client.disconnect()
            return

        self._desarmar_mision("destino")
        time.sleep(self.args.espera_final)
        self.client.loop_stop()
        self.client.disconnect()
        print(f"Fin: {self.seq} MP enviados (eventos en {self.eventos.path})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker-host", required=True, help="broker MQTT del servidor central")
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--trayectoria", required=True, help="CSV de scripts/trayectorias/generar.py")
    ap.add_argument("--obu-id", default=None, help="seudonimo de sesion (por defecto ses-<aleatorio>)")
    ap.add_argument("--clase-tipo", type=int, default=1,
                    help="clase NTCIP 1211 (1 = emergencia reconocida; otro valor para probar RF-05)")
    ap.add_argument("--factor", type=float, default=1.0, help="velocidad de reproduccion (1 = tiempo real)")
    ap.add_argument("--espera-final", type=float, default=2.0, help="s a esperar tras el MF antes de cerrar")
    ObuEmulada(ap.parse_args()).correr()


if __name__ == "__main__":
    main()
