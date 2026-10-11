# Software de gestión central (`centro_control/software_gestion.py`)

## Qué es y por qué existe

En una arquitectura de gestión SNMP, el dispositivo de campo -- la RSU -- es
el **agente**; quien lo consulta o le ordena algo (en producción, el centro
de gestión de tránsito) es el **gestor**. `centro_control/software_gestion.py`
simula ese software de gestión: monitorea el estado de la RSU y le envía
comandos, con logs con timestamp como lo haría una consola de operación real.

No reemplaza a `snmpget`/`snmpset`/`snmpwalk` de `net-snmp` (que siguen
siendo la referencia más completa); existe para máquinas donde instalar
`net-snmp` es fricción extra, como Windows -- la laptop, en este caso, no lo
tenía instalado. Tampoco depende de ninguna MIB estandarizada en particular
por ahora: solo conoce los OID genéricos que expone `agent/rsu_middleware.py`
(ver CLAUDE.md para cuándo se agrega esa capa).

## Modos de uso

- **`interactive`**: menú en pantalla (ver estado, activar/liberar
  prioridad, entrar y salir del modo monitoreo) -- pensado para explorar o
  demostrar el lazo completo en vivo.
- **`monitor`**: sin menú, solo logs periódicos de `fase` y
  `prioridad_activa` cada `--interval` segundos -- pensado para dejarlo
  corriendo de fondo mientras se prueba el resto del sistema (OBU, SNMP
  manual desde otra terminal, etc.).
- **`get` / `set` / `walk`**: comandos puntuales de una sola vez, para
  scripting o para replicar exactamente lo que haría un `snmpget`/`snmpset`
  real. Ver `docs/GUIA_COMANDOS.md` para ejemplos completos.

## Cómo se probó (2026-09-13, en su versión anterior)

Este script es la evolución de un `get`/`set`/`walk` puntual que ya se
había probado desde la laptop, con el agente corriendo en la Pi:

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r centro_control/requirements.txt
# Aplicar el parche de importlib.util en
# .venv/Lib/site-packages/pysnmp/smi/builder.py (ver docs/agent.md)

./.venv/Scripts/python.exe centro_control/software_gestion.py get \
  --host 192.168.18.163 --port 1161 \
  --v3-user rsuLabUser --auth-key labAuthPass123 --priv-key labPrivPass123 \
  1.3.6.1.4.1.99999.1.1.0
```

Resultado (con el agente mínimo de entonces, un solo OID en memoria): `GET`
devolvió `42` (de una prueba previa), `SET` a `7` confirmado, `GET`
posterior ya devolvía `7`.

## Hallazgo de dependencias (se mantiene documentado)

Instalar el commit parcheado de `pysnmp` en un entorno limpio de Windows
resuelve por defecto una versión de `pyasn1 >= 0.5` que ya no trae el
submódulo `pyasn1.compat`, y falla con:

```
ModuleNotFoundError: No module named 'pyasn1.compat'
```

Se resuelve fijando `pyasn1<0.5.0` (ver `centro_control/requirements.txt`).
No estaba documentado antes porque en la Pi el entorno (`~/rsu-env`) ya
tenía una versión compatible de `pyasn1` instalada de antes.

## Pendiente

- El `.venv` de la laptop es local (está en `.gitignore`, no se comitea).
  Si se recrea desde cero, seguir los pasos de arriba.
- Los modos `interactive`/`monitor` todavía no se probaron contra
  `agent/rsu_middleware.py` corriendo en la Raspberry Pi real -- se
  probaron los mismos `get`/`set`/`walk` subyacentes en una sola máquina de
  desarrollo (ver README, "Estado actual del desarrollo").
