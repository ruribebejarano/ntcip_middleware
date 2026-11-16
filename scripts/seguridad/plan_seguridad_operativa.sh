#!/usr/bin/env bash
#
# Plan completo de las pruebas de seguridad operativa (OBU comprometida y
# saturación), docs/PRUEBA_SEGURIDAD_OPERATIVA.md. Corre en la laptop con un
# broker propio en 127.0.0.1:8884: no necesita la Pi ni el broker de la
# laptop, y no choca con ninguno de los dos. ~55 min, desatendido.
#
# Los retardos del operador (30 s y 120 s) representan el tiempo de respuesta
# humana (leer la alerta, llamar al despacho, decidir): NO se miden en el
# banco, son parámetros de la prueba.
#
# Uso (Git Bash, raíz del repo):
#   bash scripts/seguridad/plan_seguridad_operativa.sh
#   REPS=1 bash scripts/seguridad/plan_seguridad_operativa.sh   # prueba corta

set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${PY:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python3
REPS="${REPS:-3}"
R=scripts/seguridad/prueba_seguridad_operativa.py

"$PY" $R --escenario base --repeticiones "$REPS" --sin-operador --etiqueta referencia
"$PY" $R --escenario mision_falsa --repeticiones "$REPS" --retardo-s 30 --etiqueta operador30
"$PY" $R --escenario mision_falsa --repeticiones "$REPS" --retardo-s 120 --etiqueta operador120
"$PY" $R --escenario mision_falsa --repeticiones "$REPS" --sin-operador --confirmacion-s 20 --etiqueta confirmacion20
"$PY" $R --escenario clon --repeticiones "$REPS" --retardo-s 30 --etiqueta operador30
"$PY" $R --escenario clon --repeticiones "$REPS" --politica suspender --sin-operador --etiqueta automatico
"$PY" $R --escenario inundacion --repeticiones "$REPS" --hz 50 --sin-operador --etiqueta hz50_sin_respuesta
"$PY" $R --escenario inundacion --repeticiones "$REPS" --hz 50 --politica suspender --sin-operador --etiqueta hz50_automatico
"$PY" $R --escenario inundacion --repeticiones "$REPS" --hz 200 --sin-operador --etiqueta hz200_sin_respuesta

"$PY" scripts/seguridad/analisis_seguridad_operativa.py
