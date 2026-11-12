"""Payloads REST y WebSocket de Fluport (contrato M0).

Convenciones:
- Fechas en ISO 8601 con zona horaria (hora de Veracruz, -06:00). Los tiempos `*_sim` son tiempo simulado.
- Minutos como float. Distancias/progreso de ruta 0..1.
- Nombres en español y snake_case.
"""
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.nucleo.contracts.enums import (
    Canal,
    CanalAviso,
    Clima,
    EstadoAcceso,
    EstadoAviso,
    EstadoCamion,
    EstadoCita,
    EstadoSim,
    Mundo,
    OrigenCita,
    Semaforo,
    TipoCarga,
    TipoEventoSim,
)


class Modelo(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────────────────────── Accesos ─────────────────────────────
class AccesoOut(Modelo):
    id: str
    nombre: str
    zona: str
    lat: float
    lon: float
    carriles: int
    tiempo_servicio_min: float
    capacidad_hora: int
    estado: EstadoAcceso


class AccesoEstado(Modelo):
    """Estado instantáneo de un acceso en un mundo de la simulación."""

    acceso_id: str
    estado: EstadoAcceso
    en_fila: int
    en_revision: int
    espera_min: float
    semaforo: Semaforo
    atendidos_hora: float


# ───────────────────────────── Pronóstico (M2) ─────────────────────────────
class FranjaPronostico(Modelo):
    inicio: datetime
    espera_min: float
    semaforo: Semaforo


class PronosticoOut(Modelo):
    acceso_id: str
    generado_en: datetime
    modelo_version: str
    franja_min: int = 30
    franjas: list[FranjaPronostico]  # próximas 12 h


# ───────────────────────────── Citas (M3) ─────────────────────────────
class CitaCreate(Modelo):
    telefono: str | None = Field(None, description="Identifica/crea al transportista (solo números de prueba con consentimiento)")
    transportista_id: int | None = None
    alias: str | None = None
    agencia_id: str | None = Field(None, description="Agencia del transportista si se crea uno nuevo")
    acceso_id: str
    ventana_inicio: datetime
    ventana_fin: datetime
    tipo_carga: TipoCarga
    origen: OrigenCita = OrigenCita.web

    @model_validator(mode="after")
    def _validar(self) -> "CitaCreate":
        if self.ventana_fin <= self.ventana_inicio:
            raise ValueError("ventana_fin debe ser posterior a ventana_inicio")
        if self.telefono is None and self.transportista_id is None:
            raise ValueError("se requiere telefono o transportista_id")
        return self


class CitaReprogramar(Modelo):
    acceso_id: str | None = None
    ventana_inicio: datetime
    ventana_fin: datetime


class CitaOut(Modelo):
    id: int
    transportista_id: int
    acceso_id: str
    ventana_inicio: datetime
    ventana_fin: datetime
    tipo_carga: TipoCarga
    prioridad: int
    estado: EstadoCita
    origen: OrigenCita
    espera_estimada_min: float | None
    cita_anterior_id: int | None
    confirmada_en: datetime | None = None


class ResumenCitas(Modelo):
    """Panel de cumplimiento de citas."""

    total: int
    por_estado: dict[EstadoCita, int]
    cumplimiento_pct: float  # cumplidas / (cumplidas + no_show)
    por_acceso: dict[str, int]


class SugerenciaRequest(Modelo):
    acceso_id: str | None = Field(None, description="None = considerar todos los accesos abiertos")
    desde: datetime
    hasta: datetime
    tipo_carga: TipoCarga
    duracion_min: int = 30
    max_resultados: int = Field(3, ge=1, le=10)
    preferencia: Literal["centro", "temprano"] = Field(
        "centro", description="Desempate entre esperas similares: la hora más cercana al centro de la ventana "
        "(el transportista dio una hora) o la más próxima (no dio hora)")

    @model_validator(mode="after")
    def _validar(self) -> "SugerenciaRequest":
        if self.hasta <= self.desde:
            raise ValueError("hasta debe ser posterior a desde")
        return self


class Sugerencia(Modelo):
    acceso_id: str
    inicio: datetime
    fin: datetime
    espera_min_est: float
    semaforo: Semaforo
    ahorro_vs_pico_min: float | None = None


# ───────────────────────────── Simulación (M1) ─────────────────────────────
class CamionEstado(Modelo):
    id: str
    acceso_id: str
    ruta_id: str
    progreso: float = Field(ge=0, le=1)  # 0..1 sobre la polilínea de la ruta; el front interpola
    estado: EstadoCamion
    tipo_carga: TipoCarga
    cita_id: int | None = None
    es_demo: bool = False
    agencia_id: str | None = None


class FlotaAgencia(Modelo):
    """Camiones activos de una agencia por estado (todos, no solo los dibujados) y su desempeño acumulado."""

    en_ruta: int = 0
    en_fila: int = 0
    en_revision: int = 0
    dentro: int = 0  # dentro del recinto o saliendo
    atendidos: int = 0
    espera_prom_min: float = 0.0


class Kpis(Modelo):
    espera_prom_min: float
    espera_max_min: float
    horas_camion_espera: float
    camiones_atendidos: int
    pico_fila: int


class MundoEstado(Modelo):
    camiones: list[CamionEstado]  # tope = sim_max_camiones_visibles
    camiones_ocultos: int = 0
    accesos: list[AccesoEstado]
    kpis: Kpis
    flota: dict[str, FlotaAgencia] = {}  # por agencia_id


class EventoOut(Modelo):
    id: int | None = None
    tipo: TipoEventoSim
    acceso_id: str | None = None
    ts_sim: datetime
    payload: dict[str, Any] = {}


class SimSnapshot(Modelo):
    corrida_id: int
    tick: int
    ts_sim: datetime
    velocidad: float
    estado: EstadoSim
    clima: Clima
    mundos: dict[Mundo, MundoEstado]  # una sola clave: "B" (operación con Fluport)
    eventos_recientes: list[EventoOut] = []
    etiqueta: str = "SIMULACIÓN"


class SimControl(Modelo):
    accion: Literal["play", "pause", "velocidad", "reset"]
    velocidad: float | None = Field(None, gt=0)
    semilla: int | None = None


class SimEstadoOut(Modelo):
    corrida_id: int
    estado: EstadoSim
    velocidad: float
    semilla: int
    ts_sim: datetime


class EventoCreate(Modelo):
    tipo: TipoEventoSim
    acceso_id: str | None = None
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="buque_atraca: {contenedores, terminal}; norte: {duracion_h, factor_servicio}; "
        "cierre_acceso/reapertura: {}; carga_urgente: {camiones, tipo_carga}",
    )


class KpisResponse(Modelo):
    ts_sim: datetime
    B: Kpis


# ───────────────────────────── Mensajes WebSocket ─────────────────────────────
class WsSnapshot(Modelo):
    tipo: Literal["snapshot"] = "snapshot"
    data: SimSnapshot


class WsEvento(Modelo):
    tipo: Literal["evento"] = "evento"
    data: EventoOut


class WsAviso(Modelo):
    tipo: Literal["aviso"] = "aviso"
    data: "AvisoOut"


WsMensaje = Annotated[WsSnapshot | WsEvento | WsAviso, Field(discriminator="tipo")]


# ───────────────────────────── Asistente (M4) y avisos (M5) ─────────────────────────────
class AsistenteRequest(Modelo):
    canal: Canal
    remitente: str  # teléfono o id de chat
    texto: str


class AccionAsistente(Modelo):
    herramienta: str  # consultar_espera | sugerir_horario | crear_cita | reprogramar_cita | cancelar_cita
    resultado: dict[str, Any]


class AsistenteResponse(Modelo):
    respuesta: str
    acciones: list[AccionAsistente] = []


class AvisoOut(Modelo):
    id: int
    transportista_id: int
    cita_id: int | None
    canal: Canal
    tipo: str
    mensaje: str
    estado: EstadoAviso = EstadoAviso.pendiente
    detalle: str | None = None  # id del proveedor o motivo del error
    creado_en: datetime


WsAviso.model_rebuild()


# ───────────────────────────── Vista pública (M7) ─────────────────────────────
class HoraPico(Modelo):
    """Intervalo continuo con espera prevista Lenta o Saturada; `semaforo` es el peor del intervalo."""

    inicio: datetime
    fin: datetime
    semaforo: Semaforo
    espera_max_min: float


class ZonaPublica(Modelo):
    acceso_id: str
    nombre: str  # nombre público de la caseta
    zona: str
    semaforo: Semaforo
    espera_min: float
    abierto: bool
    en_fila: int = 0  # camiones formados en la caseta (dato agregado)
    horas_pico: list[HoraPico]  # próximas 12 h
    mejor_hora: datetime | None = None  # franja con menor espera prevista en las próximas 12 h
    contingencia: Literal["normal", "lenta", "saturada", "cerrada"] = "normal"
    norte: bool = False  # norte activo: la revisión es más lenta en todas las casetas
    actualizado_en: datetime
    etiqueta: str = "SIMULACIÓN"


# ───────────────────────────── Agencias ─────────────────────────────
class AgenciaOut(Modelo):
    id: str
    nombre: str
    transportistas: int = 0


class TransportistaOut(Modelo):
    id: int
    alias: str
    telefono_fin: str | None = None  # solo los últimos 4 dígitos
    telegram: bool = False
    canal_aviso: CanalAviso = CanalAviso.telegram
    placas: str | None = None
    citas_activas: int = 0
    proxima_cita: datetime | None = None


class SolicitudAltaOut(Modelo):
    """Solicitud de un transportista que pidió unirse a la agencia desde el bot (teléfono enmascarado)."""

    id: int
    nombre: str
    telefono_fin: str
    estado: str
    creada_en: datetime


class AprobarSolicitud(Modelo):
    placas: str | None = Field(None, max_length=20)


class TransportistaCreate(Modelo):
    """Alta de un transportista por su agencia (solo números de prueba con consentimiento)."""

    alias: str = Field(min_length=2, max_length=80)
    telefono: str
    placas: str | None = Field(None, max_length=20)
    canal_aviso: CanalAviso = CanalAviso.telegram  # sms: transportista sin smartphone


class TransportistaUpdate(Modelo):
    """Edición por la agencia: solo los campos enviados cambian."""

    alias: str | None = Field(None, min_length=2, max_length=80)
    placas: str | None = Field(None, max_length=20)
    canal_aviso: CanalAviso | None = None


class Salud(Modelo):
    estado: Literal["ok"] = "ok"
    bd: bool
    simulador: EstadoSim
    version: str
