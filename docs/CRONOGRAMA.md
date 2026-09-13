# Cronograma de trabajo — Tesis de Bachillerato

**Integración y validación de una RSU con middleware NTCIP y malla Wi-SUN para
la priorización semafórica de vehículos de emergencia en Lima Metropolitana**

| | |
|---|---|
| **Autor** | Ricardo Bryan Uribe Bejarano |
| **Asesor** | John Edward Esquiagola Aranda |
| **Inicio del periodo planificado** | 14 de septiembre de 2026 |
| **Entrega** | 20 de noviembre de 2026 |
| **Duración** | 10 semanas |
| **Última actualización** | 13 de septiembre de 2026 |

---

## Nota sobre el alcance

Diez semanas para redactar dos capítulos y cerrar seis objetivos específicos es
un plazo ajustado. El plan **no tiene holgura**: un atraso de una semana en
cualquier fase se propaga hasta la entrega.

Por eso se toman tres decisiones de alcance desde el inicio, que conviene
acordar con el asesor ahora y no en noviembre:

1. **El lazo EVP se valida antes que la malla I2I.** El aporte central de la
   tesis es el canal de comunicación estandarizado entre vehículo y controlador
   (OE3 y OE6). La coordinación de ola verde (OE4) es la parte complementaria.
   Por eso el orden de trabajo invierte lo que sugiere el índice del documento:
   se cierra el lazo OBU → RSU → controlador antes de tocar Wi-SUN. Así, si algo
   se atrasa, lo que queda incompleto es la parte prescindible y no el núcleo.
   **Esto no cambia la estructura de la tesis**, solo el orden en que se produce
   la evidencia.

2. **OE4 se reduce a una caracterización única.** Dos nodos, una configuración,
   una campaña de medición del error de sincronización. Sin barrido de
   condiciones ni pruebas de escalamiento a más de dos RSU. El barrido pasa
   explícitamente a trabajo futuro en las conclusiones.

3. **El Capítulo 4 se redacta en paralelo, no al final.** Cada campaña de
   medición se escribe en la semana en que se ejecuta. No hay un bloque final de
   redacción: no alcanza el tiempo.

---

## Estado al inicio del periodo

| Capítulo | Estado |
|----------|--------|
| Capítulo 1 — Contexto, problemática y objetivos | Redactado, correcciones menores pendientes |
| Capítulo 2 — Marco teórico | Redactado, correcciones pendientes (ver S1) |
| Capítulo 3 — Diseño e integración | **Sin redactar** |
| Capítulo 4 — Implementación, pruebas y resultados | **Sin redactar** |
| Conclusiones | Sin redactar |

| Objetivo específico | Avance |
|---------------------|--------|
| OE1 — Arquitectura y límites | 0 % |
| OE2 — Plataforma física RSU | ~30 % (entorno Linux y venv listos; CC1352P sin integrar) |
| OE3 — Middleware NTCIP | ~35 % (agente SNMPv3 funcional sobre OID de prueba; MIB no oficiales) |
| OE4 — Malla Wi-SUN y sincronización | 0 % |
| OE5 — OBU | 0 % (validación manual del lector OBD-II pendiente) |
| OE6 — Validación del lazo completo | 0 % |

---

## Fase I — Diseño · Capítulo 3 (S1–S3)

### S1 · 14–20 septiembre
- **Solicitar por correo a `ntcip@nema.org` los archivos MIB oficiales de NTCIP
  1202, 1209 y 1211.** Primer día de la semana. El tiempo de respuesta no
  depende de ti y condiciona todo OE3.
- Redactar 3.1 Requerimientos funcionales, no funcionales y restricciones de la
  infraestructura heredada.
- Redactar 3.2 Arquitectura general y frontera del sistema **(OE1)**.
- Aplicar correcciones de los Capítulos 1 y 2: conteo de objetivos específicos,
  `tabularx` suelto antes de la Tabla 2.1, citas faltantes de las cifras de
  supervivencia, entradas bibliográficas contradictorias de NTCIP 1211, dato de
  intersecciones Ecotrafix, incorporación de RFC 9456 y restitución del sustento
  de las filas de la Tabla 2.3.

### S2 · 21–27 septiembre
- Redactar 3.3 Selección tecnológica con matriz de criterios ponderados: canal
  V2I, canal I2I, mecanismo de sincronización y modelo de seguridad SNMPv3.
- Redactar **3.9 Plan de pruebas y métricas** con umbrales numéricos: latencia
  máxima extremo a extremo, error de sincronización tolerable para la ola verde
  y tasa de éxito mínima de solicitudes.
- 🚦 **Decisión G1 — TLSTM.** Verificar experimentalmente el soporte de TLSTM en
  el stack. Si no es viable, el diseño adopta USM y la limitación queda escrita
  en 3.8 esa misma semana. **No se arrastra la duda más allá de esta fecha.**

### S3 · 28 septiembre – 4 octubre
- Redactar 3.4 Diseño de la OBU y 3.5 Diseño e integración de la RSU.
- Redactar 3.6 Mapeo a objetos NTCIP, 3.7 Malla I2I y 3.8 Diseño de seguridad.
- 📌 **Entregable al asesor: Capítulo 3 completo.**

---

## Fase II — Middleware NTCIP · núcleo del aporte (S4–S5)

### S4 · 5–11 octubre
- Emulador de controlador semafórico conforme a NTCIP **(OE3)**. Elimina la
  dependencia de hardware de la MML y desbloquea toda la validación posterior.
- 🚦 **Decisión G2 — MIB.** Si las MIB oficiales de NEMA no llegaron, se continúa
  con las MIB reconstruidas y **se declara como limitación** en el Capítulo 4,
  indicando qué OID quedaron sin confirmar. No se espera más.

### S5 · 12–18 octubre
- Agente SNMPv3 sobre las MIB 1202, 1209 y 1211: sustituir el OID de prueba
  `1.3.6.1.4.1.99999.1.1.0` por los objetos reales **(OE3)**.
- Adaptador hacia el protocolo propietario del controlador.
- Verificación GET/SET contra un gestor NTCIP de referencia, **desde un segundo
  equipo físico**, no desde la propia Raspberry Pi.
- 📌 **Entregable al asesor: middleware NTCIP verificado. OE3 cerrado.**

---

## Fase III — Lazo EVP extremo a extremo (S6–S7)

### S6 · 19–25 octubre
- OBU: lector OBD-II, PIDs y conversión a magnitudes físicas; aplicación del
  operador con adquisición de posición y publicación MQTT **(OE5)**.
- Cálculo cinemático del ETA y criterio de emisión de la solicitud.

### S7 · 26 octubre – 1 noviembre
- Campaña de medición del lazo completo OBU → RSU → controlador **(OE6)**.
  Latencia extremo a extremo y tasa de éxito, con repeticiones suficientes para
  reportar dispersión y no solo promedios.
- Redacción de las secciones del Capítulo 4 correspondientes a OE3, OE5 y OE6.
- 📌 **Hito crítico: con esto la tesis ya es defendible aunque OE4 quede
  reducido.**

---

## Fase IV — Malla I2I y cierre (S8–S10)

### S8 · 2–8 noviembre
- Enlace serie Raspberry Pi ↔ LaunchPad CC1352P; reparto de tareas y modelo de
  concurrencia **(OE2)**.
- Formación de la malla Wi-SUN FAN entre dos RSU con el SDK SimpleLink:
  RPL / 6LoWPAN **(OE4)**.

### S9 · 9–15 noviembre
- Intercambio de estado de fase con marcas de tiempo NTP; caracterización del
  error de sincronización y su efecto sobre el desfase de ola verde **(OE4)**.
- Redacción de las secciones del Capítulo 4 correspondientes a OE2 y OE4.
- 🚦 **Decisión G3 — alcance de OE4.** Si la malla no forma para el 11 de
  noviembre, se reporta lo alcanzado, se documenta el obstáculo y el resto pasa
  a trabajo futuro. No se sacrifica la semana de cierre.

### S10 · 16–20 noviembre
- Conclusiones y trabajo futuro, contrastando cada resultado contra los umbrales
  fijados en 3.9.
- Revisión integral: estilo, referencias, coherencia entre objetivos declarados
  y evidencia presentada.
- 📌 **Entrega final: viernes 20 de noviembre.**

---

## Puntos de decisión

| Gate | Fecha límite | Decisión |
|------|--------------|----------|
| G1 | 27 septiembre | TLSTM viable → se implementa. No viable → USM + limitación escrita en 3.8. |
| G2 | 11 octubre | MIB oficiales recibidas → se usan. No recibidas → MIB reconstruidas + limitación declarada. |
| G3 | 11 noviembre | Malla Wi-SUN formada → se caracteriza. No formada → se reporta lo alcanzado y pasa a trabajo futuro. |

Cada gate tiene una salida definida de antemano. El propósito es que ninguna de
las tres incertidumbres pueda consumir tiempo indefinido.

---

## Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| R1 | Las MIB oficiales de NEMA no llegan | Alto — validez de OE3 | Solicitud el primer día; salida definida en G2 |
| R2 | TLSTM sin soporte maduro en el stack Python | Medio — obliga a replantear 3.8 | Verificación en S2; salida definida en G1 |
| R3 | Dependencia de un commit no publicado de pysnmp | Medio — reproducibilidad | Fijar el commit exacto y registrarlo en el Capítulo 4 |
| R4 | Puesta en marcha de la malla Wi-SUN más lenta de lo previsto | Medio — ya acotado | OE4 está al final y con alcance reducido por diseño; salida en G3 |
| R5 | Sin acceso a un controlador semafórico físico | Medio | El emulador de S4 elimina la dependencia |
| R6 | El lector OBD-II no responde con el vehículo disponible | Medio — bloquea OE5 | Validar manualmente con Torque o Car Scanner **antes de S6**, no durante |

**R6 es la tarea más barata de adelantar y la más cara de descubrir tarde.**
Probar el lector esta semana no cuesta nada y evita perder la S6 completa.
