# Numeración de los requerimientos funcionales

La tesis retiró RF-01 y renumeró los demás: cada RF de la tesis es una posición
menor que el del software. Los comentarios, registros y documentos de este
repositorio conservan la numeración original. Las tablas y figuras que generan
`validacion_ntcip.py`, `cumplimiento_rf8.py`, `graficos_campana_centralizada.py`
y `resumen_capitulo4.py` usan la de la tesis.

| Repositorio | Tesis | Requerimiento |
|---|---|---|
| RF-01 | (retirado) | Bus OBD-II como fuente de velocidad |
| RF-02 | RF-01 | Posición, rumbo y velocidad por GNSS |
| RF-03 | RF-02 | Publicar MP a 1 Hz con misión activa |
| RF-04 | RF-03 | Armar y desarmar la misión |
| RF-05 | RF-04 | Autenticación y clases de vehículo reconocidas |
| RF-06 | RF-05 | Verificar tiempos de fase y encolar en el despeje |
| RF-07 | RF-06 | Traducir a NTCIP 1211 |
| RF-08 | RF-07 | Leer NTCIP 1202 e informar el estado |
| RF-09 | RF-08 | Caducidad de la solicitud |
| RF-10 | RF-09 | Registro de eventos |
| RF-11 | RF-10 | Indicador y mapa en la aplicación |
| RF-12 | RF-11 | Autenticar la OBU y registrar la misión |
| RF-13 | RF-12 | Ruta y lista de RSU |
| RF-14 | RF-13 | ETA y anticipación |
| RF-15 | RF-14 | Verificación de geocerca |
| RF-16 | RF-15 | Recálculo ante desvío |
| RF-17 | RF-16 | Arbitraje entre misiones |
| RF-18 | RF-17 | Solo el servidor solicita prioridad a la RSU |
