# 2026-11-02 — Costo de TLS en la latencia (S4, opcional)

**Objetivo específico:** OE5 (caracterización del canal)  **Requerimientos:** RNF-01, RNF-05
**Sección de la tesis:** 4.6/4.3 (costo de la seguridad sobre la latencia)
**Commit:** (ver informe final)

Ítem S4 de `prompt_seguridad.md` (opcional, solo si S1–S3 terminaban — terminaron). Campaña `lazo`, condición `local`, con y sin `--tls`, cuotas por defecto (4 por condición, tope 18), factor 1 (tiempo real).

## Qué se implementó

No se cambió código: se corrió la campaña dos veces contra el banco de
seguridad (`scripts/seguridad/banco_local.py`, el mismo de S2/S3).

## Bloqueador real encontrado y resuelto

`rsu-agent.service` estaba **activo de verdad en la Raspberry Pi**
(`broker.conf` apuntando al broker de esta laptop, mismo `client_id` que
usaría el runner local — el riesgo real documentado en
`docs/bitacora/2026-10-28_campana-centralizada-lazo-desvio.md`). El
propio `_verificar_pi_agente_inactivo()` de
`scripts/campanas/lazo_centralizado.py` abortó la primera corrida antes
de lanzar nada. Con autorización explícita del autor: se detuvo el
servicio (`scripts/pi.sh stop agent rsu`), se corrieron ambas campañas, y
se repuso el servicio al terminar (`scripts/pi.sh start agent rsu`,
confirmado `Active: active (running)`).

## Resultado

| Condición | n (misiones) | L mediana (ms) | L p95 (ms) | t_OBU→srv mediana (ms) | t_OBU→srv p95 (ms) |
|---|---|---|---|---|---|
| sin TLS (`127.0.0.1:1883`) | 17 | 3.63 | 28.13 | 0.44 (n=754) | 0.65 |
| con TLS (`localhost:8886`, mTLS) | 16 | 4.62 | 26.81 | 0.59 (n=710) | 0.77 |

- **L (latencia del lazo, RNF-01):** la diferencia (mediana +0,99 ms,
  p95 **menor** con TLS, -1,32 ms) está dentro del ruido de muestras
  tan chicas (16-17 misiones, condiciones de llegada repartidas distinto
  entre las dos corridas) — no hay una diferencia atribuible a TLS que
  se distinga del ruido de medición en esta escala. Ambas, muy por
  debajo del presupuesto de 1000 ms.
- **t_OBU→servidor (por MP, no por misión):** con mucho más n (710-754
  muestras, una por MP), muestra un costo pequeño pero consistente de
  TLS: +0,15 ms en la mediana, +0,12 ms en p95 — el overhead de
  cifrado/descifrado de cada mensaje, visible porque esta métrica tiene
  mucho más n que L (una muestra por MP, no por misión).
- **Conclusión:** en local (loopback, sin la variable de la red 4G), el
  costo de TLS 1.3 + mTLS es del orden de una décima de milisegundo por
  mensaje — no compite con el presupuesto de latencia de RNF-01 (1000
  ms). El costo real sobre 4G (que sí puede ser significativo por el
  RTT del enlace celular, no por el cifrado en sí) se mide en la
  campaña `pi-4g`, no acá.

## Cómo

```
python scripts/campanas/lazo_centralizado.py --escenario lazo --config local \
    --broker-host 127.0.0.1 --broker-port 1883 --factor 1 \
    --salida resultados/campana_s4_sin_tls
# (banco_local.levantar(puerto=8886) aparte, detached)
python scripts/campanas/lazo_centralizado.py --escenario lazo --config local \
    --broker-host localhost --broker-port 8886 --factor 1 \
    --tls deploy/pki_banco --salida resultados/campana_s4_con_tls
```

Carpetas renombradas y movidas a la ubicación estándar de campañas
(`resultados/campana/`, no un directorio nuevo) con el sufijo
`_sin-tls`/`_con-tls` para distinguirlas, ya que ambas son condición
`local` (la diferencia está en `broker` de `config.json`: `127.0.0.1:1883`
vs `localhost:8886`):
- `resultados/campana/20261102-105719_lazo_local_sin-tls/`
- `resultados/campana/20261102-112840_lazo_local_con-tls/`

Analizadas con `scripts/analisis/lazo_centralizado.py --dir <carpeta>`
(sin cambios en el script de análisis).

## Desviaciones respecto del diseño de la tesis

Ninguna — es una caracterización adicional, no un cambio de diseño.

## Evidencia

- `resultados/campana/20261102-105719_lazo_local_sin-tls/lazo_resumen.json`
  y `20261102-112840_lazo_local_con-tls/lazo_resumen.json`.

## Problemas y solución

- La primera corrida con `--tls` falló porque el runner de campaña **no
  levanta el broker por su cuenta** (solo lanza
  controller/agent/servidor/OBU) — había que levantar
  `scripts/seguridad/banco_local.py` aparte, en un puerto fijo conocido,
  *antes* de apuntar la campaña ahí. El primer intento (`rep_01`, carpeta
  descartada antes de comitear) falló con "agent no reportó conexión" por
  esto.

## Pendiente

- Repetir esta comparación contra `pi-4g` cuando esa campaña se ejecute
  (hardware real), donde el RTT del enlace celular sí puede hacer que el
  costo relativo de TLS sea más visible.
