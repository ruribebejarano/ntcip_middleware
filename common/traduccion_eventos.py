"""Traduccion de eventos del lazo (common/events.py) a frases en espanol.

Extraido de scripts/demo/linea_tiempo.py (que lo usa igual que antes, solo
importando de aqui) para que consola/ pueda reutilizar la MISMA logica de
traduccion sin duplicarla -- ver docs/CONSOLA.md y el prompt que origino
este modulo. Sin red, sin estado: funcion pura sobre (origen, evento)."""

from __future__ import annotations

FASE = {"verde": "VERDE", "amarillo": "AMBAR", "todo_rojo": "TODO ROJO", "rojo_general": "ROJO"}

MOTIVO_CTRL = {
    "solicitud_prioridad": "por la prioridad",
    "ciclo_normal": "ciclo normal",
    "liberacion_manual": "prioridad liberada",
    "caducidad_prioridad": "fin del tiempo maximo de prioridad",
}

ACCION_RSU = {
    "request_priority": "acepta (clase de emergencia, RF-05) y escribe la prioridad en el controlador (NTCIP 1211)",
    "en_cola_despeje": "acepta, pero el semaforo esta en {fase}: ESPERA el fin del despeje (RF-06)",
    "activar_cola_rf06": "termino el despeje: ahora si escribe la prioridad en el controlador (NTCIP 1211)",
    "clear_priority_m3": "libera la prioridad en el controlador por la cancelacion",
    "rechazada": "RECHAZA la solicitud: {motivo} (RF-05); no toca el controlador",
}


def describir(origen: str, e: dict) -> str | None:
    """Traduce un evento a una frase. None = no se muestra (ruido).

    `origen` es "OBU", "RSU" o "CTRL"; `e` es {"tipo": str, "x": dict}
    (el dict `extra` de common/events.py, ya parseado de extra_json)."""
    t, x = e["tipo"], e["x"]
    if origen == "OBU":
        if t == "M1_tx":
            if x.get("seq") == 1:
                return (f"envia M1 NUEVA SOLICITUD al tema rsu/{x.get('rsu_id')}/solicitudes: "
                        f"interseccion {x.get('interseccion_id')}, acceso {x.get('acceso')}, "
                        f"a {x.get('distancia_m')} m (entro en la geocerca)")
            return f"envia M1 actualizacion #{x.get('seq')} (sigue aproximandose)"
        if t == "M2_rx":
            rtt = x.get("rtt_ms")
            rtt_txt = (f" - ida y vuelta {rtt:.1f} ms" if rtt is not None
                       else " - aviso inmediato de la RSU, sin esperar el siguiente M1")
            motivo = f", motivo {x['motivo']}" if x.get("motivo") else ""
            return (f"recibe M2: solicitud {str(x.get('estado')).upper()} "
                    f"(semaforo en {FASE.get(x.get('fase'), x.get('fase'))}{motivo}){rtt_txt}")
        if t == "M3_tx":
            return f"envia M3 CANCELACION (motivo: {x.get('motivo')})"
    if origen == "RSU":
        if t == "M1_rx":
            if x.get("duplicado"):
                return f"descarta M1 duplicado (seq {x.get('seq')})"
            if x.get("seq") == 1:
                return f"recibe M1 nueva por {x.get('topic')}"
            return None  # las actualizaciones se resumen
        if t == "snmp_set_tx":
            acc = x.get("accion")
            plantilla = ACCION_RSU.get(acc)
            if plantilla is None:
                return f"accion {acc}"
            return plantilla.format(fase=FASE.get(x.get("fase"), x.get("fase")), motivo=x.get("motivo"))
        if t == "M2_tx":
            return None  # se ve del lado de la OBU
        if t == "M3_rx":
            return f"recibe M3 (motivo: {x.get('motivo')})"
        if t == "caducidad":
            return "CADUCIDAD: 3 s sin actualizaciones de la OBU -> libera la prioridad sola (RF-09)"
    if origen == "CTRL" and t == "ctrl_fase_cambio":
        return f"semaforo -> {FASE.get(x.get('fase'), x.get('fase'))} ({MOTIVO_CTRL.get(x.get('motivo'), x.get('motivo'))})"
    return None
