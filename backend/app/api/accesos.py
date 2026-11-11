"""Accesos y su estado actual (M1/M6)."""
from fastapi import APIRouter, Query

from app.api._stub import pendiente
from app.contracts.enums import Mundo
from app.contracts.schemas import AccesoEstado, AccesoOut

router = APIRouter(prefix="/api/accesos", tags=["accesos"])


@router.get("", response_model=list[AccesoOut])
def listar_accesos() -> list[AccesoOut]:
    raise pendiente("M1")


@router.get("/estado", response_model=list[AccesoEstado])
def estado_accesos(mundo: Mundo = Query(Mundo.B)) -> list[AccesoEstado]:
    raise pendiente("M1")
