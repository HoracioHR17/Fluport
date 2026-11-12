"""Agencias (empresas transportistas): catálogo y sus transportistas, para la vista de agencia."""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.citas.servicio import ACTIVAS
from app.contracts.schemas import AgenciaOut, TransportistaOut
from app.db.base import get_db
from app.db.models import Agencia, Cita, Transportista

router = APIRouter(prefix="/api/agencias", tags=["agencias"])


@router.get("", response_model=list[AgenciaOut])
async def listar(db: Session = Depends(get_db)) -> list[AgenciaOut]:
    conteo = dict(db.execute(select(Transportista.agencia_id, func.count()).group_by(Transportista.agencia_id)).all())
    return [AgenciaOut(id=a.id, nombre=a.nombre, transportistas=conteo.get(a.id, 0))
            for a in db.scalars(select(Agencia).order_by(Agencia.id))]


@router.get("/{agencia_id}/transportistas", response_model=list[TransportistaOut])
async def transportistas(agencia_id: str, db: Session = Depends(get_db)) -> list[TransportistaOut]:
    """Transportistas de la agencia con sus citas activas (teléfono enmascarado)."""
    if db.get(Agencia, agencia_id) is None:
        raise HTTPException(404, f"agencia {agencia_id} no existe")
    filas = list(db.scalars(select(Transportista).where(Transportista.agencia_id == agencia_id)
                            .order_by(Transportista.alias)))
    activas: dict[int, list[datetime]] = defaultdict(list)
    if filas:
        q = select(Cita.transportista_id, Cita.ventana_inicio).where(
            Cita.transportista_id.in_([t.id for t in filas]), Cita.estado.in_(ACTIVAS))
        for tid, inicio in db.execute(q):
            activas[tid].append(inicio)
    return [TransportistaOut(id=t.id, alias=t.alias, telefono_fin=(t.telefono or "")[-4:] or None,
                             telegram=t.telegram_chat_id is not None, citas_activas=len(activas[t.id]),
                             proxima_cita=min(activas[t.id]) if activas[t.id] else None) for t in filas]
