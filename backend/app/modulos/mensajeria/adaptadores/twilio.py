"""Twilio (WhatsApp): validación de la firma de los webhooks y envío de mensajes por la API REST.

Se usa `httpx` y la biblioteca estándar; no se agrega el SDK de Twilio.
"""
import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from urllib.parse import parse_qsl

import httpx

from app.nucleo.config import get_settings

log = logging.getLogger("fluport.twilio")
URL_MENSAJES = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
LIMITE_WHATSAPP = 1500  # Twilio admite 1 600 caracteres por mensaje de WhatsApp


def firma(url: str, params: Mapping[str, str], token: str) -> str:
    """X-Twilio-Signature esperada: HMAC-SHA1 (llave = AuthToken) de URL + parámetros ordenados (nombre+valor), Base64."""
    datos = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(token.encode(), datos.encode(), hashlib.sha1).digest()).decode()


def firma_valida(url: str, params: Mapping[str, str], recibida: str | None, token: str) -> bool:
    return bool(recibida) and hmac.compare_digest(firma(url, params, token), recibida)


def parsear_formulario(cuerpo: bytes) -> dict[str, str]:
    """Cuerpo application/x-www-form-urlencoded → dict (sin depender de python-multipart)."""
    return dict(parse_qsl(cuerpo.decode("utf-8"), keep_blank_values=True))


def configurado() -> bool:
    c = get_settings()
    return bool(c.twilio_account_sid and c.twilio_auth_token and c.twilio_whatsapp_from)


_direcciones: dict[str, str] = {}  # teléfono normalizado → dirección exacta con la que escribió ("whatsapp:+52…")


def recordar_direccion(telefono: str, direccion: str) -> None:
    """Guarda la dirección exacta de WhatsApp de un remitente para responderle al mismo formato."""
    _direcciones[telefono] = direccion


def a_whatsapp(telefono: str) -> str:
    """Dirección de WhatsApp para un teléfono normalizado.

    Si el transportista ya escribió, se usa exactamente su dirección. Si no, los celulares de México se envían
    con el "1" después del 52 (formato con el que WhatsApp los reporta en Twilio).
    """
    if telefono in _direcciones:
        return _direcciones[telefono]
    t = telefono.removeprefix("whatsapp:")
    if t.startswith("+52") and len(t) == 13:
        t = "+521" + t[3:]
    return "whatsapp:" + t


async def enviar(telefono: str, texto: str) -> tuple[bool, str]:
    """Envía un WhatsApp. Devuelve (enviado, sid o motivo del fallo)."""
    if not configurado():
        return False, "Twilio no está configurado"
    c = get_settings()
    texto = texto if len(texto) <= LIMITE_WHATSAPP else texto[: LIMITE_WHATSAPP - 1] + "…"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                URL_MENSAJES.format(sid=c.twilio_account_sid),
                auth=(c.twilio_account_sid, c.twilio_auth_token),
                data={"From": c.twilio_whatsapp_from, "To": a_whatsapp(telefono), "Body": texto},
            )
    except httpx.HTTPError as e:
        log.error("Twilio sin conexión: %s", e)
        return False, f"sin conexión con Twilio ({type(e).__name__})"
    if r.status_code >= 300:
        log.error("Twilio respondió %s: %s", r.status_code, r.text[:300])
        return False, f"Twilio respondió {r.status_code}"
    return True, r.json().get("sid", "")


class CanalWhatsApp:
    """Adaptador del puerto CanalMensajeria para WhatsApp por Twilio."""

    def configurado(self) -> bool:
        return configurado()

    async def enviar(self, destino, texto: str) -> tuple[bool, str]:
        return await enviar(destino, texto)

