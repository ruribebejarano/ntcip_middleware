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
SALIDA="$C/_figuras_cap4_2026-11-11"
L_LOCAL="$C/20261111-173108_lazo_local_1hz_con-tls"
D_LOCAL="$C/20261111-180333_desvio_local_1hz_con-tls"
L_SINTLS="$C/20261111-183407_lazo_local_1hz_sin-tls"
L_LAN="$C/20261104-045004_lazo_pi-lan"
D_LAN="$C/20261104-052338_desvio_pi-lan"
L_4G="$C/20261103-232704_lazo_pi-4g"
D_4G="$C/20261103-235034_desvio_pi-4g"
TODAS=(--dir "$L_LOCAL" --dir "$D_LOCAL" --dir "$L_LAN" --dir "$D_LAN" --dir "$L_4G" --dir "$D_4G")
# Etiquetas legibles: los identificadores internos (pi-lan, pi-4g) no van a la tesis.
ETIQ=(--dir "$L_LOCAL" --etiqueta Local --dir "$D_LOCAL" --etiqueta Local
      --dir "$L_LAN" --etiqueta Wi-Fi --dir "$D_LAN" --etiqueta Wi-Fi
      --dir "$L_4G" --etiqueta 4G --dir "$D_4G" --etiqueta 4G)
NOTA="Wi-Fi es la RSU física alcanzada por Wi-Fi mediante una red superpuesta; 4G, la misma RSU por el módem celular; Local, el banco de desarrollo."
MULTI_RSU="resultados/espacio_tiempo/2026-11-02_2308"  # ruta con tres RSU (sección 4.3.6)

mkdir -p "$SALIDA"
for d in "$L_LOCAL" "$D_LOCAL" "$L_SINTLS" "$L_LAN" "$D_LAN" "$L_4G" "$D_4G"; do
  "$PY" scripts/analisis/lazo_centralizado.py --dir "$d" > "$d/analisis.txt"
done
"$PY" scripts/analisis/recalculo_por_mensaje.py --salida "$SALIDA" > "$SALIDA/recalculo_por_mensaje.txt"
"$PY" scripts/analisis/latencia_percentiles.py "${ETIQ[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/graficos_campana_centralizada.py "${ETIQ[@]}" --salida "$SALIDA" --nota "$NOTA"
"$PY" scripts/analisis/cumplimiento_rf8.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/llegadas_verde_contrafactual.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/resumen_capitulo4.py "${TODAS[@]}" --salida "$SALIDA"
"$PY" scripts/analisis/offset_reloj.py --dir "$L_LAN" --dir "$D_LAN" --dir "$L_4G" --dir "$D_4G" --salida "$SALIDA"
# Traducción NTCIP sobre las seis corridas más la ruta con tres RSU. También
# escribe tabla_ntcip_rechazo.tex, que NO se copia: la de la tesis tiene una
# redacción revisada a mano de los mismos 22 casos.
"$PY" scripts/analisis/validacion_ntcip.py "${TODAS[@]}" --dir "$MULTI_RSU" --salida "$SALIDA" > "$SALIDA/validacion_ntcip.txt"
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
  # cuerpo del capítulo
  for f in tabla_latencia_mensaje tabla_entrega tabla_anticipacion tabla_condicion_llegada \
           tabla_renovacion tabla_ntcip_traduccion; do
    cp "$SALIDA/$f.tex" "$T/tablas/resultados/$f.tex"
  done
  # anexo
  cp "$SALIDA/tabla_latencia.tex" "$T/tablas/resultados/tabla_latencia_inicial.tex"
  cp "$SALIDA/tabla_condicion.tex" "$T/tablas/resultados/tabla_condicion_completa.tex"
  # decimales con coma en las filas de datos (el generador usa punto)
  sed -E '/&/ s/([0-9])\.([0-9])/\1,\2/g' "$SALIDA/tabla_contrafactual.tex" \
    > "$T/tablas/resultados/tabla_contrafactual.tex"
  for f in fig_rtt_cdf fig_comparacion fig_tramos fig_offset_reloj fig_anticipacion_cdf; do
    cp "$SALIDA/$f.pdf" "$T/figuras/resultados/$f.pdf"
  done
fi
