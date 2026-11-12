"""Asistente IA (M4) y canales de mensajería: Telegram y WhatsApp con Twilio (M5)."""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.agente import asistente
from app.citas.servicio import ErrorCita
from app.config import get_settings
from app.contracts.schemas import AsistenteRequest, AsistenteResponse, AvisoOut
from app.db.base import get_db
from app.db.models import Aviso
from app.messaging import twilio
from app.messaging.bot_telegram import procesar_update
from app.messaging.servicio import atender_mensaje, en_segundo_plano
from app.sim.servicio import servicio

router = APIRouter(tags=["asistente"])
log = logging.getLogger("fluport.whatsapp")
TWIML_VACIO = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@router.post("/api/asistente/mensaje", response_model=AsistenteResponse)
async def mensaje(body: AsistenteRequest, db: Session = Depends(get_db)) -> AsistenteResponse:
    """Conversación con el asistente de citas (la usan los canales de mensajería, el tablero y las pruebas)."""
    try:
        return await asistente.responder(db, servicio.requerir(), body)
    except ErrorCita as e:  # p. ej. teléfono inválido
        raise HTTPException(e.codigo, e.mensaje) from e


def _url_publica(request: Request) -> str:
    """URL exacta que Twilio llamó: la configurada o la reconstruida (respetando el proxy/túnel)."""
    cfg = get_settings()
    if cfg.twilio_webhook_url:
        return cfg.twilio_webhook_url
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    url = f"{proto}://{host}{request.url.path}"
    return url + (f"?{request.url.query}" if request.url.query else "")


@router.post("/webhook/whatsapp", include_in_schema=True)
async def recibir_whatsapp(request: Request) -> Response:
    """Webhook de Twilio para mensajes de WhatsApp entrantes.

    Responde de inmediato (Twilio espera una respuesta rápida) y contesta al transportista en segundo plano
    por la API REST de Twilio.
    """
    cfg = get_settings()
    params = twilio.parsear_formulario(await request.body())
    if cfg.twilio_validar_firma and cfg.twilio_auth_token:
        if not twilio.firma_valida(_url_publica(request), params, request.headers.get("x-twilio-signature"),
                                   cfg.twilio_auth_token):
            log.warning("Firma de Twilio inválida para %s", _url_publica(request))
            raise HTTPException(403, "Firma de Twilio inválida")
    remitente, texto = params.get("From", ""), params.get("Body", "").strip()
    if remitente:
        en_segundo_plano(atender_mensaje(servicio.requerir(), remitente, texto))
    return Response(content=TWIML_VACIO, media_type="application/xml")


@router.post("/webhook/telegram")
async def recibir_telegram(request: Request) -> dict:
    """Webhook de Telegram (modo `webhook`; en modo `polling` no se usa).

    Telegram envía el secreto configurado con setWebhook en el encabezado X-Telegram-Bot-Api-Secret-Token.
    """
    cfg = get_settings()
    if cfg.telegram_modo != "webhook" or not cfg.telegram_webhook_secret:
        raise HTTPException(404, "El webhook de Telegram no está activo")
    if request.headers.get("x-telegram-bot-api-secret-token") != cfg.telegram_webhook_secret:
        raise HTTPException(403, "Secreto inválido")
    en_segundo_plano(procesar_update(servicio.requerir(), await request.json()))
    return {"ok": True}


@router.get("/api/telegram/enlace")
async def enlace_telegram() -> dict:
    """Enlace t.me del bot (para mostrarlo o convertirlo en QR en la demo)."""
    from app.messaging import telegram

    if not telegram.configurado():
        raise HTTPException(404, "Telegram no está configurado")
    r = await telegram.llamar("getMe")
    if not r.get("ok"):
        raise HTTPException(502, "Telegram no respondió")
    usuario = r["result"]["username"]
    return {"usuario": "@" + usuario, "enlace": f"https://t.me/{usuario}"}


@router.get("/api/whatsapp/enlace")
async def enlace_whatsapp() -> dict:
    """Enlace wa.me para abrir el chat con el número de Fluport (respaldo para la demo)."""
    numero = get_settings().twilio_whatsapp_from.removeprefix("whatsapp:").lstrip("+")
    if not numero:
        raise HTTPException(404, "WhatsApp no está configurado")
    return {"numero": "+" + numero, "enlace": f"https://wa.me/{numero}?text={quote('Hola, quiero agendar una cita')}",
            "configurado": twilio.configurado()}


@router.get("/api/avisos", response_model=list[AvisoOut])
async def avisos(limite: int = 10, db: Session = Depends(get_db)) -> list[AvisoOut]:
    """Últimos avisos proactivos generados (para el tablero)."""
    filas = db.scalars(select(Aviso).order_by(Aviso.id.desc()).limit(min(limite, 50)))
    return [AvisoOut.model_validate(a) for a in filas]
