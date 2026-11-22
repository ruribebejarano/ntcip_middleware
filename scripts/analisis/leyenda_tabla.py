"""Formato de las leyendas de las tablas generadas para la tesis.

Las tablas que generan los scripts de análisis llevaban en su leyenda,
además del título, la definición de cada columna. En la tesis el título
debe ser corto (una línea en el índice de tablas): `formalizar(tex)`
reemplaza la leyenda por un título corto (CORTAS, por etiqueta) y pasa el
resto del texto a una nota al pie de la tabla, en letra pequeña. Si la
etiqueta de la tabla no está en CORTAS, devuelve el texto sin cambios.

Uso en un generador, justo antes de escribir el archivo:

    from leyenda_tabla import formalizar
    (salida / "tabla_x.tex").write_text(formalizar(tex), encoding="utf-8")
"""

from __future__ import annotations

import re

CORTAS = {
    "tab:fallos": r"Inyección de fallos con una prioridad activa (RNF-07, RNF-08).",
    "tab:costo_obu": r"Consumo y costo mensual de datos de una OBU.",
    "tab:carga": r"Carga del servidor central y del \emph{broker}.",
    "tab:direccionamiento": r"Exactitud del direccionamiento del servidor con ruido de posición creciente.",
    "tab:ntcip_traduccion": r"Traducción de las solicitudes a NTCIP en la campaña de medición.",
    "tab:costo_planes": r"Costo mensual de datos de una RSU.",
    "tab:latencia_inicial": r"Latencia de la solicitud inicial y del tramo OBU--servidor, por enlace.",
    "tab:bytes": r"Bytes por mensaje y por misión, con y sin TLS.",
    "tab:latencia_mensaje": r"Latencia servidor--RSU por mensaje, por condición de enlace.",
    "tab:seguridad_operativa": r"Respuesta ante una OBU comprometida o que satura el \emph{broker}.",
    "tab:condicion_completa": r"Latencia de la solicitud inicial por condición de llegada.",
    "tab:snmp_niveles": r"Costo de SNMPv3 por nivel de seguridad en la RSU física.",
    "tab:handshake": r"Costo de establecer la conexión segura con el \emph{broker}, por enlace.",
    "tab:campana_nube": r"Lazo por 4G con el \emph{broker} en la laptop y en la nube.",
    "tab:recuperacion_plan": r"Recuperación del plan del controlador emulado tras liberar una prioridad.",
    "tab:latencia_por_condicion": r"Espera por despeje y anticipación por condición de llegada.",
    "tab:proyeccion_datos": r"Proyección del consumo mensual de datos de una RSU.",
    "tab:anticipacion_parada": r"Anticipación $A$ por enlace frente a los límites de RF-11.",
    "tab:rf11_indra": r"Anticipación $A$ con los tiempos del controlador INDRA.",
    "tab:separacion_rsu": r"Separación entre intersecciones consecutivas de una ruta real.",
    "tab:entrega": r"Tasa de entrega por tipo de mensaje y enlace.",
    "tab:cola": r"Emisión de la solicitud con el vehículo en una cola.",
    "tab:conflicto": r"Conflicto entre dos misiones en el banco de pruebas.",
    "tab:renovacion_campana": r"Renovación y caducidad de las solicitudes.",
}


def _fin_argumento(texto: str, k: int) -> int:
    """Índice justo después de la llave que cierra el argumento que empieza en k."""
    nivel, j = 1, k
    while nivel:
        nivel += {"{": 1, "}": -1}.get(texto[j], 0)
        j += 1
    return j


def _primera_oracion(cap: str) -> tuple[str, str]:
    nivel = 0
    for i, ch in enumerate(cap):
        nivel += {"{": 1, "}": -1}.get(ch, 0)
        if (ch == "." and nivel == 0 and i + 2 < len(cap) and cap[i + 1] == " "
                and (cap[i + 2].isupper() or cap[i + 2] in "`$\\")):
            return cap[:i + 1], cap[i + 2:]
    return cap, ""


def formalizar(tex: str) -> str:
    etiqueta = re.search(r"\\label\{([^}]*)\}", tex)
    if not etiqueta or etiqueta.group(1) not in CORTAS:
        return tex
    c = re.search(r"\\caption(\[[^\]]*\])?\{", tex)
    if not c:
        return tex
    j = _fin_argumento(tex, c.end())
    original = re.sub(r"\s*Elaboración propia\.?\s*$", "", tex[c.end():j - 1].strip())
    primera, resto = _primera_oracion(original)
    nota = resto if len(primera) < 110 else original
    nuevo = tex[:c.start()] + "\\caption{" + CORTAS[etiqueta.group(1)] + "}" + tex[j:]
    if nota:
        pos = max(nuevo.rfind("\\end{tabular}"), nuevo.rfind("\\end{tabularx}"))
        cierre = nuevo.find("}", pos) + 1
        if nuevo[cierre:cierre + 1] == "}":  # tabla dentro de \resizebox{...}{...}{...}
            cierre += 1
        nuevo = (nuevo[:cierre] + "\n\\par\\vspace{3pt}{\\footnotesize\\raggedright\\textit{Nota:} "
                 + nota.strip() + " Elaboración propia.\\par}" + nuevo[cierre:])
    return nuevo
