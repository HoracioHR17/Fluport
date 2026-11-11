"""Pronóstico de congestión (M2)."""
from fastapi import APIRouter, HTTPException, Query

from app.contracts.enums import Mundo
from app.contracts.schemas import PronosticoOut
from app.prediction.features import FRANJA_MIN
from app.prediction.pronosticador import pronosticador
from app.sim.servicio import servicio

router = APIRouter(prefix="/api/pronostico", tags=["pronostico"])


@router.get("", response_model=list[PronosticoOut])
async def pronostico(
    acceso_id: str | None = Query(None, description="None = todos los accesos"),
    horas: int = Query(12, ge=1, le=12),
    mundo: Mundo = Query(Mundo.B, description="B = con Fluport (operación), A = sin Fluport"),
) -> list[PronosticoOut]:
    sim = servicio.requerir()
    res = pronosticador.obtener(sim, mundo)
    if acceso_id is not None:
        res = [p for p in res if p.acceso_id == acceso_id]
        if not res:
            raise HTTPException(404, f"acceso_id inexistente: {acceso_id}")
    n = horas * 60 // FRANJA_MIN
    return [p.model_copy(update={"franjas": p.franjas[:n]}) for p in res]


@router.get("/modelo")
async def modelo() -> dict:
    """Versión y métricas de evaluación del modelo en uso (error medio en minutos sobre días no vistos)."""
    return {"version": pronosticador.version, "metricas": pronosticador.metricas}
