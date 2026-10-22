# Contrato OBU ↔ Servidor central

Especificación de los mensajes entre la OBU (app del operador) y el
servidor central, para construir la app Android real sobre esta base.
**Este documento NO construye la app** — es el contrato que la app debe
cumplir del lado del cliente, simétrico a lo que ya implementa
`gateway/obu_emulada.py` del lado emulado. El servidor está implementado en
`servidor/` (`servidor/main.py` es el proceso MQTT; `servidor/gestor_mision.py`
contiene la lógica de cada mensaje).

Referencia de diseño: sección 1.2 de
`E:\Tesis\prompt_arquitectura_centralizada.md` y
`docs/bitacora/2026-10-22_arquitectura-centralizada.md`.

## 1. Transporte

- **Protocolo:** MQTT 5 sobre TCP, dentro de una sesión **TLS 1.3**.
  `paho-mqtt` 2.x del lado emulado (`gateway/obu_emulada.py`); la app
  Android puede usar cualquier cliente MQTT 5 (p. ej. HiveMQ MQTT Client,
  Eclipse Paho Android Service).
- **Autenticación:** **mTLS** — cada OBU tiene un certificado propio y
  revocable, emitido por la CA del proyecto
  (`scripts/seguridad/generar_ca.py emitir --tipo obu --id <obu_id>`). El
  **Common Name** del certificado debe ser exactamente el `obu_id` que la
  app usa en los tópicos (sin prefijo) — la ACL del broker
  (`scripts/seguridad/mosquitto_acl.conf`) depende de que coincidan
  exactamente, vía `use_identity_as_username`.
- **Estado real de este requisito en el repositorio:** la CA y la
  configuración de Mosquitto con TLS/mTLS están implementadas
  (`scripts/seguridad/`) y la CA se probó de verdad (emisión, verificación,
  revocación). **No se probó contra un broker real en este entorno** — ver
  `docs/bitacora/2026-10-22_arquitectura-centralizada.md`. La app no debe
  construirse contra un broker sin TLS "temporalmente": si el entorno de
  desarrollo de la app todavía no tiene el broker con TLS listo, usar un
  broker de prueba separado, nunca el de producción sin cifrar.
- **QoS:** todos los mensajes de este contrato van con **QoS 1** (al menos
  una entrega). La RSU y el servidor ya deduplican por `seq`
  (`agent/rsu_middleware.py::_es_duplicado`); la app debe ignorar un M2/MR/ME
  repetido en vez de tratarlo como un evento nuevo.
- **Client ID:** `obu-{obu_id}` (ver `gateway/obu_emulada.py`).

## 2. Identificadores

| Campo | Tipo | Notas |
|---|---|---|
| `obu_id` | string | Identifica la sesión/dispositivo. Pseudónimo, NO la placa del vehículo (ssec:minimizacion). Debe coincidir con el CN del certificado mTLS. |
| `mision_id` | string | Lo asigna el SERVIDOR al recibir MI (`mis-<hex>`); la app lo recibe implícitamente en MR/ME pero no lo necesita para publicar MI/MP/MF (esos van por `obu_id`, no por `mision_id`). |
| `id_solicitud` | string | Por RSU/parada (`{mision_id}-{interseccion_id}`), interno al servidor↔RSU. La app no lo usa directamente — ve el resumen por RSU en ME. |
| `clase` | int | Clase NTCIP 1211 del vehículo (`clase_tipo`). **El banco de pruebas actual solo reconoce `1`** (`agent/ntcip1211.py::CLASES_EMERGENCIA_RECONOCIDAS = {1}`) — cualquier otro valor se rechaza en la RSU (RF-05), no en el servidor. [CITAR: verificar la tabla de clases contra el D.S. N.º 016-2009-MTC antes de ampliar esta lista]. |

## 3. Mensajes OBU → Servidor

### MI — Iniciar misión

**Tópico:** `obu/{obu_id}/mision` · **Cuándo:** al pulsar "Iniciar
emergencia" + destino en la app.

```json
{
  "tipo": "MI",
  "obu_id": "ses-abc123",
  "clase": 1,
  "origen": {"lat": -12.1100, "lon": -77.0320},
  "destino": {"lat": -12.1022, "lon": -77.0320},
  "ts_ms": 1761144000000
}
```

- `origen` es la posición GNSS actual de la OBU en el momento de armar la
  misión — **no está en la tabla mínima del prompt original** (que solo
  pide `obu_id, clase, destino, ts`), pero es necesaria para que el
  servidor calcule la ruta de inmediato. Si la app no la envía, el
  servidor espera la primera MP para armar la misión (ver
  `servidor/main.py::_procesar_mi`) — esto agrega latencia hasta la
  primera MP y no está probado con hardware real; **se recomienda que la
  app siempre envíe `origen`**.
- `destino`: lat/lon del punto de llegada. La app debe resolverlo desde un
  mapa o una dirección — no hay geocodificación en el servidor.

### MP — Posición

**Tópico:** `obu/{obu_id}/posicion` · **Cuándo:** a 1 Hz, **solo** mientras
la misión está activa (ssec:minimizacion: sin misión armada, la app no
debe publicar nada aquí).

```json
{
  "tipo": "MP",
  "obu_id": "ses-abc123",
  "lat": -12.10874,
  "lon": -77.03201,
  "velocidad_kmh": 36.0,
  "rumbo_deg": 0.0,
  "fuente_velocidad": "obd2",
  "ts_ms": 1761144002000,
  "seq": 2
}
```

- `fuente_velocidad`: `"obd2"` | `"gps"` | `"respaldo"` — informativo, el
  servidor no distingue hoy entre fuentes al calcular el ETA (usa
  `VELOCIDAD_RESPALDO_KMH` de `servidor/gestor_mision.py` si
  `velocidad_kmh` es inválida o ≈0). [REVISAR con asesor] si conviene que
  el servidor penalice la confianza del ETA según la fuente.
- `seq`: contador creciente por OBU (no por solicitud). Se usa para
  detectar reordenamientos/duplicados a nivel de aplicación.
- **Si la app pierde señal GNSS:** debe dejar de publicar MP (no inventar
  una posición) y la misión queda "congelada" en el servidor hasta la
  siguiente muestra válida — no hay un mensaje explícito de "posición
  perdida" en este contrato. [REVISAR con asesor] si se necesita uno para
  distinguir "sin GPS" de "red caída" en la consola de monitoreo.

### MF — Fin de misión

**Tópico:** `obu/{obu_id}/mision` · **Cuándo:** botón "Terminar
emergencia", o automáticamente si la propia app detecta que llegó al
destino (aunque el servidor también lo detecta de forma independiente, ver
§5).

```json
{"tipo": "MF", "obu_id": "ses-abc123", "motivo": "boton", "ts_ms": 1761144090000}
```

`motivo`: `"boton"` (la app lo envía) — los motivos `"destino"` y
`"tiempo_maximo"` los genera el propio servidor sin que la app tenga que
enviarlos (ver §5); la app los recibe reflejados en el último ME.

## 4. Mensajes Servidor → OBU

### MR — Ruta

**Tópico:** `obu/{obu_id}/ruta` · **Cuándo:** al armar la misión (MI o
primera MP), y de nuevo cada vez que el servidor recalcula por desvío.

```json
{
  "tipo": "MR",
  "mision_id": "mis-756ed62d",
  "version": 1,
  "longitud_total_m": 867.3,
  "geometria": [[-12.1100, -77.0320], [-12.1098, -77.0320], "..."],
  "paradas": [
    {"rsu_id": "1", "interseccion_id": "OSM-C24", "acceso_id": "S", "distancia_llegada_m": 289.1},
    {"rsu_id": "2", "interseccion_id": "OSM-C902", "acceso_id": "S", "distancia_llegada_m": 723.8}
  ],
  "ts_ms": 1761144000300
}
```

- `geometria`: lista de `[lat, lon]` en el orden de la ruta — para dibujar
  la polilínea en el mapa de la app (**mapa con ruta obligatorio**, según
  la interfaz mínima acordada).
- `paradas`: lista ORDENADA de RSU/accesos que la ruta atraviesa — para el
  indicador de "próximo semáforo".
- Un MR nuevo con el mismo `mision_id` reemplaza al anterior (desvío
  recalculado): la app debe redibujar la ruta completa, no acumular
  tramos.

### ME — Estado

**Tópico:** `obu/{obu_id}/estado` · **Cuándo:** después de cada MP
procesado y de cada M2 recibido de una RSU (así que, con la OBU activa, a
~1 Hz o más).

```json
{
  "tipo": "ME",
  "mision_id": "mis-756ed62d",
  "paradas": [
    {"interseccion_id": "OSM-C24", "rsu_id": "1", "acceso_id": "S", "estado": "concedida", "eta_s": 4.2, "fase": "verde"},
    {"interseccion_id": "OSM-C902", "rsu_id": "2", "acceso_id": "S", "estado": "pendiente", "eta_s": 38.7, "fase": null}
  ],
  "proximo": {"interseccion_id": "OSM-C24", "rsu_id": "1", "acceso_id": "S", "estado": "concedida", "eta_s": 4.2, "fase": "verde"},
  "conflicto": false,
  "ts_ms": 1761144002050
}
```

- `estado` por parada: `pendiente | solicitada | en_cola | concedida |
  cancelada | rechazada | en_espera`. `en_espera` significa que otra
  misión tiene prioridad en esa RSU en este momento (ver
  `servidor/conflictos.py`) — la app debe mostrarlo explícitamente (no
  como un error), con el texto en español natural ("en espera por otra
  unidad"), nunca con el identificador interno.
- `proximo`: la primera parada que no esté `cancelada`/`rechazada` — el
  dato que alimenta el indicador de "próximo semáforo" de la interfaz
  mínima. `null` si no queda ninguna parada pendiente en la ruta.
- `conflicto`: `true` si alguna parada de ESTA misión está `en_espera`.

## 5. Ciclo de vida de la misión (quién la desarma)

La misión se desarma (todo lo pendiente se cancela, M3 a cada RSU con
solicitud vigente) en tres casos, todos reflejados en el ME final antes de
que la app deje de recibir nada:

1. **Botón** ("Terminar emergencia"): la app envía MF `motivo="boton"`.
2. **Llegada a destino**: el servidor lo detecta solo, comparando la
   posición MP con el destino de la misión. [DATO: el umbral de distancia
   para considerar "llegó" no está definido en este contrato — ver
   `MARGEN_CRUCE_M` en `servidor/gestor_mision.py` como referencia de
   orden de magnitud, pero no es literalmente ese parámetro].
3. **Tiempo máximo** (`TIEMPO_MAXIMO_MISION_S` en
   `servidor/gestor_mision.py`, 1800 s = 30 min, **valor PROVISIONAL**
   [REVISAR con asesor]): el servidor desarma la misión aunque la app no
   haya hecho nada, para que una misión olvidada no quede publicando
   posición indefinidamente.

La app debe tratar cualquiera de los tres como "fin de misión": dejar de
publicar MP y volver a la pantalla de "Iniciar emergencia".

## 6. Lo que la app NO debe hacer

- No calcular ella misma a qué RSU/acceso dirigirse (eso ya no es parte
  del diseño vigente).
- No descargar ni cachear `config/registro_rsu.json` — ese archivo vive
  solo en el servidor.
- No publicar MP sin una misión armada.
- No interactuar con el conductor mientras el vehículo está en marcha más
  allá del indicador de próximo semáforo — [CITAR: D.S. N.º 016-2009-MTC,
  verificar el artículo exacto sobre uso de dispositivos móviles durante la
  conducción] antes de diseñar la pantalla.

## 7. Ejemplo de referencia funcionando

`gateway/obu_emulada.py` implementa este contrato completo (sin GNSS/OBD-II
reales: lee una trayectoria de un CSV) y
`evidencia/2026-10-22_arquitectura-centralizada/` tiene tres corridas
reales contra `servidor/main.py` y `agent/rsu_middleware.py` por MQTT —
útil como referencia de implementación y de los mensajes reales que se
intercambian.
