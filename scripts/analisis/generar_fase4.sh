#!/usr/bin/env bash
#
# Reúne las tablas y figuras de las pruebas de la Fase 4 (sección 4.4 y
# 4.5 de la tesis) en $SALIDA y, con un argumento, las copia a la tesis.
# Las corridas se fijan aquí para que el resultado sea reproducible.
#
# Uso (Git Bash, raíz del repo):
#   scripts/analisis/generar_fase4.sh [carpeta de la tesis]

set -euo pipefail
cd "$(dirname "$0")/../.."
PY=".venv/Scripts/python.exe"
E="resultados/evaluacion"
SALIDA="$E/_figuras_fase4_2026-11-12"
mkdir -p "$SALIDA"
export PYTHONIOENCODING=utf-8

# Prueba 1: fallos (local y RSU física)
"$PY" scripts/evaluacion/fallos_resumen.py \
  --dir "$E/20261112-015811_fallos_broker" --dir "$E/20261112-021647_fallos_servidor" \
  --dir "$E/20261112-023511_fallos_rsu" --dir "$E/20261112-023515_fallos_pi_rsu" \
  --salida "$SALIDA" > /dev/null
# Pruebas 2, 3 y 5
"$PY" scripts/evaluacion/resumen_fase4.py --carga "$E/20261112-153503_carga" \
  --handshake-4g "$E/20261112-022340_handshake_4g" --handshake-wifi "$E/20261112-021517_handshake_wifi" \
  --bytes-tls "$E/20261112-150406_bytes_tls" --bytes-sin-tls "$E/20261112-151809_bytes_sin-tls" \
  --snmp "$E/20261112-021421_snmp_niveles_pi" --salida "$SALIDA" > "$SALIDA/resumen_fase4.txt"
# Pruebas 6, 7 y 8: sus scripts ya escribieron la tabla en su corrida
"$PY" scripts/evaluacion/conflicto_resumen.py --dir resultados/campana/20261112-014850_conflicto_local > /dev/null
cp resultados/campana/20261112-014850_conflicto_local/tabla_conflicto.tex "$SALIDA/"
cp "$E/20261112-020514_direccionamiento_ruido/tabla_direccionamiento.tex" \
   "$E/20261112-020514_direccionamiento_ruido/fig_direccionamiento.pdf" "$SALIDA/"
cp "$E/20261112-014849_recuperacion_plan/tabla_recuperacion_plan.tex" \
   "$E/20261112-014849_recuperacion_plan/fig_recuperacion_plan.pdf" "$SALIDA/"
# Costo mensual de datos de una RSU con planes IoT (sección 4.6.3)
"$PY" scripts/analisis/costo_planes_iot.py --resumen "$SALIDA" --bytes-tls "$E/20261112-150406_bytes_tls" \
  --salida "$SALIDA" > /dev/null
# Separación entre intersecciones de la ruta real de 13 RSU (OE1, Anexo 7)
"$PY" scripts/analisis/separacion_rsu.py --salida "$SALIDA" > /dev/null

if [ $# -ge 1 ]; then
  T="$1"
  for f in tabla_fallos tabla_carga tabla_handshake tabla_bytes tabla_proyeccion_datos tabla_costo_planes tabla_costo_obu tabla_snmp_niveles \
           tabla_conflicto tabla_direccionamiento tabla_recuperacion_plan tabla_separacion_rsu; do
    cp "$SALIDA/$f.tex" "$T/tablas/resultados/$f.tex"
  done
  for f in fig_carga fig_direccionamiento fig_recuperacion_plan; do
    cp "$SALIDA/$f.pdf" "$T/figuras/resultados/$f.pdf"
  done
fi
echo "Listo: $SALIDA"
