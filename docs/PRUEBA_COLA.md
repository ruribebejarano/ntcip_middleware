# Prueba de colas: emisión con el vehículo detenido o lento

## Para qué

Los dos criterios con que el servidor emite la solicitud M1 son la geocerca
de radio R_g y el ETA bajo el umbral θ_ETA (sección `ssec:emision` de la
tesis). Ambos suponen un vehículo que avanza. En una cola:

- el vehículo detenido no emite por ETA;
- a paso de hombre su ETA (distancia ÷ velocidad) queda muy por encima del
  umbral;
- la geocerca recién actúa a R_g de la intersección.

Esta prueba mide cuándo se emite la solicitud y cuánto verde llega con el
vehículo todavía en la cola. No modela la dinámica de la cola: es un perfil
fijo que no depende de la fase del semáforo.

## Perfil

Corre sobre la recta del escenario `lazo` (la RSU está a 289 m del inicio).

- **Inicio:** el vehículo arranca detenido, con 280 m de cola hasta la línea de detención.
- **Avance en la cola:** alterna 20 s detenido con 8 s a 15 km/h.
- **Salida de la cola:** desde la cabeza sigue a 36 km/h otros 150 m.

Es `lazo_centralizado.py --cola 20,8,15 --cola-largo-m 280`.

El controlador emulado usa los tiempos del manual INDRA (`--controlador-indra`).

## Criterios comparados

| Etiqueta | R_g | θ_ETA |
|---|---|---|
| `cola_geocerca_eta8` | 150 m | 8 s (campaña) |
| `cola_geocerca_eta16` | 150 m | 16,3 s (INDRA) |
| `cola_eta16` | 0 | 16,3 s |

## Cómo correr

En Git Bash, desde la raíz del repo. El script levanta su propio broker
TLS en `127.0.0.1:8884`, así que no necesita la Pi.

```bash
bash scripts/campanas/prueba_cola.sh
```

```bash
python scripts/analisis/cola_resumen.py
```

La tabla queda en `resultados/campana/_cola/tabla_cola.tex`.

## Métricas

- `d_emision_m`: distancia a la línea de detención al emitirse el primer M1.
- `t_previo_s`: tiempo en la cola antes de ese M1.
- `t_cola_s`: tiempo total en la cola.
- `verde_cola_s`: verde por prioridad concedido con el vehículo todavía en la cola.
- `emisiones`: M1 iniciales enviados.
- `m3_detenido`: suspensiones por vehículo detenido.
- `obtuvo_verde`: si el verde llegó antes del cruce.
