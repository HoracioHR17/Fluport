"""Carga y valida los parámetros del escenario (backend/data/escenario.json)."""
import json
import math
import zlib
from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.nucleo.config import RAIZ_BACKEND
from app.nucleo.contracts.enums import TipoCarga

RUTA_ESCENARIO = RAIZ_BACKEND / "data" / "escenario.json"


class Ruta(BaseModel):
    id: str
    coords: list[tuple[float, float]]  # [lat, lon] desde el origen hasta el acceso


class AccesoParam(BaseModel):
    id: str
    nombre: str
    zona: str
    entrada: Literal["norte", "sur", "urbana"] = "urbana"  # por dónde llegan los camiones (corredor carretero)
    lat: float
    lon: float
    carriles: int = Field(gt=0)
    tiempo_servicio_min: float = Field(gt=0)
    participacion: float = Field(gt=0)
    rutas: list[Ruta] = Field(min_length=1)

    @property
    def capacidad_hora(self) -> int:
        return int(self.carriles * 60 / self.tiempo_servicio_min)


class AgenciaParam(BaseModel):
    """Agencia (empresa transportista) de la demo; `participacion` = parte de los camiones simulados que son suyos.

    Si las participaciones suman menos de 1, el resto son camiones de otros transportistas, sin agencia en Fluport."""

    id: str
    nombre: str
    participacion: float = Field(gt=0)


class FranjaLlegadas(BaseModel):
    desde: int = Field(ge=0, le=24)
    hasta: int = Field(ge=0, le=24)
    pct: float = Field(ge=0, le=1)


class RevisionAduanal(BaseModel):
    prob: float = Field(ge=0, le=1)
    extra_min: float = Field(ge=0)


class Impacto(BaseModel):
    diesel_ralenti_l_h: float
    diesel_precio_mxn_l: float
    costo_hora_camion_mxn: float
    co2_kg_por_l: float


class BuquesParam(BaseModel):
    por_dia_media: float = Field(ge=0)
    contenedores: tuple[int, int]
    camiones_por_contenedor: float
    ola_horas: tuple[float, float]


class NorteParam(BaseModel):
    prob_dia: float
    duracion_h: float
    duracion_rango_h: tuple[float, float]
    reduccion_atencion: float = Field(ge=0, lt=1)  # 0.30 = se atiende 30 % menos

    @property
    def factor_servicio(self) -> float:
        """Multiplicador del tiempo de revisión: atender 30 % menos ⇒ cada camión tarda 1/0.7 veces."""
        return 1 / (1 - self.reduccion_atencion)


class Escenario(BaseModel):
    inicio_hora: int = 4
    camiones_dia: int
    camiones_dia_incluye_buques: bool = True
    llegadas_por_franja: list[FranjaLlegadas] = Field(min_length=1)
    mezcla_carga: dict[TipoCarga, float]
    cargas_prioritarias: list[TipoCarga]
    servicio_sigma: float
    ruta_min: tuple[float, float]
    estancia_min: tuple[float, float]
    con_cita: float = Field(ge=0, le=1)
    no_show: float = Field(ge=0, le=1)  # sobre los camiones con cita
    cumplimiento_sugerencia: float = Field(ge=0, le=1)  # sobre los camiones con cita
    retraso_promedio_min: float = Field(ge=0)  # desvío absoluto medio respecto a la cita
    ventana_reprogramacion_min: tuple[int, int]
    ocupacion_objetivo_franja: float
    revision_aduanal: RevisionAduanal
    buques: BuquesParam
    norte: NorteParam
    impacto: Impacto
    accesos: list[AccesoParam] = Field(min_length=1)
    agencias: list[AgenciaParam] = Field(default_factory=list)

    @field_validator("llegadas_por_franja")
    @classmethod
    def _franjas_suman_100(cls, v: list[FranjaLlegadas]) -> list[FranjaLlegadas]:
        if abs(sum(f.pct for f in v) - 1) > 0.01:
            raise ValueError("los % de llegadas por franja deben sumar 100 %")
        return v

    @property
    def perfil_horario(self) -> list[float]:
        """Peso de llegadas por hora del día (0–23), repartiendo cada franja uniformemente."""
        pesos = [0.0] * 24
        for f in self.llegadas_por_franja:
            for h in range(f.desde, f.hasta):
                pesos[h] += f.pct / (f.hasta - f.desde)
        return pesos

    @property
    def camiones_buque_dia(self) -> float:
        b = self.buques
        return b.por_dia_media * sum(b.contenedores) / 2 * b.camiones_por_contenedor

    @property
    def camiones_base_dia(self) -> float:
        """Demanda sin olas de buque (si el total diario ya las incluye, se descuentan)."""
        if self.camiones_dia_incluye_buques:
            return max(0.0, self.camiones_dia - self.camiones_buque_dia)
        return float(self.camiones_dia)

    @property
    def retraso_sigma_min(self) -> float:
        """σ de una Normal(0, σ) cuyo desvío absoluto medio es retraso_promedio_min (E|X| = σ·√(2/π))."""
        return self.retraso_promedio_min * math.sqrt(math.pi / 2)

    @field_validator("accesos")
    @classmethod
    def _ids_unicos(cls, v: list[AccesoParam]) -> list[AccesoParam]:
        if len({a.id for a in v}) != len(v):
            raise ValueError("ids de acceso repetidos")
        return v

    def agencia_de(self, camion_id: str) -> str | None:
        """Agencia de un camión simulado: fija por su id (crc32) para no alterar los números aleatorios."""
        if not self.agencias:
            return None
        total = max(1.0, sum(a.participacion for a in self.agencias))
        u = (zlib.crc32(camion_id.encode()) % 10_000) / 10_000 * total
        for a in self.agencias:
            u -= a.participacion
            if u < 0:
                return a.id
        return None  # camión de otro transportista (no es de ninguna agencia de Fluport)

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
