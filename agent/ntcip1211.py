"""NTCIP 1211 v02 -- Priority Request Server (PRS), subconjunto minimo.

*** BORRADOR SIN VERIFICAR CONTRA LA NORMA OFICIAL ***
No existe, al momento de escribir este modulo (2026-10-11), una copia del
documento oficial NTCIP 1211 v02 (2014) disponible -- se solicito a
ntcip@nema.org (ver E:\\Tesis\\redaccion\\correo_nema.md). El orden y tamano
de los campos de abajo salen de
E:\\Tesis\\datasheets\\ntcip1211_borrador\\NTCIP1211v02_PRS-MIB1_BORRADOR_SIN_VERIFICAR.mib
(extraido automaticamente de un .docx del borrador v02A-SE03, 2017).
Pendiente confirmar contra la version publicada v02 (2014) cuando este
disponible (el estudiante la va a descargar de NEMA y dejarla en
E:\\Tesis\\datasheets).

Codificacion de prgPriorityRequestAbsolute (OCTET STRING, SIZE(29)):
para un SEQUENCE OER (ITU-T X.696) sin componentes OPTIONAL/DEFAULT ni
extensiones, no hay preambulo: es la concatenacion de cada campo en su
propia codificacion OER, en el orden declarado por el borrador. Un
INTEGER de rango acotado se codifica en el numero minimo de octetos sin
signo que representan ese rango, big-endian (el byte de mayor peso
primero); un OCTET STRING de tamano fijo son sus bytes tal cual, sin
prefijo de longitud (el tamano ya esta fijado por el tipo). Con eso:

    priorityRequestID                        INTEGER (1..255)         1 byte
    priorityRequestVehicleID                 OCTET STRING (17)       17 bytes
    priorityRequestVehicleClassType          INTEGER (1..10)          1 byte
    priorityRequestVehicleClassLevel         INTEGER (1..10)          1 byte
    priorityRequestServiceStrategyNumber     INTEGER (1..255)         1 byte
    priorityRequestTimeOfServiceDesired      INTEGER (1..65535)       2 bytes
    priorityRequestTimeOfEstimatedDeparture  INTEGER (1..65535)       2 bytes
    priorityRequestTimeOfRequest             INTEGER (0..4294967295)  4 bytes
                                                                 TOTAL: 29 bytes

coincide exactamente con el SIZE(29) que exige la norma para este objeto.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Codec OER de prgPriorityRequestAbsolute
# ---------------------------------------------------------------------------

_FORMATO = ">B17sBBBHHI"
TAMANO_BYTES = struct.calcsize(_FORMATO)
assert TAMANO_BYTES == 29, f"el formato debe codificar 29 bytes, da {TAMANO_BYTES}"


class ErrorLongitud(ValueError):
    """La cadena no mide exactamente 29 bytes."""


class ErrorRangoCampo(ValueError):
    """Algun campo esta fuera del rango que exige la norma."""


@dataclass
class SolicitudPrioridadAbsoluta:
    """Los 8 campos de prgPriorityRequestAbsolute, ya decodificados."""

    id_solicitud: int  # 1..255
    vehiculo_id: bytes  # hasta 17 bytes; se rellena con \x00 a la derecha
    clase_tipo: int  # 1..10 (1 = mayor precedencia)
    clase_nivel: int  # 1..10 (1 = mayor precedencia)
    estrategia: int  # 1..255
    t_servicio_deseado: int  # 1..65535, segundos relativos
    t_salida_estimada: int  # 1..65535, segundos relativos
    t_solicitud: int  # 0..4294967295, epoch segundos (0 = no se usa)

    def validar(self) -> None:
        campos = (
            ("priorityRequestID", self.id_solicitud, 1, 255),
            ("priorityRequestVehicleClassType", self.clase_tipo, 1, 10),
            ("priorityRequestVehicleClassLevel", self.clase_nivel, 1, 10),
            ("priorityRequestServiceStrategyNumber", self.estrategia, 1, 255),
            ("priorityRequestTimeOfServiceDesired", self.t_servicio_deseado, 1, 65535),
            ("priorityRequestTimeOfEstimatedDeparture", self.t_salida_estimada, 1, 65535),
            ("priorityRequestTimeOfRequest", self.t_solicitud, 0, 4294967295),
        )
        for nombre, valor, minimo, maximo in campos:
            if not (minimo <= valor <= maximo):
                raise ErrorRangoCampo(
                    f"{nombre}={valor} fuera de rango [{minimo}, {maximo}]"
                )
        if len(self.vehiculo_id) > 17:
            raise ErrorRangoCampo(
                f"priorityRequestVehicleID mide {len(self.vehiculo_id)} bytes, maximo 17"
            )


def codificar(s: SolicitudPrioridadAbsoluta) -> bytes:
    """SolicitudPrioridadAbsoluta -> 29 bytes OER (prgPriorityRequestAbsolute)."""
    s.validar()
    vehiculo_id = s.vehiculo_id.ljust(17, b"\x00")
    return struct.pack(
        _FORMATO,
        s.id_solicitud,
        vehiculo_id,
        s.clase_tipo,
        s.clase_nivel,
        s.estrategia,
        s.t_servicio_deseado,
        s.t_salida_estimada,
        s.t_solicitud,
    )


def decodificar(datos: bytes) -> SolicitudPrioridadAbsoluta:
    """29 bytes OER -> SolicitudPrioridadAbsoluta. Rechaza con ErrorLongitud
    cualquier cadena que no mida exactamente 29 bytes (prgPriorityRequestAbsolute
    es SIZE(29) fijo, sin campos opcionales)."""
    if len(datos) != TAMANO_BYTES:
        raise ErrorLongitud(
            f"prgPriorityRequestAbsolute debe medir exactamente {TAMANO_BYTES} bytes, "
            f"se recibieron {len(datos)}"
        )
    (id_solicitud, vehiculo_id, clase_tipo, clase_nivel, estrategia,
     t_servicio_deseado, t_salida_estimada, t_solicitud) = struct.unpack(_FORMATO, datos)
    s = SolicitudPrioridadAbsoluta(
        id_solicitud=id_solicitud,
        vehiculo_id=vehiculo_id.rstrip(b"\x00"),
        clase_tipo=clase_tipo,
        clase_nivel=clase_nivel,
        estrategia=estrategia,
        t_servicio_deseado=t_servicio_deseado,
        t_salida_estimada=t_salida_estimada,
        t_solicitud=t_solicitud,
    )
    s.validar()
    return s


# ---------------------------------------------------------------------------
# priorityRequestStatusInPRS (enum real de la norma, PRS-MIB1 clausula 9)
# ---------------------------------------------------------------------------

IDLE_NOT_VALID = 1
READY_QUEUED = 2
READY_OVERRIDDEN = 3
ACTIVE_PROCESSING = 4
ACTIVE_CANCEL = 5
ACTIVE_OVERRIDE = 6
ACTIVE_NOT_OVERRIDDEN = 7
CLOSED_CANCELED = 8
RESERVICE_ERROR = 9
CLOSED_TIME_TO_LIVE_ERROR = 10
CLOSED_TIMER_ERROR = 11
CLOSED_STRATEGY_ERROR = 12
CLOSED_COMPLETED = 13
ACTIVE_ADJUST_NOT_NEEDED = 14
CLOSED_FLASH = 15

# RF-05: clases de vehiculo reconocidas como de emergencia. NTCIP define
# priorityRequestVehicleClassType como 1..10 (1 = mayor precedencia) sin fijar
# que significa cada numero -- esa asignacion es local a cada despliegue.
# TODO (estudiante): confirmar contra D.S. N.o 016-2009-MTC que clase(s) de
# vehiculo de emergencia corresponden a que valor(es) de
# priorityRequestVehicleClassType; por ahora solo se reconoce la clase 1
# (maxima precedencia), como placeholder minimo, no como un mapeo oficial.
CLASES_EMERGENCIA_RECONOCIDAS = frozenset({1})

# RNF-03 / RF-09: plazo de caducidad de una solicitud sin actualizar.
T_CAD_SEGUNDOS = 3.0


class SolicitudRechazada(Exception):
    """RF-05/RF-06: la solicitud no se acepta. `motivo` identifica la causa
    para el llamador (p. ej. para devolver el error de SNMP adecuado)."""

    def __init__(self, motivo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.motivo = motivo


def clase_reconocida(clase_tipo: int) -> bool:
    """RF-05: True si clase_tipo corresponde a una clase de vehiculo
    reconocida como de emergencia."""
    return clase_tipo in CLASES_EMERGENCIA_RECONOCIDAS


# Fases del controlador (ver controller/controller_emulator.py) durante las
# cuales no es seguro interrumpir con una transicion forzada: todavia se
# estan cumpliendo los intervalos minimos de seguridad (amarillo, todo rojo)
# de la restriccion R-02.
FASES_NO_INTERRUMPIBLES = frozenset({"amarillo", "todo_rojo"})


def respeta_limites_operacionales(fase_actual: str) -> bool:
    """RF-06: True si, dada la fase actual del controlador, es seguro
    forzar una transicion de prioridad ahora mismo (no se interrumpe un
    intervalo de seguridad en curso)."""
    return fase_actual not in FASES_NO_INTERRUMPIBLES


# ---------------------------------------------------------------------------
# Estado del PRS: una sola fila activa (sin arbitraje entre solicitudes
# concurrentes, consistente con ssec:alcance de la tesis).
# ---------------------------------------------------------------------------


@dataclass
class _FilaPRS:
    numero: int
    id_solicitud: int = 0
    vehiculo_id: bytes = b""
    clase_tipo: int = 0
    clase_nivel: int = 0
    estrategia: int = 0
    t_servicio_deseado: int = 0
    t_salida_estimada: int = 0
    estado: int = IDLE_NOT_VALID
    t_mensaje: int = 0
    ultima_actualizacion_monotonic: float = field(default_factory=time.monotonic)


class PriorityRequestServer:
    """Logica del PRS, sin dependencias de red -- testable en aislamiento.
    Las 10 filas que exige priorityRequestTable (SIZE fijo en 10, ver norma);
    solo la fila 1 se usa de verdad, el resto queda en idleNotValid."""

    NUM_FILAS = 10

    def __init__(self) -> None:
        self._filas = [_FilaPRS(numero=i) for i in range(1, self.NUM_FILAS + 1)]

    def fila(self, numero: int) -> _FilaPRS:
        return self._filas[numero - 1]

    def fila_activa(self) -> Optional[_FilaPRS]:
        f = self._filas[0]
        return f if f.estado not in (IDLE_NOT_VALID, CLOSED_CANCELED, CLOSED_COMPLETED,
                                      CLOSED_TIME_TO_LIVE_ERROR, CLOSED_STRATEGY_ERROR,
                                      CLOSED_TIMER_ERROR) else None

    def aceptar_solicitud(
        self, s: SolicitudPrioridadAbsoluta, fase_actual: str
    ) -> _FilaPRS:
        """RF-05 + RF-06: valida clase y limites antes de aceptar. Levanta
        SolicitudRechazada si no se puede aceptar; no modifica el estado en
        ese caso."""
        if not clase_reconocida(s.clase_tipo):
            raise SolicitudRechazada(
                "clase_no_reconocida",
                f"priorityRequestVehicleClassType={s.clase_tipo} no esta en "
                f"CLASES_EMERGENCIA_RECONOCIDAS={sorted(CLASES_EMERGENCIA_RECONOCIDAS)}",
            )
        if not respeta_limites_operacionales(fase_actual):
            raise SolicitudRechazada(
                "limite_operacional",
                f"no se puede forzar una transicion durante la fase '{fase_actual}' "
                f"(intervalo de seguridad en curso, restriccion R-02)",
            )

        f = self._filas[0]
        f.id_solicitud = s.id_solicitud
        f.vehiculo_id = s.vehiculo_id
        f.clase_tipo = s.clase_tipo
        f.clase_nivel = s.clase_nivel
        f.estrategia = s.estrategia
        f.t_servicio_deseado = s.t_servicio_deseado
        f.t_salida_estimada = s.t_salida_estimada
        f.estado = ACTIVE_PROCESSING
        f.t_mensaje = s.t_solicitud or int(time.time())
        f.ultima_actualizacion_monotonic = time.monotonic()
        return f

    def refrescar(self, id_solicitud: int, ahora_monotonic: Optional[float] = None) -> bool:
        """Marca la fila activa como actualizada ahora (equivalente a un
        prgPriorityUpdate, o a una actualizacion M1 del mismo id_solicitud
        por V2I). Devuelve False si no hay una solicitud activa con ese id.
        `ahora_monotonic` es para pruebas; en uso real se omite y se toma
        time.monotonic()."""
        f = self._filas[0]
        if f.estado == ACTIVE_PROCESSING and f.id_solicitud == id_solicitud:
            f.ultima_actualizacion_monotonic = (
                ahora_monotonic if ahora_monotonic is not None else time.monotonic()
            )
            return True
        return False

    def completar(self) -> None:
        f = self._filas[0]
        if f.estado == ACTIVE_PROCESSING:
            f.estado = CLOSED_COMPLETED

    def cancelar(self) -> None:
        f = self._filas[0]
        if f.estado == ACTIVE_PROCESSING:
            f.estado = CLOSED_CANCELED

    def verificar_caducidad(self, ahora_monotonic: Optional[float] = None) -> bool:
        """RF-09 / RNF-03: si la fila activa no se actualizo en los
        ultimos T_CAD_SEGUNDOS, la marca closedTimeToLiveError. Devuelve
        True si acaba de caducar en esta llamada (para que el llamador
        decida si tambien debe avisar al controlador)."""
        ahora = ahora_monotonic if ahora_monotonic is not None else time.monotonic()
        f = self._filas[0]
        if f.estado != ACTIVE_PROCESSING:
            return False
        if ahora - f.ultima_actualizacion_monotonic > T_CAD_SEGUNDOS:
            f.estado = CLOSED_TIME_TO_LIVE_ERROR
            return True
        return False
