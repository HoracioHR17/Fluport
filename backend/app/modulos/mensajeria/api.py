"""Asistente IA (M4) y canal de mensajería por Telegram (M5)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.citas.servicio import ErrorCita
from app.modulos.mensajeria.asistente.agente import asistente
from app.modulos.mensajeria.bot_telegram import procesar_update
from app.modulos.mensajeria.servicio import en_segundo_plano
from app.nucleo.config import get_settings
from app.nucleo.contracts.schemas import AsistenteRequest, AsistenteResponse, AvisoOut
from app.nucleo.db.base import get_db
from app.nucleo.db.models import Aviso, Transportista
from app.nucleo.dependencias import operacion

router = APIRouter(tags=["asistente"])


@router.post("/api/asistente/mensaje", response_model=AsistenteResponse)
async def mensaje(body: AsistenteRequest, db: Session = Depends(get_db)) -> AsistenteResponse:
    """Conversación con el asistente por HTTP, para pruebas locales (`FLUPORT_ASISTENTE_WEB_ACTIVO=true`).

    No autentica al remitente: en un despliegue público queda desactivada y los transportistas usan el bot.
    """
    if not get_settings().asistente_web_activo:
        raise HTTPException(404, "El canal web del asistente está desactivado")
    try:
        return await asistente.responder(db, operacion(), body)
    except ErrorCita as e:  # p. ej. teléfono inválido
        raise HTTPException(e.codigo, e.mensaje) from e


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
    en_segundo_plano(procesar_update(operacion(), await request.json()))
    return {"ok": True}


@router.get("/api/telegram/enlace")
async def enlace_telegram() -> dict:
    """Enlace t.me del bot (para mostrarlo o convertirlo en QR en la demo)."""
    from app.modulos.mensajeria.adaptadores import telegram

    if not telegram.configurado():
        raise HTTPException(404, "Telegram no está configurado")
    r = await telegram.llamar("getMe")
    if not r.get("ok"):
        raise HTTPException(502, "Telegram no respondió")
    usuario = r["result"]["username"]
    return {"usuario": "@" + usuario, "enlace": f"https://t.me/{usuario}"}


@router.get("/api/avisos", response_model=list[AvisoOut])
async def avisos(limite: int = 10, agencia_id: str | None = None, db: Session = Depends(get_db)) -> list[AvisoOut]:
    """Últimos avisos proactivos generados (para el tablero; opcional: solo los de una agencia)."""
    q = select(Aviso).order_by(Aviso.id.desc()).limit(min(limite, 50))
    if agencia_id is not None:
        q = q.join(Transportista, Transportista.id == Aviso.transportista_id).where(Transportista.agencia_id == agencia_id)
    filas = db.scalars(q)
    return [AvisoOut.model_validate(a) for a in filas]
