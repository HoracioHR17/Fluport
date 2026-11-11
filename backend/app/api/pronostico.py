"""Pronóstico de congestión (M2)."""
from fastapi import APIRouter, Query

from app.api._stub import pendiente
from app.contracts.schemas import PronosticoOut

router = APIRouter(prefix="/api/pronostico", tags=["pronostico"])


@router.get("", response_model=list[PronosticoOut])
def pronostico(
    acceso_id: str | None = Query(None, description="None = todos los accesos"),
    horas: int = Query(12, ge=1, le=24),
) -> list[PronosticoOut]:
    raise pendiente("M2")
