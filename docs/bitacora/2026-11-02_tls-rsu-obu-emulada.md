# 2026-11-02 — TLS 1.3 + mTLS en la RSU y la OBU emulada (S1)

**Objetivo específico:** OE4 (seguridad del canal V2I)  **Requerimientos:** RNF-05 (confidencialidad/autenticación)
**Sección de la tesis:** 3.x (diseño de seguridad, ssec:seg_impl) → 4.6 (pruebas de seguridad)
**Commit:** `22a22e5`

Ítem S1 de `prompt_seguridad.md`. Todo corrido en la laptop, sin Raspberry
Pi ni tablet, con el mosquitto 2.1.2 (OpenSSL 3.x) ya instalado localmente.

## Qué se implementó

- **`common/mqtt_tls.py`**, helper único para los cuatro clientes
  paho-mqtt del proyecto (antes cada uno construía su propio
  `ssl.SSLContext`, o ninguno). Fija **TLS 1.3 como mínimo** (no "la
  versión más alta disponible", que es lo que hacía
  `servidor/main.py::_tls_kwargs()` con
  `tls_version=ssl.PROTOCOL_TLS_CLIENT` — eso permite negociar hasta
  1.2), verifica el nombre del servidor contra el SAN de su certificado,
  y exige los tres archivos completos. Si no se pasa ninguna ruta, no
  toca el cliente (sin TLS, como hasta ahora); si el puerto es el de TLS
  por convención (8883) y no hay rutas, **falla explícito** en vez de
  conectar en claro.
- Conectado en `servidor/main.py` (sin cambiar sus variables de entorno),
  `agent/rsu_middleware.py` (`RSU_TLS_CA/CERT/KEY`, nuevas),
  `gateway/obu_emulada.py` (`--tls-ca/--tls-cert/--tls-key`) y
  `gateway/obu_simulator.py` (sigue en uso por `scripts/demo_asesor.sh`,
  se verificó antes de tocarlo).
- **Hallazgo real, no hipotético:** `scripts/seguridad/generar_ca.py` no
  emitía SAN en ningún certificado. Con `check_hostname=True` (lo que
  pide S1), eso habría hecho fallar el handshake de TODOS los clientes
  contra el certificado del servidor, aunque la CA fuera de confianza —
  OpenSSL moderno no cae a CN si no hay SAN. Corregido con `--san` en
  `emitir --tipo servidor` (por defecto `localhost`, `127.0.0.1`,
  `laptopricardoub`, `100.121.77.97` — nombre e IP de Tailscale de la
  laptop, ya documentados en `docs/ARRANQUE_BROKER_LAPTOP.md`, sin
  `[DATO]`). El SAN se firma del lado de la CA vía `-extfile`/
  `-extensions`, sin tocar `copy_extensions = none` (que sigue siendo
  correcto: nunca copiar extensiones de un CSR a ciegas).
- `scripts/campanas/lazo_centralizado.py`: opción `--tls <carpeta_pki>`.
  Reparte certificado y llave al servidor y a cada OBU emulada que el
  propio script lanza (los emite al vuelo si no existen, reusando
  `generar_ca.py` como librería en vez de otro CLI). El `obu_id` de cada
  OBU sigue sufijado por repetición (`-rNN`): un `obu_id` fijo para toda
  la campaña, como sugería el ejemplo del prompt, habría roto la
  correlación `(obu_id, seq)` de `scripts/analisis/lazo_centralizado.py`,
  que junta TODAS las repeticiones de una corrida en un solo análisis.

## Cómo

- Verificado de punta a punta contra un mosquitto real: CA + certificado
  de servidor con SAN + certificado de RSU, `mosquitto_tls.conf`
  adaptado a un puerto libre y rutas locales, cliente paho conectado vía
  `aplicar_tls()` → `Resultado conexion: {'rc': Success}`. Experimento
  manual, no comiteado (no depende de pytest; se repite con
  `scripts/seguridad/banco_local.py` en S2).
- `tests/test_mqtt_tls.py` (6 pruebas, con un CA/certificado de un solo
  uso generado con `openssl` en un `tmp_path`): construcción del
  contexto, TLS 1.3 fijo, puerto 8883 sin rutas falla, rutas parciales
  fallan, con las tres rutas se llama `tls_set_context`.
- `pytest -q`: 127 pruebas.

## Desviaciones respecto del diseño de la tesis

- `--tls` de la campaña usa `obu_id` sufijado por repetición, no el
  `obu_id` fijo de ejemplo del prompt (`obu-emu-01`) — documentado
  arriba y en el docstring de `_rutas_tls()`.
- La distribución de certificados a la RSU remota (Pi, `pi-lan`/`pi-4g`)
  **no se automatizó**: `--tls` solo cubre los procesos que el propio
  script lanza (servidor, OBU). La RSU en la Pi necesita su certificado
  y las variables `RSU_TLS_*` provistas a mano (systemd), igual que ya
  pasa con el resto de su configuración — documentado en
  `redaccion/plan_pruebas_4G.md`.

## Evidencia

- Salida del experimento manual (no versionada): `aplicar_tls` devolvió
  `True`, `Resultado conexion: {'rc': ReasonCode(Connack, 'Success')}`.
- `openssl x509 ... -ext subjectAltName` sobre el certificado de
  servidor emitido con el nuevo `--san`: `DNS:localhost, IP
  Address:127.0.0.1, DNS:laptopricardoub, IP Address:100.121.77.97`.

## Problemas y solución

- El hallazgo del SAN faltante no estaba en el alcance literal de "crear
  el helper" (S1.1-S1.4); se encontró al revisar S1.5 y se corrigió en
  el mismo commit porque sin él, **nada** de lo demás de S1 podría
  funcionar contra un broker real con `check_hostname=True`.

## Pendiente

- S2 (banco de seguridad local reproducible) y S3 (matriz de pruebas
  automatizadas) todavía no se hicieron en esta sesión — ver el resto
  de `prompt_seguridad.md`.
- Probar `--tls` de la campaña con hardware real (`pi-4g`): sin Pi en
  esta sesión, solo se validó el helper y la emisión de certificados por
  separado.
