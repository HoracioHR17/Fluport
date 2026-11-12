"""Orquestación de mensajería: WhatsApp entrante → asistente → respuesta, y ciclo de avisos proactivos.

Los avisos se envían por Telegram si el transportista se registró en el bot; si no, por WhatsApp.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.modulos.citas.servicio import ErrorCita, normalizar_telefono
from app.modulos.mensajeria.adaptadores import telegram, twilio
from app.modulos.mensajeria.asistente.agente import asistente, guardar_turnos
from app.modulos.mensajeria.dominio.avisos import AvisoNuevo, CitaActiva, revisar
from app.nucleo.contracts.enums import Canal, EstadoAviso, EstadoCita
from app.nucleo.contracts.schemas import AsistenteRequest, AvisoOut, WsAviso
from app.nucleo.db.base import SessionLocal
from app.nucleo.db.models import Aviso, Cita, Transportista
from app.nucleo.puertos import Operacion

log = logging.getLogger("fluport.whatsapp")
_tareas: set[asyncio.Task] = set()  # referencias para que el recolector no cancele tareas en curso


def en_segundo_plano(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tareas.add(t)
    t.add_done_callback(_tareas.discard)
    return t


# ───────────────────────────── Mensajes entrantes ─────────────────────────────
async def atender_mensaje(sim: Operacion, direccion: str, texto: str) -> str:
    """Pasa el mensaje al asistente y envía la respuesta por WhatsApp. Devuelve el texto respondido."""
    try:
        telefono = normalizar_telefono(direccion)
    except ErrorCita:
        log.warning("Remitente inválido: %r", direccion)
        return ""
    twilio.recordar_direccion(telefono, direccion)
    with SessionLocal() as db:
        r = await asistente.responder(db, sim, AsistenteRequest(canal=Canal.whatsapp, remitente=telefono,
                                                                  texto=texto or "(mensaje sin texto)"))
    enviado, detalle = await twilio.enviar(telefono, r.respuesta)
    if not enviado:
        log.error("No se pudo responder a %s: %s", telefono, detalle)
    return r.respuesta


# ───────────────────────────── Avisos proactivos ─────────────────────────────
def leer_citas_activas() -> tuple[list[CitaActiva], set[tuple[int, str]]]:
    """Citas activas de transportistas con teléfono y los avisos ya generados (para no repetir)."""
    with SessionLocal() as db:
        filas = db.execute(
            select(Cita, Transportista.telefono, Transportista.telegram_chat_id)
            .join(Transportista, Cita.transportista_id == Transportista.id)
            .where(Cita.estado.in_((EstadoCita.agendada, EstadoCita.en_ruta)), Transportista.telefono.is_not(None))
        ).all()
        citas = [CitaActiva(c.id, c.transportista_id, tel, c.acceso_id, c.ventana_inicio, c.tipo_carga.value, c.estado,
                            chat)
                 for c, tel, chat in filas]
        enviados = {(cid, tipo) for cid, tipo in db.execute(select(Aviso.cita_id, Aviso.tipo)).all() if cid}
    return citas, enviados


CANALES = {Canal.telegram: telegram.CanalTelegram(), Canal.whatsapp: twilio.CanalWhatsApp()}  # adaptadores


def canal_de(a: AvisoNuevo) -> Canal:
    """Telegram si el transportista se conectó al bot y el canal está configurado; si no, WhatsApp."""
    return Canal.telegram if a.telegram_chat_id is not None and CANALES[Canal.telegram].configurado() else Canal.whatsapp


def registrar_aviso(a: AvisoNuevo) -> AvisoOut:
    canal = canal_de(a)
    with SessionLocal() as db:
        fila = Aviso(transportista_id=a.transportista_id, cita_id=a.cita_id, canal=canal,
                     tipo=a.tipo, mensaje=a.mensaje, estado=EstadoAviso.pendiente)
        db.add(fila)
        db.commit()
        # el aviso queda en el historial del asistente (del mismo canal): un "SÍ" posterior tiene contexto
        guardar_turnos(db, canal, a.telefono, [{"role": "model", "parts": [{"text": a.mensaje}]}])
        return AvisoOut.model_validate(fila)


async def enviar_aviso(a: AvisoNuevo) -> tuple[bool, str]:
    canal = canal_de(a)
    destino = a.telegram_chat_id if canal == Canal.telegram else a.telefono
    return await CANALES[canal].enviar(destino, a.mensaje)


def marcar_aviso(aviso_id: int, enviado: bool) -> None:
    with SessionLocal() as db:
        fila = db.get(Aviso, aviso_id)
        if fila is not None:
            fila.estado = EstadoAviso.enviado if enviado else EstadoAviso.fallido
            fila.enviado_en = datetime.now().astimezone() if enviado else None
            db.commit()


# ───────────────────────────── Citas asignadas por la agencia ─────────────────────────────
def mensaje_asignacion(sim: Operacion, cita_id: int) -> AvisoNuevo | None:
    """Aviso de cita nueva para el transportista (solo si está conectado a Telegram)."""
    with SessionLocal() as db:
        c = db.get(Cita, cita_id)
        t = c.transportista if c else None
        if t is None or t.telegram_chat_id is None or not t.telefono:
            return None
        zona = ZoneInfo(sim.cfg.zona_horaria)
        ini, fin = c.ventana_inicio.astimezone(zona), c.ventana_fin.astimezone(zona)
        agencia = t.agencia.nombre if t.agencia else "Tu agencia"
        espera = f"\nEspera prevista: ~{round(c.espera_estimada_min)} min." if c.espera_estimada_min is not None else ""
        texto = (f"*Nueva cita* asignada por {agencia}:\n{ini:%d/%m} de {ini:%H:%M} a {fin:%H:%M} · "
                 f"{sim.esc.acceso(c.acceso_id).nombre}{espera}\n¿La confirmas? Responde *SÍ* o *NO*.")
        return AvisoNuevo(c.id, t.id, t.telefono, "cita_asignada", texto, t.telegram_chat_id)


async def notificar_asignacion(sim: Operacion, cita_id: int, publicar) -> AvisoOut | None:
    """Envía al transportista la cita que le asignó su agencia y la deja en los avisos del tablero."""
    a = await asyncio.to_thread(mensaje_asignacion, sim, cita_id)
    if a is None:
        return None
    out = await asyncio.to_thread(registrar_aviso, a)
    publicar(WsAviso(data=out).model_dump_json())
    enviado, detalle = await enviar_aviso(a)
    if not enviado:
        log.warning("Cita asignada %s no enviada: %s", cita_id, detalle)
    await asyncio.to_thread(marcar_aviso, out.id, enviado)
    return out


async def ciclo_avisos(sim: Operacion, publicar) -> list[AvisoOut]:
    """Revisa citas, genera avisos nuevos, los guarda, los publica en el tablero y los envía por WhatsApp."""
    citas, enviados = await asyncio.to_thread(leer_citas_activas)
    if not citas:
        return []
    nuevos = revisar(sim, citas, enviados)  # usa el simulador: en el event loop
    salida = []
    for a in nuevos:
        out = await asyncio.to_thread(registrar_aviso, a)
        publicar(WsAviso(data=out).model_dump_json())
        enviado, detalle = await enviar_aviso(a)
        if not enviado:
            log.warning("Aviso %s (%s) no enviado: %s", out.id, a.tipo, detalle)
        await asyncio.to_thread(marcar_aviso, out.id, enviado)
        salida.append(out)
    return salida
