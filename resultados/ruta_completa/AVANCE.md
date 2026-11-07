# Avance: campaña de ruta completa (Av. La Marina → hospital de Breña)

Plan: [PLAN.md](PLAN.md). Cinco repeticiones por escenario, a pedido del autor; destino en
Breña. Decisiones por defecto aplicadas:

- El origen se llama Av. La Marina.
- Las RSU 102 y 113 se mantienen.
- B lleva una detención dirigida.

## Hecho

- **Registro de 13 RSU:** `scripts/campanas/fixtures/registro_ruta_hospital_nino.json`, generado
  por `scripts/datos/registro_ruta.py`.
  - Las 13 intersecciones a menos de 25 m de la ruta se aceptaron, sin descartes; ninguna está
    entre 25 y 60 m.
  - Los rumbos de acceso salen del grafo real.
  - El servidor reconoce las 13 como paradas.
- **Controlador emulado:** nueva opción `--desfase-s`, que con 0 se comporta igual que antes, y
  evento `ctrl_inicio` con el instante de inicio del ciclo. Prueba agregada; las 48 pruebas
  relacionadas pasan.
- **Trayectorias base y validación sin red:** `scripts/campanas/preparar_ruta_completa.py` deja
  todo en `scripts/campanas/fixtures/ruta_completa/`.
  - A: 530 s; cada semilla solo cambia el ruido.
  - B: un perfil sintético por semilla, de 596 a 649 s.
  - C: desvío por Jr. Mariscal Toribio Luzuriaga, a 4135 m del origen, hasta 140 m fuera de la
    ruta.
- **Runner:** `scripts/campanas/ruta_completa.py`.
- **Análisis:** `scripts/analisis/ruta_completa.py`.
- **Figuras:** `scripts/analisis/figuras_ruta_completa.py`.
- **Broker de campaña:** TLS 1.3 + mTLS en el puerto 8883, arrancado aparte; el servicio de 1883
  no se tocó.
- **Repetición de prueba (A, semilla 100):** `_prueba/`, no cuenta como dato.
  - Las 13 solicitudes se concedieron y respondieron (13/13).
  - Arranque de 6,1 s y 542 s de duración.
  - La memoria libre bajó como mínimo a 2014 MB.
- **Campaña lanzada:** A, B y C en secuencia, desde las 12:36. Log en `_campana_*.log`.

## Hallazgos ya visibles (prueba y simulación sin red)

- **Una sola solicitud activa a la vez.** La geocerca sigue una sola intersección.
- **`t_servicio = 8 s` en las solicitudes de la geocerca.** Las solicitudes que abre la geocerca a
  150 m llevan la anticipación mínima, aunque el vehículo esté a unos 15 s.
- **RSU 104 por debajo de 8 s en la prueba.** La anticipación fue de 7,98 s: la solicitud sale
  por ETA justo después de un giro.
- **Doble recálculo en el desvío (C).** El primer recálculo parte de un nodo que todavía está
  sobre Av. Brasil.
- **La solicitud de la RSU 108 se cancela con motivo "cruce" al girar.** La geocerca la cancela
  al quedar atrás, aunque el vehículo no cruzó esa intersección.

## Resultado (campaña completa)

- **Corridas:** A, B y C terminaron sin problemas (11/11 repeticiones). Broker de 8883 detenido.
- **Análisis, figuras y textos:** listos. Ver `RESUMEN.md`, `LEEME.md` y
  `borrador_seccion_tesis.tex`.
- **Corrección del análisis:** "verde con vehículo detenido" ahora cuenta solo los tramos con la
  solicitud vigente, de cada concesión al M3 siguiente.

## Falta

- Decidir con el asesor cómo se reconcilia la anticipación < 8 s con la tabla de cumplimiento y
  las conclusiones.
- Corregir el destino en la subsección 4.3.7 vigente, que dice "Hospital del Niño" para una ruta
  de 2928 m.
