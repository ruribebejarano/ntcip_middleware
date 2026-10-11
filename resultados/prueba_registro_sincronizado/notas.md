# Prueba de registro de eventos, con W32Time activo (comparación con `resultados/prueba_registro/`)

## Cómo se corrió

Igual que `resultados/prueba_registro/` (ver su `notas.md`), pero con
W32Time configurado y corriendo en la laptop (`time.cloudflare.com` /
`time.google.com`, arranque automático). `scripts/pi.sh clock` se corrió
**en el mismo momento** que la solicitud, para registrar el offset exacto
vigente en ese instante (ver `config.json`).

## Resultado crudo (sin corregir)

```
id_solicitud                  t_V2I     t_RSU   t_NTCIP   L_aprox  (ms)
ambulancia-sync-a2fcf0d2     157.60      0.19      0.55    158.35
```

**Sigue sin ser un valor de latencia utilizable tal cual.** W32Time
*estaba* corriendo, pero su corrección es gradual ("slew", no un salto
instantáneo): entre que se activó y el momento de esta corrida, el
offset de la laptop había bajado de ~194 ms a ~156 ms, pero no a cero
(ver la entrada de bitácora de este hito para el detalle de la
convergencia). El signo cambió respecto de la corrida anterior
(`-2.75 ms` entonces, `+157.60 ms` ahora) porque la dirección del
desfase entre laptop y Pi se invirtió mientras la laptop corregía su
reloj "desde abajo" tras horas sin sincronizar.

## Resultado corregido con el offset medido al momento de la corrida

Dato medido en el instante de la corrida (`config.json`):
laptop vs. `time.cloudflare.com` = **+156.0605 ms**; Pi vs. NTP =
**−0.8928 ms** (`chronyc tracking`, "System time... slow of NTP time").
Offset combinado (laptop por delante de la Pi) = 156.0605 − (−0.8928)
= **156.9533 ms**.

Restando ese offset de los tramos que cruzan de la laptop a la Pi
(`t_V2I` y, por lo tanto, `L_aprox`; `t_RSU` y `t_NTCIP` no cambian,
están calculados enteramente con marcas de tiempo de la Pi):

```
t_V2I_corregido  = 157.603 − 156.953 ≈  0.65 ms
L_aprox_corregido = 158.347 − 156.953 ≈  1.39 ms
```

Esto **sí** es un valor plausible para un salto MQTT en la misma red
Wi-Fi local (sub-milisegundo a ~1 ms), consistente con `t_RSU` (0.19 ms)
y `t_NTCIP` (0.55 ms), que nunca necesitaron corrección por estar
calculados con marcas de tiempo de una sola máquina.

## Comparación de las dos corridas

| | `prueba_registro/` (sin W32Time) | `prueba_registro_sincronizado/` (con W32Time, sin converger del todo) |
|---|---|---|
| `t_V2I` crudo | −2.75 ms | +157.60 ms |
| `t_RSU` | 0.19 ms | 0.19 ms |
| `t_NTCIP` | 0.74 ms | 0.55 ms |
| `L_aprox` crudo | −1.82 ms | +158.35 ms |
| Offset laptop↔Pi en el momento | no medido | +156.95 ms (medido) |
| `t_V2I` corregido con el offset | no se midió el offset, no se puede corregir | **≈0.65 ms** |

## Conclusión metodológica

Ninguna de las dos corridas sin corregir produce un `t_V2I` utilizable
—ambas están dominadas por el desfase de reloj entre máquinas, no por
latencia de red real—, pero por razones distintas: la primera porque
W32Time no estaba activo; la segunda porque, aunque ya estaba activo,
el *slew* gradual de Windows tarda del orden de decenas de minutos en
converger para un desfase acumulado de ~190 ms, y esta corrida se hizo
antes de esa convergencia completa.

La diferencia práctica es que la segunda corrida **sí tiene su offset
medido y registrado** (`config.json`), lo que permite corregirla
analíticamente y obtener un valor plausible (~0.65–1.4 ms). La primera
no se puede corregir porque no se midió el offset en el momento exacto
de esa corrida. Esto confirma, con números concretos, por qué el diseño
original pedía guardar el offset de reloj en el `config.json` de cada
corrida (ver el pedido original en el chat): no basta con "tener NTP
activo", porque la convergencia no es instantánea; hace falta medir y
registrar el offset vigente en cada corrida para poder corregirla,
incluso si la sincronización todavía está en proceso.

## Recomendación para campañas reales (P6 en adelante)

- Medir el offset (`scripts/pi.sh clock`) inmediatamente antes de cada
  corrida y guardarlo en el `config.json`, como ya se hizo aquí.
- Dejar W32Time corriendo un tiempo prudencial (a juzgar por esta
  prueba, bastante más de los ~15 minutos transcurridos en esta sesión)
  antes de una campaña de latencia real, o aplicar la corrección
  analítica del offset medido si no se puede esperar.
- Considerar, como alternativa más robusta a futuro, que
  `scripts/analisis/latencia_tramos.py` reciba el offset medido como
  parámetro y lo aplique automáticamente a los tramos que cruzan de
  máquina — no implementado todavía, queda como mejora para cuando se
  construyan las campañas de P6.
