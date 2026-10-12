"""Panel web de supervision del centro de control (Streamlit), pensado
para correr en la laptop. Lee NTCIP 1202/1211 reales de la RSU por
SNMPv3, reutilizando centro_control/software_gestion.py (sin duplicar su
logica de transporte) -- ver snmp_helpers.py. Las credenciales SNMP salen
de centro_control/panel/.env (NO estan en el codigo; ver config.py y
.env.example). No reemplaza software_gestion.py: es una vista adicional,
mas visual, pensada para una demo en vivo.

Correr con:
    cd E:\\Tesis\\ntcip_middleware
    .venv\\Scripts\\streamlit run centro_control/panel/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from centro_control.panel import config, demo_acciones, eventos_panel, snmp_helpers  # noqa: E402

st.set_page_config(page_title="Centro de control -- Panel de supervision", layout="wide")

# --- Estilos del semaforo (HTML/CSS embebido -- Streamlit no trae un
# widget de semaforo; mas simple que una libreria externa para 3 luces). ---
_CSS_SEMAFORO = """
<style>
.semaforo { display:flex; flex-direction:column; gap:10px; align-items:center;
            background:#1c1c1c; padding:18px; border-radius:14px; width:90px; }
.luz { width:54px; height:54px; border-radius:50%; background:#2a2a2a;
       border:3px solid #111; transition: all 0.15s ease; }
.luz.roja.on   { background:#e63946; box-shadow:0 0 22px 6px #e63946aa; }
.luz.amarilla.on { background:#f4c430; box-shadow:0 0 22px 6px #f4c430aa; }
.luz.verde.on  { background:#2ecc71; box-shadow:0 0 22px 6px #2ecc71aa; }
</style>
"""


def _html_semaforo(estado: dict) -> str:
    def clase(color: str, encendida: bool) -> str:
        return f"luz {color}" + (" on" if encendida else "")

    return (
        _CSS_SEMAFORO
        + '<div class="semaforo">'
        + f'<div class="{clase("roja", estado["red"])}"></div>'
        + f'<div class="{clase("amarilla", estado["yellow"])}"></div>'
        + f'<div class="{clase("verde", estado["green"])}"></div>'
        + "</div>"
    )


st.title("Centro de control -- Panel de supervision")
st.caption(
    f"RSU: {config.SNMP_HOST}:{config.SNMP_PORT}  ·  "
    f"Usuario SNMPv3: {config.SNMP_USER}  ·  "
    + ("Credenciales desde .env" if config.ENV_ENCONTRADO else
       "⚠️ .env no encontrado -- usando valores de laboratorio por defecto, ver .env.example")
)

col_semaforo, col_tabla = st.columns([1, 3])

with col_semaforo:
    st.subheader("Semaforo (grupo 1, fase 1)")

    @st.fragment(run_every="0.5s")
    def _fragmento_semaforo():
        estado = snmp_helpers.leer_semaforo()
        st.markdown(_html_semaforo(estado), unsafe_allow_html=True)
        if estado["error"]:
            st.error(f"Error SNMP: {estado['error']}")
        else:
            st.caption("phaseStatusGroupReds/Yellows/Greens -- refresco cada 0.5s")

    _fragmento_semaforo()

with col_tabla:
    st.subheader("priorityRequestTable (NTCIP 1211)")
    st.caption(
        "Refresco cada 2s (no 0.5s): un WALK completo de las 100 celdas mide "
        "~1s contra la Pi del banco -- ver snmp_helpers.py."
    )

    @st.fragment(run_every="2s")
    def _fragmento_tabla():
        filas = snmp_helpers.leer_priority_request_table()
        filas_no_vacias = [f for f in filas if f.get("priorityRequestStatusInPRS", "1") != "1"]
        if not filas_no_vacias:
            st.info("Las 10 filas estan en idleNotValid (ninguna solicitud registrada).")
        tabla = [
            {
                "Fila": f["fila"],
                "ID": f.get("priorityRequestID", "?"),
                "Vehiculo": f.get("priorityRequestVehicleID", "?"),
                "Clase": f.get("priorityRequestVehicleClassType", "?"),
                "Estado": f["estado_nombre"],
                "T. servicio deseado (s)": f.get("priorityRequestTimeOfServiceDesired", "?"),
            }
            for f in filas
        ]
        st.dataframe(tabla, hide_index=True, width="stretch")

    _fragmento_tabla()

st.divider()

# --- Estado del banco ---
st.subheader("Estado del banco de pruebas")
if "estado_banco" not in st.session_state:
    st.session_state.estado_banco = None
if st.button("🔄 Verificar estado del banco (check_pi.sh + pi.sh status/clock)"):
    with st.spinner("Consultando la Pi por SSH..."):
        ok, texto = demo_acciones.estado_del_banco()
        st.session_state.estado_banco = (ok, texto)
if st.session_state.estado_banco is not None:
    ok, texto = st.session_state.estado_banco
    (st.success if ok else st.warning)("Banco verificado (ver detalle abajo)")
    with st.expander("Detalle", expanded=False):
        st.code(texto)

st.divider()

# --- Linea de tiempo de eventos + latencia por tramo ---
st.subheader("Linea de tiempo de eventos y latencia por tramo")
col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("⬇️ Traer eventos de la Pi (pi.sh fetch)"):
        with st.spinner("Copiando resultados/ de la Pi..."):
            ok, salida = eventos_panel.traer_eventos_de_la_pi()
            if ok:
                st.success("Eventos traidos.")
            else:
                st.warning(f"pi.sh fetch no termino bien: {salida[:300]}")

datos_eventos = eventos_panel.linea_de_tiempo_y_latencias()
if datos_eventos["aviso"]:
    st.info(datos_eventos["aviso"])
else:
    st.caption(f"{datos_eventos['num_archivos']} archivo(s) eventos_*.csv combinados "
               f"(resultados/panel_vivo/, ver eventos_panel.py)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ultimos eventos** (mas reciente primero)")
        st.dataframe(
            [
                {
                    "nodo": e["nodo"], "evento": e["tipo_evento"],
                    "id_solicitud": e["id_solicitud"], "extra": str(e["extra"]),
                }
                for e in datos_eventos["eventos_recientes"]
            ],
            hide_index=True, width="stretch", height=320,
        )
    with c2:
        st.markdown(
            "**Latencia aproximada por tramo** (L = t_V2I + t_RSU + t_NTCIP, "
            "cota inferior de RNF-01 -- ver scripts/analisis/latencia_tramos.py)"
        )
        if datos_eventos["latencias"]:
            st.dataframe(
                [
                    {
                        "id_solicitud": f["id_solicitud"],
                        "t_V2I (ms)": round(f["t_V2I_aprox_ms"], 2),
                        "t_RSU (ms)": round(f["t_RSU_aprox_ms"], 2),
                        "t_NTCIP (ms)": round(f["t_NTCIP_aprox_ms"], 2),
                        "L_aprox (ms)": round(f["L_aprox_ms"], 2),
                    }
                    for f in datos_eventos["latencias"]
                ],
                hide_index=True, width="stretch", height=320,
            )
        else:
            st.info("Ninguna solicitud tiene los 4 eventos completos (M1_tx, M1_rx, "
                    "snmp_set_tx, ctrl_fase_cambio) todavia.")

st.divider()

# --- Botones de casos de prueba (reimplementan pasos de demo_asesor.sh) ---
st.subheader("Casos de prueba (reimplementados de scripts/demo_asesor.sh)")
st.caption(
    "No ejecutan demo_asesor.sh directamente (es un script interactivo pensado "
    "para la demo en vivo, no para invocarse paso a paso) -- hacen la misma "
    "accion SNMP de punta a punta en Python. Ver demo_acciones.py."
)

for id_accion, etiqueta, funcion, requerimiento in demo_acciones.ACCIONES:
    clave_resultado = f"resultado_{id_accion}"
    with st.expander(f"{etiqueta}  ·  {requerimiento}"):
        if st.button("▶ Ejecutar", key=f"boton_{id_accion}"):
            with st.spinner("Ejecutando..."):
                ok, texto = funcion()
                st.session_state[clave_resultado] = (ok, texto)
        if clave_resultado in st.session_state:
            ok, texto = st.session_state[clave_resultado]
            (st.success if ok else st.error)("OK" if ok else "Fallo/inesperado")
            st.code(texto)
