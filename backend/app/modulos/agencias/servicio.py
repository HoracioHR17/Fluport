"""Solicitudes de alta: un transportista sin alta pide unirse desde el bot y su agencia la aprueba o rechaza.

Estados: `sin_agencia` (el bot espera que diga su agencia) → `pendiente` (la agencia la ve en su panel)
→ `aprobada` (queda dado de alta y ligado al chat) | `rechazada`.
"""
import unicodedata
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.nucleo.db.models import Agencia, SolicitudAlta, Transportista

ABIERTAS = ("sin_agencia", "pendiente")
GENERICAS = {"agencia", "aduanal", "aduanera", "aduanero", "aduana", "grupo", "corporativo", "consorcio",
             "despachos", "del", "de", "la", "el", "los", "y"}


class ErrorSolicitud(Exception):
    def __init__(self, codigo: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _normal(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFD", texto.lower())
    return " ".join("".join(c for c in sin_acentos if unicodedata.category(c) != "Mn" and (c.isalnum() or c == " "))
                    .split())


def buscar_agencia(db: Session, texto: str) -> Agencia | None:
    """Agencia por código (AG01) o por nombre, aunque venga incompleto o sin acentos ("altamar", "horizonte").
    Devuelve None si no coincide ninguna o si coincide más de una."""
    n = _normal(texto)
    if not n:
        return None
    agencias = list(db.scalars(select(Agencia).order_by(Agencia.id)))
    for a in agencias:
        if n in (_normal(a.id), _normal(a.nombre)):
            return a
    palabras = {p for p in n.split() if p not in GENERICAS and len(p) > 2}
    if not palabras:
        return None
    candidatas = [a for a in agencias if palabras & set(_normal(a.nombre).split())]
    return candidatas[0] if len(candidatas) == 1 else None


def nombres_agencias(db: Session) -> list[str]:
    return list(db.scalars(select(Agencia.nombre).order_by(Agencia.id)))


def solicitud_abierta(db: Session, chat_id: int) -> SolicitudAlta | None:
    return db.scalar(select(SolicitudAlta).where(SolicitudAlta.telegram_chat_id == chat_id,
                                                 SolicitudAlta.estado.in_(ABIERTAS))
                     .order_by(SolicitudAlta.id.desc()).limit(1))


def abrir_solicitud(db: Session, chat_id: int, telefono: str, nombre: str | None,
                    agencia_id: str | None = None) -> SolicitudAlta:
    """Crea (o actualiza) la solicitud abierta del chat. Con agencia queda `pendiente`; sin ella, `sin_agencia`."""
    s = solicitud_abierta(db, chat_id)
    if s is None:
        s = SolicitudAlta(telegram_chat_id=chat_id, telefono=telefono, nombre="")
        db.add(s)
    s.telefono, s.nombre = telefono, (nombre or f"Transportista {telefono[-4:]}")[:80]
    if agencia_id is not None:
        s.agencia_id = agencia_id
    s.estado = "pendiente" if s.agencia_id else "sin_agencia"
    db.commit()
    return s


def elegir_agencia(db: Session, s: SolicitudAlta, agencia: Agencia) -> SolicitudAlta:
    s.agencia_id, s.estado = agencia.id, "pendiente"
    db.commit()
    return s


def listar(db: Session, agencia_id: str, estado: str | None = "pendiente") -> list[SolicitudAlta]:
    q = select(SolicitudAlta).where(SolicitudAlta.agencia_id == agencia_id)
    if estado:
        q = q.where(SolicitudAlta.estado == estado)
    return list(db.scalars(q.order_by(SolicitudAlta.creada_en.desc(), SolicitudAlta.id.desc())))


def _pendiente(db: Session, agencia_id: str, solicitud_id: int) -> SolicitudAlta:
    s = db.get(SolicitudAlta, solicitud_id)
    if s is None or s.agencia_id != agencia_id:
        raise ErrorSolicitud(404, f"solicitud {solicitud_id} no existe en {agencia_id}")
    if s.estado != "pendiente":
        raise ErrorSolicitud(409, f"la solicitud ya fue {s.estado}")
    return s


def aprobar(db: Session, agencia_id: str, solicitud_id: int, placas: str | None = None) -> Transportista:
    """Da de alta al transportista en la agencia y lo liga al chat de Telegram desde el que pidió unirse."""
    s = _pendiente(db, agencia_id, solicitud_id)
    t = db.scalar(select(Transportista).where(Transportista.telefono == s.telefono))
    if t is not None and t.agencia_id not in (None, agencia_id):
        raise ErrorSolicitud(409, "ese número ya está dado de alta en otra agencia")
    otro = db.scalar(select(Transportista).where(Transportista.telegram_chat_id == s.telegram_chat_id))
    if otro is not None and otro is not t:
        otro.telegram_chat_id = None  # el chat cambió de número
        db.flush()
    if t is None:
        t = Transportista(telefono=s.telefono, alias=s.nombre, es_demo=True)
        db.add(t)
    t.agencia_id, t.telegram_chat_id = agencia_id, s.telegram_chat_id
    if placas and placas.strip():
        t.placas = placas.strip().upper()
    s.estado, s.resuelta_en = "aprobada", datetime.now().astimezone()
    db.commit()
    return t


def rechazar(db: Session, agencia_id: str, solicitud_id: int) -> SolicitudAlta:
    s = _pendiente(db, agencia_id, solicitud_id)
    s.estado, s.resuelta_en = "rechazada", datetime.now().astimezone()
    db.commit()
    return s
