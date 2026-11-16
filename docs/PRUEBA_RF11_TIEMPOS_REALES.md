# Prueba de RF-11 con los tiempos de un controlador real

Verifica si el criterio de emisión de M1 cumple RF-11
(`T_m ≤ A_v ≤ A_v,max`) cuando el controlador tiene tiempos de una
programación real, en lugar de los del controlador emulado de la campaña
(verde 8 s, ámbar 3 s, todo rojo 2 s, rojo general 8 s, ciclo de 21 s).

## Por qué

El controlador emulado de la campaña modela un solo grupo semafórico: una
solicitud que llega en "rojo general" recibe el verde de inmediato. Un
controlador real no puede hacerlo: si el acceso pedido está en rojo, otra
fase tiene verde y debe cumplir su verde mínimo, su ámbar y su todo rojo
antes de ceder (ecuación de `T_desp` del capítulo III). Con ciclos reales
de 100 s o más, casi toda llegada que no cae en verde paga ese despeje.

## Tiempos usados

Del manual de programación del controlador INDRA (tablas 21, 22 y 23,
intersección de ejemplo E06-01, tres fases, modo de tiempos fijos). El
manual los presenta como ejemplo; no se sabe si son el plan vigente de
una intersección.

| Parámetro | Valor |
|---|---|
| Ámbar ("tiempo posición A" de cada transitorio) | 3 s |
| Rojo-rojo ("tiempo posición B") | 1 s |
| Verde mínimo de cada fase | 5 s |
| Verde de plan, fases A / B / C | 50 / 28 / 20 s |
| Ciclo | 110 s |

El grupo solicitado es el de la fase A; B y C son las fases en conflicto.
Con estos tiempos, el peor caso de despeje es una solicitud que llega al
empezar el ámbar del propio acceso: termina ese ámbar y su rojo-rojo
(3 + 1 s) y, como la fase siguiente ya arrancó, debe cumplir su verde
mínimo, su ámbar y su rojo-rojo (5 + 3 + 1 s). Así,
`T_desp,max = 13 s` y `A_v,max = T_desp,max + T_m + Δt = 13 + 2 + 1 = 16 s`.
(La prueba de humo del 2026-11-16 lo mostró: una llegada en ámbar esperó
10,57 s, más que los 9 s del despeje de una sola fase.)

## Qué cambió en el código

- `controller/controller_emulator.py`: modo multifase (`--verde-plan`,
  `--fases-conflicto`, `--verde-min-conflicto`). Sin esas opciones se
  comporta como antes. Pruebas en `tests/test_controller_emulator.py`.
- `servidor/main.py`: el radio de la geocerca de emisión y el umbral de ETA
  se leen de `SERVIDOR_R_G_M` y `SERVIDOR_ETA_EMISION_S` (por defecto,
  150 m y 8 s, los de la campaña). `R_g = 0` deja solo el ETA. Una
  intersección del registro de RSU (`config/registro_rsu.json`) puede
  declarar su propio umbral con el campo opcional `theta_eta_s`
  (L + T_desp,max + T_m + Δt de su controlador); si lo declara, reemplaza
  al global para esa intersección.
- `scripts/campanas/lazo_centralizado.py`: `--velocidad-kmh` (rehace la
  trayectoria recta de `lazo` a otra velocidad), `--controlador-indra`,
  `--r-g`, `--eta-emision`, `--repeticiones` (número fijo, sin cuotas) y
  `--etiqueta`. La verificación de `config=local` ya no aborta si el agente
  de la Pi está activo pero conectado a otro broker (Oracle).

## Corridas

Cuatro corridas de 12 repeticiones, `config=local`, TLS 1.3 + mTLS:

| Velocidad | Emisión |
|---|---|
| 36 km/h | geocerca 150 m o ETA 8 s (criterio de la campaña) |
| 60 km/h | geocerca 150 m o ETA 8 s |
| 36 km/h | solo ETA, 16,3 s |
| 60 km/h | solo ETA, 16,3 s |

Umbral de ETA: `T_act + Δt = (L + T_desp,max + T_m) + Δt = (0,33 + 13 + 2)
+ 1 ≈ 16,3 s`, con `L` el p95 por 4G de la campaña (330,9 ms) y `Δt = 1 s`
porque el servidor evalúa el ETA una vez por MP.

Duración estimada: 12 repeticiones × (≈ 90 s de misión a 36 km/h o ≈ 55 s
a 60 km/h + pausa aleatoria de 0 a 110 s + arranque) ≈ 1 h 50 min las
cuatro corridas.

## Cómo correrla

Requisitos:

1. Broker TLS de la laptop en 8883 corriendo
   (`deploy/pki/mosquitto_laptop_tls.conf`).
2. El agente de la Pi **no** debe estar conectado al broker de la laptop
   (comparten el identificador `rsu-middleware-1`). Durante una sesión de
   la campaña en la nube (`docs/CAMPANA_4G_NUBE.md`) la Pi apunta a Oracle
   y la verificación lo detecta solo; si la Pi está en modo normal, hay que
   detener su agente (`scripts/pi.sh stop agent rsu`).

En Git Bash, desde la raíz del repo:

```bash
bash scripts/campanas/prueba_rf11_indra.sh
```

Puede correr en paralelo con la campaña 4G en la nube: esa corre en la
máquina de Oracle; esta, en la laptop.

## Análisis

```bash
python scripts/analisis/rf11_indra_resumen.py
```

Imprime, por corrida, `t_verde` y `A_v` (mínimo, mediana y máximo) y
cuántas paradas quedan dentro de `[T_m; A_v,max]`, y escribe
`resultados/campana/_rf11_indra/rf11_indra_resumen.json` y
`tabla_rf11_indra.tex`.

## Qué se espera (aritmética, por confirmar con la prueba)

- Geocerca de 150 m a 36 km/h: la emisión ocurre 15,0 s antes del cruce;
  una llegada que paga más de 13 s de despeje quedaría con `A_v` < 2 s.
- Geocerca de 150 m a 60 km/h: 150 m son 9,0 s; toda llegada que pague más
  de 7 s de despeje quedaría con `A_v` < 2 s.
- Solo ETA de 16,3 s: emisión a 15,3–16,3 s del cruce a cualquier
  velocidad; `A_v` entre 2 s y 16 s.
