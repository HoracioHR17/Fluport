"""API de citas (M3). Cada cita creada/reprogramada se inyecta en el Mundo B del simulador.

Los handlers son `async` (mismo event loop que el simulador); las consultas a la BD son breves.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.citas import servicio as citas
from app.citas.servicio import ErrorCita
from app.contracts.enums import EstadoCita, OrigenCita
from app.contracts.schemas import CitaCreate, CitaOut, CitaReprogramar, ResumenCitas, Sugerencia, SugerenciaRequest
from app.db.base import get_db
from app.sim.servicio import servicio

router = APIRouter(prefix="/api/citas", tags=["citas"])


def _http(e: ErrorCita) -> HTTPException:
    return HTTPException(status_code=e.codigo, detail=e.mensaje)


@router.post("", response_model=CitaOut, status_code=status.HTTP_201_CREATED)
async def crear_cita(body: CitaCreate, db: Session = Depends(get_db)) -> CitaOut:
    """Crea la cita. Si la asigna la agencia (origen web), el transportista la recibe en Telegram para confirmarla."""
    try:
        cita = citas.crear(db, servicio.requerir(), body)
    except ErrorCita as e:
        raise _http(e) from e
    if body.origen == OrigenCita.web:
        from app.messaging.servicio import en_segundo_plano, notificar_asignacion

        en_segundo_plano(notificar_asignacion(servicio.requerir(), cita.id, servicio.publicar))
    return cita


@router.get("", response_model=list[CitaOut])
async def listar_citas(
    telefono: str | None = None,
    transportista_id: int | None = None,
    acceso_id: str | None = None,
    estado: EstadoCita | None = None,
    agencia_id: str | None = None,
    limite: int = Query(100, le=500),
    db: Session = Depends(get_db),
) -> list[CitaOut]:
    try:
        return citas.listar(db, telefono, transportista_id, acceso_id, estado, limite, agencia_id)
    except ErrorCita as e:
        raise _http(e) from e


@router.post("/sugerencias", response_model=list[Sugerencia])
async def sugerir_horarios(body: SugerenciaRequest) -> list[Sugerencia]:
    try:
        return citas.sugerir(servicio.requerir(), body)
    except ErrorCita as e:
        raise _http(e) from e
    except KeyError as e:
        raise HTTPException(404, f"acceso inexistente: {e.args[0]}") from e


@router.get("/resumen", response_model=ResumenCitas)
async def resumen(agencia_id: str | None = None, db: Session = Depends(get_db)) -> ResumenCitas:
    """Panel de cumplimiento: citas por estado, % cumplimiento y citas por acceso (opcional: de una agencia)."""
    return citas.resumen(db, agencia_id)


@router.get("/{cita_id}", response_model=CitaOut)
async def obtener_cita(cita_id: int, db: Session = Depends(get_db)) -> CitaOut:
    try:
        return CitaOut.model_validate(citas.obtener(db, cita_id))
    except ErrorCita as e:
        raise _http(e) from e


@router.patch("/{cita_id}", response_model=CitaOut)
async def reprogramar_cita(cita_id: int, body: CitaReprogramar, db: Session = Depends(get_db)) -> CitaOut:
    """Crea una cita nueva con `cita_anterior_id` y marca la original como `reprogramada`."""
    try:
        return citas.reprogramar(db, servicio.requerir(), cita_id, body)
    except ErrorCita as e:
        raise _http(e) from e


@router.delete("/{cita_id}", response_model=CitaOut)
async def cancelar_cita(cita_id: int, db: Session = Depends(get_db)) -> CitaOut:
    try:
        return citas.cancelar(db, servicio.requerir(), cita_id)
    except ErrorCita as e:
        raise _http(e) from e
