#!/usr/bin/env bash
#
# Crea los hitos (milestones) y las issues del cronograma de tesis en GitHub.
# Requiere: gh CLI autenticado (`gh auth status`).
#
# Uso:
#   ./scripts/init_github_planning.sh --dry-run    # muestra qué haría
#   ./scripts/init_github_planning.sh              # lo ejecuta
#
# Idempotencia: GitHub NO deduplica. Si lo corres dos veces tendrás issues
# repetidas. Usa --dry-run primero.

set -euo pipefail

REPO="ruribebejarano/ntcip_middleware"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

run() {
  if $DRY_RUN; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# --- Etiquetas por objetivo específico -------------------------------------
echo "==> Creando etiquetas"
declare -A LABELS=(
  [OE1]="Arquitectura y límites del sistema|1d76db"
  [OE2]="Plataforma física de la RSU|0e8a16"
  [OE3]="Middleware NTCIP|5319e7"
  [OE4]="Malla Wi-SUN y sincronización|fbca04"
  [OE5]="OBU del vehículo de emergencia|d93f0b"
  [OE6]="Validación del lazo completo|b60205"
  [tesis]="Redacción del documento|c5def5"
  [riesgo]="Riesgo identificado en el cronograma|e99695"
)
for name in "${!LABELS[@]}"; do
  IFS='|' read -r desc color <<< "${LABELS[$name]}"
  run gh label create "$name" --repo "$REPO" --description "$desc" --color "$color" --force
done

# --- Hitos por fase ---------------------------------------------------------
echo "==> Creando hitos"
create_milestone() {
  local title="$1" due="$2" desc="$3"
  if $DRY_RUN; then
    printf '[dry-run] milestone: %s (vence %s)\n' "$title" "$due"
  else
    gh api "repos/$REPO/milestones" -f title="$title" -f state=open \
      -f description="$desc" -f due_on="${due}T23:59:59Z" >/dev/null
  fi
}
create_milestone "Fase I — Diseño (Cap. 3)"        "2026-10-04" "Capítulo 3 completo, con plan de pruebas y umbrales numéricos. Gate G1 (TLSTM) el 27-sep."
create_milestone "Fase II — Middleware NTCIP"      "2026-10-18" "Emulador NTCIP, agente sobre MIB reales y adaptador verificados. Gate G2 (MIB) el 11-oct."
create_milestone "Fase III — Lazo EVP extremo a extremo" "2026-11-01" "OBU integrada y lazo OBU-RSU-controlador medido. Núcleo del aporte cerrado."
create_milestone "Fase IV — Malla I2I y cierre"    "2026-11-20" "Enlace serie, malla Wi-SUN caracterizada, conclusiones y entrega. Gate G3 el 11-nov."

# --- Issues -----------------------------------------------------------------
echo "==> Creando issues"
issue() {
  local title="$1" milestone="$2" labels="$3" body="$4"
  if $DRY_RUN; then
    printf '[dry-run] issue: %s  [%s]\n' "$title" "$labels"
  else
    gh issue create --repo "$REPO" --title "$title" --milestone "$milestone" \
      --label "$labels" --body "$body"
  fi
}

M1="Fase I — Diseño (Cap. 3)"
M2="Fase II — Middleware NTCIP"
M3="Fase III — Lazo EVP extremo a extremo"
M4="Fase IV — Malla I2I y cierre"

issue "Solicitar MIB oficiales de NEMA (1202/1209/1211)" "$M1" "OE3,riesgo" \
  "Escribir a ntcip@nema.org. Tiempo de respuesta desconocido: es el camino crítico de OE3. Registrar fecha de envío y de respuesta."
issue "Redactar 3.1 Requerimientos y restricciones" "$M1" "OE1,tesis" \
  "Funcionales, no funcionales y restricciones impuestas por la infraestructura heredada."
issue "Redactar 3.2 Arquitectura general y frontera del sistema" "$M1" "OE1,tesis" \
  "Función de cada elemento (OBU, RSU, controlador), mensajes intercambiados y latencia máxima por enlace."
issue "Redactar 3.3 Selección tecnológica con matriz ponderada" "$M1" "OE1,tesis" \
  "Canal V2I, canal I2I, mecanismo de sincronización y modelo de seguridad SNMPv3. Criterios y pesos explícitos."
issue "Redactar 3.9 Plan de pruebas y umbrales numéricos" "$M1" "OE6,tesis" \
  "Latencia máxima extremo a extremo, error de sincronización tolerable y tasa de éxito mínima. Bloquea todo el Capítulo 4."
issue "Correcciones pendientes de los Capítulos 1 y 2" "$M1" "tesis" \
  "Conteo de objetivos específicos; tabularx suelto antes de la Tabla 2.1; citas de las cifras de supervivencia; entradas contradictorias de NTCIP 1211 en la bibliografía; intersecciones Ecotrafix; incorporar RFC 9456; restituir el sustento de las filas de la Tabla 2.3."
issue "Emulador de controlador semafórico NTCIP" "$M2" "OE3" \
  "Permite validar el middleware sin depender de hardware de la MML. Desbloquea todas las pruebas del Capítulo 4."
issue "Migrar el agente de OID de prueba a las MIB reales" "$M2" "OE3" \
  "Sustituir 1.3.6.1.4.1.99999.1.1.0 y los stubs NEMA-SMI por los objetos oficiales. Confirmar el OID real del nodo scp."
issue "Verificar interoperabilidad contra un gestor NTCIP de referencia" "$M2" "OE3" \
  "GET/SET desde un segundo equipo físico, no desde la propia Raspberry Pi."
issue "Resolver TLSTM frente a USM en la interfaz NTCIP" "$M2" "OE3,riesgo" \
  "Verificar soporte real de TLSTM en el stack. Si no es viable, declarar la limitación en el Capítulo 4 con su justificación, sin disimularla."
issue "Enlace serie Raspberry Pi ↔ LaunchPad CC1352P" "$M4" "OE2" \
  "Configuración del enlace, reparto de tareas y modelo de concurrencia entre ambas plataformas."
issue "Formación de la malla Wi-SUN FAN entre dos RSU" "$M4" "OE4" \
  "SDK SimpleLink, formación automática RPL/6LoWPAN."
issue "Caracterizar el error de sincronización NTP sobre la malla" "$M4" "OE4" \
  "Intercambio de estado de fase con marcas de tiempo. Medir el error y su efecto sobre el desfase de ola verde."
issue "Integrar la OBU: OBD-II, app del operador y ETA" "$M3" "OE5" \
  "PIDs y conversión a magnitudes físicas; adquisición de posición; publicación MQTT; cálculo cinemático del ETA."
issue "Campaña de medición del lazo completo" "$M3" "OE6" \
  "Latencia extremo a extremo y tasa de éxito, con repeticiones suficientes para reportar dispersión."
issue "Redactar el Capítulo 4 con los resultados" "$M4" "tesis" \
  "Tablas y figuras generadas automáticamente desde los scripts de análisis, nunca copiadas a mano."
issue "Redactar conclusiones y trabajo futuro" "$M4" "tesis" \
  "Contrastar cada resultado contra los umbrales fijados en la sección 3.9."

issue "Validar manualmente el lector OBD-II (antes de S6)" "$M2" "OE5,riesgo" \
  "Probar el lector con Torque o Car Scanner en el vehículo disponible. Tarea barata de adelantar y cara de descubrir tarde: si el lector no responde, bloquea toda la Fase III."
issue "Gate G1 — Decidir TLSTM vs USM (límite 27-sep)" "$M1" "OE3,riesgo" \
  "Verificar soporte real de TLSTM en el stack. Salida definida: si no es viable, se adopta USM y la limitación se escribe en 3.8 esa misma semana."
issue "Gate G3 — Alcance final de OE4 (límite 11-nov)" "$M4" "OE4,riesgo" \
  "Si la malla Wi-SUN no forma para esta fecha, se reporta lo alcanzado y el resto pasa a trabajo futuro. No se sacrifica la semana de cierre."

echo "==> Listo."
$DRY_RUN && echo "(fue una simulación; ejecuta sin --dry-run para aplicarlo)"
