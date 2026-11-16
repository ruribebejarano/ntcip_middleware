# Seguridad operativa: OBU comprometida y saturación del broker

Complementa la matriz de seguridad T01–T17 (credenciales inválidas, ACL,
SNMPv3). Esa matriz prueba que un atacante **sin** credenciales no entra.
Estas pruebas miran el caso que la matriz no cubre: un atacante **con** una
credencial válida, es decir, una OBU robada, clonada o manipulada.

## Por qué este es el ataque relevante

Con la arquitectura centralizada (E3), una OBU no puede ordenarle nada a una
RSU: la ACL solo deja publicar solicitudes al servidor. El camino más
barato para encender verdes es otro: armar una misión falsa con un
certificado válido y dejar que el servidor pida la prioridad. TLS no lo
impide, porque la credencial es legítima. Lo detienen dos cosas:

- la plausibilidad de lo que la OBU reporta (detección automática);
- la verificación humana de que la misión existe (procedimiento operativo).

## Respuesta en capas

| Capa | Quién actúa | Qué hace |
|---|---|---|
| 1. Detección | Servidor central (`servidor/seguridad.py`), automático | Detecta saltos de posición imposibles, inundación de MP o misiones repetidas, y avisa de cada misión armada para que se verifique |
| 2. Notificación | Servidor → operador de la central | Alerta en el tema `servidor/central/alertas` (solo la lee la identidad `operador-central`); el aviso a la Municipalidad (CCGT de la MML) sale de este paso |
| 3. Verificación humana | Operador de la central ↔ despacho de la institución | Llamada o radio a la central de despacho dueña del vehículo (SAMU 106, Bomberos 116, PNP 105): ¿esa unidad tiene una emergencia en curso? |
| 4. Contención | Operador de la central (y el CCGT) | Suspender la misión o la OBU (comando en `servidor/central/comandos`); revocar su certificado (`generar_ca.py revocar`, la CRL corta la reconexión); si el ataque persiste en una intersección, el CCGT desactiva la prioridad en esa RSU |
| 5. Cierre | Municipalidad e institución | Informe del incidente con el registro de eventos (RF-08), recuperación del dispositivo, denuncia si corresponde |

Quién opera el servidor central (el CCGT, la institución o ambos) es una
decisión pendiente del diseño: define quién recibe la alerta en la capa 2.
El código no depende de eso: solo exige la identidad `operador-central`.

## Qué se construyó

- `servidor/seguridad.py`: detección, alertas, suspensión de OBU y de
  misión, confirmación obligatoria opcional. Parámetros por variable de
  entorno (`SEG_*`); los valores por defecto son parámetros de prueba del
  banco, no umbrales normativos: velocidad implícita máxima 150 km/h con un
  salto mínimo de 50 m, tasa máxima de MP 3 Hz en ventanas de 5 s (el
  contrato fija 1 Hz), 3 MI en 60 s.
- `servidor/main.py`: integra el monitor; publica alertas y lee comandos.
- `scripts/seguridad/mosquitto_acl.conf`: identidad `operador-central`
  (lee alertas, escribe comandos); el servidor escribe alertas y lee
  comandos.
- `scripts/seguridad/generar_ca.py`: tipo de certificado `operador`.
- `scripts/seguridad/operador_central.py`: el operador emulado (responde a
  cada alerta tras un retardo) y, con `--comando`, una consola mínima para
  un operador real.
- `scripts/seguridad/prueba_seguridad_operativa.py`: corre los escenarios
  con un broker propio en `127.0.0.1:8884`.
- `scripts/seguridad/analisis_seguridad_operativa.py`: métricas.
- `tests/test_seguridad_operativa.py`: pruebas del monitor.

## Escenarios

| Escenario | Ataque | Variantes |
|---|---|---|
| `base` | Ninguno: misión legítima sola (referencia) | — |
| `mision_falsa` | OBU con certificado válido arma una misión que no existe, con trayectoria plausible | operador con 30 s y 120 s de respuesta; confirmación obligatoria de 20 s sin operador |
| `clon` | El mismo certificado en dos lugares: las posiciones alternan con un punto a 3 km | operador con 30 s; suspensión automática |
| `inundacion` | OBU válida publica MP a 50 o 200 Hz mientras corre una misión legítima | sin respuesta; suspensión automática |

Los retardos del operador representan el tiempo de respuesta humana. **No
se miden en el banco**: son parámetros, y la tabla de resultados muestra
cuántos verdes indebidos produce cada uno.

## Métricas

- Tiempo de detección: primer mensaje anómalo del atacante → alerta.
- Tiempo de contención: alerta → comando aplicado en el servidor.
- M3 a la RSU y liberación del controlador tras el comando.
- Verdes por prioridad que obtuvo el atacante y sus segundos.
- Con inundación: latencia L y RTT de la misión legítima frente a la
  referencia, entrega de M1, y MP del atacante que el servidor ignoró tras
  suspenderlo (el broker los sigue reenviando: suspender en el servidor no
  desconecta al cliente; eso lo hace la revocación).

## Cómo correrlo

Git Bash, raíz del repo (no necesita la Pi ni el broker de la laptop):

```bash
bash scripts/seguridad/plan_seguridad_operativa.sh
```

Unos 55 minutos con 3 repeticiones por variante. Resultados en
`resultados/seguridad/`; resumen con:

```bash
python scripts/seguridad/analisis_seguridad_operativa.py
```

## Límites de la prueba

- Todo en la condición local: mide la lógica de detección y contención, no
  el enlace celular.
- El tiempo de respuesta humana es un parámetro, no una medición.
- La revocación del certificado no se repite aquí: ya está probada en T05.
  El broker de esta prueba lee la CRL al arrancar; en un despliegue, cargar
  una CRL nueva exige recargar el broker.
- La desactivación de la prioridad en una RSU desde el CCGT queda como
  procedimiento: no se inventa un objeto para eso. En el borrador de la MIB
  de NTCIP 1211 que tiene el proyecto (sin verificar contra la norma
  oficial) aparecen dos mecanismos que conviene revisar con la norma:
  `prgPriorityClear` (borra una solicitud) y
  `priorityRequestReserviceClassXTime` (tiempo mínimo entre el fin de una
  estrategia y el siguiente servicio de una clase, un bloqueo que acota
  cuántos verdes puede obtener un abuso en la misma intersección, como el
  bloqueo de dos ciclos del piloto de Oakland County).
