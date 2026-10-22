"""Servidor central de la arquitectura centralizada (ver docstring de
servidor/gestor_mision.py y E:\\Tesis\\prompt_arquitectura_centralizada.md).

El servidor es el UNICO decisor: calcula la ruta (servidor/rutas.py),
administra el ciclo de vida de la mision y la verificacion por geocerca
(servidor/gestor_mision.py), arbitra conflictos entre misiones
(servidor/conflictos.py) y expone todo eso como un proceso MQTT 5
(servidor/main.py), simetrico a agent/rsu_middleware.py del lado de la RSU.
"""
