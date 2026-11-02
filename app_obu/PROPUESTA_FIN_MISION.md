# Propuesta: señal explícita de fin de misión en ME

**Implementado 2026-11-01 (B3), en `E:\Tesis\ntcip_middleware`** (los
puntos 2, 3 y 4 de la sección 3 de abajo; el punto 5, pruebas unitarias,
también): `docs/CONTRATO_OBU.md` ya documenta `mision_activa`/
`motivo_fin` como campos vigentes del ME, y `servidor/gestor_mision.py`
detecta la llegada a destino. Esta app (`app_obu/`) ya los interpretaba
desde antes (ver `ObuSessionService.onMensajeEstado()`), así que no
necesitó cambios propios. Se deja el resto de este documento tal cual,
como registro de la propuesta original.

Este documento era una propuesta, no una implementación, cuando se
escribió. Lo escribió la sesión de `app_obu/` (worktree
`E:\Tesis\ntcip_app`, rama `app-obu`) porque el cambio que hacía falta
caía en `docs/CONTRATO_OBU.md` y `servidor/gestor_mision.py`, fuera de la
carpeta de la app y de las instrucciones de esa sesión.

## 1. El problema

`docs/CONTRATO_OBU.md` §5 dice que la app debe tratar como fin de misión
cualquiera de tres casos (botón, destino, tiempo máximo), "todos
reflejados en el ME final". Pero revisando `servidor/gestor_mision.py`:

- **`_cuerpo_me()`** (línea 443) no incluye ningún campo que diga si la
  misión sigue activa ni por qué terminó. Solo expone `paradas`,
  `proximo` y `conflicto`.
- **El estado "todas las paradas canceladas" es ambiguo.** Pasa en el ME
  final de un desarme (botón o tiempo máximo) -- pero pasa IGUAL de forma
  normal cuando el vehículo ya cruzó la última RSU de la ruta y sigue
  manejando hacia el destino, sin más semáforos por delante. Un cliente
  que mire solo `paradas`/`proximo` no puede distinguir "la misión
  terminó" de "la misión sigue, ya no hay más semáforos". Confirmado
  revisando `_aplicar_decision_geocerca` (motivo `"cruce"`, línea ~278) y
  `desarmar_mision` (línea 493): ambos casos dejan el mismo patrón
  (`paradas` todas en `cancelada`, `proximo = null`).
- **El caso "destino" no está implementado todavía.** No encontré, en
  `procesar_mp()` (línea 218), ninguna comparación entre la posición MP y
  `mision.destino` que dispare `desarmar_mision(obu_id, motivo="destino")`.
  Hoy una misión solo se desarma por botón (MF) o por
  `TIEMPO_MAXIMO_MISION_S` (1800 s). El `[DATO]` de §5 del contrato
  ("el umbral de distancia... no está definido") es consistente con que
  esto quedó pendiente, no solo sin umbral fijado.

Por instrucción explícita de esta sesión, `app_obu/` **no** implementa su
propia detección de llegada a destino ni envía MF con otro motivo que
`"boton"` (eso dejaría al servidor y a la app con dos lógicas de "llegó"
que podrían no coincidir). La detección de llegada le corresponde al
servidor, que es quien ya tiene la posición MP y el destino de la misión.

## 2. Cambio propuesto al contrato (`docs/CONTRATO_OBU.md` §4, ME)

Agregar dos campos al JSON de ME:

```json
{
  "tipo": "ME",
  "mision_id": "mis-756ed62d",
  "paradas": [...],
  "proximo": null,
  "conflicto": false,
  "mision_activa": false,
  "motivo_fin": "destino",
  "ts_ms": 1761144090000
}
```

- `mision_activa` (bool): `true` en todos los ME salvo el último. Ese
  último ME (el que ya refleja el desarme) lleva `false`.
- `motivo_fin` (string | null): `"boton" | "destino" | "tiempo_maximo"`
  en ese último ME; `null` en todos los anteriores.
- **Compatibilidad hacia atrás:** ambos campos van después de los
  existentes y son opcionales. Un cliente que no los conozca sigue
  funcionando igual que hoy. `app_obu/` (esta app) ya los interpreta: si
  llegan ausentes (`null`, servidor actual sin este cambio), NO termina la
  misión por su cuenta -- solo lo hace el botón. Ver
  `app_obu/app/src/main/java/pe/pucp/ntcip/obu/obu/Mensajes.kt`
  (`MensajeME.mision_activa`/`motivo_fin`) y
  `ObuSessionService.onMensajeEstado()`.

## 3. Cambio propuesto en `servidor/gestor_mision.py` (boceto, no aplicado)

1. Agregar a `Mision` (línea ~110) un campo `motivo_fin: Optional[str] = None`.
2. En `desarmar_mision()` (línea 493), antes de construir el ME final,
   asignar `mision.motivo_fin = motivo`.
3. En `_cuerpo_me()` (línea 443), agregar al dict de salida:
   `"mision_activa": mision.activa, "motivo_fin": mision.motivo_fin`.
4. Implementar la detección de llegada a destino en `procesar_mp()`
   (línea ~232, junto al cálculo de `progreso`): comparar `(lat, lon)`
   contra `mision.destino` con un umbral del mismo orden que
   `MARGEN_CRUCE_M` (20 m, línea 80) -- por ejemplo una constante nueva
   `UMBRAL_LLEGADA_DESTINO_M` -- y si está dentro del umbral, llamar
   `self.desarmar_mision(obu_id, motivo="destino")` y retornar antes de
   seguir con la geocerca.
5. `tests/test_gestor_mision.py`: agregar un caso por cada motivo de
   desarme (`"boton"`, `"destino"`, `"tiempo_maximo"`) que verifique que
   el ME final trae `mision_activa=false` y el `motivo_fin` correcto.

## 4. Nota secundaria: `fuente_velocidad="simulada"` (aplicado 2026-11-01)

El modo de trayectoria simulada de `app_obu/` (ver `app_obu/README.md`,
sección "Modo simulado") publica MP con `"fuente_velocidad": "simulada"`.
Ese valor ya está en el enum vigente de `docs/CONTRATO_OBU.md` §3
(`"gps" | "respaldo" | "simulada"`, tras retirar el lector OBD-II del
alcance -- ver trabajo futuro). Es un campo informativo que
`servidor/gestor_mision.py` no valida ni distingue hoy:

```
`fuente_velocidad`: `"gps" | "respaldo" | "simulada"` -- "simulada"
solo lo usa app_obu/ en su modo de trayectoria pregrabada para pruebas en
mesa sin GNSS (ver app_obu/README.md), nunca en una misión real.
```
