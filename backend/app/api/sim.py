"""Control de la simulación y stream en vivo (M1).

Todos los handlers son `async` para ejecutarse en el mismo event loop que el simulador
(sin hilos concurrentes modificando su estado).
"""
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.contracts.schemas import EventoCreate, EventoOut, KpisResponse, SimControl, SimEstadoOut, SimSnapshot, WsSnapshot
from app.sim.servicio import SimNoIniciada, servicio

router = APIRouter(tags=["simulacion"])
log = logging.getLogger("fluport.ws")


@router.get("/api/sim/estado", response_model=SimEstadoOut)
async def estado() -> SimEstadoOut:
    return servicio.requerir().estado_out()


@router.post("/api/sim/control", response_model=SimEstadoOut)
async def control(body: SimControl) -> SimEstadoOut:
    try:
        return await servicio.control(body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/api/sim/eventos", response_model=EventoOut, status_code=status.HTTP_201_CREATED)
async def inyectar_evento(body: EventoCreate) -> EventoOut:
    try:
        return servicio.evento(body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/api/sim/kpis", response_model=KpisResponse)
async def kpis() -> KpisResponse:
    return servicio.requerir().kpis_response()


@router.get("/api/sim/snapshot", response_model=SimSnapshot)
async def snapshot() -> SimSnapshot:
    """Respaldo por polling (cada 1 s) si el WebSocket falla."""
    return servicio.requerir().snapshot()


@router.websocket("/ws/sim")
async def ws_sim(ws: WebSocket) -> None:
    """Envía mensajes `WsMensaje` (snapshot | evento | aviso) en JSON, uno por tick."""
    await ws.accept()
    cola = servicio.suscribir()
    try:
        await ws.send_text(WsSnapshot(data=servicio.requerir().snapshot()).model_dump_json())  # estado inicial
        while True:
            await ws.send_text(await cola.get())
    except (WebSocketDisconnect, RuntimeError, SimNoIniciada):
        pass
    finally:
        servicio.desuscribir(cola)
