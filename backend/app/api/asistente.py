"""Asistente IA (M4) y webhooks de mensajería (M5)."""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.api._stub import pendiente
from app.config import get_settings
from app.contracts.schemas import AsistenteRequest, AsistenteResponse

router = APIRouter(tags=["asistente"])


@router.post("/api/asistente/mensaje", response_model=AsistenteResponse)
def mensaje(body: AsistenteRequest) -> AsistenteResponse:
    raise pendiente("M4")


@router.get("/webhook/whatsapp", response_class=PlainTextResponse)
def verificar_whatsapp(
    modo: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> str:
    """Verificación del webhook de WhatsApp Cloud API."""
    if modo == "subscribe" and token == get_settings().whatsapp_verify_token:
        return challenge
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@router.post("/webhook/whatsapp")
async def recibir_whatsapp(request: Request) -> dict:
    raise pendiente("M5")


@router.post("/webhook/telegram")
async def recibir_telegram(request: Request) -> dict:
    raise pendiente("M5")
