"""Vista pública para vecinos (M7): sin datos de operación."""
from fastapi import APIRouter

from app.api._stub import pendiente
from app.contracts.schemas import ZonaPublica

router = APIRouter(prefix="/api/publico", tags=["publico"])


@router.get("/zonas", response_model=list[ZonaPublica])
def zonas() -> list[ZonaPublica]:
    raise pendiente("M7")
