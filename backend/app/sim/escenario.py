"""Carga y valida los parámetros del escenario (backend/data/escenario.json)."""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.contracts.enums import TipoCarga

RUTA_ESCENARIO = Path(__file__).resolve().parents[2] / "data" / "escenario.json"


class Ruta(BaseModel):
    id: str
    coords: list[tuple[float, float]]  # [lat, lon] desde el origen hasta el acceso


class AccesoParam(BaseModel):
    id: str
    nombre: str
    zona: str
    lat: float
    lon: float
    carriles: int = Field(gt=0)
    tiempo_servicio_min: float = Field(gt=0)
    participacion: float = Field(gt=0)
    rutas: list[Ruta] = Field(min_length=1)

    @property
    def capacidad_hora(self) -> int:
        return int(self.carriles * 60 / self.tiempo_servicio_min)


class BuquesParam(BaseModel):
    por_dia: tuple[int, int]
    contenedores: tuple[int, int]
    camiones_por_contenedor: float
    ola_horas: tuple[float, float]


class NorteParam(BaseModel):
    prob_dia: float
    duracion_h: float
    factor_servicio: float


class Escenario(BaseModel):
    inicio_hora: int = 4
    camiones_dia: int
    perfil_horario: list[float] = Field(min_length=24, max_length=24)
    mezcla_carga: dict[TipoCarga, float]
    cargas_prioritarias: list[TipoCarga]
    servicio_sigma: float
    ruta_min: tuple[float, float]
    estancia_min: tuple[float, float]
    retraso_sigma_min: float
    no_show: float
    cumplimiento_sugerencia: float
    ventana_reprogramacion_min: tuple[int, int]
    ocupacion_objetivo_franja: float
    buques: BuquesParam
    norte: NorteParam
    accesos: list[AccesoParam] = Field(min_length=1)

    @field_validator("accesos")
    @classmethod
    def _ids_unicos(cls, v: list[AccesoParam]) -> list[AccesoParam]:
        if len({a.id for a in v}) != len(v):
            raise ValueError("ids de acceso repetidos")
        return v

    def acceso(self, acceso_id: str) -> AccesoParam:
        for a in self.accesos:
            if a.id == acceso_id:
                return a
        raise KeyError(acceso_id)


def cargar_escenario(ruta: Path = RUTA_ESCENARIO) -> Escenario:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("_nota", None)
    return Escenario.model_validate(datos)


@lru_cache
def escenario_actual() -> Escenario:
    return cargar_escenario()
