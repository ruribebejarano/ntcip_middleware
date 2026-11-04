# Resultados de la campaña de medición

Estado al 4 de noviembre de 2026. El sistema se probó con un controlador emulado
y una OBU emulada, en tres condiciones de enlace, a 1 Hz y con TLS 1.3 + mTLS:
99 misiones en total, sin ninguna solicitud rechazada ni caducada.

## Condiciones

| Condición | RSU | Enlace servidor–RSU | Repeticiones (lazo + desvío) |
|---|---|---|---|
| `local` | Procesos en la laptop | Misma máquina | 17 + 17 |
| `pi-lan` | Raspberry Pi 5 | Wi-Fi, con red superpuesta Tailscale | 18 + 18 |
| `pi-4g` | Raspberry Pi 5 | Módem SIM7670G por red celular, con Wi-Fi apagado | 12 + 17 |

La OBU emulada, el servidor y el broker corren en la laptop en las tres
condiciones, así que solo el tramo servidor–RSU usa el enlace medido.

## Resultados

| Métrica | `local` | `pi-lan` | `pi-4g` |
|---|---|---|---|
| RTT servidor–RSU, mediana (ms) | 32,56 | 11,20 | 173,82 |
| RTT servidor–RSU, p95 (ms) | 65,51 | 17,71 | 395,30 |
| RTT servidor–RSU, máximo (ms) | 72,84 | 21,03 | 418,77 |
| `t_RSU`, mediana (ms) | 2,40 | 1,02 | 1,02 |
| `L`, p95 (ms) | 14,40 | no se reporta | no se reporta |
| Anticipación real, mediana (s) | 14,00 | 14,85 | 14,04 |

- **RNF-01 (`L` ≤ 1 s, p95):** se cumple en las tres condiciones.
- **RNF-02 (≥ 1 Hz):** intervalo mediano de 1,00 s en MP y en las renovaciones de
  M1, en todas las corridas. La frecuencia la fija el paso de la trayectoria
  reproducida.
- **RNF-03 (caducidad):** ninguna caducidad en 1348 renovaciones.
- **Anticipación:** todas las paradas superan los 8 s; la mínima es 9,21 s.
- **Consumo 4G de la RSU:** 5,43 MB en las dos corridas, unos 0,19 MB por
  repetición, según los contadores de `usb0`.
- **Costo de TLS (lazo local, 17 misiones):** +0,29 ms en la mediana y +0,36 ms en
  el p95 de `t_OBU→srv`. En `L` la diferencia queda dentro del ruido (mediana de
  2,96 ms sin TLS y 3,32 ms con TLS).

## Por qué no se reporta `L` con la RSU física

Las 36 paradas de `pi-lan` dan `L` negativa (mediana cercana a −55 ms, con un RTT
de 11 ms). Eso solo se explica porque el desfase entre los relojes de la laptop y
de la Pi supera al tramo medido, y el reloj de la laptop no está caracterizado.

Por eso, en `pi-lan` y `pi-4g` se usa el RTT, medido con un solo reloj, como cota
superior de `L`: la RSU decide antes de que M2 vuelva al servidor. Los datos no se
corrigen restando un desfase estimado. La anticipación también cruza dos relojes,
pero un error de decenas de milisegundos es despreciable frente a 8 s.

## Límites de estos resultados

- El controlador es emulado y las trayectorias son reproducidas, no tráfico real.
- Las corridas `pi-4g` duraron cerca de una hora, de noche y desde el lugar del
  banco de pruebas. No caracterizan una intersección de Lima ni las horas de mayor
  carga de la red.
- El consumo medido es solo el de la RSU, sin el de una OBU real.
- La corrida de lazo en `pi-lan` llegó al tope de 18 repeticiones con 3 de los 4
  casos pedidos en ámbar/todo rojo.
- Con 29 a 36 valores por condición, el p99 coincide con el máximo.
- No se midieron la tasa de entrega ni la tasa de acierto de acceso.
- La app Android todavía no se ha verificado en la tableta ni con mTLS.

## Cómo regenerar las tablas y figuras

Desde Git Bash, en la raíz del repositorio:

```bash
scripts/analisis/generar_cap4.sh
```

La salida queda en `resultados/campana/_figuras_cap4_2026-11-04/`. Las corridas
están en `resultados/campana/`:

| Condición | Lazo | Desvío |
|---|---|---|
| `local` con mTLS | `20261104-002341_lazo_local_1hz_con-tls` | `20261104-005352_desvio_local_1hz_con-tls` |
| `local` sin TLS | `20261104-012402_lazo_local_1hz_sin-tls` | no se corrió |
| `pi-lan` | `20261104-045004_lazo_pi-lan` | `20261104-052338_desvio_pi-lan` |
| `pi-4g` | `20261103-232704_lazo_pi-4g` | `20261103-235034_desvio_pi-4g` |

Para repetir una campaña, `scripts/campanas/noche_pi4g.sh` corre la de 4G de forma
desatendida y `scripts/campanas/noche_local.sh` corre la local. El módem se describe
en [MODEM_4G.md](MODEM_4G.md), y el método de medición en
[MEDICION_LATENCIA.md](MEDICION_LATENCIA.md).

La tesis renumeró los requerimientos funcionales: ver
[NUMERACION_RF.md](NUMERACION_RF.md). Este documento no cita RF por número.
