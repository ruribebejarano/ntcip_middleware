# 2026-10-11 — Commit del backlog pendiente y primer `scripts/pi.sh deploy`

**Objetivo específico:** OE3 (middleware), OE4 (OBU/geocerca), OE5 (controlador emulado, canal V2I, software de gestión); infraestructura transversal para el resto.
**Requerimientos:** RF-01 a RF-11, RNF-05 (indirectamente, vía el software de gestión que consulta el agente SNMPv3).
**Sección de la tesis:** 3.4–3.6 (implementación de OBU, RSU y middleware, pendiente de redactar con esta base); `sec:banco_impl`.
**Commit:** `597b77e` (laptop y Pi, ver abajo)

## Qué se implementó

Se comiteó y pusheó el código que llevaba semanas escrito en la laptop pero
nunca comiteado (ver el detalle completo en el propio mensaje del commit
`597b77e`): middleware integrado, emulador de controlador, OBU simulada,
software de gestión central, documentación de uso y la primera entrada real
de bitácora (broker EMQX). Después se corrió `scripts/pi.sh deploy` por
primera vez y se confirmó que la Pi queda exactamente en el mismo commit
que la laptop.

## Cómo

- Antes de comitear: barrido con `grep` sobre todos los archivos pendientes
  (`agent/`, `controller/`, `gateway/`, `centro_control/`, `docs/`,
  `evidencia/`, `scripts/`) buscando patrones de contraseña/clave/token y
  nombres de archivo típicos de secretos (`.env`, `.pem`, `.key`,
  `credentials*`); se revisó también la captura de `evidencia/` a simple
  vista. No se encontró nada sensible más allá de las credenciales SNMPv3
  de laboratorio ya documentadas en el README (`labAuthPass123`/
  `labPrivPass123`).
- `git add -A && git commit && git push origin master` desde la laptop.
- `scripts/pi.sh deploy` (creado en el hito anterior) para llevar el commit
  a la Pi.

## Desviaciones respecto del diseño de la tesis

Ninguna sobre el diseño del sistema. Una desviación operativa relevante:

- **Historia divergente de git entre laptop y Pi, sin detectar desde el
  2026-09-13.** Ambas máquinas tenían un commit distinto pero con el mismo
  mensaje ("agente, cronogrma, scripts") y el mismo autor/timestamp exacto
  (`d2844d3` en la Pi, `b1e1730` en la laptop): evidentemente el mismo
  cambio aplicado dos veces, en dos checkouts separados, sin que uno se
  empujara/jalara del otro. La única diferencia real de contenido era
  `CLAUDE.md`: la Pi lo había comiteado (`d2844d3`), la laptop en cambio
  agregó `.gitignore` con `CLAUDE.md` en la lista de exclusión (`b1e1730`)
  — el resto de los archivos (`README.md`, `docs/CRONOGRAMA.md`,
  `scripts/init_github_planning.sh`) eran idénticos byte a byte entre
  ambos commits. `scripts/pi.sh deploy` lo detectó porque `git pull
  --ff-only` rechaza un historial no fast-forwardable.

## Evidencia

No aplica (commit de código y verificación de sincronización de git, no es
una prueba del lazo de priorización).

## Problemas y solución

- **`git pull --ff-only` falló en la Pi con "Not possible to fast-forward"**
  → diagnosticado el commit divergente `d2844d3` (ver arriba). Dado que
  `CLAUDE.md` nunca debió comitearse (está en `.gitignore` por diseño,
  "contexto local, no publicar") y el resto del contenido de ese commit ya
  estaba presente en la línea de la laptop, se resolvió con
  `git reset --hard origin/master` en la Pi — no con un merge, porque un
  merge habría dejado `CLAUDE.md` trackeado de nuevo (gitignore no
  des-trackea archivos ya comiteados). El commit `d2844d3` queda accesible
  en el reflog local de la Pi si hiciera falta recuperarlo, pero no aporta
  nada que no esté ya en `597b77e`.

## Pendiente

- Instalar con `sudo` (manual, ver `deploy/systemd/README.md` y
  `docs/CONEXION_RASPBERRY.md`) las unidades systemd y `chrony`: el código
  ya está en la Pi, pero `rsu-agent`/`rsu-controller` todavía no están
  corriendo como servicio.
- Verificar el lazo completo (`docs/GUIA_COMANDOS.md`, sección 4) con los
  servicios corriendo por systemd en vez de en terminales manuales.
- Decidir si la IP de la Pi se fija, y configurar `rsu2` (ver entrada de
  bitácora anterior).
