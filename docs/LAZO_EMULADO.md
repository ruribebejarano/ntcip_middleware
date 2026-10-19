# Lazo completo con OBU emulada (sin seguridad)

Esta guía corre el lazo de priorización completo **OBU → broker MQTT → RSU →
controlador → M2 de vuelta** con una OBU que reproduce **trayectorias
sintéticas**. No hace falta vehículo, teléfono ni lector OBD-II.

## Qué es real y qué es ficticio

| Parte | En esta emulación |
|---|---|
| Posición, rumbo y velocidad | **Ficticios**: rectas a 40 km/h sobre dos intersecciones con ruido GNSS gaussiano (`scripts/trayectorias/generar.py`) |
| Centros de las intersecciones | Reales: centroides de OpenStreetMap (clusters 24 y 902, a ~436 m) |
| Rumbos de acceso | Vía principal: calculados entre los dos centroides. Transversal: **supuesta perpendicular** |
| Identificación de intersección y acceso (RF-11) | Real: reglas de `ssec:zonas` en `gateway/geometria.py` |
| Emisión y cancelación (RF-03, RF-04) | Real: geocerca R_g, M1 a 1 Hz, M3 al cruzar |
| Mensajes M1/M2/M3 por MQTT 5 | Reales, por los temas del esquema E2 (`rsu/{id}/solicitudes`, `veh/{id}/respuestas`) |
| RSU: RF-05, RF-06, RF-07, RF-09, NTCIP 1211 | Reales (el mismo middleware de P3) |
| Controlador | Emulado (como desde P2) |
| Seguridad (TLS, mTLS, USM SHA-256) | **No incluida** en esta etapa |

Los parámetros R_i = 300 m, θ = 45°, ψ_tol = 30°, R_g = 150 m y la histéresis
(3 muestras, 50 m) son **provisionales**: la tesis los deja como TODO a
calibrar con GNSS real.

## Archivos

| Archivo | Qué hace |
|---|---|
| `config/registro_rsu.json` | Copia local estática del registro de RSU (E4): 2 intersecciones, 4 accesos cada una |
| `gateway/geometria.py` | Proyección local, Δψ, condiciones 1–4 de asignación, histéresis y criterio de emisión/cancelación |
| `gateway/obu_emulada.py` | Reproduce una trayectoria y publica M1/M3; recibe M2 y mide el RTT con su propio reloj |
| `scripts/trayectorias/generar.py` | Genera las trayectorias (4 escenarios) con su verdad de terreno |
| `scripts/campanas/lazo_emulado.py` | Corre N recorridos y guarda la corrida con su `config.json` |
| `scripts/analisis/lazo_emulado.py` | Calcula PDR, acierto de acceso, RTT M1/M2, t_V2I, t_RSU, espera de despeje y tiempo hasta el verde |
| `agent/rsu_middleware.py` | Ahora también escucha `rsu/{RSU_ID}/solicitudes`, responde M2 y procesa M3 |
| `tests/test_geometria.py` | 10 pruebas de la geometría y de la máquina de estados de la OBU |

El tema legado `rsu/v2i/solicitud_prioridad` sigue funcionando:
`gateway/obu_simulator.py` y `scripts/demo_asesor.sh` no cambian.

## Variables de entorno nuevas del middleware

| Variable | Por defecto | Para qué |
|---|---|---|
| `MQTT_BROKER_HOST` | `127.0.0.1` | Apuntar la RSU a un broker central (otra máquina, EMQX) |
| `MQTT_BROKER_PORT` | `1883` | |
| `SNMP_PORT` | `1161` | Correr una segunda RSU en la misma máquina |
| `CONTROLLER_PORT` | `9000` | Ídem, junto con `controller_emulator.py --port` |
| `T_SERVICIO_NOMINAL_S` | `10` | Valor nominal de priorityRequestTimeOfServiceDesired (M1 no trae ETA) |

## Antes de medir: ajustar Mosquitto

Por defecto Mosquitto aplica el algoritmo de Nagle en sus sockets. En el
banco local eso sumó **~40 ms a cada M2** (RTT M1/M2 de 44 ms frente a 2,4 ms
con el ajuste). En la Raspberry Pi:

```bash
sudo tee /etc/mosquitto/conf.d/rsu-lab.conf > /dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
set_tcp_nodelay true
EOF
sudo systemctl restart mosquitto
```

`allow_anonymous true` sigue siendo solo de laboratorio (sin TLS).

## Opción A: RSU en la Raspberry Pi, OBU en la laptop

1. Hacer commit en la laptop y desplegar (`scripts/pi.sh deploy` hace el
   push y el `git pull` en la Pi). Luego reiniciar:
   `scripts/pi.sh restart controller && scripts/pi.sh restart agent`.
2. Generar trayectorias y correr un recorrido:

   ```bash
   python scripts/trayectorias/generar.py
   python gateway/obu_emulada.py --broker-host rsu-01 \
       --trayectoria resultados/trayectorias/avenida_ab_s1.csv
   ```

   (`rsu-01` por Tailscale; o la IP local de la Pi.)
3. Campaña y análisis:

   ```bash
   python scripts/campanas/lazo_emulado.py --broker-host rsu-01 --repeticiones 5
   scripts/pi.sh fetch
   python scripts/analisis/lazo_emulado.py --dir resultados/lazo_emulado/<corrida> --dir resultados/rsu/eventos
   ```

La trayectoria `avenida_ab` cruza **dos** intersecciones. Con una sola RSU
desplegada, las solicitudes a `rsu/2` quedan **sin respuesta**: eso muestra el
enrutamiento por tema, no un error. Para cerrarlas también, correr una
segunda RSU en la laptop **contra el broker de la Pi**, que es exactamente el
esquema de broker central:

```bash
# terminal 1
RSU_ID=2 python controller/controller_emulator.py --port 9001
# terminal 2
RSU_ID=2 SNMP_PORT=1162 CONTROLLER_PORT=9001 MQTT_BROKER_HOST=rsu-01 python agent/rsu_middleware.py
```

En PowerShell, las variables se definen con `$env:RSU_ID="2"` antes del comando.

## Opción B: todo en una máquina

Con Mosquitto local, dos controladores y dos RSU:

```bash
export RSU_EVENTOS_DIR=resultados/banco_local
RSU_ID=1 python controller/controller_emulator.py --port 9000 &
RSU_ID=2 python controller/controller_emulator.py --port 9001 &
RSU_ID=1 python agent/rsu_middleware.py &
RSU_ID=2 SNMP_PORT=1162 CONTROLLER_PORT=9001 python agent/rsu_middleware.py &
python scripts/campanas/lazo_emulado.py --broker-host 127.0.0.1 --repeticiones 3
python scripts/analisis/lazo_emulado.py --dir resultados/lazo_emulado/<corrida> --dir resultados/banco_local
```

## Qué mide el análisis y cómo leerlo

| Métrica | Reloj | Comentario |
|---|---|---|
| RTT M1/M2 | Solo el de la OBU | La más robusta; no requiere sincronizar relojes |
| t_V2I | OBU y RSU | Válida solo con relojes sincronizados (chrony/W32Time) o en la misma máquina |
| t_RSU | RSU | Validación, RF-05 y RF-06 antes de escribir al controlador |
| Espera de despeje | RSU | Solo si la solicitud llegó en ámbar o todo rojo (RF-06) |
| M1 → verde | OBU y controlador | Incluye la espera del despeje: depende de en qué fase llega la solicitud |
| PDR | Contador `seq` | Mensajes únicos recibidos sobre enviados |
| Acierto de acceso | Verdad de terreno | M1 dirigidos a la intersección y acceso correctos |

Con trayectorias sintéticas, estas cifras caracterizan **el canal y la
lógica**, no el comportamiento de un vehículo real. Así debe declararse en el
Capítulo IV.
