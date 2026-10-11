# Guía de comandos — lazo de gestión SNMP + V2I

Corre el lazo completo descrito en el README con **una Raspberry Pi (la RSU)
y una PC** (centro de control + OBU simulada). No hace falta un
microcontrolador de radio, malla I2I ni un controlador de tránsito real.

Necesitás **2 terminales en la Raspberry Pi** (controlador + middleware) y
**1-2 en la PC** (centro de control y/o OBU simulada).

---

## 0. Requisitos previos (una sola vez)

### En la Raspberry Pi (RSU)

Si ya seguiste `docs/agent.md`, el entorno (`~/rsu-env` con `pysnmp`
parcheado) y `mosquitto` ya deberían estar instalados. Falta un solo paso
nuevo: permitir que `mosquitto` acepte conexiones desde la PC (por defecto
muchas distros lo dejan escuchando solo en `localhost`).

```bash
sudo tee /etc/mosquitto/conf.d/rsu-lab.conf > /dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
sudo systemctl restart mosquitto
sudo systemctl status mosquitto --no-pager
```

⚠️ `allow_anonymous true` es **solo para el banco de pruebas de
laboratorio** (sin autenticación ni TLS) — ver "Advertencia de seguridad"
en el README.

Confirmá la IP de la Raspberry Pi (la vas a necesitar desde la PC):

```bash
hostname -I
```

### En la PC

```bash
cd ntcip_middleware
python -m venv .venv
```

PowerShell (Windows):
```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r centro_control\requirements.txt
```

Linux/macOS:
```bash
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r centro_control/requirements.txt
```

Aplicar el parche manual de `pysnmp` (bug conocido, ver `docs/agent.md`) —
editar `<venv>/Lib/site-packages/pysnmp/smi/builder.py` (Windows) o
`<venv>/lib/python3.13/site-packages/pysnmp/smi/builder.py` (Linux) según el
diff documentado en `docs/agent.md`. Si preferís aplicarlo con un script en
vez de a mano, se puede adaptar el de `snmp-playground/windows/patch_pysnmp.py`.

---

## 1. Levantar la RSU (Raspberry Pi) — 2 terminales

**Terminal A — controlador de tránsito (emulado):**
```bash
source ~/rsu-env/bin/activate
python3 controller/controller_emulator.py
```
No imprime nada por sí solo salvo cuando recibe una solicitud de prioridad
o esta vence.

**Terminal B — middleware (SNMP + V2I + adaptador):**
```bash
source ~/rsu-env/bin/activate
python3 agent/rsu_middleware.py
```
Tiene que arrancar sin errores e imprimir algo como:
```
[middleware] Conectado al broker MQTT (127.0.0.1:1883), reason_code=...
[middleware] Escuchando solicitudes V2I en mqtt://127.0.0.1:1883/rsu/v2i/solicitud_prioridad
SNMP escuchando en 0.0.0.0:1161 (usuario USM: rsuLabUser, ...)
  1.3.6.1.4.1.99999.1.1.0 = faseActualTest (solo lectura: 1=rojo 2=amarillo 3=verde)
  1.3.6.1.4.1.99999.1.2.0 = solicitudPrioridadTest (lectura/escritura: 0/1)
```

Si el middleware no puede conectarse al broker MQTT, revisá que `mosquitto`
esté corriendo (`sudo systemctl status mosquitto`) antes de seguir.

---

## 2. Desde la PC — software de gestión central (SNMP)

Reemplazá `<IP_RSU>` por la IP real (paso 0). El software de gestión
(`centro_control/software_gestion.py`) tiene tres formas de usarse:

### 2a. Modo interactivo (menú con logs — recomendado para demostrar el lazo)

```powershell
.\.venv\Scripts\python.exe centro_control\software_gestion.py interactive `
  --host <IP_RSU> --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123
```

Muestra un menú (ver estado, activar/liberar prioridad, monitoreo continuo,
salir) y registra cada acción como un log con timestamp, simulando una
consola de operación real.

### 2b. Modo monitoreo continuo (solo logs, sin menú)

```powershell
.\.venv\Scripts\python.exe centro_control\software_gestion.py monitor `
  --host <IP_RSU> --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  --interval 5
```

Útil para dejarlo corriendo de fondo en una terminal mientras probás el
resto (OBU, comandos manuales desde otra terminal) en otra.

### 2c. Comandos puntuales (scripting)

```powershell
$RSU = "<IP_RSU>"
.\.venv\Scripts\python.exe centro_control\software_gestion.py get --host $RSU --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  1.3.6.1.4.1.99999.1.1.0

.\.venv\Scripts\python.exe centro_control\software_gestion.py walk --host $RSU --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  1.3.6.1.4.1.99999.1

# Forzar prioridad a mano (sin pasar por la OBU), como si fuera un operador humano:
.\.venv\Scripts\python.exe centro_control\software_gestion.py set --host $RSU --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  1.3.6.1.4.1.99999.1.2.0 int:1

# Liberarla:
.\.venv\Scripts\python.exe centro_control\software_gestion.py set --host $RSU --port 1161 `
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 `
  1.3.6.1.4.1.99999.1.2.0 int:0
```

(En Linux/macOS: mismo comando, cambiando `.\.venv\Scripts\python.exe` por
`./.venv/bin/python` y las comillas invertidas de fin de línea de
PowerShell (`` ` ``) por `\`.)

---

## 3. Desde la PC — OBU simulada (V2I por MQTT)

```powershell
.\.venv\Scripts\python.exe gateway\obu_simulator.py --broker-host $RSU `
  --vehiculo-id ambulancia-1 --eta-seg 8
```

---

## 4. Flujo de prueba sugerido (ver el lazo completo de punta a punta)

1. Con el controlador y el middleware corriendo (paso 1), abrí el software
   de gestión en modo `monitor` o `interactive` (opción 4 del menú) — la
   fase debería ciclar sola entre `rojo`, `verde` y `amarillo` en los logs.
2. En otra terminal de la PC, corré `gateway/obu_simulator.py` (paso 3)
   simulando que se acerca una ambulancia.
3. En la Terminal B (middleware) tiene que aparecer:
   `[middleware] Solicitud V2I recibida de 'ambulancia-1' (ETA 8.0s) -> reenviando al controlador`
4. En la Terminal A (controlador) tiene que aparecer:
   `[controlador] Prioridad solicitada por 'ambulancia-1' ... -> fase forzada a verde por 15s`
5. En los logs del software de gestión (paso 1) tiene que verse
   `fase=verde  prioridad_activa=si` en la siguiente lectura.
6. Esperá 15 segundos (o activá la opción 3 del menú interactivo /
   `set ... int:0` a mano) y confirmá que la fase vuelve a ciclar sola.

Si los 6 pasos funcionan, los tres enlaces (centro de control ↔ RSU, RSU →
controlador, OBU → RSU) están validados de punta a punta.

---

## Referencia rápida de OID

| OID | Nombre | Acceso | Significado |
|---|---|---|---|
| `1.3.6.1.4.1.99999.1.1.0` | `faseActualTest` | solo lectura | `1`=rojo, `2`=amarillo, `3`=verde |
| `1.3.6.1.4.1.99999.1.2.0` | `solicitudPrioridadTest` | lectura/escritura | `0`=sin prioridad, `1`=prioridad activa |

Ver `agent/rsu_middleware.py` para el detalle de por qué estos OID son
ficticios (número de empresa no registrado, sin MIB estandarizada todavía).
