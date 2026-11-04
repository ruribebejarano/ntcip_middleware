"""lazo_centralizado._interfaz_default_activa: ruta de menor métrica, también
con la salida coloreada de `ip route` cuando ssh crea una pty."""

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# Hay otro lazo_centralizado en scripts/analisis: se carga por ruta, con otro
# nombre, para no chocar con él al recolectar todas las pruebas.
_spec = importlib.util.spec_from_file_location(
    "runner_lazo_centralizado", RAIZ / "scripts" / "campanas" / "lazo_centralizado.py")
_runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _runner
_spec.loader.exec_module(_runner)
_interfaz_default_activa = _runner._interfaz_default_activa


def test_elige_la_ruta_de_menor_metrica():
    texto = ("default via 192.168.18.1 dev wlan0 proto dhcp metric 600 \n"
             "default via 192.168.0.1 dev usb0 proto dhcp metric 50 \n")
    assert _interfaz_default_activa(texto) == "usb0"


def test_ignora_codigos_de_color():
    texto = ("default via \x1b[35m192.168.0.1 \x1b[0mdev \x1b[36musb0 \x1b[0mproto dhcp src "
             "\x1b[35m192.168.0.100 \x1b[0mmetric 50 \r\n")
    assert _interfaz_default_activa(texto) == "usb0"
