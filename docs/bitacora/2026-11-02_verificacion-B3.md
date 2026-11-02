# 2026-11-02 — Verificación de B3 (cierre automático de misión)

**Objetivo específico:** OE4 (OBU/protocolo)  **Requerimientos:** RF-04 (cancelación), RF-09/RNF-03 (caducidad, por contraste)
**Sección de la tesis:** 3.x (fin de misión) → 4.x (prueba)
**Commit:** `1fe993b`

Ítem 3 de `prompt_integracion_app_obu.md`: verificar B3 (ya implementado
en `f066e28`, sesión del 2026-11-01) sin reimplementarlo.

## Qué se implementó

No se cambió la lógica de `servidor/gestor_mision.py`; se verificaron los
tres puntos que pedía el prompt:

1. **Comentario desactualizado.** `ObuSessionService.kt::onMensajeEstado`
   (~l. 332) decía "mision_activa/motivo_fin: campos propuestos, no
   implementados todavía por servidor/gestor_mision.py" — ya lo están
   desde B3. Corregido.
2. **Botón "Terminar" tras un cierre automático.** Por código:
   `terminarPorServidor()` pone `terminando = true` antes de lanzar la
   corrutina; `terminarPorBoton()` empieza con `if (terminando) return`.
   Si el usuario pulsa "Terminar" mientras el `Service` sigue vivo, el
   botón es un no-op (no envía MF). Si Android ya detuvo el `Service`
   (`stopSelf()` ya se procesó) y el intent `ACCION_TERMINAR` crea una
   instancia nueva, esa instancia tiene `obuId == null`, así que
   `terminarPorBoton()` llama `stopSelf()` sin publicar nada. En ningún
   caso se envía un MF de más o se lanza una excepción. No se agregó una
   prueba para esto: `ObuSessionService` es un `LifecycleService` de
   Android y no es testeable en JVM sin Robolectric (no es dependencia
   del proyecto); se deja verificado por lectura de código.
3. **Cierre por destino/tiempo máximo y las solicitudes abiertas en la
   RSU.** `test_desarme_por_llegada_a_destino` y
   `test_desarme_por_tiempo_maximo` solo comprobaban
   `mision.activa`/`motivo_fin`/el ME, no si una solicitud que había
   quedado abierta en una RSU se cerraba de verdad. Ambos caminos ya
   pasaban por `desarmar_mision()` (la misma función que
   `test_desarme_cancela_todo_lo_pendiente` prueba para `motivo="boton"`),
   pero no había una prueba específica para "destino" ni "tiempo_maximo".
   Se amplió cada prueba para dejar una solicitud abierta en SINT-C antes
   del cierre y verificar que termina en `ESTADO_CANCELADA` con un M3 del
   motivo correspondiente.

## Cómo

- `app_obu/obu/ObuSessionService.kt` (solo comentario).
- `tests/test_gestor_mision.py`: las dos pruebas existentes, ampliadas
  (no se agregaron pruebas nuevas, se les agregaron aserciones).
- `pytest -q`: 121 pruebas; `gradlew testDebugUnitTest`: 28 pruebas Kotlin.

## Desviaciones respecto del diseño de la tesis

Ninguna — no se cambió comportamiento, solo se verificó y se documentó
mejor lo que ya existía.

## Evidencia

- `pytest tests/test_gestor_mision.py -q`: 16/16 en ese archivo.

## Problemas y solución

Ninguno nuevo.

## Pendiente

- `UMBRAL_LLEGADA_DESTINO_M = 20 m` (constante de B3, en
  `servidor/gestor_mision.py`) sigue provisional, `[REVISAR con
  asesor]` — no se tocó en este ítem, solo se confirma que sigue
  pendiente de validar con el asesor.
