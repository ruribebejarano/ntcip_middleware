# Plan: campaña de ruta completa hasta el hospital de Breña

**Estado: planificada, sin ejecutar.** Nada de esto se lanza hasta que el autor lo indique.
Basado en `E:\Tesis\prompt_ruta_pucp_hospital_nino.md`, con estos cambios acordados: destino
en Breña y 5 repeticiones por escenario en lugar de 10.

Las cifras de este plan salen del grafo, de OSM y de una simulación sin red
(`simulacion_previa.py`, con reloj falso y sin broker, RSU ni controladores). **No son
resultados de la campaña y no deben ir a la tesis.**

## 1. Caso

| Dato | Valor | Fuente |
|---|---|---|
| Origen | Av. La Marina, `-12.074664, -77.082933` | `app_obu/pruebas/registro_rsu_hospital_nino.json` |
| Destino | Instituto Nacional de Salud del Niño, `-12.0649978, -77.0464372` | OSM `way/194898813`, `app_obu/pruebas/hospitales_zona_pucp.json` |
| Ruta | 5301,5 m, 59 nodos | `servidor/rutas.py` sobre `data/grafo_san_miguel_real.graphml` |
| Calles | Dulanto → Toribio Ara → Vivanco → San Felipe → Av. Brasil → 28 de Julio | Grafo |
| Fin de ruta | Nodo a 71 m del punto del hospital, en 28 de Julio | Grafo |
| Grafo | **No hace falta uno nuevo**: el actual cubre la ruta con más de 500 m de margen | Caja del grafo |

### RSU: 13 candidatas

Distancia sobre el nodo de ruta que usa el servidor, según la simulación.

| RSU | Distancia | Nodos OSM | Solicitud en la simulación | Nota |
|---|---|---|---|---|
| 101 | 547 m | 4 | Por ETA, ~8 s antes | Después de un giro |
| 102 | 741 m | 2 | ~12 s antes | **Revisar:** solo 2 nodos |
| 103 | 2152 m | 3 | ~15 s antes | |
| 104 | 3062 m | 8 | Por ETA, ~8 s antes | Después de un giro |
| 105 | 3358 m | 8 | ~16 s antes | |
| 106 | 3856 m | 6 | ~15 s antes | |
| 107 | 3996 m | 4 | ~15 s antes | |
| 108 | 4278 m | 4 | ~15 s antes | |
| 109 | 4418 m | 4 | ~14 s antes | |
| 110 | 4697 m | 5 | ~15 s antes | |
| 111 | 4838 m | 4 | ~15 s antes | |
| 112 | 4978 m | 4 | ~15 s antes | |
| 113 | 5254 m | 6 | ~15 s antes | **Revisar:** a 47 m del fin de ruta |

Ninguna de las 13 está marcada en OSM como solo peatonal. Entre 741 m y 2152 m no hay
semáforos en OSM; no se verificó si es real o falta de mapeo. Se usan las 13 y se reporta esto
como limitación.

## 2. Qué mostró la simulación

1. **Las 13 RSU quedan como paradas** y las 13 cierran con cancelación por cruce. La RSU 113
   también, aunque está cerca del destino.
2. **Como máximo hay una solicitud activa a la vez.** La geocerca sigue una sola intersección, y
   en Av. Brasil la solicitud siguiente sale justo cuando se cancela la anterior. Con esta
   lógica, el diseño no apunta a solicitudes simultáneas. La campaña lo medirá con el sistema real.
3. **Las RSU 101 y 104 son las críticas para los 8 s.** Sus solicitudes salen por ETA a ~8 s, sin
   margen. Si llegan en ámbar o todo rojo, el despeje de hasta 5 s podría dejar la anticipación
   por debajo de 8 s. Si ocurre, se reporta; no se ajusta nada para evitarlo.
4. **Las detenciones al azar no ejercitan la suspensión.** En el perfil probado hubo 3
   detenciones y 0 suspensiones: dentro de la geocerca la solicitud se sigue renovando, y la
   suspensión solo aplica a solicitudes sostenidas por ETA. Ver la decisión 2 de la sección 7.

## 3. Trabajo previo (sin correr campaña)

| # | Cambio | Archivo | Por qué |
|---|---|---|---|
| 1 | Registro de 13 RSU, `rsu_id` 101 a 113, rumbos desde el grafo | `scripts/campanas/fixtures/registro_ruta_hospital_nino.json` | Los id 1, 60, 61 y 62 ya tienen certificado, y el 1 es de la Pi. Así se evita compartir `client_id` con ella sin conectarse a la Pi. |
| 2 | Opción `--desfase-s`, por defecto 0, y registro del arranque | `controller/controller_emulator.py` | Hoy no existe. Con 0 no cambia el comportamiento. |
| 3 | Generador de trayectorias sobre la ruta (A, B, C) | `scripts/trayectorias/generar_ruta.py`, nuevo | `generar.py` solo hace rectas. **Desviación del prompt.** |
| 4 | Runner de N RSU y repeticiones fijas | `scripts/campanas/ruta_completa.py`, nuevo | `lazo_centralizado.py` está fijo a la RSU 1 y usa cuotas adaptativas. Reutiliza sus funciones sin modificarlo. |
| 5 | Análisis y figuras | `scripts/analisis/ruta_completa.py`, nuevo | Reutiliza `analizar()` y `fase_natural_en_cruce()`. Generaliza `anticipacion_hasta_centro.py` a un centro por RSU. |
| 6 | Pruebas | `tests/` | Pruebas actuales del controlador y del gestor, más una del desfase. |

**No se toca:** `agent/`, `servidor/`, la Raspberry Pi, el módem 4G, Overleaf ni el servicio de
Mosquitto en 1883.

Detalles que el generador debe respetar:

- La primera y la última fila van con velocidad 0, porque esas filas no reciben ruido. Así el
  origen y el destino del MI no cambian de nodo por el ruido GNSS.
- El escenario C debe seguir la ruta que recalcule el servidor; si no, se recalcularía una y otra
  vez. Se valida antes con la simulación sin red.

## 4. Banco

- Broker de campaña: `deploy/pki/mosquitto_laptop_tls.conf`, puerto 8883, TLS 1.3 + mTLS. La ACL
  actual ya admite estos id. Hoy **no está corriendo**: se arranca al lanzar y se detiene al final.
- 13 controladores en puertos 9101–9113 y 13 agentes en SNMP 1171–1183, relanzados en cada
  repetición, como en la campaña.
- Plan de cada controlador: verde 8 s, ámbar 3 s, todo rojo 2 s, rojo general 8 s.
- Desfase uniforme en 0–21 s por RSU, derivado de la semilla y guardado en `desfases.json` en cada
  repetición.
- Ruido GNSS de 5 m y factor 1, como en la campaña.

## 5. Escenarios y tiempo

| Escenario | Definición | Rep. | Semillas | Tiempo |
|---|---|---|---|---|
| A | 36 km/h constante | 5 | 101–105 | ~48 min |
| B | 20–50 km/h, 3 o 4 detenciones de 5–20 s. **Perfil sintético** | 5 | 201–205 | ~57 min |
| C | Sale de la ruta más de 60 m a mitad de camino, con una solicitud activa, y vuelve por otra calle | 1 | 301 | ~10 min |
| **Campaña** | | **11** | | **~2 h** |

Tiempo total estimado:

| Etapa | Tiempo |
|---|---|
| Preparación y pruebas | ~2 h |
| Repetición de prueba (no cuenta como dato) | ~10 min |
| Campaña | ~2 h |
| Análisis, figuras y borrador | ~1 h |
| **Total** | **~5 h** |

Son estimaciones; solo la duración de los recorridos sale de la ruta. El tiempo de arranque de 13
RSU no está medido, y lo mide la repetición de prueba.

## 6. Orden de ejecución y criterios de parada

1. Preparar la sección 3 y correr las pruebas.
2. Simular A, B y C sin red con el registro y las trayectorias definitivos.
3. **Revisar la memoria.** Hoy hay 2,7 GB libres de 16,7 GB, y no está medido cuánto consumen 13
   agentes con sus controladores. Se mide con una RSU y se proyecta.
4. Arrancar el broker y hacer una repetición de prueba de A con las 13 RSU. Va a
   `resultados/ruta_completa/_prueba/`.
5. Correr A, B y C sin cargas pesadas en la laptop y con la suspensión desactivada.
6. Analizar, generar figuras y escribir los entregables.

**Se detiene y pregunta al autor si:**

- La memoria proyectada deja menos de 1 GB libre, o la laptop no da abasto. No se aplica ningún
  tope de RSU sin consultar.
- Un proceso se conecta al broker más de una vez en una repetición (choque de `client_id`).
- Una repetición no tiene las 13 paradas, o hay una solicitud sin respuesta.

Las repeticiones inválidas no se borran: pasan a `_descartadas/` con el motivo y su semilla.

## 7. Decisiones pendientes del autor

1. **Nombre del origen.** Es Av. La Marina, no la PUCP. Por defecto se mantiene para seguir la
   corrida anterior y se llama por su nombre real.
2. **Detención dirigida en B.** El prompt pide puntos al azar, pero así la suspensión casi no se
   ejercita. Por defecto: 2 o 3 detenciones al azar y 1 dirigida en la zona de solicitud por ETA
   de la RSU 101 o 104, declarada en el texto.
3. **RSU 102 y 113.** Por defecto se mantienen.

## 8. Mediciones y entregables

- **Por RSU y repetición:**
  - anticipación hasta el cruce y hasta el centro;
  - fase de llegada y despeje;
  - RTT, $t_{RSU}$ y $L$ (reloj común);
  - renovaciones, caducidades y mayor hueco;
  - solicitudes simultáneas;
  - contrafactual con el método de la Tabla 4.10.
- **Escenario B:** error del ETA, solicitudes que esperaron por una detención y tiempo de verde
  pedido de más.
- **Escenario C:** tiempo hasta la nueva ruta y solicitudes canceladas.
- **Contrafactual:** como el desfase queda registrado, se puede añadir un cálculo exacto de la
  fase como contraste, sin reemplazar el método de la tesis.
- **Archivos en `resultados/ruta_completa/`:**
  - `AVANCE.md`, `LEEME.md` y `RESUMEN.md`;
  - datos crudos y resúmenes en CSV y JSON;
  - cuatro figuras en PDF vectorial;
  - `borrador_seccion_tesis.tex`: máximo 2 páginas, 2 figuras y 1 tabla.
- **Fuera de esta carpeta:** entrada en `docs/bitacora/`, nota de la versión de osmnx en
  `data/LEEME.md` solo si se regenera el grafo, y commits locales `OE5:` sin `git push`.

## 9. A corregir en la tesis (solo el autor)

La sección 4.3.7 dice que la misión de 2928,1 m va "hacia el Hospital del Niño", pero termina en
Av. Mariano Cornejo, a ~1,8 km del hospital. El borrador nuevo reemplaza esa subsección; si no se
adopta, esa frase hay que corregirla igual.
