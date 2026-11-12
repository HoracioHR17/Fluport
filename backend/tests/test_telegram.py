"""Telegram: cliente de la Bot API, registro por contacto, asistente, avisos y webhook (todo simulado)."""
import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.modulos.mensajeria import bot_telegram as bot
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.mensajeria.asistente import agente as ag
from app.nucleo.config import get_settings
from tests.conftest import vaciar_tablas

CHAT = 777000111


@pytest.fixture
def tg_conf(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "telegram_token", "123:ABC")
    monkeypatch.setattr(cfg, "telegram_solo_registrados", False)  # modo abierto; el modo con alta previa: test_agencias
    return cfg


@pytest.fixture
def enviados(monkeypatch):
    lista = []

    async def falso(chat_id, texto, teclado=None):
        lista.append((chat_id, texto, teclado))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    return lista


def _transporte(monkeypatch, manejador):
    original = httpx.AsyncClient

    class ClientePrueba(original):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(manejador)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", ClientePrueba)


def _msg(texto=None, contacto=None, chat=CHAT, de=CHAT, tipo="private"):
    m = {"chat": {"id": chat, "type": tipo}, "from": {"id": de}}
    if texto is not None:
        m["text"] = texto
    if contacto is not None:
        m["contact"] = contacto
    return {"update_id": 1, "message": m}


# ───────────── Cliente de la Bot API ─────────────
def test_enviar_sin_configuracion():
    assert asyncio.run(telegram.enviar(1, "hola")) == (False, "Telegram no está configurado")


def test_enviar_y_reintento_sin_formato(tg_conf, monkeypatch):
    import json

    cuerpos = []

    def manejador(request):
        cuerpo = json.loads(request.read())
        cuerpos.append(cuerpo)
        assert str(request.url).startswith("https://api.telegram.org/bot123:ABC/sendMessage")
        if "parse_mode" in cuerpo:
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    _transporte(monkeypatch, manejador)
    assert asyncio.run(telegram.enviar(CHAT, "texto con _guion bajo", telegram.TECLADO_CONTACTO)) == (True, "42")
    assert cuerpos[0]["parse_mode"] == "Markdown" and "parse_mode" not in cuerpos[1]
    assert cuerpos[1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True


def test_obtener_actualizaciones(tg_conf, monkeypatch):
    import json

    vistos = {}

    def manejador(request):
        vistos["cuerpo"] = json.loads(request.read())
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 5}]})

    _transporte(monkeypatch, manejador)
    assert asyncio.run(telegram.obtener_actualizaciones(5)) == [{"update_id": 5}]
    assert vistos["cuerpo"]["offset"] == 5 and vistos["cuerpo"]["timeout"] == telegram.ESPERA_POLLING_S


def test_polling_procesa_y_avanza_offset(tg_conf, monkeypatch):
    llamadas, procesados = [], []

    async def actualizaciones(offset):
        llamadas.append(offset)
        if len(llamadas) == 1:
            return [{"update_id": 10, "message": {}}]
        await asyncio.sleep(3600)

    async def procesar(sim, upd):
        procesados.append(upd["update_id"])

    async def nada():
        return None

    monkeypatch.setattr(telegram, "obtener_actualizaciones", actualizaciones)
    monkeypatch.setattr(telegram, "quitar_webhook", nada)
    monkeypatch.setattr(bot, "procesar_update", procesar)

    async def correr():
        p = bot.PollingTelegram()
        p.iniciar(lambda: object())
        await asyncio.sleep(0.1)
        await p.detener()
        return p

    p = asyncio.run(correr())
    assert procesados == [10] and llamadas[:2] == [None, 11] and p._offset == 11


# ───────────── Bot con PostgreSQL de prueba ─────────────
@pytest.fixture(scope="module")
def cliente(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c
    ag.asistente.usar_cliente(None)


def _sim():
    from app.modulos.simulacion.servicio import servicio

    return servicio.sim


def test_chat_nuevo_pide_contacto(cliente, tg_conf, enviados):
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("hola"))
    assert r == bot.BIENVENIDA and enviados[-1][2] == telegram.TECLADO_CONTACTO


def test_grupos_se_ignoran(cliente, tg_conf, enviados):
    assert cliente.portal.call(bot.procesar_update, _sim(), _msg("hola", tipo="group")) is None and enviados == []


def test_contacto_ajeno_se_rechaza(cliente, tg_conf, enviados):
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg(contacto={"phone_number": "5212290000999", "user_id": 1}))
    assert r == bot.CONTACTO_AJENO


def test_registro_y_conversacion(cliente, tg_conf, enviados):
    from app.nucleo.db.base import SessionLocal

    r = cliente.portal.call(bot.procesar_update, _sim(),
                            _msg(contacto={"phone_number": "5212290000888", "user_id": CHAT, "first_name": "Raúl"}))
    assert r.startswith("Listo ✅") and "0888" in r and enviados[-1][2] == telegram.QUITAR_TECLADO
    with SessionLocal() as db:
        t = bot.transportista_de_chat(db, CHAT)
        assert t.telefono == "+522290000888" and t.alias == "Raúl"

    class LLM:
        async def generar(self, *a):
            return {"role": "model", "parts": [{"functionCall": {"name": "consultar_espera", "args": {}}}]}

    ag.asistente.usar_cliente(LLM())
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("¿cómo está la fila?"))
    assert r.startswith("Así están las casetas") and enviados[-1][0] == CHAT
    assert cliente.portal.call(bot.procesar_update, _sim(), _msg("/start")).startswith("Listo ✅")


def test_aviso_por_telegram(cliente, tg_conf, enviados, monkeypatch):
    from app.modulos.mensajeria.adaptadores import twilio
    from app.modulos.mensajeria.servicio import ciclo_avisos

    whatsapp = []

    async def wa(tel, texto):
        whatsapp.append(tel)
        return True, "x"

    monkeypatch.setattr(twilio, "enviar", wa)
    inicio = _sim().ts() + timedelta(minutes=15)
    cita = cliente.post("/api/citas", json={"telefono": "+522290000888", "acceso_id": "A1",
                                            "ventana_inicio": inicio.isoformat(),
                                            "ventana_fin": (inicio + timedelta(minutes=30)).isoformat(),
                                            "tipo_carga": "granel"}).json()
    avisos = cliente.portal.call(ciclo_avisos, _sim(), lambda _: None)
    aviso = next(a for a in avisos if a.cita_id == cita["id"])
    assert aviso.canal == "telegram" and enviados[-1][0] == CHAT and whatsapp == []


def test_webhook_telegram(cliente, tg_conf, monkeypatch):
    assert cliente.post("/webhook/telegram", json={}).status_code == 404  # modo polling
    monkeypatch.setattr(tg_conf, "telegram_modo", "webhook")
    monkeypatch.setattr(tg_conf, "telegram_webhook_secret", "s3cr3t")
    assert cliente.post("/webhook/telegram", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}).status_code == 403
    ok = cliente.post("/webhook/telegram", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}
