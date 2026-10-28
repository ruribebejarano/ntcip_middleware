# Plan de implementación — 12 oct. al 20 nov. de 2026

Este plan sustituye la Fase II en adelante de `CRONOGRAMA.md`. El alcance es el reducido de la tesis: sin Wi-SUN, sin ETA, sin NTCIP 1209, I2I por 4G/Ethernet a través del broker y OBU con criterio de geocerca.

**Regla:** cada hito cierra con (1) un commit, (2) una entrada en `docs/bitacora/` y (3) evidencia en `evidencia/`. Sin evidencia, el hito no existe para la tesis.

Orden de prioridad, si algo se atrasa: **OE3 y OE6 (lazo OBU → RSU → controlador) antes que OE4 (I2I)**.

---

## Semana 1 · 12–18 oct. — Base y middleware NTCIP (OE3)

| Hito | Prompt | Evidencia a capturar |
|---|---|---|
| Contexto del repo actualizado | P0 | — |
| Registro de eventos con marcas de tiempo (RF-13) | P1 | Fragmento del CSV de eventos de una corrida |
| Objetos NTCIP 1202 reales y controlador emulado con ciclo de fases | P2 | `snmpwalk` sobre el subárbol 1202; consola del emulador cambiando de fase |
| Objetos NTCIP 1211, verificación de límites (RF-06) y caducidad (RF-09) | P3 | `snmpset` de una solicitud y su lectura posterior; log de una transición **rechazada** por tiempos mínimos; log de una cancelación por caducidad a los 3 s |

## Semana 2 · 19–25 oct. — Seguridad y canal V2I (RNF-05, OE5)

| Hito | Prompt | Evidencia a capturar |
|---|---|---|
| CA propia y mTLS en Mosquitto (TLS 1.3) | P4 | Configuración del broker; cliente **rechazado** sin certificado; Wireshark con el *handshake* TLS 1.3 y la carga cifrada |
| Decisión TLSTM frente a USM (G1) | P4 | Entrada de bitácora con la desviación del diseño |
| OBU simulada: M1–M3 a 1 Hz, geocerca, lista estática de RSU e identificación de acceso (RF-01 a RF-04, RF-14) | P5 | Consola de la OBU emitiendo, actualizando y cancelando; mapa o gráfico de la trayectoria con la geocerca |

## Semana 3 · 26 oct.–1 nov. — Hardware real y campaña V2I

| Hito | Prompt | Evidencia a capturar |
|---|---|---|
| RSU por 4G (SIM7670G) hacia el broker remoto — **operativo desde 2026-10-28**, ver `docs/MODEM_4G.md` y `docs/bitacora/2026-10-28_modem-4g.md` | P6 | Foto del montaje RPi + módulo 4G (pendiente); `ip addr`/`scripts/pi.sh red estado` mostrando la IP del operador (**privada `10.x`, no `100.64.x.x`** — ese rango es el de la red superpuesta Tailscale, no el de CGNAT del operador celular; corregido tras la puesta en marcha real); conexión TLS al broker por 4G (pendiente, ver gate G3 de `CRONOGRAMA.md`) |
| Lectura OBD-II real de velocidad (PID 0x0D) | P7 | Foto del lector conectado al vehículo; log de velocidades |
| **Campaña de latencia V2I** (sección 4.3) | P6 | Corridas en `resultados/v2i/`; figuras generadas |

## Semana 4 · 2–8 nov. — I2I y lazo completo (OE4, OE6)

| Hito | Prompt | Evidencia a capturar |
|---|---|---|
| Segunda RSU, chrony y M4 a 1 Hz (RF-10 a RF-12) | P8 | `chronyc tracking` en ambas RSU; log de M4 con desfase calculado |
| **Campaña de sincronización** (sección 4.4) | P8 | Serie temporal del error de sincronización |
| **Lazo completo** OBU → RSU → controlador (sección 4.5) | P9 | Línea de tiempo de un ensayo; foto del banco completo |

## Semana 5 · 9–15 nov. — Capítulo 4 y conclusiones
Pruebas de seguridad (4.6), tabla de cumplimiento (4.7), discusión (4.8) y conclusiones por OE.

## 16–20 nov. — Revisión final y entrega
Sin desarrollo nuevo.

---

# Prompts para Claude Code (abrir en `E:\Tesis\ntcip_middleware`)

> Para que Claude Code lea la tesis, agrega primero la carpeta: `/add-dir F:\tesis2\Overleaf`.
> Pega **un prompt por sesión** y no avances al siguiente sin el commit y la bitácora del anterior.

### P0 — Actualizar el contexto del repositorio
```
Lee F:\tesis2\Overleaf\main.tex (secciones ssec:rf, ssec:rnf, ssec:alcance, sec:arquitectura, sec:middleware, sec:malla, sec:diseno_seguridad) y docs/PLAN_IMPLEMENTACION.md. Actualiza CLAUDE.md y la sección "Alcance" de README.md para que reflejen el alcance actual: sin Wi-SUN ni CC1352P (I2I por 4G/Ethernet a través del broker MQTT), sin cálculo de ETA (criterio provisional de geocerca), sin NTCIP 1209, esquema de direccionamiento E2+E4 con lista estática de RSU, y los IDs actuales de RF y RNF. Agrega a CLAUDE.md esta regla: "Al terminar cada tarea que deje algo funcionando: commit con prefijo OEx, y una entrada en docs/bitacora/ con la plantilla docs/bitacora/_plantilla.md, indicando requerimientos cubiertos, versiones, desviaciones respecto de main.tex y la lista de capturas que el estudiante debe tomar." No toques el código. Commit: "docs: actualiza alcance al estado actual de la tesis".
```

### P0.5 — Trabajo conjunto laptop ↔ Raspberry Pi (hacer después de P0)
```
Lee docs/CONEXION_RASPBERRY.md y scripts/. Quiero que tú (Claude Code, en la laptop) puedas desplegar, ejecutar y recoger resultados en la Raspberry Pi sin que yo copie comandos a mano. Haz lo siguiente, preguntándome antes de cualquier cambio de red en la Pi (regla de CLAUDE.md):
1. Verifica con scripts/check_pi.sh que el alias ssh "rsu" responde. Si falla, dime exactamente qué paso de docs/CONEXION_RASPBERRY.md me falta.
2. Crea scripts/pi.sh con subcomandos: deploy (git push desde la laptop + git pull en la Pi + pip install si cambió requirements.txt), start/stop/restart/status/logs <servicio>, y fetch (rsync o scp de resultados/ de la Pi a resultados/ de la laptop). El host va como parámetro (rsu por defecto, rsu2 para la segunda RSU).
3. Crea unidades systemd en deploy/systemd/ para el agente, el controlador emulado y mosquitto, e instálalas en la Pi, para manejar los servicios con scripts/pi.sh en vez de dejar terminales abiertas.
4. Sincronización de relojes: la latencia entre la OBU (laptop) y la RSU (Pi) se mide con marcas de tiempo de dos máquinas distintas, así que ambas deben estar sincronizadas por NTP con la misma referencia. Configura chrony en la Pi y dime cómo verificar la sincronización en Windows (w32tm) o qué alternativa usar. Agrega a scripts/pi.sh un subcomando "clock" que muestre el offset de ambas máquinas antes de cada campaña, y guarda ese offset en el config.json de cada corrida.
5. Agrega a .claude/settings.json permisos para ssh rsu, ssh rsu2, scripts/pi.sh y scripts/check_pi.sh, para no tener que aprobar cada llamada.
6. Documenta todo en docs/CONEXION_RASPBERRY.md, haz la entrada de bitácora y el commit "infra: flujo laptop-Pi".
```

### P1 — Registro de eventos (RF-13)
```
Implementa un módulo común de registro de eventos del lazo de priorización (RF-13 en main.tex). Cada evento es una fila CSV con: marca de tiempo en epoch y ns (time.time_ns), nodo (obu/rsu_i/ctrl), tipo de evento (M1_tx, M1_rx, snmp_set_tx, ctrl_fase_cambio, M2_tx, M2_rx, M3_tx, caducidad, M4_tx, M4_rx...), id_solicitud y campos extra en JSON. Intégralo en agent/, controller/ y gateway/. Agrega scripts/analisis/latencia_tramos.py, que cruce los eventos por id_solicitud y calcule la latencia por tramo según la ecuación de ssec:latencia de main.tex. Prueba con una corrida local y guarda la salida en resultados/prueba_registro/. Bitácora y commit.
```

### P2 — NTCIP 1202 y controlador emulado
```
Sustituye los OID ficticios del agente por objetos reales de NTCIP 1202 v03. Fuentes: E:\Tesis\respaldos\extraccion_ntcip1202\NTCIP1202-v03_BORRADOR_SIN_VERIFICAR.mib y E:\Tesis\datasheets\NTCIP-1202v03.35e-aspublished.pdf (el PDF manda si hay conflicto). Implementa solo el subconjunto que exige la tesis: estado de fases (phaseStatusGroup...), tiempos de fase (verde mínimo, ámbar, todo rojo) y el objeto del desfase de coordinación. Antes de programar, dime qué OID vas a usar y su unidad y resolución. Necesito además la resolución del desfase para fijar RNF-04 en main.tex. Haz que controller/controller_emulator.py ejecute un ciclo de fases real con esos tiempos. Verifica con snmpwalk desde la PC. Bitácora con la lista de capturas que debo tomar, y commit "OE3: ...".
```

### P3 — NTCIP 1211, límites y caducidad
```
Implementa en el agente el subconjunto de NTCIP 1211 v02 necesario para el lazo: SET de prgPriorityRequestAbsolute, tabla priorityRequestTable y estado de la solicitud (ver Figura 15 y la sección 4.2.3 de la norma). MIB: E:\Tesis\datasheets_ntcip1211\*.mib (borrador extraído; puede requerir arreglos para compilar con pysmi. Documenta cada arreglo en la bitácora). Agrega: (a) verificación de límites antes de cada escritura al controlador (RF-06: no violar verde mínimo, ámbar ni todo rojo), (b) caducidad de la solicitud a T_cad = 3 s sin actualización (RF-09), (c) rechazo de clases de vehículo no reconocidas (RF-05). Agrega tests en tests/ para los tres casos. Bitácora y commit.
```

### P4 — Seguridad: CA, mTLS y decisión TLSTM
```
(1) Crea scripts/pki/ con scripts openssl que generen una CA propia y certificados para el broker, la OBU y cada RSU (ECDSA P-256), según ssec:seg_pki de main.tex. (2) Configura Mosquitto para escuchar en 8883 solo con TLS 1.3 y certificado de cliente obligatorio, y adapta todos los clientes MQTT. (3) Comprueba que una conexión sin certificado es rechazada. (4) Verifica si pysnmp soporta TLSTM (RFC 6353). Si no lo soporta, NO lo implementes: registra en la bitácora la desviación (en el prototipo se usa USM authPriv) e indica qué secciones de main.tex habría que ajustar (ssec:sel_snmp y ssec:seg_tlstm). Bitácora con la lista de capturas (incluida la de Wireshark) y commit.
```

### P5 — OBU simulada con geocerca
```
Reescribe gateway/obu_simulator.py como la OBU del diseño: lee una trayectoria (CSV con t, lat, lon, rumbo, velocidad) y la reproduce en tiempo real; carga al inicio una lista estática de RSU y la geometría de accesos (JSON); identifica la intersección y el acceso con la regla de ssec:zonas de main.tex (RF-14); emite M1 al entrar en una geocerca de radio R_g configurable (RF-03), lo actualiza a 1 Hz y emite M3 al cruzar (RF-04). Los campos de M1, M2 y M3 deben coincidir con la tabla de mensajes de main.tex. Usa mTLS. Incluye dos trayectorias sintéticas de ejemplo en resultados/trayectorias/. Bitácora y commit "OE5: ...".
```

### P6 — RSU por 4G y campaña de latencia V2I
```
Usando "F:\tesis2\Overleaf\Comandos módulo 4G SIM7670G y MQTT.pdf", documenta y automatiza en scripts/ la conexión de la RSU por el módulo SIM7670G (servicio systemd que levante la interfaz). Luego crea scripts/campanas/v2i.py, que ejecute N solicitudes con la OBU simulada contra la RSU por 4G y guarde cada corrida en resultados/v2i/<fecha>/ (datos.csv, config.json con el commit y notas.md). Y crea scripts/analisis/v2i.py, que genere en F:\tesis2\Overleaf\figuras\resultados\ la CDF de latencia extremo a extremo, un diagrama de cajas por tramo y una tabla LaTeX con media, mediana, percentil 95 e intervalo de confianza. Bitácora y commit.
```

### P7 — Lectura OBD-II real
```
Agrega gateway/obd_reader.py, que lea la velocidad (PID 0x0D) desde un lector ELM327 por Bluetooth o serie con la librería python-OBD, a 1 Hz, y la registre con el módulo de eventos. Debe poder alimentar a la OBU en lugar de la velocidad de la trayectoria. Incluye un modo de prueba sin vehículo (emulador de ELM327, si existe uno disponible). Bitácora con la lista de fotos y capturas, y commit.
```

### P8 — I2I y sincronización
```
Implementa el canal I2I según sec:malla de main.tex: cada RSU publica M4 a 1 Hz por el broker con la marca de tiempo de inicio de fase y calcula el desfase respecto de la vecina (RF-11, RF-12). Configura chrony en ambas RSU (scripts/chrony/). Crea scripts/campanas/sync.py, que registre durante X minutos el offset de chrony y la diferencia de marcas de tiempo entre RSU, y scripts/analisis/sync.py, que genere la serie temporal y la distribución del error en F:\tesis2\Overleaf\figuras\resultados\. Si solo hay una Raspberry Pi, dime qué alternativa usar para la segunda RSU (por ejemplo, la PC) y qué limita eso. Bitácora y commit "OE4: ...".
```

### P9 — Lazo completo
```
Crea scripts/campanas/lazo.py para el ensayo de punta a punta (sección 4.5 de main.tex): OBU → broker → RSU → controlador emulado → M2 de vuelta, con trayectorias reproducidas. Guarda las corridas en resultados/lazo/ y genera la línea de tiempo de un ensayo representativo y la tabla resumen de N ensayos en F:\tesis2\Overleaf\figuras\resultados\. Bitácora y commit "OE6: ...".
```

---

# Prompt semanal para la tesis (abrir en `F:\tesis2\Overleaf`)
```
/add-dir E:\Tesis\ntcip_middleware
Lee las entradas de E:\Tesis\ntcip_middleware\docs\bitacora\ posteriores a la última que ya está reflejada en main.tex. Redacta o completa las subsecciones de implementación del Capítulo III que correspondan, en el estilo del documento (español formal, impersonal). Inserta como figuras las capturas de E:\Tesis\ntcip_middleware\evidencia\ que la bitácora indique, copiándolas a figuras/implementacion/. Si una entrada registra una desviación respecto del diseño, NO cambies el texto de diseño: avísame y propón la redacción. No inventes datos. Compila y haz commit.
```
