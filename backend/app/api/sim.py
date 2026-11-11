"""Control de la simulación y stream en vivo (M1)."""
from fastapi import APIRouter, WebSocket, status

from app.api._stub import pendiente
from app.contracts.schemas import EventoCreate, EventoOut, KpisResponse, SimControl, SimEstadoOut, SimSnapshot

router = APIRouter(tags=["simulacion"])


@router.post("/api/sim/control", response_model=SimEstadoOut)
def control(body: SimControl) -> SimEstadoOut:
    raise pendiente("M1")


@router.post("/api/sim/eventos", response_model=EventoOut, status_code=status.HTTP_201_CREATED)
def inyectar_evento(body: EventoCreate) -> EventoOut:
    raise pendiente("M1")


@router.get("/api/sim/kpis", response_model=KpisResponse)
def kpis() -> KpisResponse:
    raise pendiente("M1")


@router.get("/api/sim/snapshot", response_model=SimSnapshot)
def snapshot() -> SimSnapshot:
    """Respaldo por polling (cada 1 s) si el WebSocket falla."""
    raise pendiente("M1")


@router.websocket("/ws/sim")
async def ws_sim(ws: WebSocket) -> None:
    """Envía mensajes `WsMensaje` (snapshot | evento | aviso) en JSON, uno por tick."""
    await ws.accept()
    await ws.close(code=1013, reason="Pendiente de implementar en M1")
