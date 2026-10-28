# Cronograma de trabajo — Tesis de Bachillerato

**Integración y validación de una RSU de bajo costo con middleware NTCIP,
enlace 4G y coordinación por servidor central, para la priorización
semafórica de vehículos de emergencia en Lima Metropolitana**

| | |
|---|---|
| **Autor** | Ricardo Bryan Uribe Bejarano |
| **Asesor** | John Edward Esquiagola Aranda |
| **Inicio del periodo planificado** | 14 de septiembre de 2026 |
| **Entrega** | 20 de noviembre de 2026 |
| **Duración** | 10 semanas |
| **Última actualización** | 2026-10-22 (arquitectura centralizada — ver `docs/bitacora/2026-10-22_arquitectura-centralizada.md`; versión anterior del 13 de septiembre, organizada alrededor de una malla Wi-SUN entre RSU, **superada**: no hay LaunchPad CC1352P disponible y la tesis vigente coordina por 4G con un servidor central, no por una malla dedicada entre RSU — ver `CLAUDE.md`) |

---

## Nota sobre el alcance

El plan original (13 de septiembre) organizaba el trabajo alrededor de
**seis** objetivos específicos, con una malla Wi-SUN entre RSU (OE4) como
mecanismo de coordinación de "ola verde". Esa malla **no se implementó**
(sin hardware CC1352P) y la tesis fusionó la caracterización del canal V2I
con la validación del lazo completo en un solo objetivo, quedando en
**cinco** objetivos específicos (OE1–OE5, ver `CLAUDE.md`). La
coordinación entre intersecciones que antes se esperaba de la malla I2I la
cubre ahora, con enlace 4G, el **servidor central** (`servidor/`, decisión
del 2026-10-22, ver `docs/bitacora/2026-10-22_arquitectura-centralizada.md`):
calcula la ruta y la lista ordenada de RSU, y arbitra conflictos entre
misiones — un mecanismo distinto del original, no una malla entre RSU
vecinas, pero que resuelve el mismo problema de fondo (coordinar más de
una intersección). Este documento sigue sin tener una revisión completa
semana por semana desde el 13 de septiembre; lo que se corrige aquí es la
descripción de objetivos/alcance que quedaba contradicha por el código. Las
fechas de S1–S10 que siguen abajo **no se revalidaron** contra el avance
real — [REVISAR con el asesor] antes de usarlas para planificar lo que
queda.

Decisiones de alcance que siguen vigentes:

1. **El lazo EVP (OE3 + OE5) es el núcleo; todo lo demás es
   complementario.** El aporte central de la tesis es el canal de
   comunicación estandarizado entre vehículo y controlador. Se cierra el
   lazo OBU/servidor → RSU → controlador antes de profundizar en
   extensiones (p. ej. I2I experimental, ver `docs/PLAN_IMPLEMENTACION.md`
   hito P8). Así, si algo se atrasa, lo que queda incompleto es la parte
   prescindible y no el núcleo.

2. **Sin barrido de condiciones ni escalamiento más allá del escenario de
   referencia.** Una campaña de medición por escenario (lazo, conflicto,
   desvío — ver `evidencia/2026-10-22_arquitectura-centralizada/`), no una
   matriz exhaustiva. El barrido pasa explícitamente a trabajo futuro en
   las conclusiones.

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

**Tabla de objetivos reescrita el 2026-10-22** (la numeración y el
contenido de OE4/OE6 cambiaron, ver nota de alcance arriba; el avance de
OE1–OE3 es el mismo que a mediados de septiembre, no se revisó de nuevo
en esta sesión):

| Objetivo específico | Avance |
|---------------------|--------|
| OE1 — Arquitectura y límites (incluye la decisión de servidor central, 2026-10-22) | Especificación del esquema OBU→servidor→RSU implementada en código (`servidor/`) y documentada (`docs/bitacora/2026-10-22_arquitectura-centralizada.md`); falta la reescritura formal de `ssec:sel_direccionamiento` en `main.tex` (a cargo de la redacción en paralelo, fuera de este repositorio) |
| OE2 — Plataforma física RSU | ~50 % (entorno Linux y venv listos; módem 4G SIM7670G **operativo desde 2026-10-28** —datos extremo a extremo por `usb0`, ver `docs/MODEM_4G.md` y `docs/bitacora/2026-10-28_modem-4g.md`—; interfaz Ethernet sin probar; pendiente repetir la campaña de OE5 contra este enlace real) |
| OE3 — Middleware NTCIP | ~60 % (agente SNMPv3 funcional sobre objetos **reales** de NTCIP 1202 —`phaseStatusGroupTable`, `phaseTable`, subárbol `1.3.6.1.4.1.1206.4.2.1`, ya no el OID de prueba `99999`— y 1211 —`priorityRequestTable`, `prgPriorityRequestAbsolute`, `agent/ntcip1211.py`—; MIB reconstruidas, no las oficiales de NEMA; acepta M1/M3 del servidor desde el 2026-10-22, sin cambios de comportamiento en RF-05/06/09. **Corregido 2026-10-28**: esta fila describía todavía el estado previo a P2/P3 de `docs/PLAN_IMPLEMENTACION.md`, ya superado en el código) |
| OE4 — OBU (cliente delgado) + servidor central | Cliente delgado (`gateway/obu_emulada.py`) y servidor (`servidor/`: ruta, gestión de misión, conflictos) implementados y probados de punta a punta con tres escenarios (lazo, conflicto, desvío); pendiente: TLS/mTLS contra un broker real, Raspberry Pi física, app Android (ver `docs/CONTRATO_OBU.md`) |
| OE5 — Caracterizar el canal y validar el lazo completo (fusiona el OE5/OE6 anteriores) | Validación emulada completa (sin hardware real) de los tres escenarios de la arquitectura centralizada; falta repetir contra hardware real (Raspberry Pi) y con TLS/mTLS |

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
- Redactar 3.6 Mapeo a objetos NTCIP y 3.8 Diseño de seguridad. (La sección
  3.7 "Malla I2I" de esta semana quedó superada: no se implementó esa
  malla; lo que la reemplaza es la nueva `ssec:ruta_servidor` del servidor
  central, ver nota de alcance al inicio de este documento.)
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

## Fase III — Lazo EVP extremo a extremo, con servidor central (S6–S7)

**[REVISAR con el asesor]** esta fase se reescribió el 2026-10-22 para
reflejar la decisión de arquitectura centralizada; buena parte de lo que
sigue ya tiene un primer avance en código (ver `servidor/`,
`gateway/obu_emulada.py` y `evidencia/2026-10-22_arquitectura-centralizada/`),
adelantado en esta sesión de desarrollo respecto de la semana original.

### S6 · 19–25 octubre
- OBU (cliente delgado): lector OBD-II, PIDs y conversión a magnitudes
  físicas; aplicación del operador con adquisición de posición y
  publicación MQTT de la misión (MI/MP/MF) **(OE4)**.
- Servidor central: cálculo de ruta (OSMnx/NetworkX), lista ordenada de
  RSU/accesos, gestión del ciclo de vida de la misión y arbitraje de
  conflictos **(OE4)** — avance adelantado en código el 2026-10-22, falta
  TLS/mTLS real y hardware.

### S7 · 26 octubre – 1 noviembre
- Campaña de medición del lazo completo OBU → servidor → RSU →
  controlador **(OE5)**. Latencia por tramo (OBU→servidor, procesamiento,
  servidor→RSU) y extremo a extremo, anticipación real frente a la
  requerida por RF8, y tasa de éxito, con repeticiones suficientes para
  reportar dispersión y no solo promedios. El primer corte de esta campaña
  (sin repeticiones, un escenario de cada tipo) ya está en
  `evidencia/2026-10-22_arquitectura-centralizada/`.
- Redacción de las secciones del Capítulo 4 correspondientes a OE3, OE4 y OE5.
- 📌 **Hito crítico: con esto la tesis ya es defendible.**

---

## Fase IV — Seguridad, hardware real y cierre (S8–S10)

**[REVISAR con el asesor]**: esta fase reemplaza por completo a la "Fase
IV — Malla I2I y cierre" original (S8–S10 organizadas alrededor de una
malla Wi-SUN con LaunchPad CC1352P, que no se implementó y no corresponde
a la arquitectura vigente). Las tareas de seguridad (TLS/mTLS) y de
hardware real (Raspberry Pi) que siguen abajo sí son necesarias para
cerrar OE2/OE4/OE5 tal como quedan definidos ahora; las fechas S8–S10 son
una ubicación propuesta, no confirmada.

### S8 · 2–8 noviembre
- TLS 1.3 + mTLS reales: levantar un Mosquitto con la configuración de
  `scripts/seguridad/mosquitto_tls.conf` y la CA de
  `scripts/seguridad/generar_ca.py` (ya probada de forma aislada, no
  contra un broker en ejecución) **(OE4)**.
- Puesta en marcha del enlace 4G/Ethernet de la Raspberry Pi real
  **(OE2)**.

### S9 · 9–15 noviembre
- Repetir los tres escenarios de
  `evidencia/2026-10-22_arquitectura-centralizada/` (lazo, conflicto,
  desvío) contra la Raspberry Pi real y con TLS/mTLS **(OE2, OE4, OE5)**.
- Redacción de las secciones del Capítulo 4 correspondientes a OE2 y la
  seguridad de OE4.
- 🚦 **Decisión G3 — alcance de la seguridad real.** Si TLS/mTLS contra un
  broker real o la Raspberry Pi física no están listos para el 11 de
  noviembre, se reporta lo alcanzado (la CA y la ACL sí probadas de forma
  aislada), se documenta el obstáculo y el resto pasa a trabajo futuro. No
  se sacrifica la semana de cierre.

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
| G3 | 11 noviembre | TLS/mTLS real y Raspberry Pi lista → se caracteriza contra hardware real. No lista → se reporta lo alcanzado en emulación (`evidencia/2026-10-22_arquitectura-centralizada/`) y pasa a trabajo futuro. (Reemplaza al gate original de la malla Wi-SUN, que no aplica a la arquitectura vigente.) |

Cada gate tiene una salida definida de antemano. El propósito es que ninguna de
las tres incertidumbres pueda consumir tiempo indefinido.

---

## Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| R1 | Las MIB oficiales de NEMA no llegan | Alto — validez de OE3 | Solicitud el primer día; salida definida en G2 |
| R2 | TLSTM sin soporte maduro en el stack Python | Medio — obliga a replantear 3.8 | Verificación en S2; salida definida en G1 |
| R3 | Dependencia de un commit no publicado de pysnmp | Medio — reproducibilidad | Fijar el commit exacto y registrarlo en el Capítulo 4 |
| R4 | TLS/mTLS real y la Raspberry Pi física no están listos a tiempo | Medio — ya acotado | La CA y la ACL se probaron de forma aislada (`scripts/seguridad/`), sin broker real; alcance reducido por diseño si no alcanza, salida en G3. Reemplaza al riesgo original de la malla Wi-SUN (R4), descartada como mecanismo de coordinación — ver nota de alcance al inicio del documento. |
| R5 | Sin acceso a un controlador semafórico físico | Medio | El emulador de S4 elimina la dependencia |
| R6 | El lector OBD-II no responde con el vehículo disponible | Medio — bloquea OE4 | Validar manualmente con Torque o Car Scanner **antes de S6**, no durante |

**R6 es la tarea más barata de adelantar y la más cara de descubrir tarde.**
Probar el lector esta semana no cuesta nada y evita perder la S6 completa.

---

## Pendientes de la arquitectura centralizada (actualizado 2026-10-22)

El script de ruta, la gestión de misión en el servidor y su arbitraje de
conflictos — que en la versión anterior de este documento (añadida el
2026-10-22 y reemplazada por esta) aparecían como tareas futuras "a
encajar" — **ya están implementados**: `servidor/rutas.py`,
`servidor/gestor_mision.py`, `servidor/conflictos.py`, probados con 22
pruebas unitarias nuevas y 3 escenarios de punta a punta (ver
`docs/bitacora/2026-10-22_arquitectura-centralizada.md` y
`evidencia/2026-10-22_arquitectura-centralizada/`). Lo que sigue pendiente
de verdad:

- **Mapa de misión en la consola.** `consola/backend/mapa.py` y
  `consola/static/js/mapa.js` (y la página equivalente de
  `centro_control/panel/`) seguían leyendo el archivo local que escribía
  la OBU emulada ANTES de esta migración
  (`resultados/obu_vivo/estado.json`), que `gateway/obu_emulada.py` ya no
  escribe. Falta adaptarlos para mostrar la ruta (MR) y el estado (ME) que
  ahora publica el servidor. **[REVISAR: encajaría junto a la campaña de
  medición de S7.]**
- **App Android mínima con mapa y ruta.** Botón "Iniciar/Terminar
  emergencia" con selector de destino, indicador del próximo semáforo y
  mapa con la ruta del servidor (sustituye a la OBU emulada de
  `gateway/obu_emulada.py` para la validación final). El contrato de
  mensajes que debe cumplir ya está especificado en
  `docs/CONTRATO_OBU.md`. **[REVISAR: encajaría en la Fase III o al
  inicio de la Fase IV, S8, según el tiempo disponible.]**
- **TLS 1.3 + mTLS contra un broker real, y Raspberry Pi física** — ver
  Fase IV (S8–S9) y el gate G3 arriba.
