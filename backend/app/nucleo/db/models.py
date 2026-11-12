"""Esquema PostgreSQL de Fluport (contrato M0). Cambios solo con aprobación + nueva migración."""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.nucleo.contracts.enums import (
    Canal,
    Clima,
    EstadoAcceso,
    EstadoAviso,
    EstadoBuque,
    EstadoCita,
    EstadoSim,
    Mundo,
    OrigenCita,
    Semaforo,
    TipoCarga,
    TipoCorrida,
    TipoEventoSim,
)
from app.nucleo.db.base import Base


def pg_enum(e: type, name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


TS = DateTime(timezone=True)


class Acceso(Base):
    __tablename__ = "acceso"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # ej. "A1"
    nombre: Mapped[str] = mapped_column(String(120))
    zona: Mapped[str] = mapped_column(String(80))  # zona urbana para la vista pública
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    carriles: Mapped[int] = mapped_column(Integer)
    tiempo_servicio_min: Mapped[float] = mapped_column(Float)  # media del servicio por camión
    capacidad_hora: Mapped[int] = mapped_column(Integer)
    estado: Mapped[EstadoAcceso] = mapped_column(pg_enum(EstadoAcceso, "estado_acceso"), default=EstadoAcceso.abierto)

    __table_args__ = (CheckConstraint("carriles > 0", name="carriles_pos"),)


class Agencia(Base):
    """Empresa transportista que supervisa a sus transportistas y camiones (vista de agencia)."""

    __tablename__ = "agencia"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # ej. "AG01"; código del enlace del bot
    nombre: Mapped[str] = mapped_column(String(120))
    creada_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    transportistas: Mapped[list["Transportista"]] = relationship(back_populates="agencia")


class Transportista(Base):
    __tablename__ = "transportista"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(80))
    agencia_id: Mapped[str | None] = mapped_column(ForeignKey("agencia.id", ondelete="SET NULL"), index=True)
    telefono: Mapped[str | None] = mapped_column(String(20), unique=True)  # solo teléfonos de prueba con consentimiento
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)  # chat del bot, si se registró ahí
    placas: Mapped[str | None] = mapped_column(String(20))  # placas de la unidad (alta por la agencia)
    es_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    citas: Mapped[list["Cita"]] = relationship(back_populates="transportista")
    agencia: Mapped[Agencia | None] = relationship(back_populates="transportistas")


class Cita(Base):
    __tablename__ = "cita"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transportista_id: Mapped[int] = mapped_column(ForeignKey("transportista.id", ondelete="CASCADE"))
    acceso_id: Mapped[str] = mapped_column(ForeignKey("acceso.id"))
    ventana_inicio: Mapped[datetime] = mapped_column(TS)
    ventana_fin: Mapped[datetime] = mapped_column(TS)
    tipo_carga: Mapped[TipoCarga] = mapped_column(pg_enum(TipoCarga, "tipo_carga"))
    prioridad: Mapped[int] = mapped_column(Integer, default=0)  # mayor = más prioritaria
    estado: Mapped[EstadoCita] = mapped_column(pg_enum(EstadoCita, "estado_cita"), default=EstadoCita.agendada)
    origen: Mapped[OrigenCita] = mapped_column(pg_enum(OrigenCita, "origen_cita"))
    espera_estimada_min: Mapped[float | None] = mapped_column(Float)
    cita_anterior_id: Mapped[int | None] = mapped_column(ForeignKey("cita.id"))  # traza de reprogramación
    confirmada_en: Mapped[datetime | None] = mapped_column(TS)  # el transportista confirmó la cita asignada
    creada_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())

    transportista: Mapped[Transportista] = relationship(back_populates="citas")

    __table_args__ = (
        CheckConstraint("ventana_fin > ventana_inicio", name="ventana_valida"),
        Index("ix_cita_acceso_ventana", "acceso_id", "ventana_inicio"),
    )


class Buque(Base):
    __tablename__ = "buque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    terminal: Mapped[str] = mapped_column(String(80))
    eta: Mapped[datetime] = mapped_column(TS)
    contenedores: Mapped[int] = mapped_column(Integer)
    estado: Mapped[EstadoBuque] = mapped_column(pg_enum(EstadoBuque, "estado_buque"), default=EstadoBuque.programado)


class SimCorrida(Base):
    __tablename__ = "sim_corrida"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[TipoCorrida] = mapped_column(pg_enum(TipoCorrida, "tipo_corrida"))
    semilla: Mapped[int] = mapped_column(Integer)
    inicio_sim: Mapped[datetime] = mapped_column(TS)  # fecha/hora simulada de arranque
    velocidad: Mapped[float] = mapped_column(Float)
    estado: Mapped[EstadoSim] = mapped_column(pg_enum(EstadoSim, "estado_sim"))
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    creada_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class LecturaCongestion(Base):
    """Serie temporal por acceso y mundo; alimenta tablero histórico y entrenamiento (M2)."""

    __tablename__ = "lectura_congestion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    corrida_id: Mapped[int] = mapped_column(ForeignKey("sim_corrida.id", ondelete="CASCADE"))
    mundo: Mapped[Mundo] = mapped_column(pg_enum(Mundo, "mundo"))
    acceso_id: Mapped[str] = mapped_column(ForeignKey("acceso.id"))
    ts_sim: Mapped[datetime] = mapped_column(TS)
    camiones_en_fila: Mapped[int] = mapped_column(Integer)
    espera_min: Mapped[float] = mapped_column(Float)
    llegadas_hora: Mapped[float] = mapped_column(Float, default=0)
    atendidos_hora: Mapped[float] = mapped_column(Float, default=0)
    buques_atracados: Mapped[int] = mapped_column(Integer, default=0)
    citas_franja: Mapped[int] = mapped_column(Integer, default=0)
    clima: Mapped[Clima] = mapped_column(pg_enum(Clima, "clima"), default=Clima.normal)

    __table_args__ = (Index("ix_lectura_serie", "corrida_id", "mundo", "acceso_id", "ts_sim"),)


class EventoSim(Base):
    __tablename__ = "evento_sim"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corrida_id: Mapped[int] = mapped_column(ForeignKey("sim_corrida.id", ondelete="CASCADE"))
    tipo: Mapped[TipoEventoSim] = mapped_column(pg_enum(TipoEventoSim, "tipo_evento_sim"))
    acceso_id: Mapped[str | None] = mapped_column(ForeignKey("acceso.id"))
    ts_sim: Mapped[datetime] = mapped_column(TS)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    creado_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Pronostico(Base):
    __tablename__ = "pronostico"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    acceso_id: Mapped[str] = mapped_column(ForeignKey("acceso.id"))
    generado_en: Mapped[datetime] = mapped_column(TS)  # tiempo simulado
    franja_inicio: Mapped[datetime] = mapped_column(TS)
    espera_min: Mapped[float] = mapped_column(Float)
    semaforo: Mapped[Semaforo] = mapped_column(pg_enum(Semaforo, "semaforo"))
    modelo_version: Mapped[str] = mapped_column(String(40))

    __table_args__ = (Index("ix_pronostico_acceso_gen", "acceso_id", "generado_en"),)


class Aviso(Base):
    __tablename__ = "aviso"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transportista_id: Mapped[int] = mapped_column(ForeignKey("transportista.id", ondelete="CASCADE"))
    cita_id: Mapped[int | None] = mapped_column(ForeignKey("cita.id", ondelete="SET NULL"))
    canal: Mapped[Canal] = mapped_column(pg_enum(Canal, "canal"))
    tipo: Mapped[str] = mapped_column(String(40))  # acceso_saturado | ventana_cambio | turno_30min | ...
    mensaje: Mapped[str] = mapped_column(Text)
    estado: Mapped[EstadoAviso] = mapped_column(pg_enum(EstadoAviso, "estado_aviso"), default=EstadoAviso.pendiente)
    creado_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    enviado_en: Mapped[datetime | None] = mapped_column(TS)


class MensajeAsistente(Base):
    """Historial de conversación del asistente por remitente (contexto del LLM)."""

    __tablename__ = "mensaje_asistente"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canal: Mapped[Canal] = mapped_column(pg_enum(Canal, "canal"))
    remitente: Mapped[str] = mapped_column(String(40), index=True)
    rol: Mapped[str] = mapped_column(String(12))  # user | assistant | tool
    contenido: Mapped[dict[str, Any]] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(TS, server_default=func.now())
