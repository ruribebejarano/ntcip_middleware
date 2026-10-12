#!/usr/bin/env python3
"""Convierte cada .txt de evidencia/ (incluidos los de evidencia/demo_*/) en
una imagen PNG con aspecto de terminal: fondo oscuro, fuente monoespaciada,
titulo con el nombre del archivo y la fecha, ancho fijo con salto de linea
automatico. Para que cada evidencia en texto tenga tambien su version en
imagen, lista para pegar en la tesis o en diapositivas sin tener que hacer
una captura de pantalla a mano.

*** Herramienta de la laptop, NO del banco de pruebas ***
Requiere Pillow (`pip install pillow`), que a proposito NO esta en
requirements.txt: ese archivo son las dependencias de tiempo de ejecucion
que `scripts/pi.sh deploy` instala en la Raspberry Pi (ver su cabecera),
y Pillow no corre nunca ahi -- agregarla forzaria una dependencia pesada
innecesaria en cada despliegue a la Pi. Instalar aparte en el entorno de
la laptop:

    .venv\\Scripts\\pip install pillow      (Windows)
    .venv/bin/pip install pillow            (Linux/Mac)

Uso:
    python scripts/txt_a_png.py                  # convierte todo evidencia/*.txt y evidencia/demo_*/*.txt
    python scripts/txt_a_png.py archivo1.txt ...  # convierte solo esos archivos
    python scripts/txt_a_png.py --forzar          # reconvierte aunque el .png ya exista y sea mas nuevo

Cada archivo.txt genera archivo.png al lado (mismo directorio, mismo
nombre base). No modifica ni borra el .txt original.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Falta Pillow. Instalar con: .venv\\Scripts\\pip install pillow (Windows) "
          "o .venv/bin/pip install pillow (Linux/Mac)", file=sys.stderr)
    raise SystemExit(1)

RAIZ = Path(__file__).resolve().parent.parent
EVIDENCIA_DIR = RAIZ / "evidencia"

# --- aspecto "terminal" ---
ANCHO_PX = 1280
COLUMNAS = 100            # ancho fijo en caracteres antes de saltar de linea
MARGEN_PX = 28
ALTO_TITULO_PX = 56
ALTO_LINEA_PX = 20
COLOR_FONDO = (30, 30, 34)
COLOR_BARRA_TITULO = (45, 45, 52)
COLOR_TITULO = (235, 235, 240)
COLOR_FECHA = (150, 150, 160)
COLOR_TEXTO = (210, 210, 215)
COLOR_PROMPT = (120, 200, 120)   # lineas que empiezan con "$ "
COLOR_ERROR = (230, 120, 120)    # lineas con "error"/"fallo"/"wrongvalue" (insensible a mayusculas)

RUTAS_FUENTE_MONO = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cascadiamono.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
RUTAS_FUENTE_TITULO = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _cargar_fuente(rutas: list[str], tamano: int) -> ImageFont.FreeTypeFont:
    for ruta in rutas:
        if Path(ruta).exists():
            return ImageFont.truetype(ruta, tamano)
    return ImageFont.load_default()


def _envolver_lineas(texto: str, columnas: int) -> list[str]:
    """Salto de linea automatico a `columnas` caracteres, preservando las
    lineas vacias (no las colapsa) y sin cortar palabras a la mitad cuando
    es posible (textwrap con break_long_words=True como respaldo para
    lineas de un solo token mas largas que `columnas`, p. ej. un hex largo)."""
    import textwrap
    lineas_envueltas: list[str] = []
    for linea in texto.splitlines() or [""]:
        if linea == "":
            lineas_envueltas.append("")
            continue
        partes = textwrap.wrap(
            linea, width=columnas, break_long_words=True, break_on_hyphens=False,
            replace_whitespace=False, drop_whitespace=False,
        )
        lineas_envueltas.extend(partes or [""])
    return lineas_envueltas


def _color_linea(linea: str) -> tuple[int, int, int]:
    low = linea.strip().lower()
    if low.startswith("$ "):
        return COLOR_PROMPT
    if any(p in low for p in ("error", "fallo", "wrongvalue", "traceback")):
        return COLOR_ERROR
    return COLOR_TEXTO


def convertir(txt_path: Path, forzar: bool = False) -> Path | None:
    png_path = txt_path.with_suffix(".png")
    if not forzar and png_path.exists() and png_path.stat().st_mtime >= txt_path.stat().st_mtime:
        return None  # ya esta al dia, no se reconvierte

    try:
        contenido = txt_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  (omitido, no se pudo leer: {exc})")
        return None

    fuente_titulo = _cargar_fuente(RUTAS_FUENTE_TITULO, 22)
    fuente_fecha = _cargar_fuente(RUTAS_FUENTE_TITULO, 14)
    fuente_mono = _cargar_fuente(RUTAS_FUENTE_MONO, 15)

    lineas = _envolver_lineas(contenido, COLUMNAS)
    alto_total = ALTO_TITULO_PX + MARGEN_PX + len(lineas) * ALTO_LINEA_PX + MARGEN_PX

    img = Image.new("RGB", (ANCHO_PX, alto_total), color=COLOR_FONDO)
    draw = ImageDraw.Draw(img)

    # Barra de titulo: nombre del archivo + fecha de modificacion
    draw.rectangle([(0, 0), (ANCHO_PX, ALTO_TITULO_PX)], fill=COLOR_BARRA_TITULO)
    draw.text((MARGEN_PX, 10), txt_path.name, font=fuente_titulo, fill=COLOR_TITULO)
    fecha_mod = datetime.datetime.fromtimestamp(txt_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    draw.text((MARGEN_PX, 34), fecha_mod, font=fuente_fecha, fill=COLOR_FECHA)

    y = ALTO_TITULO_PX + MARGEN_PX
    for linea in lineas:
        draw.text((MARGEN_PX, y), linea, font=fuente_mono, fill=_color_linea(linea))
        y += ALTO_LINEA_PX

    img.save(png_path)
    return png_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archivos", nargs="*", help="Archivos .txt especificos a convertir (default: todos en evidencia/ y evidencia/demo_*/)")
    parser.add_argument("--forzar", action="store_true", help="Reconvertir aunque el .png ya este al dia")
    args = parser.parse_args()

    if args.archivos:
        objetivos = [Path(a) for a in args.archivos]
    else:
        if not EVIDENCIA_DIR.is_dir():
            print(f"No existe {EVIDENCIA_DIR}", file=sys.stderr)
            raise SystemExit(1)
        objetivos = sorted(EVIDENCIA_DIR.glob("*.txt")) + sorted(EVIDENCIA_DIR.glob("demo_*/*.txt"))

    if not objetivos:
        print("No se encontro ningun .txt para convertir.")
        return

    convertidos = 0
    omitidos = 0
    for txt_path in objetivos:
        if not txt_path.is_file():
            print(f"  (no existe: {txt_path})")
            continue
        resultado = convertir(txt_path, forzar=args.forzar)
        if resultado is not None:
            print(f"  {txt_path} -> {resultado.name}")
            convertidos += 1
        else:
            omitidos += 1

    print(f"\n{convertidos} convertido(s), {omitidos} ya al dia (usar --forzar para reconvertir).")


if __name__ == "__main__":
    main()
