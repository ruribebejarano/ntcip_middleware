# Experimento de consumo de datos por 4G

Mide cuánto consume la RSU en reposo y por misión, y cuánto consume una OBU emulada
por misión, sobre la red celular real. Dura unas 2,5 horas sin supervisión y consume
unas decenas de MB. Por seguridad, la Pi aborta si la interfaz supera 300 MB
(`--limite-mb`).

Reemplaza a la cifra de 0,19 MB por repetición de la campaña de medición, que incluye
el tráfico SSH con que la campaña trae los eventos y es solo una cota superior.

## Fases

| Fase | Duración | Qué ocurre | Qué mide |
|---|---|---|---|
| `fondo` | 30 min | Agente detenido | Sistema, Tailscale y NTP |
| `reposo` | 30 min | Agente conectado, sin misiones | RSU en línea |
| `misiones` | 35 min | 18 misiones con la OBU en la laptop | Consumo de la RSU por misión |
| `reposo2` | 30 min | Como `reposo` | Si el reposo cambió |
| `obu` | 25 min | Agente detenido; 12 misiones con la OBU en la Pi | Consumo de la OBU por misión |

Durante la medición, la laptop no abre SSH hacia la Pi. Un registrador en la Pi guarda
los contadores de la interfaz cada 10 s, detiene e inicia `rsu-agent`, corre la OBU de
la última fase y reinicia el agente al terminar, también si se interrumpe.

En la fase `obu`, la RSU corre en la laptop. Así, sus mensajes no pasan por el módem.

## Cómo lanzarlo

1. Abre el broker TLS en una terminal y déjala abierta:

```powershell
& "C:\Program Files (x86)\Mosquitto\mosquitto.exe" -c deploy\pki\mosquitto_laptop_tls.conf -v
```

2. Pasa la Pi a 4G con el Wi-Fi apagado. Pide tu contraseña:

```powershell
ssh -t rsu "cd ~/ntcip_middleware && bash scripts/red_4g.sh modo-campana --sin-wifi"
```

3. Verifica, sin medir:

```powershell
.venv\Scripts\python.exe scripts\consumo\experimento.py --solo-verificar
```

4. Lanza el experimento:

```powershell
.venv\Scripts\python.exe scripts\consumo\experimento.py
```

Deja la laptop encendida y conectada a internet, y **no uses SSH hacia la Pi** hasta
que termine: ese tráfico contaría como consumo.

5. Vuelve a Wi-Fi al terminar:

```powershell
ssh -t rsu "cd ~/ntcip_middleware && bash scripts/red_4g.sh modo-normal"
```

## Resultados

Quedan en `resultados/consumo/<fecha>_usb0/`:

- `resumen.txt`: MB/hora por fase, MB por misión y consumo mensual sin misiones.
- `consumo.json`: las mismas cifras, para generar tablas.
- `pi/contadores.csv`: las muestras cada 10 s.

Para agregar una proyección con un número supuesto de misiones al día:

```powershell
.venv\Scripts\python.exe scripts\consumo\analizar.py --dir resultados\consumo\<carpeta> --misiones-dia 10
```

## Cómo se calcula

- **Reposo:** bytes por segundo de cada fase, sin su primer minuto, cuando el agente se
  conecta o desconecta.
- **RSU por misión:** (bytes entre el primer armado y el último desarmado − reposo ×
  duración) ÷ misiones.
- **OBU por misión:** igual, pero descontando la fase `fondo`, porque el agente está
  detenido.

## Límites

- Los contadores miden el tráfico IP en la interfaz del módem, con la sobrecarga de TLS
  y de Tailscale. Un despliegue sin Tailscale podría consumir menos.
- Mide la OBU emulada, no la app Android, que además puede descargar mapas.
- Si una fase de reposo tiene picos, como una actualización automática de la Pi, el
  resumen los cuenta. Revísalos en `contadores.csv` antes de usar la cifra.
- El saldo del operador sirve solo como comparación aproximada, porque redondea.
- El resultado corresponde a la cobertura del banco de pruebas.
