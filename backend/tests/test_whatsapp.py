"""WhatsApp con Twilio (M5): firma, webhook, envío y avisos proactivos (Twilio y Gemini simulados)."""
import asyncio
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.modulos.mensajeria.adaptadores import twilio
from app.modulos.mensajeria.asistente import agente as ag
from app.modulos.mensajeria.dominio.avisos import CitaActiva, revisar
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import EstadoCita, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate
from tests.conftest import vaciar_tablas

TOKEN = "token-de-prueba"
URL = "https://fluport.ejemplo.com/webhook/whatsapp"


@pytest.fixture
def twilio_conf(monkeypatch):
    cfg = get_settings()
    for k, v in {"twilio_account_sid": "AC123", "twilio_auth_token": TOKEN,
                 "twilio_whatsapp_from": "whatsapp:+14155238886", "twilio_webhook_url": URL}.items():
        monkeypatch.setattr(cfg, k, v)
    return cfg


@pytest.fixture
def envios(monkeypatch):
    """Sustituye la API de Twilio: guarda (telefono, texto) en una lista."""
    lista = []

    async def falso(telefono, texto):
        lista.append((telefono, texto))
        return True, "SM123"

    monkeypatch.setattr(twilio, "enviar", falso)
    import app.modulos.mensajeria.servicio as ms
    monkeypatch.setattr(ms.twilio, "enviar", falso)
    return lista


# ───────────── Firma y utilidades ─────────────
def test_firma_ida_y_vuelta():
    params = {"From": "whatsapp:+5212290000001", "Body": "hola", "To": "whatsapp:+14155238886"}
    f = twilio.firma(URL, params, TOKEN)
    assert twilio.firma_valida(URL, params, f, TOKEN)
    assert not twilio.firma_valida(URL, {**params, "Body": "otra"}, f, TOKEN)
    assert not twilio.firma_valida(URL + "?x=1", params, f, TOKEN)
    assert not twilio.firma_valida(URL, params, None, TOKEN)


def test_firma_vector_conocido():
    # cálculo independiente: URL + parámetros ordenados (nombre+valor), HMAC-SHA1, Base64
    import base64
    import hashlib
    import hmac

    datos = URL + "Bodyhola" + "Fromwhatsapp:+1"
    esperada = base64.b64encode(hmac.new(TOKEN.encode(), datos.encode(), hashlib.sha1).digest()).decode()
    assert twilio.firma(URL, {"From": "whatsapp:+1", "Body": "hola"}, TOKEN) == esperada


def test_formulario_y_direccion():
    assert twilio.parsear_formulario(b"Body=hola+mundo&From=whatsapp%3A%2B521") == {"Body": "hola mundo", "From": "whatsapp:+521"}
    assert twilio.a_whatsapp("+522291234567") == "whatsapp:+5212291234567"
    twilio.recordar_direccion("+522291234567", "whatsapp:+522291234567")
    assert twilio.a_whatsapp("+522291234567") == "whatsapp:+522291234567"
    twilio._direcciones.clear()


def test_enviar_sin_configuracion():
    assert asyncio.run(twilio.enviar("+522290000001", "hola")) == (False, "Twilio no está configurado")


def test_enviar_llama_a_la_api_de_twilio(twilio_conf, monkeypatch):
    vistos = {}

    def manejador(request):
        vistos["url"], vistos["auth"], vistos["cuerpo"] = str(request.url), request.headers["authorization"], request.read()
        return httpx.Response(201, json={"sid": "SM999"})

    original = httpx.AsyncClient

    class ClientePrueba(original):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(manejador)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", ClientePrueba)
    assert asyncio.run(twilio.enviar("+522290000001", "hola")) == (True, "SM999")
    assert vistos["url"].endswith("/Accounts/AC123/Messages.json") and vistos["auth"].startswith("Basic ")
    assert b"To=whatsapp%3A%2B5212290000001" in vistos["cuerpo"] and b"Body=hola" in vistos["cuerpo"]


# ───────────── Avisos (sin BD) ─────────────
def _cita(sim, minutos, acceso="A2", cid=1, estado=EstadoCita.agendada):
    return CitaActiva(cid, 1, "+522290000001", acceso, sim.ts() + timedelta(minutes=minutos), "granel", estado)


def test_aviso_de_turno(sim):
    sim.avanzar(60)
    avisos = revisar(sim, [_cita(sim, 20)], set())
    assert [a.tipo for a in avisos] == ["turno_30min"] and "En 20 min es tu turno" in avisos[0].mensaje
    assert revisar(sim, [_cita(sim, 20)], {(1, "turno_30min")}) == []  # no se repite
    assert revisar(sim, [_cita(sim, 90)], set()) == []  # aún falta


def test_aviso_por_cierre_con_alternativa(sim):
    sim.avanzar(60)
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    avisos = revisar(sim, [_cita(sim, 120)], set())
    assert [a.tipo for a in avisos] == ["saturacion"]
    m = avisos[0].mensaje
    assert "cerrada" in m and "Responde *SÍ*" in m and "Paso del Toro" in m.split("¿")[0]
    assert "Paso del Toro" not in m.split("¿")[1]  # la alternativa es otra caseta


def test_sin_aviso_si_esta_en_ruta_o_fluye(sim):
    sim.avanzar(60)
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    assert revisar(sim, [_cita(sim, 120, estado=EstadoCita.en_ruta)], set()) == []
    assert revisar(sim, [_cita(sim, 120, acceso="A1")], set()) == []


# ───────────── Webhook y ciclo con PostgreSQL de prueba ─────────────
@pytest.fixture(scope="module")
def cliente(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c
    ag.asistente.usar_cliente(None)


class LLM:
    def __init__(self, turnos):
        self.turnos = list(turnos)

    async def generar(self, *a):
        return self.turnos.pop(0)


def _post(c, params, firma=None):
    cuerpo = urlencode(params)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if firma is not False:
        headers["X-Twilio-Signature"] = firma or twilio.firma(URL, params, TOKEN)
    return c.post("/webhook/whatsapp", content=cuerpo, headers=headers)


def test_webhook_rechaza_firma_invalida(cliente, twilio_conf):
    r = _post(cliente, {"From": "whatsapp:+5212290000001", "Body": "hola"}, firma="malafirma")
    assert r.status_code == 403
    assert _post(cliente, {"From": "whatsapp:+5212290000001", "Body": "hola"}, firma=False).status_code == 403


def test_webhook_responde_por_whatsapp(cliente, twilio_conf, envios):
    import time

    ag.asistente.usar_cliente(LLM([{"role": "model", "parts": [{"functionCall": {"name": "consultar_espera", "args": {}}}]}]))
    r = _post(cliente, {"From": "whatsapp:+5212290000001", "Body": "¿cómo está la fila?", "To": "whatsapp:+14155238886"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml") and "<Response>" in r.text
    for _ in range(50):  # la respuesta se envía en segundo plano
        if envios:
            break
        time.sleep(0.05)
    assert envios and envios[0][0] == "+522290000001" and envios[0][1].startswith("Así están las casetas")


def test_ciclo_de_avisos_guarda_publica_y_envia(cliente, twilio_conf, envios):
    from app.modulos.mensajeria.servicio import ciclo_avisos
    from app.modulos.simulacion.servicio import servicio

    sim = servicio.sim
    inicio = sim.ts() + timedelta(minutes=20)
    cita = cliente.post("/api/citas", json={"telefono": "+522290000005", "acceso_id": "A1",
                                            "ventana_inicio": inicio.isoformat(),
                                            "ventana_fin": (inicio + timedelta(minutes=30)).isoformat(),
                                            "tipo_carga": "granel"}).json()
    publicados = []
    avisos = cliente.portal.call(ciclo_avisos, sim, publicados.append)
    assert [a.tipo for a in avisos] == ["turno_30min"] and avisos[0].cita_id == cita["id"]
    assert '"tipo":"aviso"' in publicados[0]
    assert envios[-1][0] == "+522290000005"
    assert cliente.portal.call(ciclo_avisos, sim, publicados.append) == []  # no se repite
    lista = cliente.get("/api/avisos").json()
    assert lista[0]["tipo"] == "turno_30min"
    # el aviso quedó en el historial del asistente (para responder "SÍ" con contexto)
    from app.modulos.mensajeria.asistente.agente import cargar_historial
    from app.nucleo.contracts.enums import Canal
    from app.nucleo.db.base import SessionLocal

    with SessionLocal() as db:
        from app.nucleo.db.models import MensajeAsistente
        assert db.query(MensajeAsistente).filter_by(remitente="+522290000005", rol="model").count() == 1
        historial = cargar_historial(db, Canal.whatsapp, "+522290000005")
        assert historial[0]["role"] == "user" and "aviso automático" in historial[0]["parts"][0]["text"]
        assert historial[1]["parts"][0]["text"] == avisos[0].mensaje


def test_enlace_wa_me(cliente, twilio_conf):
    r = cliente.get("/api/whatsapp/enlace").json()
    assert r["enlace"].startswith("https://wa.me/14155238886?text=") and r["configurado"]


def test_si_a_un_aviso_reprograma(cliente, twilio_conf, envios):
    """Flujo completo: aviso de cierre con alternativa → el transportista responde SÍ → cita reprogramada."""
    import time

    from app.modulos.mensajeria.servicio import ciclo_avisos
    from app.modulos.simulacion.servicio import servicio

    sim = servicio.sim
    inicio = (sim.ts() + timedelta(hours=2)).replace(second=0, microsecond=0)
    inicio = inicio.replace(minute=0 if inicio.minute < 30 else 30)
    tel = "+522290000006"
    cita = cliente.post("/api/citas", json={"telefono": tel, "acceso_id": "A3", "ventana_inicio": inicio.isoformat(),
                                            "ventana_fin": (inicio + timedelta(minutes=30)).isoformat(),
                                            "tipo_carga": "granel"}).json()
    cliente.post("/api/sim/eventos", json={"tipo": "cierre_acceso", "acceso_id": "A3"})
    avisos = cliente.portal.call(ciclo_avisos, sim, lambda _: None)
    aviso = next(a for a in avisos if a.cita_id == cita["id"])
    assert aviso.tipo == "saturacion" and "SÍ" in aviso.mensaje

    recibido = {}

    class LLMQueVeElAviso:
        async def generar(self, contenidos, sistema, herramientas):
            recibido["contenidos"] = contenidos
            return {"role": "model", "parts": [{"functionCall": {"name": "reprogramar_cita", "args": {
                "cita_id": cita["id"], "inicio": (inicio + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
                "acceso_id": "A1"}}}]}

    ag.asistente.usar_cliente(LLMQueVeElAviso())
    envios.clear()
    _post(cliente, {"From": "whatsapp:+5212290000006", "Body": "SÍ"})
    for _ in range(50):
        if envios:
            break
        time.sleep(0.05)
    textos = [p.get("text", "") for t in recibido["contenidos"] for p in t["parts"]]
    assert aviso.mensaje in textos and textos[-1] == "SÍ"  # Gemini recibió el aviso como contexto
    assert envios and envios[0][1].startswith("Cambié tu cita")
    assert cliente.get(f"/api/citas/{cita['id']}").json()["estado"] == "reprogramada"
    cliente.post("/api/sim/eventos", json={"tipo": "reapertura", "acceso_id": "A3"})
