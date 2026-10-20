"""Aplicacion FastAPI de la consola: expone el estado del banco por REST y
por SSE (/sse), y sirve el frontend estatico (consola/static/). Arranca
los hilos en segundo plano (MQTT, SNMP, OBU local, eventos remotos,
estado del banco) en el evento de inicio."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from consola.backend import analisis, config, estado_banco, eventos_remotos, mapa, mqtt_cliente, obu_local, pruebas, snmp_poller
from consola.backend.bus import BUS
from consola.backend.estado import ESTADO
from consola.backend.registro_comandos import REGISTRO

ESTATICOS = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    BUS.fijar_loop(asyncio.get_running_loop())
    mqtt_cliente.iniciar()
    snmp_poller.iniciar()
    obu_local.iniciar()
    eventos_remotos.iniciar()
    estado_banco.iniciar()
    yield


app = FastAPI(title="Consola del centro de control", lifespan=lifespan)


# --------------------------------------------------------------------------
# Estado en vivo
# --------------------------------------------------------------------------

@app.get("/api/estado")
def api_estado() -> dict:
    return {"config": {
        "mqtt_broker": f"{config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}",
        "snmp_host": f"{config.SNMP_HOST}:{config.SNMP_PORT}",
        "rsu_id": config.RSU_ID,
        "ssh_alias": config.SSH_HOST_ALIAS,
    }, **ESTADO.foto()}


@app.get("/api/mapa")
def api_mapa() -> dict:
    return mapa.geometria_corredor()


@app.get("/sse")
async def sse(request: Request) -> StreamingResponse:
    q = BUS.suscribirse()

    async def flujo():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evento = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"id: {evento['id']}\nevent: {evento['tipo']}\ndata: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            BUS.desuscribirse(q)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# Pruebas (botones de la pantalla de monitoreo)
# --------------------------------------------------------------------------

@app.post("/api/pruebas/{nombre}/iniciar")
def api_prueba_iniciar(nombre: str) -> dict:
    ok, msg = pruebas.iniciar_prueba(nombre, config.MQTT_BROKER_HOST)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": ok, "mensaje": msg}


@app.post("/api/pruebas/{nombre}/detener")
def api_prueba_detener(nombre: str) -> dict:
    ok, msg = pruebas.detener_prueba(nombre)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": ok, "mensaje": msg}


# --------------------------------------------------------------------------
# Ensayos y metricas
# --------------------------------------------------------------------------

@app.get("/api/ensayos/corridas")
def api_corridas() -> list[dict]:
    return analisis.listar_corridas()


@app.get("/api/ensayos/corridas/{nombre}")
def api_corrida(nombre: str) -> dict:
    r = analisis.resumen_corrida(nombre)
    if r is None:
        raise HTTPException(404, "corrida no encontrada")
    return r


@app.get("/api/ensayos/comparar")
def api_comparar(corridas: str) -> dict:
    """`corridas` = "nombre1:Etiqueta1,nombre2:Etiqueta2"."""
    pares = []
    for parte in corridas.split(","):
        if not parte.strip():
            continue
        nombre, _, etiqueta = parte.partition(":")
        pares.append((nombre.strip(), (etiqueta or nombre).strip()))
    if len(pares) < 2:
        raise HTTPException(400, "se necesitan al menos dos corridas")
    return analisis.comparar_corridas(pares)


@app.post("/api/ensayos/corridas/{nombre}/exportar")
def api_exportar(nombre: str, nota: str = "") -> dict:
    ok, salida, carpeta = analisis.exportar_figuras(nombre, nota)
    if not ok:
        raise HTTPException(500, salida[-2000:])
    return {"ok": ok, "carpeta": carpeta, "salida": salida[-4000:]}


# --------------------------------------------------------------------------
# Registro de comandos (auditoria)
# --------------------------------------------------------------------------

@app.get("/api/comandos")
def api_comandos(canal: str | None = None, buscar: str | None = None, limite: int = 500) -> list[dict]:
    return REGISTRO.listar(canal=canal, texto=buscar, limite=limite)


@app.get("/api/comandos/descargar")
def api_comandos_descargar() -> FileResponse:
    if not config.REGISTRO_COMANDOS_PATH.exists():
        raise HTTPException(404, "todavia no hay registro")
    return FileResponse(config.REGISTRO_COMANDOS_PATH, filename="registro_comandos.jsonl",
                        media_type="application/x-ndjson")


# --------------------------------------------------------------------------
# Frontend estatico
# --------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=ESTATICOS, html=True), name="static")
