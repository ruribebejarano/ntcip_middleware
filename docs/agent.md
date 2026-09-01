# Agente SNMPv3 de prueba (`agent/rsu_snmpv3_agent.py`)

## Qué es

Un agente SNMPv3 minimo hecho con `pysnmp` que expone un unico objeto entero
ficticio (OID `1.3.6.1.4.1.99999.1.1.0`, bajo un numero de empresa privado
NO registrado) para validar la pila USM (autenticacion SHA-1 + privacidad
AES-128) con `snmpget`/`snmpset` reales. **No implementa la MIB NTCIP 1202
ni 1211** — ver el comentario de cabecera del propio script.

## Bug conocido de pysnmp y por qué el setup es distinto de lo esperado

La ultima version de `pysnmp` publicada en PyPI al momento de escribir esto
(`7.1.29`, 2026-08-21) tiene un bug en el modelo de seguridad USM: la
combinacion **SHA-1 (auth) + AES-128 (priv)** — exactamente la que pide esta
tesis — falla con `Decryption error` en cualquier `snmpget`/`snmpset`
SNMPv3, sin importar que la contraseña/config sean correctas.

- Reportado en: <https://github.com/pysnmp/pysnmp/issues/54>
- Corregido en: <https://github.com/pysnmp/pysnmp/pull/98> (mergeado
  2026-08-27), pero **aun no publicado en PyPI**.

Por eso `requirements.txt` instala `pysnmp` directo desde el commit del fix
en GitHub (`398095c912d8d8494af6916ea53d1c9a9622d874`), en vez de la version
de PyPI. Dos cosas a tener en cuenta:

1. Ese commit distribuye el paquete como **`pysnmplib`** (no `pysnmp`) en
   los metadatos de pip — es un cambio de nombre del proyecto en curso — pero
   el codigo Python se sigue important como `import pysnmp` normalmente.
2. Ese commit tiene un bug propio menor en Python 3.13+: falta un
   `import importlib.util` explicito en `pysnmp/smi/builder.py`, lo que
   rompe con:
   ```
   AttributeError: module 'importlib' has no attribute 'util'
   ```
   **Parche manual necesario** despues de cada `pip install`, en el archivo
   `<venv>/lib/python3.13/site-packages/pysnmp/smi/builder.py`:
   ```diff
    import importlib
   +import importlib.util
   +import importlib.machinery

    PY_MAGIC_NUMBER = importlib.util.MAGIC_NUMBER
   ```

**Accion pendiente**: revisar periodicamente si ya salio una version oficial
en PyPI con el fix incluido, y en ese caso volver a `pip install pysnmp`
normal (quitando la dependencia del commit de git y el parche manual).

## Como correrlo

```bash
source ~/rsu-env/bin/activate
python3 agent/rsu_snmpv3_agent.py
```

Escucha en `0.0.0.0:1161` (puerto no privilegiado; el `snmpd` de referencia
del sistema sigue en el 161). Usuario USM: `rsuLabUser`, auth SHA-1
(`labAuthPass123`), priv AES-128 (`labPrivPass123`) — credenciales de
laboratorio, no usar en produccion.

## Como probarlo

Desde la misma Raspberry Pi o desde otra maquina de la red (reemplazar
`<IP_RSU>` por la IP de la Raspberry Pi, ej. `192.168.18.163`):

```bash
snmpget -v3 -u rsuLabUser -l authPriv -a SHA -A labAuthPass123 \
        -x AES -X labPrivPass123 -n "" <IP_RSU>:1161 1.3.6.1.4.1.99999.1.1.0

snmpset -v3 -u rsuLabUser -l authPriv -a SHA -A labAuthPass123 \
        -x AES -X labPrivPass123 -n "" <IP_RSU>:1161 \
        1.3.6.1.4.1.99999.1.1.0 i 42
```

Verificado localmente (`snmpget`/`snmpset`/`snmpget`): devuelve `5` (valor
inicial), confirma el `SET` a `42`, y el `GET` posterior ya devuelve `42`.
Tambien verificado accediendo por la IP LAN de la Raspberry Pi (no solo
`localhost`), confirmando que el socket esta en `0.0.0.0` y es alcanzable
desde la red. Falta la prueba final desde un segundo equipo fisico distinto.
