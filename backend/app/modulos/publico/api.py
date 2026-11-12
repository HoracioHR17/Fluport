"""Vista pública para vecinos (M7): sin datos de operación."""
from fastapi import APIRouter

from app.modulos.publico.servicio import zonas as calcular_zonas
from app.nucleo.contracts.schemas import ZonaPublica
from app.nucleo.dependencias import operacion

router = APIRouter(prefix="/api/publico", tags=["publico"])


@router.get("/zonas", response_model=list[ZonaPublica])
async def zonas() -> list[ZonaPublica]:
    """Semáforo actual, horas pico de las próximas 12 h y mejor hora para circular, por caseta."""
    return calcular_zonas(operacion())
