"""Agencias (empresas transportistas): catálogo y sus transportistas, para la vista de agencia."""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modulos.citas.servicio import ACTIVAS, ErrorCita, normalizar_telefono
from app.nucleo.contracts.schemas import (
    AgenciaOut,
    TransportistaCreate,
    TransportistaOut,
)
from app.nucleo.db.base import get_db
from app.nucleo.db.models import Agencia, Cita, Transportista

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
    return [_out(t, activas[t.id]) for t in filas]


def _out(t: Transportista, activas: list[datetime] | None = None) -> TransportistaOut:
    activas = activas or []
    return TransportistaOut(id=t.id, alias=t.alias, telefono_fin=(t.telefono or "")[-4:] or None,
                            telegram=t.telegram_chat_id is not None, placas=t.placas, citas_activas=len(activas),
                            proxima_cita=min(activas) if activas else None)


@router.post("/{agencia_id}/transportistas", response_model=TransportistaOut, status_code=status.HTTP_201_CREATED)
async def alta_transportista(agencia_id: str, body: TransportistaCreate, db: Session = Depends(get_db)) -> TransportistaOut:
    """La agencia da de alta a un transportista; solo los números dados de alta pueden vincularse al bot."""
    if db.get(Agencia, agencia_id) is None:
        raise HTTPException(404, f"agencia {agencia_id} no existe")
    try:
        tel = normalizar_telefono(body.telefono)
    except ErrorCita as e:
        raise HTTPException(e.codigo, e.mensaje) from e
    t = db.scalar(select(Transportista).where(Transportista.telefono == tel))
    if t is not None and t.agencia_id not in (None, agencia_id):
        raise HTTPException(409, "ese número ya está dado de alta en otra agencia")
    if t is None:
        t = Transportista(telefono=tel, es_demo=True, alias=body.alias)
        db.add(t)
    t.alias, t.placas, t.agencia_id = body.alias, (body.placas or "").strip().upper() or None, agencia_id
    db.commit()
    return _out(t)
