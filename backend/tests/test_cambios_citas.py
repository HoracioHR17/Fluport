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
    ids = {k: [x.split()[0] for x in v] for k, v in e.items()}
    assert ids == {"norte": ["A1", "A2", "A3"], "sur": ["A4", "A5"], "urbana": ["A6"]}
    t = instrucciones(sim)
    assert "entrada norte: A1" in t and "entrada sur: A4" in t and "conservando la hora" in t


def test_reprogramar_y_cancelar_sin_numero_de_cita():
    for nombre in ("reprogramar_cita", "cancelar_cita"):
        h = next(h for h in HERRAMIENTAS if h["name"] == nombre)
        assert "required" not in h["parameters"] and "cita_id" in h["parameters"]["properties"]


def test_intencion_de_modificar():
    from app.modulos.mensajeria.asistente.agente import quiere_modificar

    assert quiere_modificar("cancela mi cita") and quiere_modificar("ya no voy a llegar") and quiere_modificar("Cámbiala")
    assert not quiere_modificar("¿cuáles son mis citas?")


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


def _cita(c, acceso="A1", horas=3, origen="web"):
    """origen "web" = la asigna la agencia (obligatoria); "telegram" = la pidió el chofer en el bot."""
    r = c.post("/api/citas", json={"telefono": TEL, "acceso_id": acceso, "ventana_inicio": _ts(c, horas),
                                   "ventana_fin": _ts(c, horas + 0.5), "tipo_carga": "contenedor_40", "origen": origen})
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


def test_agencia_asigna_y_cambia_sin_pedir_confirmacion(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente)
    _esperar(cliente, enviados, 1)
    assert "Nueva cita" in enviados[-1][1] and "SÍ" not in enviados[-1][1] and "Preséntate" in enviados[-1][1]
    assert cliente.get(f"/api/citas/{cita['id']}").json()["confirmada_en"] is not None  # obligatoria desde que se asigna
    r = cliente.patch(f"/api/citas/{cita['id']}", json={"acceso_id": "A4", "ventana_inicio": _ts(cliente, 4),
                                                        "ventana_fin": _ts(cliente, 4.5)})
    nueva = r.json()
    _esperar(cliente, enviados, 2)
    assert "cambió tu cita" in enviados[-1][1] and f"#{nueva['id']}" in enviados[-1][1] and "SÍ" not in enviados[-1][1]
    assert nueva["acceso_id"] == "A4" and nueva["confirmada_en"] is not None


def test_transportista_cambia_de_entrada_conservando_la_hora(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente, "A1", horas=5)
    llm = ag.asistente
    llm.usar_cliente(_Guion([{"role": "model", "parts": [
        {"functionCall": {"name": "reprogramar_cita", "args": {"cita_id": cita["id"], "acceso_id": "A4"}}}]}]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("ya no entro por el norte, voy a entrar por el sur"))
    assert r.startswith("Cambié tu cita") and "Entronque San Julián" in r and "antes Av. Rafael Cuervo" in r
    vieja = cliente.get(f"/api/citas/{cita['id']}").json()
    assert vieja["estado"] == "reprogramada"
    nueva = next(c for c in cliente.get(f"/api/citas?telefono={TEL}").json() if c.get("cita_anterior_id") == cita["id"])
    assert nueva["acceso_id"] == "A4" and nueva["ventana_inicio"] == vieja["ventana_inicio"]
    assert nueva["confirmada_en"] is not None  # la pidió el propio transportista
    assert any(a["cita_id"] == nueva["id"] for a in _avisos(cliente, "cambio_chofer"))


def test_transportista_cancela_su_propia_cita(cliente, enviados):
    _transportista_con_bot()
    cita = _cita(cliente, "A3", horas=6, origen="telegram")
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


def test_cancelar_pidiendo_primero_la_lista(cliente, enviados):
    """El LLM consulta mis_citas y luego cancela: la lista no debe cortar la conversación."""
    _transportista_con_bot()
    for c in cliente.get(f"/api/citas?telefono={TEL}").json():  # deja una sola cita activa
        if c["estado"] in ("agendada", "en_ruta"):
            cliente.delete(f"/api/citas/{c['id']}")
    cita = _cita(cliente, "A2", horas=8, origen="telegram")
    ag.asistente.usar_cliente(_Guion([
        {"role": "model", "parts": [{"functionCall": {"name": "mis_citas", "args": {}}}]},
        {"role": "model", "parts": [{"functionCall": {"name": "cancelar_cita", "args": {}}}]},
    ]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("cancela mi cita por favor"))
    assert r.startswith("Cancelé tu cita") and f"#{cita['id']}" in r
    assert cliente.get(f"/api/citas/{cita['id']}").json()["estado"] == "cancelada"


def test_cita_de_la_agencia_no_la_cancela_el_chofer(cliente, enviados):
    """La cita asignada es obligatoria: si el chofer pide cancelarla, se le pasa la petición a la agencia."""
    _transportista_con_bot()
    cita = _cita(cliente, "A1", horas=9)
    ag.asistente.usar_cliente(_Guion([{"role": "model", "parts": [
        {"functionCall": {"name": "cancelar_cita", "args": {"cita_id": cita["id"]}}}]}]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("cancela mi cita, no voy a poder"))
    assert "es obligatoria" in r and "avisé" in r
    assert cliente.get(f"/api/citas/{cita['id']}").json()["estado"] == "agendada"
    assert any(a["cita_id"] == cita["id"] for a in _avisos(cliente, "solicitud_cancelacion"))


def test_si_o_no_los_atiende_el_asistente(cliente, enviados):
    """Ya no hay confirmación con SÍ / NO: cualquier respuesta corta va al asistente."""
    _transportista_con_bot()
    cita = _cita(cliente, "A1", horas=10, origen="telegram")
    ag.asistente.usar_cliente(_Guion([{"role": "model", "parts": [
        {"functionCall": {"name": "cancelar_cita", "args": {"cita_id": cita["id"]}}}]}]))
    r = cliente.portal.call(bot.procesar_update, _sim(), _msg("sí"))
    assert r.startswith("Cancelé tu cita")


def test_en_ruta_avisa_cuello_de_botella_con_eta(cliente, enviados):
    """Con cita y ubicación en tiempo real: si su entrada se cierra, el bot sugiere otra con hora de llegada."""
    from app.nucleo.contracts.enums import TipoEventoSim
    from app.nucleo.contracts.schemas import EventoCreate

    _transportista_con_bot()
    for c in cliente.get(f"/api/citas?telefono={TEL}").json():  # deja solo la cita de esta prueba
        if c["estado"] in ("agendada", "en_ruta"):
            cliente.delete(f"/api/citas/{c['id']}")
    cita = _cita(cliente, "A3", horas=1, origen="telegram")
    cliente.post("/api/sim/eventos", json={"tipo": "cierre_acceso", "acceso_id": "A3"})
    try:
        upd = {"update_id": 9, "message": {"chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT},
                                           "location": {"latitude": 19.181, "longitude": -96.216, "live_period": 900}}}
        r = cliente.portal.call(bot.procesar_update, _sim(), upd)
        assert "Cuello de botella" in r and f"#{cita['id']}" in r and "llegas ~" in r
    finally:
        cliente.post("/api/sim/eventos", json={"tipo": "reapertura", "acceso_id": "A3"})
        bot._en_vivo.clear()
