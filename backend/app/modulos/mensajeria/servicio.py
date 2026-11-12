"""Orquestación de mensajería: avisos proactivos, citas asignadas, canceladas o cambiadas por la agencia y resultado
de las solicitudes de alta.

Cada aviso sale por el canal que la agencia eligió para el transportista (`canal_aviso`): Telegram (bot) o SMS
(transportistas sin smartphone), ambos detrás del puerto `NotificadorPort`. Todo aviso queda registrado con su
destino y estado; si el envío falla queda como `fallido` con el motivo, sin interrumpir la simulación.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.modulos.mensajeria.adaptadores import sms, telegram
from app.modulos.mensajeria.asistente.agente import guardar_turnos
from app.modulos.mensajeria.dominio.avisos import AvisoNuevo, CitaActiva, revisar
from app.modulos.mensajeria.dominio.sms import sms as texto_sms
from app.modulos.mensajeria.puertos import NotificadorPort
from app.nucleo.contracts.enums import Canal, CanalAviso, EstadoAviso, EstadoCita
from app.nucleo.contracts.schemas import AvisoOut, WsAviso
from app.nucleo.db.base import SessionLocal
from app.nucleo.db.models import Aviso, Cita, Transportista
from app.nucleo.puertos import Operacion

log = logging.getLogger("fluport.mensajeria")
_tareas: set[asyncio.Task] = set()  # referencias para que el recolector no cancele tareas en curso


def en_segundo_plano(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tareas.add(t)
    t.add_done_callback(_tareas.discard)
    return t


# ───────────────────────────── Avisos proactivos ─────────────────────────────
def leer_citas_activas() -> tuple[list[CitaActiva], set[tuple[int, str]]]:
    """Citas activas de transportistas con teléfono y los avisos ya generados (para no repetir)."""
    with SessionLocal() as db:
        filas = db.execute(
            select(Cita, Transportista.telefono, Transportista.telegram_chat_id, Transportista.canal_aviso)
            .join(Transportista, Cita.transportista_id == Transportista.id)
            .where(Cita.estado.in_((EstadoCita.agendada, EstadoCita.en_ruta)), Transportista.telefono.is_not(None))
        ).all()
        citas = [CitaActiva(c.id, c.transportista_id, tel, c.acceso_id, c.ventana_inicio, c.tipo_carga.value, c.estado,
                            chat, CanalAviso(canal).value)
                 for c, tel, chat, canal in filas]
        enviados = {(cid, tipo) for cid, tipo in db.execute(select(Aviso.cita_id, Aviso.tipo)).all() if cid}
    return citas, enviados


# adaptadores del puerto NotificadorPort, uno por canal de aviso
CANALES: dict[Canal, NotificadorPort] = {Canal.telegram: telegram.TelegramAdapter(), Canal.sms: sms.SmsAdapter()}


def canal_de(a: AvisoNuevo) -> Canal:
    """Canal por el que se avisa al transportista: el `canal_aviso` que eligió su agencia."""
    return Canal.sms if a.canal == CanalAviso.sms else Canal.telegram


def registrar_aviso(a: AvisoNuevo) -> AvisoOut:
    canal = canal_de(a)
    destino = None if a.destino is None else str(a.destino)
    with SessionLocal() as db:
        fila = Aviso(transportista_id=a.transportista_id, cita_id=a.cita_id, canal=canal, tipo=a.tipo,
                     mensaje=a.texto, destino=destino, estado=EstadoAviso.pendiente)
        db.add(fila)
        db.commit()
        if canal == Canal.telegram:
            # el aviso queda en el historial del asistente: un "SÍ" posterior tiene contexto (el SMS es solo salida)
            guardar_turnos(db, canal, a.telefono, [{"role": "model", "parts": [{"text": a.mensaje}]}])
        return AvisoOut.model_validate(fila)


async def enviar_aviso(a: AvisoNuevo) -> tuple[bool, str]:
    """Envía el aviso por su canal. Nunca lanza: un fallo se devuelve como (False, motivo)."""
    try:
        return await CANALES[canal_de(a)].enviar(a.destino, a.texto)
    except Exception as e:  # noqa: BLE001 - un fallo del canal nunca debe detener la simulación
        log.exception("Aviso %s no enviado", a.tipo)
        return False, f"error inesperado ({type(e).__name__})"


def marcar_aviso(aviso_id: int, enviado: bool, detalle: str | None = None) -> AvisoOut | None:
    with SessionLocal() as db:
        fila = db.get(Aviso, aviso_id)
        if fila is None:
            return None
        fila.estado = EstadoAviso.enviado if enviado else EstadoAviso.fallido
        fila.enviado_en = datetime.now().astimezone() if enviado else None
        fila.detalle = (detalle or "")[:500] or None
        db.commit()
        return AvisoOut.model_validate(fila)


# ───────────────────────────── Citas asignadas por la agencia ─────────────────────────────
def _avisable(t: Transportista | None) -> bool:
    """Si el transportista puede recibir avisos por su canal: SMS con teléfono o Telegram con el bot conectado."""
    if t is None or not t.telefono:
        return False
    return t.canal_aviso == CanalAviso.sms or t.telegram_chat_id is not None


def _aviso(c: Cita, t: Transportista, tipo: str, texto: str, sms_txt: str) -> AvisoNuevo:
    return AvisoNuevo(c.id, t.id, t.telefono, tipo, texto, t.telegram_chat_id, CanalAviso(t.canal_aviso).value,
                      texto_sms(sms_txt))


def mensaje_asignacion(sim: Operacion, cita_id: int) -> AvisoNuevo | None:
    """Aviso de cita nueva para el transportista (por Telegram o SMS, según su canal)."""
    with SessionLocal() as db:
        c = db.get(Cita, cita_id)
        t = c.transportista if c else None
        if not _avisable(t):
            return None
        zona = ZoneInfo(sim.cfg.zona_horaria)
        ini, fin = c.ventana_inicio.astimezone(zona), c.ventana_fin.astimezone(zona)
        agencia = t.agencia.nombre if t.agencia else "Tu agencia"
        espera = f"\nEspera prevista: ~{round(c.espera_estimada_min)} min." if c.espera_estimada_min is not None else ""
        texto = (f"*Nueva cita* asignada por {agencia}:\n{ini:%d/%m} de {ini:%H:%M} a {fin:%H:%M} · "
                 f"{sim.esc.acceso(c.acceso_id).nombre}{espera}\nPreséntate en ese horario; te recuerdo 30 min antes.")
        placas = f" Placas {t.placas}." if t.placas else ""
        sms_txt = (f"Cita #{c.id} {ini:%d/%m} {ini:%H:%M}-{fin:%H:%M} en {sim.esc.acceso(c.acceso_id).nombre}."
                   f"{placas} Llega a tiempo, te avisamos 30 min antes.")
        return _aviso(c, t, "cita_asignada", texto, sms_txt)


def mensaje_cancelacion(sim: Operacion, cita_id: int) -> AvisoNuevo | None:
    """Aviso de que la agencia canceló la cita (por Telegram o SMS, según su canal)."""
    with SessionLocal() as db:
        c = db.get(Cita, cita_id)
        t = c.transportista if c else None
        if not _avisable(t):
            return None
        ini = c.ventana_inicio.astimezone(ZoneInfo(sim.cfg.zona_horaria))
        agencia = t.agencia.nombre if t.agencia else "Tu agencia"
        texto = (f"❌ *{agencia}* canceló tu cita *#{c.id}* del {ini:%d/%m} a las {ini:%H:%M} en "
                 f"{sim.esc.acceso(c.acceso_id).nombre}.\nYa no tienes que presentarte. Si necesitas otra, "
                 "escríbeme día, hora y tipo de carga.")
        sms_txt = (f"{agencia} cancelo tu cita #{c.id} del {ini:%d/%m} {ini:%H:%M} en "
                   f"{sim.esc.acceso(c.acceso_id).nombre}. Ya no tienes que presentarte.")
        return _aviso(c, t, "cita_cancelada", texto, sms_txt)


def mensaje_reasignacion(sim: Operacion, cita_id: int) -> AvisoNuevo | None:
    """Aviso de que la agencia cambió la cita (`cita_id` es la cita nueva, ligada a la anterior)."""
    with SessionLocal() as db:
        c = db.get(Cita, cita_id)
        t = c.transportista if c else None
        if not _avisable(t):
            return None
        zona = ZoneInfo(sim.cfg.zona_horaria)
        ini, fin = c.ventana_inicio.astimezone(zona), c.ventana_fin.astimezone(zona)
        agencia = t.agencia.nombre if t.agencia else "Tu agencia"
        anterior = f" *#{c.cita_anterior_id}*" if c.cita_anterior_id else ""
        texto = (f"🔁 *{agencia}* cambió tu cita{anterior}. Ahora es la *#{c.id}*:\n{ini:%d/%m} de {ini:%H:%M} a "
                 f"{fin:%H:%M} · {sim.esc.acceso(c.acceso_id).nombre}")
        texto += "\nPreséntate en el nuevo horario; te recuerdo 30 min antes."
        previa = f" #{c.cita_anterior_id}" if c.cita_anterior_id else ""
        sms_txt = (f"CAMBIO de cita{previa}. Nueva #{c.id}: {ini:%d/%m} {ini:%H:%M}-{fin:%H:%M} en "
                   f"{sim.esc.acceso(c.acceso_id).nombre}.")
        return _aviso(c, t, "cita_reasignada", texto, sms_txt)


async def _despachar(a: AvisoNuevo, publicar) -> AvisoOut:
    """Guarda el aviso, lo publica en el tablero, lo envía por su canal y registra el resultado."""
    out = await asyncio.to_thread(registrar_aviso, a)
    publicar(WsAviso(data=out).model_dump_json())
    enviado, detalle = await enviar_aviso(a)
    if not enviado:
        log.warning("Aviso %s (%s, %s) no enviado: %s", out.id, a.tipo, a.canal, detalle)
    final = await asyncio.to_thread(marcar_aviso, out.id, enviado, detalle) or out
    publicar(WsAviso(data=final).model_dump_json())  # el tablero refresca el estado: enviado o fallido
    return final


async def _notificar(armar, sim: Operacion, cita_id: int, publicar) -> AvisoOut | None:
    """Arma el aviso de una cita y lo despacha por el canal del transportista."""
    a = await asyncio.to_thread(armar, sim, cita_id)
    if a is None:
        return None
    return await _despachar(a, publicar)


async def notificar_asignacion(sim: Operacion, cita_id: int, publicar) -> AvisoOut | None:
    """Envía al transportista la cita que le asignó su agencia y la deja en los avisos del tablero."""
    return await _notificar(mensaje_asignacion, sim, cita_id, publicar)


async def notificar_cancelacion(sim: Operacion, cita_id: int, publicar) -> AvisoOut | None:
    """Avisa al transportista que su agencia canceló la cita."""
    return await _notificar(mensaje_cancelacion, sim, cita_id, publicar)


async def notificar_reasignacion(sim: Operacion, cita_id: int, publicar) -> AvisoOut | None:
    """Avisa al transportista que su agencia cambió la cita (`cita_id` = cita nueva)."""
    return await _notificar(mensaje_reasignacion, sim, cita_id, publicar)


async def ciclo_avisos(sim: Operacion, publicar) -> list[AvisoOut]:
    """Revisa citas, genera avisos nuevos, los guarda, los publica en el tablero y los envía (Telegram o SMS).

    También revisa a quienes comparten su ubicación en tiempo real (su mejor entrada pudo cambiar sin que se muevan).
    """
    from app.modulos.mensajeria.bot_telegram import revisar_en_vivo

    await revisar_en_vivo(sim)
    citas, enviados = await asyncio.to_thread(leer_citas_activas)
    if not citas:
        return []
    nuevos = revisar(sim, citas, enviados)  # usa el simulador: en el event loop
    return [await _despachar(a, publicar) for a in nuevos]


ALTA_APROBADA = ("¡Bienvenido! ✅ *{agencia}* aprobó tu alta en Fluport.\n"
                 "Escríbeme, por ejemplo: _llego mañana a las 9 con un contenedor de 40_ o _¿cómo está la fila?_")
ALTA_RECHAZADA = ("*{agencia}* no aprobó tu solicitud de alta. Si crees que es un error, comunícate con ellos; "
                  "puedes volver a compartir tu número para enviar una nueva solicitud.")


async def avisar_resultado_alta(chat_id: int, agencia: str, aprobada: bool) -> tuple[bool, str]:
    """Le dice al transportista por Telegram si su agencia aprobó o rechazó su solicitud de alta."""
    texto = (ALTA_APROBADA if aprobada else ALTA_RECHAZADA).format(agencia=agencia)
    return await telegram.enviar(chat_id, texto, telegram.TECLADO_UBICACION if aprobada else telegram.TECLADO_CONTACTO)
