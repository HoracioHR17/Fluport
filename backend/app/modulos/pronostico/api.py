"""Pronóstico de congestión (M2)."""
from fastapi import APIRouter, HTTPException, Query

from app.modulos.pronostico.dominio.features import FRANJA_MIN
from app.modulos.pronostico.pronosticador import pronosticador
from app.nucleo.contracts.enums import Mundo
from app.nucleo.contracts.schemas import PronosticoOut
from app.nucleo.dependencias import operacion

router = APIRouter(prefix="/api/pronostico", tags=["pronostico"])


@router.get("", response_model=list[PronosticoOut])
async def pronostico(
    acceso_id: str | None = Query(None, description="None = todos los accesos"),
    horas: int = Query(12, ge=1, le=12),
    mundo: Mundo = Query(Mundo.B, description="B = operación con Fluport (único mundo)"),
) -> list[PronosticoOut]:
    sim = operacion()
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
