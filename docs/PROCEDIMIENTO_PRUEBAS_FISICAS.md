# Procedimiento de las pruebas con la RSU física

Pruebas de la evaluación que necesitan la Raspberry Pi real o una acción
física del autor. Todas escriben en `resultados/evaluacion/` con la fecha y
hora en el nombre de la carpeta.

## 0. Preparación común

1. La Pi debe tener el mismo commit que la laptop:
   ```bash
   scripts/pi.sh deploy rsu
   ```
   El despliegue reinicia `rsu-agent.service` con el código nuevo, que usa
   SHA-256 en SNMPv3 (un gestor que todavía use SHA-1 deja de funcionar).
2. En la laptop, el broker TLS de la campaña en 8883
   (`docs/ARRANQUE_BROKER_LAPTOP.md`) y, para la prueba de *handshake*, el
   broker de desarrollo en 1883 y un listener TLS 1.2 temporal en 8884:
   ```bash
   "/c/Program Files (x86)/Mosquitto/mosquitto.exe" -c deploy/pki/mosquitto_laptop_tls12_prueba.conf
   ```
   (`deploy/pki/mosquitto_laptop_tls12_prueba.conf` es una copia de
   `mosquitto_laptop_tls.conf` con `listener 8884` y `tls_version tlsv1.2`;
   no se usa fuera de esta prueba).
3. Verificar el agente de la Pi:
   ```bash
   scripts/pi.sh status agent rsu
   ```

## 1. Caída del proceso de la RSU (automática)

Con la Pi en modo campaña por 4G (`scripts/pi.sh red modo-campana rsu`):
```bash
.venv/Scripts/python.exe scripts/evaluacion/inyeccion_fallos_pi.py --caso rsu --repeticiones 10
```
Mata el agente con SIGKILL tres a ocho segundos después de concedida la
prioridad; systemd lo reinicia a los 2 s.

## 2. Corte del enlace 4G (lo ejecuta el autor, junto a la Pi)

El corte solo es real si la Pi no tiene otra salida: con el Wi-Fi activo,
el tráfico se desviaría por él.

1. Estar junto a la Pi, con acceso local (teclado y monitor, o cable serie)
   por si el módem no vuelve.
2. Poner la Pi en modo campaña sin Wi-Fi:
   ```bash
   scripts/pi.sh red modo-campana rsu --sin-wifi
   ```
3. En la laptop:
   ```bash
   .venv/Scripts/python.exe scripts/evaluacion/inyeccion_fallos_pi.py --caso enlace4g --repeticiones 10
   ```
   Cuando la pantalla diga **DESCONECTE EL MÓDEM AHORA**, desconectar el
   cable USB del módem; cuando diga **VUELVA A CONECTAR EL MÓDEM AHORA**
   (20 s después), volver a conectarlo. El script espera solo a que la Pi
   vuelva a responder antes de la repetición siguiente.
4. Al terminar, volver al modo normal:
   ```bash
   scripts/pi.sh red modo-normal rsu
   ```

## 3. Costo del *handshake* (automática, en la Pi)

```bash
ssh rsu 'cd ~/ntcip_middleware && ~/rsu-env/bin/python scripts/evaluacion/handshake_tls.py --host <IP de la laptop en la red superpuesta> --etiqueta 4g --rondas 30 --ca ~/rsu-pki/ca.crt --cert ~/rsu-pki/rsu-1.crt --key ~/rsu-pki/rsu-1.key'
scripts/pi.sh fetch rsu
```
Las rutas de la PKI en la Pi son las de la unidad `rsu-agent.service`
(`deploy/systemd/rsu-agent.service.d/tls.conf`). Repetir con
`--etiqueta wifi` en modo normal como referencia.

## 4. SNMPv3 por nivel de seguridad (automática, en la Pi)

```bash
ssh rsu 'cd ~/ntcip_middleware && ~/rsu-env/bin/python scripts/evaluacion/snmp_niveles.py --etiqueta pi --por-nivel 1000'
scripts/pi.sh fetch rsu
```
Lanza su propio agente y controlador en los puertos 1171 y 9171, con un
broker local sin TLS (el Mosquitto propio de la Pi en 1883); el agente de
operación no se toca.

## 5. Nueva campaña 4G (la ejecuta el autor)

Objetivo: repetir la condición 4G en al menos tres sesiones y horarios
distintos, con el broker en un equipo con IP pública y, si es posible, con
la OBU también por la red celular.

1. **Broker con IP pública.** Instalar Mosquitto en el equipo elegido y
   copiar `deploy/pki/mosquitto_laptop_tls.conf` cambiando las rutas. El
   certificado del broker debe incluir en su SAN el nombre o la IP pública
   de ese equipo:
   ```bash
   python scripts/seguridad/generar_ca.py emitir --tipo servidor --san "<nombre o IP pública>,localhost"
   ```
   Abrir solo el puerto 8883/TCP.
2. **RSU.** En la Pi, apuntar `MQTT_BROKER_HOST` del drop-in
   `deploy/systemd/rsu-agent.service.d/broker.conf` al nuevo broker y
   reiniciar el agente. La RSU sale por 4G sin la red superpuesta.
3. **OBU por celular (opcional).** Correr la OBU emulada en un segundo
   equipo conectado a un punto de acceso celular, con `--broker-host` del
   nuevo broker. El servidor puede seguir en la laptop.
4. **Sesiones.** Tres sesiones en horarios distintos (mañana, tarde y
   noche, en días distintos si es posible). En cada una:
   ```bash
   .venv/Scripts/python.exe scripts/campanas/lazo_centralizado.py --escenario lazo --config pi-4g --factor 1 --broker-host <broker> --broker-port 8883 --tls deploy/pki
   .venv/Scripts/python.exe scripts/campanas/lazo_centralizado.py --escenario desvio --config pi-4g --factor 1 --broker-host <broker> --broker-port 8883 --tls deploy/pki
   ```
   Anotar hora de inicio, lugar y operador.
5. Al terminar, volver a apuntar la RSU al broker de la laptop.
