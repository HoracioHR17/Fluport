"""Cambios y cancelaciones de citas: la agencia avisa al transportista y el transportista cambia su entrada desde el bot."""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modulos.mensajeria import bot_telegram as bot
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.mensajeria.asistente import agente as ag
from app.modulos.mensajeria.asistente.agente import HERRAMIENTAS, entradas, instrucciones
from app.nucleo.config import get_settings
from tests.conftest import vaciar_tablas

CHAT = 777000333
TEL = "+522290003330"


# ───────────── Sin BD ─────────────
def test_casetas_por_entrada(sim):
    e = entradas(sim)
    assert [x.split()[0] for x in e["norte"]] == ["A1", "A3"] and [x.split()[0] for x in e["sur"]] == ["A2"]
    t = instrucciones(sim)
    assert "entrada norte: A1" in t and "entrada sur: A2" in t and "conservando la hora" in t


def test_reprogramar_permite_omitir_la_hora():
    h = next(h for h in HERRAMIENTAS if h["name"] == "reprogramar_cita")
    assert h["parameters"]["required"] == ["cita_id"]


# ───────────── Con PostgreSQL de prueba ─────────────
@pytest.fixture(scope="module")
def cliente(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c
    ag.asistente.usar_cliente(None)


@pytest.fixture
def enviados(monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    lista = []

    async def falso(chat_id, texto, teclado=None):
        lista.append((chat_id, texto))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    return lista


def _ts(c, horas: float) -> str:
    ahora = datetime.fromisoformat(c.get("/api/sim/estado").json()["ts_sim"])
    return (ahora + timedelta(hours=horas)).replace(minute=0, second=0, microsecond=0).isoformat()


def _transportista_con_bot():
    """Transportista de AG01 conectado al bot."""
    from app.nucleo.db.base import SessionLocal
    from app.nucleo.db.models import Transportista

    with SessionLocal() as db:
        t = db.scalar(select(Transportista).where(Transportista.telefono == TEL))
        if t is None:
            t = Transportista(telefono=TEL, alias="Rosa", es_demo=True)
            db.add(t)
        t.agencia_id, t.telegram_chat_id = "AG01", CHAT
        db.commit()


def _cita(c, acceso="A1", horas=3):
    r = c.post("/api/citas", json={"telefono": TEL, "acceso_id": acceso, "ventana_inicio": _ts(c, horas),
                                   "ventana_fin": _ts(c, horas + 0.5), "tipo_carga": "contenedor_40"})
    assert r.status_code == 201, r.text
    return r.json()


def _esperar(c, enviados, n):
    """Los avisos salen en segundo plano: da tiempo al event loop del TestClient."""
    for _ in range(50):
        if len(enviados) >= n:
            return
        c.portal.call(asyncio.sleep, 0.02)
    raise AssertionError(f"se esperaban {n} mensajes y llegaron {len(enviados)}")


def _avisos(c, tipo):
    return [a for a in c.get("/api/avisos?agencia_id=AG01&limite=50").json() if a["tipo"] == tipo]


def test_agencia_cancela_y_avisa_al_transportista(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente)
    _esperar(cliente, enviados, 1)  # aviso de cita asignada
    assert cliente.delete(f"/api/citas/{cita['id']}").json()["estado"] == "cancelada"
    _esperar(cliente, enviados, 2)
    chat, texto = enviados[-1]
    assert chat == CHAT and "canceló tu cita" in texto and f"#{cita['id']}" in texto
    assert _avisos(cliente, "cita_cancelada")[0]["cita_id"] == cita["id"]


def test_agencia_cambia_la_cita_y_el_si_la_confirma(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente)
    _esperar(cliente, enviados, 1)
    r = cliente.patch(f"/api/citas/{cita['id']}", json={"acceso_id": "A2", "ventana_inicio": _ts(cliente, 4),
                                                        "ventana_fin": _ts(cliente, 4.5)})
    nueva = r.json()
    _esperar(cliente, enviados, 2)
    assert "cambió tu cita" in enviados[-1][1] and f"#{nueva['id']}" in enviados[-1][1] and "SÍ" in enviados[-1][1]
    respuesta = cliente.portal.call(bot.procesar_update, _sim(), _msg("sí"))
    assert respuesta.startswith("Cita confirmada") and "Paso del Toro" in respuesta
    assert cliente.get(f"/api/citas/{nueva['id']}").json()["confirmada_en"] is not None


def test_transportista_cambia_de_entrada_conservando_la_hora(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente, "A1", horas=5)
    llm = ag.asistente
    llm.usar_cliente(_Guion([{"role": "model", "parts": [
        {"functionCall": {"name": "reprogramar_cita", "args": {"cita_id": cita["id"], "acceso_id": "A2"}}}]}]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("ya no entro por el norte, voy a entrar por el sur"))
    assert r.startswith("Cambié tu cita") and "Paso del Toro" in r and "antes Caseta La Antigua" in r
    vieja = cliente.get(f"/api/citas/{cita['id']}").json()
    assert vieja["estado"] == "reprogramada"
    nueva = next(c for c in cliente.get(f"/api/citas?telefono={TEL}").json() if c.get("cita_anterior_id") == cita["id"])
    assert nueva["acceso_id"] == "A2" and nueva["ventana_inicio"] == vieja["ventana_inicio"]
    assert nueva["confirmada_en"] is not None  # la pidió el propio transportista
    assert any(a["cita_id"] == nueva["id"] for a in _avisos(cliente, "cambio_chofer"))


def test_transportista_cancela_y_la_agencia_se_entera(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente, "A3", horas=6)
    ag.asistente.usar_cliente(_Guion([{"role": "model", "parts": [
        {"functionCall": {"name": "cancelar_cita", "args": {"cita_id": cita["id"]}}}]}]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("cancela mi cita, se descompuso el camión"))
    assert r.startswith("Cancelé tu cita") and "agencia" in r
    assert any(a["cita_id"] == cita["id"] for a in _avisos(cliente, "cancelacion_chofer"))


def test_cambio_sin_datos_es_error(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente, "A1", horas=7)
    from app.modulos.mensajeria.asistente.agente import Herramientas
    from app.nucleo.contracts.enums import OrigenCita
    from app.nucleo.db.base import SessionLocal

    with SessionLocal() as db:
        h = Herramientas(db, _sim(), TEL, OrigenCita.telegram)
        assert "error" in h.ejecutar("reprogramar_cita", {"cita_id": cita["id"]})
        assert "error" in h.ejecutar("reprogramar_cita", {"cita_id": cita["id"], "acceso_id": "A1"})


class _Guion:
    def __init__(self, turnos):
        self.turnos = list(turnos)

    async def generar(self, contenidos, sistema, herramientas):
        return self.turnos.pop(0)


def _sim():
    from app.modulos.simulacion.servicio import servicio

    return servicio.sim


def _msg(texto):
    return {"update_id": 1, "message": {"chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT}, "text": texto}}
