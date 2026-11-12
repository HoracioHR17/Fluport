"""Agencias (empresas transportistas): catálogo y sus transportistas, para la vista de agencia."""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modulos.agencias import servicio
from app.modulos.citas.servicio import ACTIVAS, ErrorCita, normalizar_telefono
from app.modulos.mensajeria import servicio as mensajeria
from app.nucleo.contracts.schemas import (
    AgenciaOut,
    AprobarSolicitud,
    SolicitudAltaOut,
    TransportistaCreate,
    TransportistaOut,
    TransportistaUpdate,
)
from app.nucleo.db.base import get_db
from app.nucleo.db.models import Agencia, Cita, SolicitudAlta, Transportista

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
                            telegram=t.telegram_chat_id is not None, canal_aviso=t.canal_aviso, placas=t.placas,
                            citas_activas=len(activas),
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
    t.canal_aviso = body.canal_aviso
    db.commit()
    return _out(t)


@router.patch("/{agencia_id}/transportistas/{transportista_id}", response_model=TransportistaOut)
async def editar_transportista(agencia_id: str, transportista_id: int, body: TransportistaUpdate,
                               db: Session = Depends(get_db)) -> TransportistaOut:
    """La agencia cambia nombre, placas o canal de avisos (Telegram o SMS) de uno de sus transportistas."""
    _agencia(db, agencia_id)
    t = db.get(Transportista, transportista_id)
    if t is None or t.agencia_id != agencia_id:
        raise HTTPException(404, f"transportista {transportista_id} no existe en {agencia_id}")
    if body.alias is not None:
        t.alias = body.alias.strip()
    if body.placas is not None:
        t.placas = body.placas.strip().upper() or None
    if body.canal_aviso is not None:
        t.canal_aviso = body.canal_aviso
    db.commit()
    activas = list(db.scalars(select(Cita.ventana_inicio).where(Cita.transportista_id == t.id,
                                                                Cita.estado.in_(ACTIVAS))))
    return _out(t, activas)


def _agencia(db: Session, agencia_id: str) -> Agencia:
    a = db.get(Agencia, agencia_id)
    if a is None:
        raise HTTPException(404, f"agencia {agencia_id} no existe")
    return a


def _solicitud_out(s: SolicitudAlta) -> SolicitudAltaOut:
    return SolicitudAltaOut(id=s.id, nombre=s.nombre, telefono_fin=s.telefono[-4:], estado=s.estado,
                            creada_en=s.creada_en)


@router.get("/{agencia_id}/solicitudes", response_model=list[SolicitudAltaOut])
async def solicitudes(agencia_id: str, estado: str | None = "pendiente",
                      db: Session = Depends(get_db)) -> list[SolicitudAltaOut]:
    """Transportistas que pidieron unirse a la agencia desde el bot (por defecto, solo las pendientes)."""
    _agencia(db, agencia_id)
    return [_solicitud_out(s) for s in servicio.listar(db, agencia_id, estado or None)]


@router.post("/{agencia_id}/solicitudes/{solicitud_id}/aprobar", response_model=TransportistaOut)
async def aprobar_solicitud(agencia_id: str, solicitud_id: int, body: AprobarSolicitud | None = None,
                            db: Session = Depends(get_db)) -> TransportistaOut:
    """Da de alta al transportista, lo liga a su chat y le avisa por Telegram."""
    a = _agencia(db, agencia_id)
    try:
        t = servicio.aprobar(db, agencia_id, solicitud_id, body.placas if body else None)
    except servicio.ErrorSolicitud as e:
        raise HTTPException(e.codigo, e.mensaje) from e
    mensajeria.en_segundo_plano(mensajeria.avisar_resultado_alta(t.telegram_chat_id, a.nombre, True))
    return _out(t)


@router.post("/{agencia_id}/solicitudes/{solicitud_id}/rechazar", response_model=SolicitudAltaOut)
async def rechazar_solicitud(agencia_id: str, solicitud_id: int, db: Session = Depends(get_db)) -> SolicitudAltaOut:
    a = _agencia(db, agencia_id)
    try:
        s = servicio.rechazar(db, agencia_id, solicitud_id)
    except servicio.ErrorSolicitud as e:
        raise HTTPException(e.codigo, e.mensaje) from e
    mensajeria.en_segundo_plano(mensajeria.avisar_resultado_alta(s.telegram_chat_id, a.nombre, False))
    return _solicitud_out(s)
