#!/usr/bin/env bash
#
# Regenera las tablas y figuras de la campaña del Capítulo IV: tres condiciones
# de enlace (local, pi-lan, pi-4g), todas a 1 Hz y con TLS 1.3 + mTLS, más el par
# con y sin TLS para el costo de la seguridad.
#
# Uso (Git Bash, raíz del repo):
#   scripts/analisis/generar_cap4.sh [carpeta de la tesis]
# Sin argumento solo escribe en $SALIDA. Con ella copia lo que usa main.tex.

set -euo pipefail
cd "$(dirname "$0")/../.."
PY=".venv/Scripts/python.exe"
C="resultados/campana"
SALIDA="$C/_figuras_cap4_2026-11-04"
L_LOCAL="$C/20261104-002341_lazo_local_1hz_con-tls"
D_LOCAL="$C/20261104-005352_desvio_local_1hz_con-tls"
L_SINTLS="$C/20261104-012402_lazo_local_1hz_sin-tls"
L_LAN="$C/20261104-045004_lazo_pi-lan"
D_LAN="$C/20261104-052338_desvio_pi-lan"
L_4G="$C/20261103-232704_lazo_pi-4g"
D_4G="$C/20261103-235034_desvio_pi-4g"
TODAS=(--dir "$L_LOCAL" --dir "$D_LOCAL" --dir "$L_LAN" --dir "$D_LAN" --dir "$L_4G" --dir "$D_4G")
ETIQ=(--dir "$L_LOCAL" --etiqueta local --dir "$D_LOCAL" --etiqueta local
      --dir "$L_LAN" --etiqueta pi-lan --dir "$D_LAN" --etiqueta pi-lan
      --dir "$L_4G" --etiqueta pi-4g --dir "$D_4G" --etiqueta pi-4g)
NOTA="La condición pi-lan es la RSU real por Wi-Fi mediante una red superpuesta, no un enlace cableado; pi-4g, la RSU real por el módem celular; local, el banco de desarrollo, con los procesos compitiendo por CPU en la misma máquina, y no debe leerse como una cota inferior."

mkdir -p "$SALIDA"
for d in "$L_LOCAL" "$D_LOCAL" "$L_SINTLS" "$L_LAN" "$D_LAN" "$L_4G" "$D_4G"; do
  "$PY" scripts/analisis/lazo_centralizado.py --dir "$d" > "$d/analisis.txt"
done
"$PY" scripts/analisis/latencia_percentiles.py "${ETIQ[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/graficos_campana_centralizada.py "${ETIQ[@]}" --salida "$SALIDA" --nota "$NOTA"
"$PY" scripts/analisis/cumplimiento_rf8.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/llegadas_verde_contrafactual.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/resumen_capitulo4.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/offset_reloj.py --dir "$L_LAN" --dir "$D_LAN" --dir "$L_4G" --dir "$D_4G" --salida "$SALIDA"
{
  for d in "$L_LOCAL" "$D_LOCAL" "$L_SINTLS" "$L_LAN" "$D_LAN" "$L_4G" "$D_4G"; do
    echo "== $(basename "$d")"
    "$PY" scripts/analisis/frecuencia_actualizacion.py --dir "$d"
  done
} > "$SALIDA/frecuencia_actualizacion.txt"
"$PY" scripts/analisis/consumo_datos.py --dir "$L_4G" --dir "$D_4G" > "$SALIDA/consumo_datos.txt"
{
  echo "== con TLS"; grep -aE '^(L --|t_OBU_srv)' "$L_LOCAL/analisis.txt"
  echo "== sin TLS"; grep -aE '^(L --|t_OBU_srv)' "$L_SINTLS/analisis.txt"
} > "$SALIDA/costo_tls.txt"

if [ $# -ge 1 ]; then
  T="$1"
  for f in tabla_latencia tabla_latencia_percentiles tabla_condicion tabla_renovacion tabla_contrafactual; do
    cp "$SALIDA/$f.tex" "$T/tablas/resultados/$f.tex"
  done
  cp "$SALIDA/tabla_rf8.tex" "$T/tablas/resultados/tabla_rf14.tex"
  for f in fig_rtt_cdf fig_comparacion fig_tramos fig_offset_reloj; do
    cp "$SALIDA/$f.pdf" "$T/figuras/resultados/$f.pdf"
  done
  cp "$SALIDA/fig_rf8_cdf.pdf" "$T/figuras/resultados/fig_anticipacion_cdf.pdf"
fi
