"""Ubicación: entradas cercanas (dominio) y bot de Telegram con ubicación puntual y en tiempo real (sin BD)."""
import asyncio

import pytest

from app.modulos.mensajeria import bot_telegram as bot
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.mensajeria.dominio import ubicacion
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate

CHAT = 555000111
CERCA_A1 = (19.1890, -96.1590)  # a unos metros de Av. Rafael Cuervo (A1)


@pytest.fixture
def enviados(monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    lista = []

    async def falso(chat_id, texto, teclado=None):
        lista.append((chat_id, texto))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    bot._en_vivo.clear()
    yield lista
    bot._en_vivo.clear()


def _ubicacion(lat, lon, vivo=None, editado=False):
    loc = {"latitude": lat, "longitude": lon}
    if vivo:
        loc["live_period"] = vivo
    m = {"chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT}, "location": loc}
    return {"update_id": 1, ("edited_message" if editado else "message"): m}


# ───────────── Dominio ─────────────
def test_distancia_haversine():
    assert ubicacion.distancia_km(19.0, -96.0, 19.0, -96.0) == 0
    # 1° de latitud ≈ 111 km
    assert 110 < ubicacion.distancia_km(19.0, -96.0, 20.0, -96.0) < 112


def test_cercanas_ordenadas_y_recomendada(sim):
    lista = ubicacion.cercanas(sim, *CERCA_A1)
    assert len(lista) == len(sim.esc.accesos) and lista[0].acceso_id == "A1"
    assert [x.distancia_km for x in lista] == sorted(x.distancia_km for x in lista)
    mejor = ubicacion.recomendada(lista)
    assert mejor is not None and mejor.abierta


def test_recomendada_omite_cerradas(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A1"))
    lista = ubicacion.cercanas(sim, *CERCA_A1)
    assert lista[0].acceso_id == "A1" and lista[0].estado == "cerrada"
    assert ubicacion.recomendada(lista).acceso_id != "A1"


def test_empeoro():
    assert ubicacion.empeoro("verde", "rojo") and ubicacion.empeoro("amarillo", "cerrada")
    assert not ubicacion.empeoro("rojo", "verde") and not ubicacion.empeoro(None, "rojo")


# ───────────── Bot (no requiere alta ni BD) ─────────────
def test_ubicacion_puntual(sim, enviados):
    r = asyncio.run(bot.procesar_update(sim, _ubicacion(*CERCA_A1)))
    assert r.startswith("📍 *Entradas más cercanas a ti*") and "Av. Rafael Cuervo" in r and "Te conviene" in r
    assert "tiempo real" in r and CHAT not in bot._en_vivo  # sugiere compartir en vivo, sin seguimiento


def test_ubicacion_invalida(sim, enviados):
    assert asyncio.run(bot.procesar_update(sim, _ubicacion(200, -96.1))) == bot.UBICACION_INVALIDA


def test_ubicacion_en_vivo_avisa_cuando_la_mejor_se_cierra(sim, enviados, monkeypatch):
    r = asyncio.run(bot.procesar_update(sim, _ubicacion(*CERCA_A1, vivo=900)))
    assert "Te sigo en tiempo real" in r and CHAT in bot._en_vivo
    antes = bot._en_vivo[CHAT].mejor
    # moverse sin cambios: no se manda nada
    assert asyncio.run(bot.procesar_update(sim, _ubicacion(19.1891, -96.1591, editado=True))) is None
    # la mejor entrada se cierra: aviso (sin esperar el intervalo mínimo)
    monkeypatch.setattr(bot, "AVISO_MIN_S", 0)
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id=antes))
    asyncio.run(bot.revisar_en_vivo(sim))
    assert enviados[-1][0] == CHAT and ("Ahora te conviene" in enviados[-1][1] or "se cerraron" in enviados[-1][1])
    assert bot._en_vivo[CHAT].mejor != antes


def test_ubicacion_en_vivo_expira(sim, enviados):
    asyncio.run(bot.procesar_update(sim, _ubicacion(*CERCA_A1, vivo=900)))
    bot._en_vivo[CHAT].hasta = 0
    asyncio.run(bot.revisar_en_vivo(sim))
    assert CHAT not in bot._en_vivo


def test_ediciones_de_texto_se_ignoran(sim, enviados):
    upd = {"update_id": 2, "edited_message": {"chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT}, "text": "hola"}}
    assert asyncio.run(bot.procesar_update(sim, upd)) is None and enviados == []


def test_cuello_de_botella_en_la_entrada_de_la_cita(sim):
    """Si la entrada de su cita se cierra, se le sugiere otra con su hora estimada de llegada."""
    cita = bot.CitaEnCurso(cita_id=7, acceso_id="A1", telefono="+522290000007")
    assert bot.texto_cuello_de_botella(sim, *CERCA_A1, cita) is None  # abierta y sin fila: nada que avisar
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A1"))
    texto, sugerida = bot.texto_cuello_de_botella(sim, *CERCA_A1, cita)
    assert sugerida != "A1" and "Cuello de botella" in texto and "cerrada" in texto
    assert "llegas ~" in texto and "#7" in texto and "SÍ" in texto
