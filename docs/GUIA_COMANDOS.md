# Guía de comandos: levantar, demostrar y recompilar el sistema

Esta guía reúne, en orden, todo lo necesario para una presentación: qué se
instala una sola vez, qué se revisa antes de empezar, cómo se levanta la
demo, cómo se recompilan la app, los resultados y la tesis, y qué hacer si
algo falla.

> **Atajo.** Casi todo se hace con un solo script:
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 verificar
> powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 iniciar
> powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 obu
> powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 detener
> ```
>
> El resto del documento explica qué hace cada paso y cómo hacerlo a mano.

**Convenciones**

- Todos los comandos se ejecutan **desde la raíz del repositorio**
  (`E:\Tesis\ntcip_middleware`), salvo que se indique otra carpeta.
- **PowerShell**: los comandos con `.\.venv\Scripts\python.exe` o `.ps1`.
  **Git Bash**: los que usan `scripts/pi.sh` o rutas con `/`.
- "Como administrador" significa abrir PowerShell con clic derecho >
  *Ejecutar como administrador*.

---

## 1. Qué corre dónde

| Proceso | Máquina | Cómo se inicia | Rol |
|---|---|---|---|
| Mosquitto (broker MQTT) | Laptop | Servicio de Windows, arranca solo | Canal de todos los mensajes |
| `servidor/main.py` | Laptop | `presentacion.ps1 iniciar` | Único decisor: ruta, ETA, solicitudes M1/M3 |
| `controller/controller_emulator.py` | Laptop (demo) o Raspberry Pi | `presentacion.ps1 iniciar` / servicio `rsu-controller` | Controlador semafórico emulado |
| `agent/rsu_middleware.py` | Laptop (demo) o Raspberry Pi | `presentacion.ps1 iniciar` / servicio `rsu-agent` | RSU: agente SNMPv3 NTCIP 1202/1211 y traducción M1 → controlador |
| `consola/servidor.py` | Laptop | `presentacion.ps1 iniciar` | Consola web en `http://127.0.0.1:8080/` |
| OBU | Laptop (emulada) o tablet | `presentacion.ps1 obu` / app Android | Arma la misión y envía su posición a 1 Hz |

En la demo principal, **todo corre en la laptop**: una RSU y un controlador
emulados por cada intersección del escenario. La Raspberry Pi y la tablet
son variantes opcionales (secciones 6 y 7).

## 2. Orden y dependencias

```
  Mosquitto (siempre primero: todos se conectan a él)
      │
      ├──► controladores ──► RSU (cada RSU necesita su controlador ya escuchando)
      │                         │
      ├──► servidor central ◄───┘ (puede arrancar antes o después de las RSU)
      │
      ├──► consola web (lee el broker y sondea cada RSU por SNMPv3)
      │
      └──► OBU (SIEMPRE AL FINAL: si arranca antes que el servidor,
                su MI se pierde y la misión no se arma)
```

**Secuencial:** Mosquitto → (controladores, RSU, servidor, consola) → OBU.
`presentacion.ps1 iniciar` respeta ese orden: espera a que cada controlador
y cada RSU abran su puerto antes de seguir.

**Independiente** de la demo (se puede hacer en cualquier momento, incluso
con la demo apagada): las pruebas automatizadas, las figuras, la compilación
de la app y la de la tesis (sección 8).

---

## 3. Una sola vez (instalación)

### 3.1 Entorno de Python — PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r centro_control\requirements.txt
```

Crea el entorno aislado `.venv` e instala MQTT (paho), SNMPv3 (pysnmp), el
enrutamiento (networkx) y la consola web (FastAPI). La librería `pysnmp`
lleva un parche documentado en `docs/agent.md`; si el agente falla al
arrancar con un error de `builder.py`, aplicarlo.

### 3.2 Broker Mosquitto — PowerShell como administrador

Ver `docs/ARRANQUE_BROKER_LAPTOP.md`, Paso 2 (instalación con `winget`,
`mosquitto.conf` con `listener 1883 0.0.0.0` y regla de firewall). Queda
como servicio de Windows que arranca con el equipo.

### 3.3 Consola web

```powershell
Copy-Item consola\.env.example consola\.env
```

Solo hace falta editar `consola\.env` si se va a supervisar la Raspberry
Pi con otro nombre o IP.

### 3.4 Raspberry Pi y tablet (solo si se usan)

- Pi: `docs/CONEXION_RASPBERRY.md` y `docs/ARRANQUE_BROKER_LAPTOP.md`,
  pasos 3 y 4 (alias SSH `rsu`, despliegue y servicios systemd).
- Tablet: compilar e instalar la app (sección 8.3) y configurar el broker
  en sus Ajustes (`app_obu/README.md`, "Probar en la tablet real").

---

## 4. Antes de presentar (15 minutos antes)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 verificar
```

**Qué hace:** revisa, sin levantar nada, que exista `.venv` con sus
librerías, que Mosquitto esté corriendo y escuchando en el 1883, que estén
el registro de RSU, la trayectoria y el grafo vial del escenario, y si quedó
viva una demo anterior. Por cada problema imprime `[FALLA]` y la línea
**"Que hacer"** con la solución.

Opciones: `-ConPi` revisa también la Raspberry Pi por SSH, y `-ConTablet`
revisa que `adb` vea la tablet. `-Escenario pucp` cambia de escenario.

Recomendaciones:

- Si se usará la Pi: encenderla **10 minutos antes**, para que su reloj
  (chrony) se estabilice.
- Cerrar programas pesados; la demo levanta unos 8 procesos de Python.
- Tener abierta esta guía en la sección 9 ("Si algo falla").

---

## 5. Demo principal (todo en la laptop)

### 5.1 Levantar el sistema

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 iniciar
```

**Qué hace, en orden:**

1. Ejecuta la verificación de la sección 4. Si hay fallas, **no levanta
   nada** y dice qué corregir.
2. Llama a `scripts\demo\lanzar_rsus.ps1` con el registro del escenario
   (`app_obu\pruebas\registro_rsu_hospital_nino.json`: RSU 4, 5 y 6). Por
   cada intersección arranca un controlador emulado y una RSU, en segundo
   plano y sin ventanas, con puertos libres asignados solos (SNMP desde
   1170, controlador desde 9100).
3. Arranca el servidor central con ese mismo registro.
4. Arranca la consola web y abre el navegador en `http://127.0.0.1:8080/`,
   en la pantalla **Misión (varias RSU)**.

Todo queda en `resultados\demo\<fecha>\`: un `.log` y un `.err.log` por
proceso, los eventos de cada RSU y `estado.json` con los puertos y PID.

**Qué se debe ver:** en la consola, las tres RSU con su semáforo cambiando
de fase (sondeo SNMPv3 a 1 Hz). Si una RSU dice "sin conexión", ver la
sección 9.

### 5.2 Lanzar la OBU (la misión)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 obu
```

**Qué hace:** ejecuta `gateway\obu_emulada.py` con la trayectoria del
escenario. La OBU envía el MI (arma la misión), el servidor le responde con
la ruta (MR) y la OBU publica su posición a 1 Hz (MP). Cuando el ETA a la
siguiente intersección baja de 8 s, el servidor envía el M1 a esa RSU, que
lo traduce a NTCIP 1211 hacia su controlador. Al cruzar, el servidor envía
el M3. Al terminar la trayectoria, la OBU cierra la misión (MF).

**Duración:** con `-Factor 4` (por defecto) unos 75 s; con `-Factor 1`
(tiempo real) unos 5 minutos. Para la presentación, `-Factor 4` o `6`.

**Qué se debe ver en la consola:** la ruta en el mapa, el vehículo
avanzando y, en orden, cada RSU pasando por *solicitada → concedida →
liberada*, con la línea de tiempo de mensajes debajo.

### 5.3 Repetir la misión

Basta con volver a ejecutar `presentacion.ps1 obu`. No hace falta reiniciar
el resto.

### 5.4 Detener todo

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 detener
```

**Qué hace:** llama a `scripts\demo\detener_rsus.ps1`, que detiene solo los
procesos que registró el lanzador (con sus procesos hijos). Nunca toca
procesos lanzados a mano ni Mosquitto.

---

## 6. Variante: la OBU es la tablet

Requiere la app instalada (sección 8.3) y la demo levantada (5.1).

1. En la app, **Ajustes**: host del broker = IP de la laptop en la misma
   red Wi-Fi (`ipconfig` en la laptop), o su IP de Tailscale; puerto `1883`.
2. Pantalla principal: **Ruta emulada** > escenario **Hospital del Niño** >
   **Iniciar emergencia**.
3. Se ve lo mismo que en 5.2, más la ruta y el próximo semáforo en la
   tablet. La misión termina sola al llegar al destino.

**Plan B:** si la tablet no conecta, seguir con la OBU emulada
(`presentacion.ps1 obu`): el resto de la demo no cambia.

## 7. Variante: la RSU real (Raspberry Pi)

La Pi corre la RSU 1 como servicios systemd (`rsu-agent` y
`rsu-controller`) conectados al broker de la laptop por Tailscale. Desde
**Git Bash**:

```bash
scripts/pi.sh status agent              # debe decir active (running)
scripts/pi.sh status controller
scripts/pi.sh start controller          # solo si no estaban activos
scripts/pi.sh start agent
scripts/pi.sh logs agent                # ver la RSU en vivo (Ctrl+C para salir)
```

Para mostrar el estado NTCIP de la Pi por SNMPv3 (PowerShell):

```powershell
.\.venv\Scripts\python.exe centro_control\software_gestion.py interactive --host rsu-01 --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123
```

La autenticación es HMAC-SHA-256 con cifrado AES-128; si la Pi todavía
tiene una versión anterior del agente, el gestor será rechazado: desplegar
con `scripts/pi.sh deploy` y reiniciar con `scripts/pi.sh restart agent`.

> La RSU de la Pi (RSU 1) no choca con la demo principal (RSU 4, 5 y 6).
> Sí choca con una **campaña de medición local** (sección 8.2), que también
> usa la RSU 1: el script de la campaña lo detecta y aborta.

---

## 8. Recompilar y regenerar (independiente de la demo)

### 8.1 Pruebas automatizadas — PowerShell

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # todas (unos minutos)
.\.venv\Scripts\python.exe -m pytest -q -m seguridad    # solo la matriz de seguridad
```

Las pruebas `seguridad` levantan un Mosquitto temporal en un puerto libre y
se saltan solas si `mosquitto` no está en el PATH.

**Evidencia de seguridad para la tesis** (tabla T01–T16):

```powershell
.\.venv\Scripts\python.exe scripts\seguridad\correr_matriz.py
```

Escribe `evidencia\<fecha>_seguridad\` con `resultados.csv`, un registro por
caso y `tabla_seguridad.tex`. Si un caso falla, aparece con ✘: no se oculta.

### 8.2 Campañas de medición y figuras

Una campaña **tarda** (decenas de minutos) y **no debe correr junto con la
demo** ni con la RSU 1 de la Pi activa contra el mismo broker. Ejemplo,
escenario `lazo` en local:

```powershell
.\.venv\Scripts\python.exe scripts\campanas\lazo_centralizado.py --escenario lazo --config local
```

Análisis y figuras a partir de las corridas guardadas en
`resultados\campana\` (no hace falta repetir la campaña para regenerar las
figuras):

```powershell
.\.venv\Scripts\python.exe scripts\analisis\graficos_campana_centralizada.py `
  --dir resultados\campana\20261029-005510_lazo_local --etiqueta local `
  --dir resultados\campana\20261029-012758_desvio_local --etiqueta local `
  --dir resultados\campana\20261029-020001_lazo_pi-lan --etiqueta pi-lan `
  --dir resultados\campana\20261029-023433_desvio_pi-lan --etiqueta pi-lan `
  --salida resultados\campana\_figuras_regeneradas

.\.venv\Scripts\python.exe scripts\analisis\resumen_capitulo4.py `
  --dir resultados\campana\20261029-005510_lazo_local `
  --dir resultados\campana\20261029-012758_desvio_local `
  --dir resultados\campana\20261029-020001_lazo_pi-lan `
  --dir resultados\campana\20261029-023433_desvio_pi-lan `
  --salida resultados\campana\_figuras_regeneradas
```

Generan los PDF y PNG de las figuras (`fig_rtt_cdf`, `fig_tramos`,
`fig_comparacion`) y las tablas `.tex` de latencia, condición de llegada y
renovación. Para usarlas en la tesis, copiarlas a la carpeta de figuras del
proyecto LaTeX.

### 8.3 App Android (OBU) — PowerShell, carpeta `app_obu`

```powershell
cd app_obu
.\gradlew.bat assembleDebug
adb devices
adb install -r app\build\outputs\apk\debug\app-debug.apk
cd ..
```

**Qué hace:** compila la app (la primera vez descarga Gradle y las
dependencias: necesita internet y varios minutos), verifica que la tablet
esté conectada por USB y la instala encima de la versión anterior, sin
borrar sus Ajustes. Requiere un JDK con `JAVA_HOME` configurado.

Pruebas unitarias de la app: `.\gradlew.bat testDebugUnitTest`.

### 8.4 Tesis (LaTeX) — carpeta del proyecto LaTeX

En la carpeta del proyecto de la tesis (la copia local del proyecto de
Overleaf):

```powershell
latexmk -pdf main.tex
```

Compila `main.tex` con su bibliografía las veces necesarias hasta resolver
todas las referencias. Si el proyecto usa otro motor (por ejemplo
`-pdflua` o `-pdfxe`), usar el mismo que tiene configurado Overleaf. Si no
hay una distribución de TeX instalada, compilar directamente en Overleaf.

---

## 9. Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `verificar` dice "Mosquitto esta detenido" | El servicio no arrancó | PowerShell como administrador: `Start-Service mosquitto` |
| `verificar` dice "Faltan librerias" | `.venv` incompleto | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r centro_control\requirements.txt` |
| No se puede ejecutar el `.ps1` ("la ejecución de scripts está deshabilitada") | Política de ejecución de Windows | Usar siempre `powershell -ExecutionPolicy Bypass -File ...` como en esta guía |
| `iniciar` aborta por RSU_ID repetido o servidor ya corriendo | Quedó viva una demo anterior | `presentacion.ps1 detener` y volver a `iniciar` |
| `iniciar` muestra `FALLO: middleware RSU n` | La RSU no abrió su puerto SNMP | Abrir `resultados\demo\<fecha>\rsu_n.err.log`; suele ser un puerto ocupado o el parche de `pysnmp` (sección 3.1) |
| La consola no abre | El navegador no se abrió solo, o la consola falló | Abrir `http://127.0.0.1:8080/` a mano; si no carga, ver `consola.err.log` de la corrida |
| Una RSU aparece "sin conexión" en la consola | Su proceso terminó | Ver su `.err.log`; `detener` e `iniciar` de nuevo |
| La OBU arranca pero no llega la ruta (MR) | El servidor no estaba listo o terminó | Revisar `servidor.err.log`; esperar 5 s tras `iniciar` y relanzar `obu` |
| La misión avanza pero ninguna RSU cambia de estado | El servidor usa otro registro que las RSU | Lanzar siempre con `presentacion.ps1`, que usa el mismo registro para ambos |
| La tablet no conecta | IP o red distinta, o firewall | Misma red que la laptop; IP de `ipconfig`; regla del 1883 (`docs/ARRANQUE_BROKER_LAPTOP.md`). Si no, plan B: OBU emulada |
| `adb` no ve la tablet | Depuración USB no autorizada | Desconectar y reconectar el USB y aceptar el aviso en la tablet |
| La Pi no responde | Apagada, sin red o Tailscale caído | `tailscale status`; `scripts/check_pi.sh`. Si no se resuelve en 2 minutos, seguir con la demo principal (todo en la laptop) |
| El gestor SNMPv3 es rechazado por la Pi | Agente de la Pi desactualizado | `scripts/pi.sh deploy` y `scripts/pi.sh restart agent` (Git Bash) |
| `gradlew` falla al compilar | `JAVA_HOME` sin configurar o sin internet la primera vez | Configurar `JAVA_HOME` al JDK; conectar a internet para la primera descarga |
| La campaña aborta diciendo que el agente de la Pi está activo | La RSU 1 de la Pi usa el mismo broker | Detenerlo mientras dure la campaña (`scripts/pi.sh stop agent`) y volver a arrancarlo al terminar |

**Regla general:** cada proceso de la demo deja su salida en
`resultados\demo\<fecha>\<proceso>.err.log`. El primer error de ese archivo
suele decir exactamente qué pasó.

**Si todo falla durante la presentación:** `presentacion.ps1 detener`,
luego `presentacion.ps1 iniciar` (unos 30 s) y `presentacion.ps1 obu`.

---

## 10. Referencia rápida

| Quiero… | Comando |
|---|---|
| Revisar que todo esté listo | `presentacion.ps1 verificar` |
| Levantar la demo | `presentacion.ps1 iniciar` |
| Lanzar una misión | `presentacion.ps1 obu` (`-Factor 1` en tiempo real) |
| Otro escenario | agregar `-Escenario pucp` |
| Detener todo | `presentacion.ps1 detener` |
| Correr las pruebas | `.\.venv\Scripts\python.exe -m pytest -q` |
| Evidencia de seguridad | `.\.venv\Scripts\python.exe scripts\seguridad\correr_matriz.py` |
| Compilar la app | `cd app_obu; .\gradlew.bat assembleDebug` |
| Compilar la tesis | `latexmk -pdf main.tex` (en la carpeta de la tesis) |

(`presentacion.ps1` es `powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1`.)

Documentación relacionada: `docs/CONSOLA.md` (consola y lanzador),
`docs/ARRANQUE_BROKER_LAPTOP.md` (broker y Raspberry Pi),
`docs/CONTRATO_OBU.md` (mensajes), `app_obu/README.md` (app y tablet),
`docs/MEDICION_LATENCIA.md` (métricas de las campañas).
