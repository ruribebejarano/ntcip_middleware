"""Modulos compartidos entre agent/, controller/, gateway/ y scripts/analisis/.

No es un paquete instalado (no hay setup.py/pyproject): cada script que lo
importa agrega la raiz del repo a sys.path antes de "import common...". Ver
el inicio de agent/rsu_middleware.py, controller/controller_emulator.py,
gateway/obu_simulator.py y scripts/analisis/latencia_tramos.py.
"""
