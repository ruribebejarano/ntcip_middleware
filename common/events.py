"""Registro de eventos del lazo de priorizacion (RF-10 en main.tex, antes
RF-13: la numeracion cambio cuando se fusiono la validacion del canal V2I
con la del lazo completo en un unico objetivo OE5 -- ver la nota de
desalineacion en CLAUDE.md).

Cada evento es una fila CSV con:

    ts_ns        -- marca de tiempo en epoch y nanosegundos (time.time_ns()),
                    un solo entero: epoch da la referencia, ns la resolucion.
    nodo         -- que proceso lo registro: "obu", "rsu_<id>" o "ctrl_<id>"
                    (ver RSU_ID en agent/rsu_middleware.py y
                    controller/controller_emulator.py para el banco con mas
                    de una RSU).
    tipo_evento  -- uno de EVT_* abajo (lista abierta, no es un enum cerrado:
                    agregar las que hagan falta, documentandolas aqui).
    id_solicitud -- identificador de solicitud de M1 (Tabla tab:mensajes de
                    main.tex), que permite cruzar eventos entre procesos y
                    maquinas distintas. Para eventos sin una solicitud de
                    origen (p. ej. un ciclo normal de fases sin prioridad
                    activa), se usa "-".
    extra_json   -- campos adicionales especificos del evento, serializados
                    como JSON en una sola columna (para no tener que fijar
                    de antemano un esquema de columnas distinto por tipo de
                    evento).

Cada proceso escribe su PROPIO archivo (eventos_<nodo>.csv): no hay un
archivo compartido entre maquinas en tiempo real. scripts/analisis/
latencia_tramos.py es quien despues lee los archivos de las tres maquinas
(copiados a la misma carpeta, p. ej. con scripts/pi.sh fetch) y cruza por
id_solicitud.

Seguro para hilos dentro de un mismo proceso (un lock por EventLogger).
NO esta pensado para que varios PROCESOS distintos escriban el mismo
archivo en paralelo (p. ej. varias OBU simuladas a la vez): en ese caso,
cada proceso debe usar un nodo distinto (ver obu_id en
gateway/obu_simulator.py) para no compartir archivo.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

FIELDNAMES = ("ts_ns", "nodo", "tipo_evento", "id_solicitud", "extra_json")

# Directorio por defecto, relativo al directorio de trabajo del proceso
# (en agent/ y controller/ eso es la raiz del repo, por WorkingDirectory=
# en deploy/systemd/*.service; en la laptop, la raiz del repo si se corre
# "python gateway/obu_simulator.py" desde ahi). Sobreescribible con la
# variable de entorno RSU_EVENTOS_DIR o con el parametro directorio=.
DEFAULT_DIR = Path(os.environ.get("RSU_EVENTOS_DIR", "resultados/eventos"))

# Tipos de evento usados hoy por agent/, controller/ y gateway/. Lista
# abierta: agregar los que hagan falta (p. ej. M3_rx, M4_tx/M4_rx cuando se
# implemente el enlace I2I -- ver la nota de desalineacion en CLAUDE.md,
# ese enlace no es un objetivo especifico vigente de la tesis) y
# documentarlos aqui.
EVT_M1_TX = "M1_tx"              # OBU publica la solicitud de prioridad
EVT_M1_RX = "M1_rx"              # RSU recibe la solicitud por MQTT
EVT_SNMP_SET_TX = "snmp_set_tx"  # RSU traduce y escribe hacia el controlador
EVT_CTRL_FASE_CAMBIO = "ctrl_fase_cambio"  # el controlador cambia de fase
EVT_M2_TX = "M2_tx"              # RSU publica el estado de la solicitud (M2, tema de respuesta de la OBU)
EVT_M2_RX = "M2_rx"              # OBU recibe M2; extra: rtt_ms del par M1/M2 (reloj de la OBU)
EVT_M3_TX = "M3_tx"              # OBU cancela la solicitud (RF-04); extra: motivo
EVT_M3_RX = "M3_rx"              # RSU recibe la cancelacion
EVT_CADUCIDAD = "caducidad"      # la RSU cancela por caducidad sin M3 (RF-09)
EVT_MUESTRA = "muestra"          # OBU lee una fila de la trayectoria, antes de
                                  # decidir geometria (gateway/obu_emulada.py).
                                  # id_solicitud = "-" (no hay una activa
                                  # necesariamente); extra: t_tray_s, que es la
                                  # clave para emparejar esta fila con el M1_tx
                                  # (o ACTUALIZAR_M1) que haya disparado, si
                                  # alguno. Permite medir t_OBU = M1_tx - muestra
                                  # con el reloj de la propia OBU (docs/MEDICION_LATENCIA.md).
EVT_BROKER_RX = "broker_rx"      # scripts/testigo_broker.py: un suscriptor mas
                                  # corriendo en la MISMA maquina que el broker,
                                  # registra la llegada de cada M1/M2/M3 con el
                                  # reloj del broker. extra: tipo (M1/M2/M3),
                                  # seq (o seq_ref para M2), topic. Permite
                                  # estimar t_up y t_down (docs/MEDICION_LATENCIA.md);
                                  # es una COTA SUPERIOR del tiempo real del
                                  # broker, porque el propio testigo agrega
                                  # procesamiento (deserializar, loguear).


class EventLogger:
    """Logger de eventos CSV de un nodo, agrega filas, nunca sobrescribe."""

    def __init__(self, nodo: str, directorio: Optional[Path] = None) -> None:
        self.nodo = nodo
        self.directorio = Path(directorio) if directorio is not None else DEFAULT_DIR
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.path = self.directorio / f"eventos_{nodo}.csv"
        self._lock = threading.Lock()
        self._ensure_header()

    def _ensure_header(self) -> None:
        es_nuevo = not self.path.exists() or self.path.stat().st_size == 0
        if es_nuevo:
            with self.path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(FIELDNAMES)

    def log(self, tipo_evento: str, id_solicitud: str, **extra: Any) -> None:
        """Registra un evento. Los kwargs en `extra` se guardan como JSON."""
        fila = (
            time.time_ns(),
            self.nodo,
            tipo_evento,
            id_solicitud or "-",
            json.dumps(extra, ensure_ascii=False, separators=(",", ":")),
        )
        with self._lock:
            with self.path.open("a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(fila)


def iter_eventos(directorio: Path | str) -> Iterator[dict]:
    """Lee todos los eventos_*.csv de `directorio` y los produce como dicts,
    con extra_json ya parseado a dict y ts_ns como int. Usado por
    scripts/analisis/latencia_tramos.py; no requiere que los archivos vengan
    de la misma maquina, solo que esten en la misma carpeta (ver
    scripts/pi.sh fetch)."""
    directorio = Path(directorio)
    for ruta in sorted(directorio.glob("eventos_*.csv")):
        with ruta.open("r", newline="", encoding="utf-8") as fh:
            for fila in csv.DictReader(fh):
                try:
                    extra = json.loads(fila["extra_json"]) if fila["extra_json"] else {}
                except json.JSONDecodeError:
                    extra = {}
                yield {
                    "ts_ns": int(fila["ts_ns"]),
                    "nodo": fila["nodo"],
                    "tipo_evento": fila["tipo_evento"],
                    "id_solicitud": fila["id_solicitud"],
                    "extra": extra,
                    "archivo": ruta.name,
                }
