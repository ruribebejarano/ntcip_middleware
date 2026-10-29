# Corridas descartadas — 2026-10-28

No usar ninguna de estas carpetas en el análisis de la campaña. Dos
motivos distintos, no confundir uno con otro:

## 1. Choque de client_id (datos inválidos, las cinco carpetas)

`rsu-agent.service` en la Pi (activo sin interrupción desde 2026-10-11,
con `/etc/systemd/system/rsu-agent.service.d/broker.conf`:
`MQTT_BROKER_HOST=100.121.77.97` — la IP Tailscale de ESTA laptop —
`RSU_ID=1`) estuvo conectado al **mismo** broker Mosquitto de la laptop
que usan las campañas `config=local`, con el **mismo** `client_id`
(`rsu-middleware-1`, `agent/rsu_middleware.py:845`). Mosquitto expulsa a
quien tenía ese `client_id` cuando otro cliente se conecta con el mismo
id: los dos agentes (el de la Pi y el que lanza cada repetición local) se
expulsaban uno al otro en bucle.

Verificado con `grep -c "Conectado al broker" rep_NN/agent.log` en las
cuatro corridas que llegaron a tener agente local: **47 a 59 conexiones
por repetición**, no 1. El síntoma visible (`sin_respuesta` en varias
repeticiones de `lazo_resumen.json`) es consecuencia directa de esto, NO
de memoria insuficiente ni de puertos sin liberar entre repeticiones (esa
hipótesis se descartó: no hubo que atribuir nada sin evidencia, se
verificó el log).

Se detuvo `rsu-agent.service` en la Pi (`scripts/pi.sh stop agent rsu`,
2026-10-28 19:42) y se agregó la verificación correspondiente al runner
(`scripts/campanas/lazo_centralizado.py::_verificar_sin_interferencia_local`
y `_verificar_una_sola_conexion`, que ahora abortan si vuelve a pasar).
Ver `docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md`.

- `20261028-180853_lazo_local`
- `20261028-182928_desvio_local`
- `20261028-191800_lazo_local`
- `20261028-193548_desvio_local` (además incompleta: solo llegó a rep_02/03, la corrida se detuvo a mano)

## 2. Fuera de alcance (decisión del autor, 2026-10-28)

El escenario `conflicto` queda fuera de la campaña de medición y del
Capítulo 4 (caso demasiado específico para el alcance de la tesis; el
arbitraje sigue verificado con `tests/test_conflictos.py`). Ver
`docs/CRONOGRAMA.md` (decisión de alcance #2) y la bitácora arriba. Esta
corrida, además, también tiene el problema del punto 1 (mismo choque de
client_id), así que sobran dos motivos para no usarla:

- `20261028-184751_conflicto_local`

## 3. `--broker-host` apuntaba a un broker equivocado (datos inválidos, las tres carpetas)

Primeras corridas `config=pi-lan` del 2026-10-28: el servidor (laptop) se
conectó, con éxito, al Mosquitto **propio de la Pi**
(`--broker-host 100.105.28.51`, siguiendo lo que decía entonces el
docstring de `scripts/campanas/lazo_centralizado.py`), pero el agente
real de la Pi está conectado, desde `docs/ARRANQUE_BROKER_LAPTOP.md`, al
Mosquitto **de la laptop**
(`deploy/systemd/rsu-agent.service.d/broker.conf`:
`MQTT_BROKER_HOST=100.121.77.97`). Dos brokers Mosquitto independientes:
cada M1 se publicaba en uno sin que nadie lo escuchara del otro lado →
100 % `sin_respuesta` (etapa `m1_tx_sin_m1_rx`), no un problema de
client_id esta vez. Corregido el docstring del runner y repetida la
campaña con `--broker-host 127.0.0.1`. Ver
`docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md`, sección
"Fase 3".

- `20261028-204629_lazo_pi-lan` (además incompleta: solo rep_01, de un intento interrumpido a mano)
- `20261028-204722_lazo_pi-lan`
- `20261028-210533_desvio_pi-lan`

## 4. Emulador de un paso (banco de pruebas, no middleware) -- las cuatro corridas limpias del 2026-10-28

Estas cuatro eran las corridas que se habían dado por buenas (Fase 3/4 de
`docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md`, 0
`sin_respuesta`, cota de reloj corregida). Se descartan de todas formas:
`controller/controller_emulator.py::Controller._advance_locked()` solo
avanzaba **una** fase por llamada a `status()`, y nada hace poll al
controlador mientras no hay una solicitud activa (ni entre repeticiones,
donde la OBU sigue publicando posición varios segundos después de cruzar
—`trayectoria_lazo_base.csv` dura 88 s completos— ni, con `config=pi-lan`,
entre campañas). El resultado: en las 40 solicitudes de estas cuatro
corridas, la RSU decidió **siempre** con fase reportada "amarillo"
(100 %, `cola_despeje=True` en las 40) — nunca verde, nunca rojo_general
— sin importar la pausa aleatoria sorteada (0–25 s). Diagnóstico completo,
con los datos que lo confirman, en
`docs/bitacora/2026-10-29_fase-controlador-emulado.md`. Corregido el
2026-10-29 (reloj continuo por módulo del ciclo, no un paso por consulta)
y repetida la campaña con cuotas adaptativas por condición de llegada.

- `20261028-195302_lazo_local`
- `20261028-201105_desvio_local`
- `20261028-212725_lazo_pi-lan`
- `20261028-214736_desvio_pi-lan`
- `_figuras_2026-10-28/` y `_figuras_2026-10-28_local_vs_pi-lan/` (figuras
  y `tabla_latencia.tex` generadas a partir de las cuatro corridas de
  arriba -- mismo motivo, no usar en el Capítulo 4).
