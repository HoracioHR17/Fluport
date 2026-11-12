"""Vista pública para vecinos (M7): sin datos de operación."""
from fastapi import APIRouter

from app.contracts.schemas import ZonaPublica
from app.publico.servicio import zonas as calcular_zonas
from app.sim.servicio import servicio

router = APIRouter(prefix="/api/publico", tags=["publico"])


@router.get("/zonas", response_model=list[ZonaPublica])
async def zonas() -> list[ZonaPublica]:
    """Semáforo actual, horas pico de las próximas 12 h y mejor hora para circular, por caseta."""
    return calcular_zonas(servicio.requerir())
