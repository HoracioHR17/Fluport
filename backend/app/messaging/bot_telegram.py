"""Bot de Telegram de Fluport: identifica al transportista por su teléfono y lo conecta con el asistente.

Flujo:
1. Chat nuevo → se le pide compartir su número con el botón de contacto de Telegram.
2. Comparte su propio contacto → se registra (`transportista.telegram_chat_id`) y queda identificado.
3. Mensajes de texto → asistente (mismo que WhatsApp y web) → respuesta en el chat.
"""
import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.agente import asistente
from app.citas.servicio import ErrorCita, normalizar_telefono
from app.contracts.enums import Canal
from app.contracts.schemas import AsistenteRequest
from app.db.base import SessionLocal
from app.db.models import Transportista
from app.messaging import telegram
from app.sim.motor import Simulador

log = logging.getLogger("fluport.telegram")

BIENVENIDA = ("¡Hola! Soy el asistente de *FLUPORT* para las casetas del puerto de Veracruz (simulación).\n"
              "Para ver y agendar tus citas, comparte tu número con el botón de abajo.")
REGISTRADO = ("Listo ✅ Ya te identifiqué con el número terminado en {fin}.\n"
              "Escríbeme, por ejemplo: _llego mañana a las 9 con un contenedor de 40_ o _¿cómo está la fila?_")
CONTACTO_AJENO = "Por seguridad solo puedo registrar *tu propio* número. Usa el botón para compartirlo."


def transportista_de_chat(db: Session, chat_id: int) -> Transportista | None:
    return db.scalar(select(Transportista).where(Transportista.telegram_chat_id == chat_id))


def registrar_contacto(db: Session, chat_id: int, telefono: str, nombre: str | None) -> Transportista:
    """Liga el chat con el transportista de ese teléfono (lo crea si no existe)."""
    tel = normalizar_telefono(telefono)
    anterior = transportista_de_chat(db, chat_id)
    if anterior is not None and anterior.telefono != tel:
        anterior.telegram_chat_id = None  # el chat cambió de número
        db.flush()
    t = db.scalar(select(Transportista).where(Transportista.telefono == tel))
    if t is None:
        t = Transportista(alias=nombre or f"Transportista {tel[-4:]}", telefono=tel, es_demo=True)
        db.add(t)
    t.telegram_chat_id = chat_id
    db.commit()
    return t


async def procesar_update(sim: Simulador, update: dict[str, Any]) -> str | None:
    """Atiende una actualización de Telegram. Devuelve el texto enviado (útil en pruebas)."""
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if chat_id is None or (msg.get("chat") or {}).get("type") not in (None, "private"):
        return None  # solo chats privados
    remitente_id = (msg.get("from") or {}).get("id")

    if "contact" in msg:
        contacto = msg["contact"]
        if contacto.get("user_id") != remitente_id:
            await telegram.enviar(chat_id, CONTACTO_AJENO, telegram.TECLADO_CONTACTO)
            return CONTACTO_AJENO
        try:
            with SessionLocal() as db:
                t = registrar_contacto(db, chat_id, contacto.get("phone_number", ""), contacto.get("first_name"))
                fin = (t.telefono or "")[-4:]
        except ErrorCita:
            await telegram.enviar(chat_id, "No pude leer ese número. Inténtalo de nuevo con el botón.",
                                  telegram.TECLADO_CONTACTO)
            return None
        texto = REGISTRADO.format(fin=fin)
        await telegram.enviar(chat_id, texto, telegram.QUITAR_TECLADO)
        return texto

    texto_usuario = (msg.get("text") or "").strip()
    with SessionLocal() as db:
        t = transportista_de_chat(db, chat_id)
        if t is None or texto_usuario.startswith("/start"):
            if t is None:
                await telegram.enviar(chat_id, BIENVENIDA, telegram.TECLADO_CONTACTO)
                return BIENVENIDA
            texto = REGISTRADO.format(fin=(t.telefono or "")[-4:])
            await telegram.enviar(chat_id, texto)
            return texto
        if not texto_usuario:
            return None
        r = await asistente.responder(db, sim, AsistenteRequest(canal=Canal.telegram, remitente=t.telefono,
                                                                  texto=texto_usuario))
    await telegram.enviar(chat_id, r.respuesta)
    return r.respuesta


class PollingTelegram:
    """Lee mensajes del bot con long polling (no requiere URL pública ni túnel)."""

    def __init__(self) -> None:
        self._tarea: asyncio.Task | None = None
        self._offset: int | None = None
        self._en_curso: set[asyncio.Task] = set()  # referencias a mensajes en atención

    def iniciar(self, obtener_sim) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle(obtener_sim), name="fluport-telegram")

    async def detener(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self, obtener_sim) -> None:
        try:
            await telegram.quitar_webhook()
        except Exception:  # noqa: BLE001
            log.warning("No se pudo quitar el webhook de Telegram")
        log.info("Bot de Telegram escuchando (long polling)")
        while True:
            try:
                for upd in await telegram.obtener_actualizaciones(self._offset):
                    self._offset = upd["update_id"] + 1
                    sim = obtener_sim()
                    if sim is not None:
                        t = asyncio.create_task(self._atender(sim, upd))
                        self._en_curso.add(t)
                        t.add_done_callback(self._en_curso.discard)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (red caída, token inválido…): reintenta sin tumbar la app
                log.warning("Polling de Telegram: %s", e)
                await asyncio.sleep(5)

    async def _atender(self, sim: Simulador, upd: dict[str, Any]) -> None:
        try:
            await procesar_update(sim, upd)
        except Exception:  # noqa: BLE001
            log.exception("Error al atender un mensaje de Telegram")


polling = PollingTelegram()
