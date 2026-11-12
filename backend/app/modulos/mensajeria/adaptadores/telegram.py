"""Telegram (Bot API): envío de mensajes y lectura de actualizaciones por long polling.

Se usa `httpx`; no se agrega ninguna biblioteca de Telegram.
"""
import logging
from typing import Any

import httpx

from app.nucleo.config import get_settings

log = logging.getLogger("fluport.telegram")
API = "https://api.telegram.org/bot{token}/{metodo}"
LIMITE_TEXTO = 4000  # Telegram admite 4 096 caracteres por mensaje
ESPERA_POLLING_S = 25  # long polling: Telegram mantiene la petición abierta hasta que haya mensajes

TECLADO_CONTACTO = {
    "keyboard": [[{"text": "📱 Compartir mi número", "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
QUITAR_TECLADO = {"remove_keyboard": True}


def configurado() -> bool:
    return bool(get_settings().telegram_token)


async def llamar(metodo: str, datos: dict[str, Any] | None = None, timeout_s: float = 15) -> dict[str, Any]:
    """Llama a un método de la Bot API. Devuelve el JSON de respuesta (con "ok")."""
    url = API.format(token=get_settings().telegram_token, metodo=metodo)
    async with httpx.AsyncClient(timeout=timeout_s) as http:
        r = await http.post(url, json=datos or {})
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "description": f"HTTP {r.status_code}"}


async def enviar(chat_id: int, texto: str, teclado: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Envía un mensaje. Usa el formato *negritas* (Markdown de Telegram); si el texto no se puede
    interpretar, lo reenvía como texto plano."""
    if not configurado():
        return False, "Telegram no está configurado"
    texto = texto if len(texto) <= LIMITE_TEXTO else texto[: LIMITE_TEXTO - 1] + "…"
    datos: dict[str, Any] = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    if teclado:
        datos["reply_markup"] = teclado
    try:
        r = await llamar("sendMessage", datos)
        if not r.get("ok") and "parse" in str(r.get("description", "")).lower():
            datos.pop("parse_mode")
            r = await llamar("sendMessage", datos)
    except httpx.HTTPError as e:
        log.error("Telegram sin conexión: %s", e)
        return False, f"sin conexión con Telegram ({type(e).__name__})"
    if not r.get("ok"):
        log.error("Telegram rechazó el mensaje: %s", r.get("description"))
        return False, str(r.get("description", "error"))
    return True, str(r["result"]["message_id"])


async def obtener_actualizaciones(offset: int | None) -> list[dict[str, Any]]:
    """Long polling: espera hasta ESPERA_POLLING_S s por mensajes nuevos a partir de `offset`."""
    datos: dict[str, Any] = {"timeout": ESPERA_POLLING_S, "allowed_updates": ["message"]}
    if offset is not None:
        datos["offset"] = offset
    r = await llamar("getUpdates", datos, timeout_s=ESPERA_POLLING_S + 10)
    if not r.get("ok"):
        raise RuntimeError(f"getUpdates falló: {r.get('description')}")
    return r.get("result", [])


async def quitar_webhook() -> None:
    """getUpdates no funciona si el bot tiene un webhook configurado."""
    await llamar("deleteWebhook", {"drop_pending_updates": False})


class CanalTelegram:
    """Adaptador del puerto CanalMensajeria para Telegram (Bot API)."""

    def configurado(self) -> bool:
        return configurado()

    async def enviar(self, destino, texto: str) -> tuple[bool, str]:
        return await enviar(destino, texto)

