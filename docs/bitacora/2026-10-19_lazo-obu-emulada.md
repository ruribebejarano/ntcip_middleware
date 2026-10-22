# 2026-10-19 — Lazo completo con OBU emulada (M1/M2/M3, sin seguridad)

**Objetivo específico:** OE4 (OBU, parte lógica) y OE5 (lazo completo)  **Requerimientos:** RF-03, RF-04, RF-08, RF-10, RF-11, RNF-02
**Sección de la tesis:** 3.5.3–3.5.5 (`ssec:zonas`, `ssec:emision`, `ssec:minimizacion`) → `ssec:obu_impl` / 4.4–4.5
**Commit:** `fa14ebe` (código); evidencia en el commit siguiente

## Qué se implementó
Una OBU emulada que reproduce trayectorias sintéticas, identifica intersección
y acceso con la regla de `ssec:zonas`, emite M1 al entrar en la geocerca R_g,
lo actualiza a 1 Hz y emite M3 al cruzar. La RSU ahora escucha
`rsu/{RSU_ID}/solicitudes`, responde M2 (recibida, concedida, rechazada,
cancelada) por el Response Topic de MQTT 5 y libera la prioridad con M3. Antes
solo existía un M1 manual sin respuesta ni cancelación.

## Cómo
- `gateway/geometria.py`: ecuaciones `eq:proyeccion_local` y `eq:deltapsi`, condiciones 1–4, histéresis y criterio de emisión/cancelación (tres motivos de M3).
- `gateway/obu_emulada.py`: paho-mqtt 2.1.0 en MQTT 5; Correlation Data `<id>:<seq>` para el RTT con el reloj de la OBU.
- `config/registro_rsu.json`: centros reales de OSM (clusters 24 y 902); rumbos transversales supuestos.
- `scripts/trayectorias/generar.py`: 4 escenarios (avenida_ab, avenida_ba, transversal_a, detenido_en_cola), ruido 5 m / 5°, verdad de terreno.
- `scripts/campanas/lazo_emulado.py` y `scripts/analisis/lazo_emulado.py`.
- `agent/rsu_middleware.py`: broker, puertos y T_servicio nominal por variable de entorno; tema legado intacto.
- `agent/ntcip1211.py`: `cancelar()` también cierra una fila en `readyQueued`.
- Pruebas: 29 en total (10 nuevas de geometría, 2 nuevas de cancelación).

## Desviaciones respecto del diseño de la tesis
- OBU como programa en Python con datos ficticios, no la app Android de `ssec:app` (decisión abierta con el asesor).
- Sin TLS ni mTLS: Mosquitto en 1883 con `allow_anonymous` (P4 pendiente).
- t_servicio_deseado nominal fijo (10 s), no `L_zona / v_d` calculado.
- Parámetros geométricos provisionales: R_i 300 m, θ 45°, ψ_tol 30°, R_g 150 m, histéresis 3 muestras / 50 m.
- Tras un M2 "rechazada" (RF-05) la OBU deja de actualizar esa solicitud; la tesis no lo especifica.

## Evidencia
Primera prueba en el banco real (19/10, 12:04–12:05), con la arquitectura de broker central:
Mosquitto 2.0 en la laptop (`set_tcp_nodelay true`), RSU en la Raspberry Pi conectada a él por
Tailscale (`MQTT_BROKER_HOST=100.121.77.97`), OBU emulada en la laptop, trayectoria `transversal_a_s1`.

| Archivo en `evidencia/` | Qué muestra |
|---|---|
| `2026-10-19_rsu_conectada-broker-laptop.txt` | La RSU se conecta al broker de la laptop (`reason_code=Success`) y expone NTCIP 1202/1211 |
| `2026-10-19_relojes-antes-de-medir.txt` | Desfase contra time.cloudflare.com: Pi −8,7 ms, laptop +7,5 a +8,5 ms (≈16 ms entre ambas) |
| `2026-10-19_snmpwalk-por-tailscale.txt` | Supervisión SNMPv3 del subárbol NTCIP 1202 desde la laptop por Tailscale (rehacer con `2>&1`: la primera vez quedó vacío) |
| `2026-10-19_obu-emulada-transversal.txt` | Consola de la OBU: M1 a 142 m, M2 recibida → concedida, M3 al cruzar, M2 cancelada |
| `2026-10-19_rsu-lazo-transversal.txt` | RSU: solicitud en cola durante todo rojo (RF-06), activada al terminar el despeje, liberada por M3 |
| `2026-10-19_controlador-lazo-transversal.txt` | Controlador: verde por prioridad a las 12:05:03, renovado cada segundo, liberado a las 12:05:14 |

Secuencia observada (relojes de la Pi y de la laptop):

| Hora | Evento |
|---|---|
| 12:05:01 | M1 (seq 1) llega con el controlador en todo rojo → `readyQueued` (RF-06); M2 "recibida", RTT 14,2 ms |
| 12:05:03 | Fin del despeje → la RSU activa la solicitud; controlador en verde; M2 "concedida" sin esperar al siguiente M1 |
| 12:05:03–12:05:13 | 11 M1 de actualización a 1 Hz; cada uno renueva la prioridad en el controlador |
| 12:05:14 | M3 (cruce) → `clear_priority`; M2 "cancelada", RTT 11,1 ms; el controlador vuelve al ciclo normal |

Totales: 13 M1 + 1 M3 enviados, 15 M2 recibidos, acceso asignado = verdad de terreno (OSM-C24/O).
Es un solo recorrido: sirve como demostración del lazo, no como medición estadística.

Banco local previo (en la nube, una sola máquina): 8 recorridos, 12 solicitudes concedidas,
PDR 1,0 (210/210), RTT M1/M2 mediano 2,6 ms. Solo validó la lógica antes de pasar a la Pi.

## Problemas y solución
- RTT M1/M2 de ~44 ms en localhost, con t_V2I de 0,5 ms → Mosquitto aplica Nagle por defecto en el envío de M2. Con `set_tcp_nodelay true` bajó a ~2,4 ms. Hay que aplicarlo en la Pi antes de medir y declararlo en la configuración del broker del Capítulo IV.
- A x4 de velocidad la solicitud caía en ámbar y el vehículo cruzaba antes del fin del despeje: las campañas deben correrse en tiempo real (`--factor 1`).
- El M2 "concedida" llegaba hasta 1 s tarde (con el siguiente M1). Ahora la RSU lo envía en cuanto activa una solicitud en cola (pasos 5–8 de `fig:secuencia`).

- Vehículo detenido 20 s en cola (escenario `detenido_en_cola`): el controlador soltaba el verde a los 15 s (`PRIORITY_HOLD_SECONDS`) aunque la OBU seguía renovando M1 a 1 Hz, porque la renovación solo reiniciaba el plazo RF-09 en la RSU y no llegaba al controlador. Ahora cada M1 de una solicitud activa también renueva la prioridad en el controlador; si la OBU deja de renovar, RF-09 libera a los 3 s. Verificado: verde sostenido desde los 5 s hasta el cruce, a los 32 s.

## Pendiente
- Decidir con el asesor si hace falta un tope máximo de verde sostenido por prioridad (caso v → 0 que la tesis deja como TODO en `ssec:emision`): hoy un vehículo detenido dentro de R_g mantiene el verde mientras siga emitiendo M1.
- Correr la campaña de 5 repeticiones contra la Pi y analizarla con `scripts/pi.sh fetch`.
- Opcional: segunda RSU en la laptop contra el mismo broker, para cerrar las solicitudes a `rsu/2`.
- Reemplazar los rumbos transversales supuestos por los de Overpass.
- Llevar M1/M2/M3 al broker con TLS (P4).
