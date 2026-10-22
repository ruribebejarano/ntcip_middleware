"""*** LEGADO (pre-arquitectura centralizada, 2026-10-22) ***
Esta pagina depende de resultados/obu_vivo/estado.json, que
gateway/obu_emulada.py YA NO escribe (la OBU paso a ser un cliente delgado;
la posicion viaja en MP hacia el servidor, que calcula la asignacion de
RSU/acceso -- ver servidor/gestor_mision.py). Queda sin alimentacion hasta
que se adapte para mostrar la MR/ME del servidor en su lugar (pendiente,
ver docs/bitacora/2026-10-22_arquitectura-centralizada.md). No se borra:
documenta como se veia el panel con el esquema anterior (E2+E4).

Pagina "Lazo V2I en vivo" del panel: el lazo de priorizacion completo en
una sola pantalla, para la demo con la OBU emulada (gateway/obu_emulada.py).

Que muestra y de donde sale cada cosa:

- Mapa: las intersecciones del registro (config/registro_rsu.json) con su
  radio de candidatura R_i y su geocerca R_g, la trayectoria y el vehiculo.
  La posicion del vehiculo se lee del archivo LOCAL que escribe la OBU
  emulada (resultados/obu_vivo/estado.json): NO viaja por MQTT, porque la
  tesis exige que la posicion no salga de la OBU (ssec:minimizacion).
- Semaforo: estado real de la fase leido por SNMPv3 (NTCIP 1202), igual que
  la pagina principal del panel.
- Mensajes: lo que realmente pasa por el broker (M1, M2, M3), escuchando
  rsu/# y veh/# como un suscriptor mas.

Se abre desde la barra lateral del panel:
    .venv\\Scripts\\streamlit run centro_control/panel/app.py
Broker: MQTT_BROKER_HOST en centro_control/panel/.env (por defecto 127.0.0.1).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import pydeck as pdk
import streamlit as st

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
from centro_control.panel import config, snmp_helpers  # noqa: E402
from gateway.geometria import cargar_registro, desplazar  # noqa: E402

BROKER = os.environ.get("MQTT_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
ESTADO_OBU = Path(os.environ.get("OBU_ESTADO_LOCAL", RAIZ / "resultados" / "obu_vivo" / "estado.json"))
REGISTRO = RAIZ / "config" / "registro_rsu.json"

st.set_page_config(page_title="Lazo V2I en vivo", layout="wide")

# Colores (RGB) -- el estado de la solicitud siempre va tambien escrito.
COLOR_ESTADO = {
    None: [120, 120, 120], "recibida": [235, 104, 52], "concedida": [12, 163, 12],
    "rechazada": [208, 59, 59], "cancelada": [120, 120, 120],
}
NOMBRE_ACCESO = {"N": "Norte", "S": "Sur", "E": "Este", "O": "Oeste"}
ICONO_TIPO = {"M1": "🔵 M1", "M2": "🟢 M2", "M3": "🟠 M3"}


# ---------------------------------------------------------------------------
# Suscriptor MQTT (uno por proceso de Streamlit, compartido entre recargas)
# ---------------------------------------------------------------------------


class Escucha:
    def __init__(self, host: str, port: int) -> None:
        self.mensajes: deque = deque(maxlen=300)
        self.lock = threading.Lock()
        self.conectado = False
        self.error: str | None = None
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"panel-vivo-{os.getpid()}",
                                   protocol=mqtt.MQTTv5)
        self.cliente.on_connect = self._on_connect
        self.cliente.on_disconnect = self._on_disconnect
        self.cliente.on_message = self._on_message
        try:
            self.cliente.connect(host, port, keepalive=30)
            self.cliente.loop_start()
        except OSError as exc:
            self.error = f"No se pudo conectar al broker {host}:{port}: {exc}"

    def _on_connect(self, client, _u, _f, reason_code, _p=None):
        self.conectado = not reason_code.is_failure
        client.subscribe([("rsu/#", 0), ("veh/#", 0)])

    def _on_disconnect(self, *_a, **_k):
        self.conectado = False

    def _on_message(self, _c, _u, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {"crudo": msg.payload[:80].decode("utf-8", errors="replace")}
        with self.lock:
            self.mensajes.appendleft({"t": time.time(), "tema": msg.topic, "datos": data})

    def copia(self) -> list[dict]:
        with self.lock:
            return list(self.mensajes)

    def limpiar(self) -> None:
        with self.lock:
            self.mensajes.clear()


@st.cache_resource
def escucha() -> Escucha:
    return Escucha(BROKER, BROKER_PORT)


@st.cache_data
def registro():
    return cargar_registro(REGISTRO)


@st.cache_data
def trayectoria(ruta: str) -> list[list[float]]:
    import csv
    try:
        with open(ruta, newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        col_lat = "lat_real" if filas and "lat_real" in filas[0] else "lat"
        col_lon = "lon_real" if filas and "lon_real" in filas[0] else "lon"
        return [[float(f[col_lon]), float(f[col_lat])] for f in filas]
    except OSError:
        return []


def leer_estado_obu() -> dict | None:
    try:
        datos = json.loads(ESTADO_OBU.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    datos["antiguedad_s"] = time.time() - datos.get("ts", 0)
    return datos


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------


def capas(obu: dict | None) -> list[pdk.Layer]:
    reg = registro()
    asignada = (obu or {}).get("asignacion") or {}
    r_g = (obu or {}).get("r_g_m", 150.0)
    r_i = (obu or {}).get("r_i_m", 300.0)
    estado_m2 = ((obu or {}).get("ultimo_m2") or {}).get("estado") if (obu or {}).get("solicitud") else None

    inter = [{"lon": i.lon, "lat": i.lat, "nombre": f"RSU {i.rsu_id} · {i.interseccion_id}",
              "activa": i.interseccion_id == asignada.get("interseccion_id")} for i in reg]
    accesos = []
    for i in reg:
        for a in i.accesos:
            # Linea del acceso: desde 220 m aguas arriba hasta el centro, en el sentido de llegada
            lat0, lon0 = desplazar(i.lat, i.lon, (a.rumbo_llegada_deg + 180) % 360, 220)
            lat_t, lon_t = desplazar(i.lat, i.lon, (a.rumbo_llegada_deg + 180) % 360, 245)
            activo = i.interseccion_id == asignada.get("interseccion_id") and a.acceso_id == asignada.get("acceso")
            accesos.append({"ini": [lon0, lat0], "fin": [i.lon, i.lat], "activo": activo,
                            "pos_txt": [lon_t, lat_t],
                            "txt": NOMBRE_ACCESO.get(a.acceso_id, a.acceso_id)})

    lista = [
        pdk.Layer("ScatterplotLayer", inter, get_position="[lon, lat]", get_radius=r_i, filled=False,
                  stroked=True, get_line_color=[82, 81, 78, 120], line_width_min_pixels=1),
        pdk.Layer("ScatterplotLayer", inter, get_position="[lon, lat]", get_radius=r_g, stroked=True,
                  get_fill_color="activa ? [42, 120, 214, 70] : [42, 120, 214, 25]",
                  get_line_color=[42, 120, 214, 200], line_width_min_pixels=2),
        pdk.Layer("LineLayer", accesos, get_source_position="ini", get_target_position="fin",
                  get_color="activo ? [235, 104, 52, 230] : [82, 81, 78, 90]",
                  get_width="activo ? 5 : 2"),
        pdk.Layer("TextLayer", accesos, get_position="pos_txt", get_text="txt", get_size=13,
                  get_color=[82, 81, 78, 220]),
        pdk.Layer("ScatterplotLayer", inter, get_position="[lon, lat]", get_radius=7,
                  get_fill_color=[11, 11, 11, 230]),
        pdk.Layer("TextLayer", inter, get_position="[lon, lat]", get_text="nombre", get_size=14,
                  get_color=[11, 11, 11, 255], get_pixel_offset=[0, -22]),
    ]
    if obu:
        camino = trayectoria(obu.get("trayectoria", ""))
        if camino:
            lista.insert(0, pdk.Layer("PathLayer", [{"path": camino}], get_path="path",
                                      get_color=[82, 81, 78, 110], width_min_pixels=3))
        color = COLOR_ESTADO.get(estado_m2, COLOR_ESTADO[None])
        vehiculo = [{"lon": obu["lon"], "lat": obu["lat"]}]
        lista += [
            pdk.Layer("ScatterplotLayer", vehiculo, get_position="[lon, lat]", get_radius=14,
                      get_fill_color=color + [255], stroked=True, get_line_color=[252, 252, 251],
                      line_width_min_pixels=2),
        ]
    return lista


def vista() -> pdk.ViewState:
    reg = registro()
    return pdk.ViewState(latitude=sum(i.lat for i in reg) / len(reg),
                         longitude=sum(i.lon for i in reg) / len(reg), zoom=14.9, pitch=0)


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------

st.title("Lazo V2I en vivo")
st.caption(f"Broker {BROKER}:{BROKER_PORT} (temas rsu/# y veh/#)  ·  RSU por SNMPv3 en "
           f"{config.SNMP_HOST}:{config.SNMP_PORT}  ·  posición del vehículo: archivo local de la OBU "
           f"(no viaja por MQTT)")

esc = escucha()
if esc.error:
    st.error(esc.error)

col_mapa, col_lado = st.columns([3, 1])

with col_mapa:
    @st.fragment(run_every="1s")
    def _mapa():
        obu = leer_estado_obu()
        st.pydeck_chart(pdk.Deck(layers=capas(obu), initial_view_state=vista(), map_style=None),
                        height=520)
        if obu is None:
            st.info("Esperando a la OBU emulada: lanzar gateway/obu_emulada.py en otra ventana.")
        elif obu["antiguedad_s"] > 5 and not obu.get("terminado"):
            st.warning(f"La OBU no actualiza su estado hace {obu['antiguedad_s']:.0f} s.")
        st.caption("Círculo azul: geocerca R_g (emisión de M1). Anillo gris: radio de candidatura R_i. "
                   "Línea naranja: acceso asignado. Punto del vehículo: gris sin solicitud, naranja "
                   "recibida, verde concedida, rojo rechazada.")
    _mapa()

with col_lado:
    st.subheader("Semáforo RSU 1 (NTCIP 1202)")

    @st.fragment(run_every="0.5s")
    def _semaforo():
        e = snmp_helpers.leer_semaforo()
        if e["error"]:
            st.error(f"SNMP: {e['error']}")
            return
        luces = [("rojo", e["red"], "#d03b3b"), ("ámbar", e["yellow"], "#fab219"), ("verde", e["green"], "#0ca30c")]
        html = '<div style="display:flex;gap:10px;align-items:center;background:#1c1c1c;padding:10px 14px;border-radius:12px;width:fit-content">'
        for nombre, on, color in luces:
            fondo = color if on else "#2a2a2a"
            sombra = f"box-shadow:0 0 16px 4px {color}aa;" if on else ""
            html += f'<div title="{nombre}" style="width:34px;height:34px;border-radius:50%;background:{fondo};{sombra}"></div>'
        html += "</div>"
        actual = next((n for n, on, _ in luces if on), "?")
        st.markdown(html, unsafe_allow_html=True)
        st.caption(f"Fase actual: **{actual}** (refresco 0,5 s)")
    _semaforo()

    st.subheader("OBU")

    @st.fragment(run_every="1s")
    def _obu():
        obu = leer_estado_obu()
        if obu is None:
            st.caption("Sin datos todavía.")
            return
        a = obu.get("asignacion")
        m2 = obu.get("ultimo_m2") or {}
        st.caption(f"{obu['vehiculo_id']} · {Path(obu['trayectoria']).name} · "
                   f"muestra {obu['muestra']}/{obu['muestras']}")
        c1, c2 = st.columns(2)
        c1.metric("Velocidad (km/h)", f"{obu['velocidad_kmh']:.0f}")
        c2.metric("Distancia (m)", f"{a['distancia_m']:.0f}" if a else "—")
        st.markdown(f"**Intersección / acceso:** {a['interseccion_id'] + ' / ' + a['acceso'] if a else 'ninguno'}")
        if obu.get("solicitud"):
            estado = m2.get("estado") if m2.get("id_solicitud") == obu["solicitud"] else "enviada"
            st.markdown(f"**Solicitud:** `{obu['solicitud']}` · seq {obu['seq']}")
            st.markdown(f"**Estado (M2):** {estado}" + (f" · fase {m2.get('fase')}" if m2.get("fase") else ""))
            if m2.get("rtt_ms") is not None:
                st.markdown(f"**RTT M1/M2:** {m2['rtt_ms']:.1f} ms")
        else:
            st.markdown("**Solicitud:** ninguna vigente")
        if obu.get("terminado"):
            st.success("Recorrido terminado.")
    _obu()

st.divider()
st.subheader("Mensajes en el broker")

c_a, c_b = st.columns([1, 5])
with c_a:
    if st.button("Limpiar lista"):
        esc.limpiar()


@st.fragment(run_every="1s")
def _mensajes():
    msgs = esc.copia()
    cuenta = {"M1": 0, "M2": 0, "M3": 0}
    filas = []
    for m in msgs:
        d = m["datos"]
        tipo = d.get("tipo", "legado" if m["tema"] == "rsu/v2i/solicitud_prioridad" else "?")
        if tipo in cuenta:
            cuenta[tipo] += 1
        filas.append({
            "Hora": datetime.fromtimestamp(m["t"]).strftime("%H:%M:%S.%f")[:-3],
            "Tipo": ICONO_TIPO.get(tipo, tipo),
            "Tema": m["tema"],
            "Solicitud": str(d.get("id_solicitud", ""))[-8:],
            "seq": d.get("seq", d.get("seq_ref", "")),
            "Detalle": (d.get("estado", "") + (f" · fase {d['fase']}" if d.get("fase") else "")) if tipo == "M2"
                       else (f"{d.get('interseccion_id', '')}/{d.get('acceso', '')} · {d.get('velocidad_kmh', '')} km/h"
                             if tipo == "M1" else d.get("motivo", "")),
        })
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Broker", "conectado" if esc.conectado else "desconectado")
    k2.metric("M1 vistos", cuenta["M1"])
    k3.metric("M2 vistos", cuenta["M2"])
    k4.metric("M3 vistos", cuenta["M3"])
    if filas:
        st.dataframe(filas[:60], hide_index=True, width="stretch", height=360)
    else:
        st.info("Todavía no pasa ningún mensaje por rsu/# ni veh/#.")


_mensajes()
