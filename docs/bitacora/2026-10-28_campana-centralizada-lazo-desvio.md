# 2026-10-28 — Campaña local (lazo, desvío): choque de client_id y exclusión de "conflicto"

**Objetivo específico:** OE5 (campaña de medición del lazo, `config=local`)
**Requerimientos:** RNF-01 (latencia L), RF8 (anticipación real)
**Sección de la tesis:** 4.3–4.5 (campaña y resultados) / 3.9, 4.8 (limitaciones y trabajo futuro)
**Commit:** (pendiente, se completa al cerrar esta entrada)

## Qué se implementó

Dos cosas separadas, no confundirlas:

1. **Diagnóstico y corrección de una campaña contaminada.** Las cinco
   corridas locales de hoy (tres de una sesión anterior, dos de esta)
   tenían entre 47 y 59 líneas `"Conectado al broker MQTT"` por
   repetición en `agent.log`, cuando debería haber exactamente **una**.
   Causa real: `rsu-agent.service` en la Pi, activo sin interrupción
   desde el 2026-10-11, con
   `/etc/systemd/system/rsu-agent.service.d/broker.conf` apuntando al
   broker Mosquitto de **esta laptop** (`MQTT_BROKER_HOST=100.121.77.97`,
   su IP Tailscale) con `RSU_ID=1` — el mismo `client_id`
   (`rsu-middleware-1`, `agent/rsu_middleware.py:845`) que usa cada
   agente local que lanza `scripts/campanas/lazo_centralizado.py` contra
   `127.0.0.1:1883` (el mismo broker físico). Mosquitto expulsa a quien
   tenía ese `client_id` cuando el otro se conecta: los dos agentes se
   expulsaban uno al otro en bucle, y las solicitudes que llegaban
   mientras el agente local estaba "afuera" del broker se perdían sin
   dejar ningún rastro en sus eventos (`sin_respuesta`). **No fue falta
   de memoria** — se verificó en el log antes de atribuir una causa, como
   se pidió.
2. **Exclusión del escenario `conflicto` de la campaña y del Capítulo 4**
   (decisión del autor, no un hallazgo técnico): es un caso demasiado
   específico para el alcance de esta tesis. El código
   (`servidor/conflictos.py`, el soporte en el runner y en el análisis)
   se conserva sin cambios y sigue verificado con
   `tests/test_conflictos.py`; solo se saca de la campaña de medición.

## Cómo

- **Diagnóstico** (sin cambiar código primero, como se pidió):
  - Procesos vivos en la laptop (`Get-CimInstance Win32_Process -Filter
    "name='python.exe'"`): ninguno huérfano en el momento de revisar (los
    pares que parecían duplicados eran el *launcher stub* de
    `.venv\Scripts\python.exe` en Windows —254 KB, relanza el intérprete
    real de `C:\Program Files\Python313\` como hijo— no dos campañas
    corriendo a la vez).
  - `scripts/pi.sh status agent rsu`: **activo**, reconectando cada ~2 s
    en vivo (`journalctl`, 19:39:14 → 19:39:33...), con el
    `broker.conf` ya descrito.
  - Log de Mosquitto: no existe. `mosquitto.conf` (ruta real
    `C:\Program Files (x86)\Mosquitto\mosquitto.conf`, no
    `C:\Program Files\mosquitto\` como dice `docs/ARRANQUE_BROKER_LAPTOP.md`
    — desviación menor, **[REVISAR]** corregir esa ruta en la doc) no
    tiene `log_dest`: no hay forma de citar literalmente
    "already connected"/"closing old connection". La reconexión cada 2 s
    capturada en la Pi es la evidencia directa.
  - Conteo exacto por repetición (`grep -c "Conectado al broker"
    rep_NN/agent.log`) en las cuatro corridas con agente local: entre 47 y
    59 por repetición, confirmando el choque en las cinco corridas de hoy
    (incluida `20261028-184751_conflicto_local`, aunque esa además está
    fuera de alcance por el punto 2).
- **Corrección aplicada:**
  - `scripts/pi.sh stop agent rsu` (2026-10-28 19:42) — detiene el agente
    de la Pi mientras se corren campañas `config=local`.
  - `scripts/campanas/lazo_centralizado.py`:
    `_verificar_sin_interferencia_local()` (nueva, se corre una vez al
    inicio si `config=local`): aborta si `CONTROLLER_PORT`/`SNMP_PORT` ya
    están ocupados (proceso huérfano) o si `rsu-agent.service` sigue
    activo en el host dado (mismo client_id); si no se puede verificar
    (Pi apagada/inalcanzable), avisa y continúa — no bloquea una prueba
    local solo porque la Pi no responde.
  - `_contar_conexiones_broker()` / `_verificar_una_sola_conexion()`
    (nuevas, se corren después de cada repetición): cuentan
    `"Conectado al broker"` en `agent.log`/`servidor.log` de esa
    repetición; abortan si hay más de una.
  - `tests/test_campana_runner.py` (nuevo): prueba el conteo y el
    chequeo en aislado con logs sintéticos (no se puede reproducir el
    choque real sin dos procesos de verdad).
- **Verificación de la corrección:** corrida de prueba (2 repeticiones,
  escenario `lazo`) después de detener el agente de la Pi: `agent.log`
  de ambas repeticiones con **1** conexión, no 47-59.
- **Exclusión de `conflicto`:** `docs/CRONOGRAMA.md` (decisión de alcance
  #2, tabla de avance OE4, S9), `docs/MEDICION_LATENCIA.md` (§8.3, nuevo
  banner en §8.6), y banners en los docstrings de
  `scripts/campanas/lazo_centralizado.py` y
  `scripts/analisis/lazo_centralizado.py::analizar_conflicto()`. Ningún
  código se borró.

## Redacción propuesta para la tesis (limitaciones / trabajo futuro)

**[REVISAR con asesor]**, texto exacto pedido por el estudiante, para
insertar en limitaciones/trabajo futuro (`main.tex`, sección a definir
por el estudiante — no se tocó `main.tex` en esta sesión):

> El servidor central incluye una lógica de arbitraje entre misiones
> simultáneas que solicitan accesos incompatibles de una misma
> intersección (`servidor/conflictos.py`), verificada mediante pruebas
> unitarias; su evaluación experimental queda fuera del alcance de este
> trabajo.

## Desviaciones respecto del diseño de la tesis

- La exclusión de `conflicto` de la campaña (punto 2 arriba) es una
  desviación de alcance explícita, no un hallazgo técnico — ya
  documentada en `docs/CRONOGRAMA.md`.
- `docs/ARRANQUE_BROKER_LAPTOP.md` tiene la ruta de instalación de
  Mosquitto equivocada (`C:\Program Files\mosquitto\`, debería ser
  `C:\Program Files (x86)\Mosquitto\`). **[REVISAR]** corregir esa ruta;
  no se tocó en esta sesión (fuera del pedido explícito).
- Mosquitto corre sin `log_dest`: no queda registro persistente de
  eventos del broker (conexiones, expulsiones). **[REVISAR con asesor]**
  si vale la pena agregarlo antes de la campaña con hardware real
  (ayudaría a diagnosticar justo este tipo de problema sin depender de
  los logs del lado del cliente).

## Evidencia

- `resultados/campana/_descartadas/` con `NOTA.md`: las cinco corridas
  contaminadas y/o fuera de alcance, con el motivo de cada una.
- Corrida limpia, con el agente de la Pi detenido y los chequeos nuevos
  activos: `resultados/campana/20261028-195302_lazo_local/` y
  `resultados/campana/20261028-201105_desvio_local/` (10 repeticiones
  c/u). Confirmado `grep -c "Conectado al broker" rep_NN/agent.log` = 1
  en las 20 repeticiones (antes: 47-59).
- Resultado: **0 `sin_respuesta` en las dos corridas** (10/10 concedidas
  cada una) — el choque de client_id era, en efecto, toda la causa; no
  hizo falta investigar ninguna otra causa en los logs porque no quedó
  ningún caso sin explicar.
- `resultados/campana/_figuras_2026-10-28/`: `fig_rtt_cdf`, `fig_tramos`,
  `fig_comparacion` (.pdf/.png) y `tabla_latencia.tex`, comparando `lazo`
  vs. `desvio` (`scripts/analisis/graficos_campana_centralizada.py`).
  Resumen (un solo reloj, `config=local`):

  | Métrica | lazo (mediana / p95 ms) | desvío (mediana / p95 ms) |
  |---|---|---|
  | RTT_srv | 18.80 / 35.14 | 17.23 / 41.06 |
  | t_RSU | 3.65 / 18.20 | 3.07 / 24.13 |
  | L (RNF-01) | 4.86 / 18.76 | 3.67 / 24.64 |

  RNF-01 (`L` p95 ≤ 1000 ms) **CUMPLE** en ambos escenarios, con amplio
  margen (p95 real ~20-25 ms). `desvio` no tiene anticipación real
  medible (`n=0`): mismo comportamiento que la corrida de referencia del
  2026-10-22, no es una regresión de esta sesión — pendiente de entender
  por qué (**[REVISAR]**, no investigado a fondo en esta sesión).

## Problemas y solución

Ver "Cómo" arriba (es el mismo contenido: síntoma, causa, corrección).

## Pendiente

- **PARADA 1** (próxima configuración de red para la campaña, propuesta
  — NO aplicada, no se toca la Pi hasta confirmación): broker en la
  laptop + Pi por Wi-Fi (configuración ya validada hoy, status quo) vs.
  una propuesta para Ethernet real que **no** reutilice el nombre de
  perfil `netplan-eth0` de NetworkManager (reservado para el módem 4G,
  ver `docs/MODEM_4G.md` sección 1 — si un cable Ethernet real se
  conectara y su perfil también se llamara o se detectara como
  `netplan-eth0`, `scripts/red_4g.sh` y `scripts/pi.sh red` apuntarían al
  perfil equivocado). Pendiente de que el estudiante confirme cuál usar.
- Repetir la campaña (lazo, desvío) contra la Pi real (`config=pi-lan` /
  `pi-4g`), una vez resuelta la PARADA 1.
- Corregir la ruta de instalación de Mosquitto en
  `docs/ARRANQUE_BROKER_LAPTOP.md`.
- Evaluar agregar `log_dest` a `mosquitto.conf` antes de la campaña con
  hardware real.
