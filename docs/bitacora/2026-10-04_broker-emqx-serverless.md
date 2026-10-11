# 2026-10-04 — Broker MQTT en EMQX Cloud Serverless

**Objetivo específico:** OE5 / OE6 (canal V2I) y OE4 (I2I vía broker)  **Requerimientos:** RNF-01, RNF-05
**Sección de la tesis:** 3.3.2 (`ssec:sel_protocolo_app`) → implementación del broker; 3.8 (seguridad); 4.3
**Commit:** — (configuración en la nube, sin código)

## Qué se implementó
Despliegue `rsu-tesis` (proyecto "Tesis") en EMQX Cloud, plan **Serverless**, creado el 2026-10-04 20:12.
Estado: Running. Cuota: 1000 sesiones / 1000 msg/s; límite de gasto: USD 0 (solo capa gratuita).

## Cómo
- Dirección: `p1d725c0.ala.us-east-1.emqxsl.com` (región AWS us-east-1).
- MQTT sobre TLS/SSL: puerto 8883. WebSocket sobre TLS: 8084.
- Certificado de CA del servidor descargable desde la consola (vence 2031-11-09).

## Desviaciones respecto del diseño de la tesis
- **Ubicación del broker:** en EE. UU. (us-east-1), no en Lima. Añade el retardo Lima–Virginia a t_up y t_down; debe reportarse y discutirse en 4.3 y 4.8.
- **mTLS con CA propia:** PENDIENTE DE VERIFICAR si el plan Serverless permite autenticación por certificado X.509 de cliente emitido por la CA propia (ssec:seg_pki). Si no lo permite: autenticación por usuario y contraseña sobre TLS de servidor, y registrar la desviación.

## Evidencia
- `evidencia/2026-10-11_broker_emqx-overview.png`: vista general del despliegue.

## Problemas y solución
—

## Pendiente
- Credenciales por cliente, ACL por tópico y verificación de la versión de TLS (ver la lista en el chat del 2026-10-11).
