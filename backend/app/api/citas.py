"""API de citas (M3). Cada cita creada/reprogramada se inyecta en el Mundo B."""
from fastapi import APIRouter, Query, status

from app.api._stub import pendiente
from app.contracts.enums import EstadoCita
from app.contracts.schemas import CitaCreate, CitaOut, CitaReprogramar, Sugerencia, SugerenciaRequest

router = APIRouter(prefix="/api/citas", tags=["citas"])


@router.post("", response_model=CitaOut, status_code=status.HTTP_201_CREATED)
def crear_cita(body: CitaCreate) -> CitaOut:
    raise pendiente("M3")


@router.get("", response_model=list[CitaOut])
def listar_citas(
    telefono: str | None = None,
    transportista_id: int | None = None,
    acceso_id: str | None = None,
    estado: EstadoCita | None = None,
    limite: int = Query(100, le=500),
) -> list[CitaOut]:
    raise pendiente("M3")


@router.post("/sugerencias", response_model=list[Sugerencia])
def sugerir_horarios(body: SugerenciaRequest) -> list[Sugerencia]:
    raise pendiente("M3")


@router.get("/{cita_id}", response_model=CitaOut)
def obtener_cita(cita_id: int) -> CitaOut:
    raise pendiente("M3")


@router.patch("/{cita_id}", response_model=CitaOut)
def reprogramar_cita(cita_id: int, body: CitaReprogramar) -> CitaOut:
    """Crea una cita nueva con `cita_anterior_id` y marca la original como `reprogramada`."""
    raise pendiente("M3")


@router.delete("/{cita_id}", response_model=CitaOut)
def cancelar_cita(cita_id: int) -> CitaOut:
    raise pendiente("M3")
