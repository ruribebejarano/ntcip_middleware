# 2026-11-02 — Banco de seguridad local, reproducible (S2)

**Objetivo específico:** OE5 (banco de pruebas, evidencia de seguridad)  **Requerimientos:** RNF-05
**Sección de la tesis:** 4.6 (pruebas de seguridad)
**Commit:** `37f14c2`

Ítem S2 de `prompt_seguridad.md`. Todo en la laptop, sin Pi ni tablet.

## Qué se implementó

`scripts/seguridad/banco_local.py`, con tres operaciones (`preparar`,
`levantar`, `bajar`), pensadas para usarse como librería desde
`tests/test_seguridad_broker.py` (S3) y también como CLI para uso manual:

- **`preparar()`**: PKI de prueba en `deploy/pki_banco/` (nueva entrada
  en `.gitignore`), reusando `generar_ca.py` como librería en vez de
  shell: CA propia, servidor (con SAN), RSU `1`/`2`, OBU `obu-emu-01`/
  `obu-emu-02`, y tres casos **negativos**, ninguno simulado:
  - certificado **vencido de verdad** (`openssl ca -startdate/-enddate`
    en el pasado — verificado con `openssl x509 -dates`:
    `notAfter=Jan 2 2023`);
  - certificado **revocado** (`generar_ca.revocar()`), con la CRL
    regenerada y el serial confirmado adentro (`openssl crl -text`);
  - un cliente firmado por una **CA ajena** con el mismo CN que uno
    legítimo (`obu-emu-01`) — confirmado que `openssl verify` contra la
    CA del banco lo rechaza.
- **`levantar()`**: escribe un `mosquitto.conf` temporal (mismas
  directivas que `scripts/seguridad/mosquitto_tls.conf`, con `crlfile`
  activo) en un puerto libre, con `acl_file` apuntando **directo** al
  `mosquitto_acl.conf` real del proyecto (no una copia), y confirma que
  el puerto abre antes de devolver el control.
- **`bajar()`**: `taskkill` por PID, persistido en un JSON para poder
  llamarse desde un proceso de Python distinto del que hizo `levantar()`.

## Cómo

- `log_dest file <ruta>`, no `log_dest stdout` con la salida de
  `subprocess.Popen` redirigida a un archivo desde Python — ver
  "Problemas y solución".
- Verificado en vivo: PID real, puerto confirmado abierto
  (`Test-NetConnection`), log con las líneas de arranque de mosquitto
  2.1.2 y la advertencia ya documentada de la ACL sobre
  `servidor/central/respuestas` sin `%c`/`%u` (la limitación conocida
  que T10 de S3 va a cubrir formalmente).
- `pytest -q`: 127 pruebas (sin pruebas propias para este módulo: lo
  ejercita directamente `test_seguridad_broker.py` en S3).

## Desviaciones respecto del diseño de la tesis

Ninguna nueva — formaliza en código la limitación de la ACL que ya
estaba documentada como comentario en `mosquitto_acl.conf` desde B4.

## Evidencia

- `openssl x509 -in .../obu-expirado-01.crt -noout -dates`:
  `notBefore=Jan 1 2023`, `notAfter=Jan 2 2023`.
- `openssl verify -CAfile deploy/pki_banco/ca/ca.crt
  deploy/pki_banco/ajena/cliente-ajeno.crt`: `error 20 ... unable to get
  local issuer certificate`.
- `openssl crl -in deploy/pki_banco/ca/ca.crl -noout -text`: serial del
  certificado revocado presente.
- Log de un `levantar`/`bajar` real (no versionado, en
  `deploy/pki_banco/mosquitto_banco.log`, que se regenera): arranque,
  apertura del puerto, la advertencia de la ACL.

## Problemas y solución

- **`levantar()` con `log_dest stdout` dejaba el log en 0 bytes.** Con
  la salida de `mosquitto.exe` redirigida a un archivo desde
  `subprocess.Popen(stdout=...)`, el proceso en Windows deja el log en
  su propio buffer interno (stdout deja de ser línea-bufferizado al no
  ser una terminal) y lo pierde al matarlo con `taskkill /F` (que no le
  da chance de vaciar el buffer al salir) — confirmado: el `.log`
  quedaba vacío aunque el broker estuviera corriendo y confirmado
  escuchando por `Test-NetConnection`. Solución: `log_dest file <ruta>`
  en el propio `mosquitto.conf`, que mosquitto escribe directo sin pasar
  por ese buffer de stdout.

## Pendiente

- S3 (matriz de pruebas automatizadas) es lo que de verdad ejercita este
  banco contra los 13+ casos — hasta que esa matriz pase, `mosquitto_tls.conf`
  y `mosquitto_acl.conf` siguen con el aviso "NO PROBADO CONTRA UN
  MOSQUITTO REAL" (se quita recién en S3, como pide el prompt).
