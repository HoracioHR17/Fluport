"""Asistente (M4) con un LLM simulado: herramientas, permisos, historial y respaldo sin LLM."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modulos.mensajeria.asistente import agente as ag
from app.modulos.mensajeria.asistente.agente import (
    HERRAMIENTAS,
    Asistente,
    Herramientas,
    instrucciones,
)
from app.modulos.mensajeria.puertos import ErrorLLM
from app.nucleo.contracts.enums import Canal, OrigenCita
from app.nucleo.contracts.schemas import AsistenteRequest
from tests.conftest import vaciar_tablas


class LLMGuion:
    """LLM falso: devuelve turnos predefinidos y guarda lo que recibió."""

    def __init__(self, turnos):
        self.turnos, self.recibido = list(turnos), []

    async def generar(self, contenidos, sistema, herramientas):
        self.recibido.append({"contenidos": list(contenidos), "sistema": sistema, "herramientas": herramientas})
        siguiente = self.turnos.pop(0)
        return siguiente(contenidos) if callable(siguiente) else siguiente


def llamada(nombre, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": nombre, "args": args}}]}


def texto(t):
    return {"role": "model", "parts": [{"text": t}]}


# ───────────── Sin BD ─────────────
def test_declaraciones_de_herramientas():
    nombres = {h["name"] for h in HERRAMIENTAS}
    assert nombres == {"consultar_espera", "sugerir_horario", "crear_cita", "reprogramar_cita", "cancelar_cita", "mis_citas"}
    assert all(h["parameters"]["type"] == "object" for h in HERRAMIENTAS)


def test_instrucciones_incluyen_hora_y_casetas(sim):
    t = instrucciones(sim)
    assert "2026-11-12 04:00" in t and "Entronque Santa Fe" in t and "SIMULACIÓN" in t


def test_respaldo_sin_llm(sim):
    from app.nucleo.config import get_settings

    a = Asistente()
    assert get_settings().llm_api_key == "" and a.cliente is None
    r = a._sin_llm(sim)
    assert "Av. Rafael Cuervo" in r.respuesta and "Fluye" in r.respuesta


def test_herramienta_consultar_espera(sim):
    h = Herramientas(db=None, sim=sim, telefono="+522290000009", origen=OrigenCita.asistente)
    r = h.ejecutar("consultar_espera", {"acceso_id": "A2"})
    assert len(r["casetas"]) == 1 and r["casetas"][0]["acceso_id"] == "A2"


def test_herramienta_desconocida_y_datos_invalidos(sim):
    h = Herramientas(db=None, sim=sim, telefono="+522290000009", origen=OrigenCita.asistente)
    assert "error" in h.ejecutar("borrar_todo", {})
    assert "error" in h.ejecutar("sugerir_horario", {"desde": "ayer", "hasta": "x", "tipo_carga": "granel"})


def test_sugerir_horario_con_fecha_sin_zona(sim):
    h = Herramientas(db=None, sim=sim, telefono="+522290000009", origen=OrigenCita.asistente)
    r = h.ejecutar("sugerir_horario", {"desde": "2026-11-12T09:00", "hasta": "2026-11-12T12:00",
                                        "tipo_carga": "contenedor_40"})
    assert len(r["opciones"]) == 3 and all(o["inicio"].startswith("2026-11-12T") for o in r["opciones"])


# ───────────── Con PostgreSQL de prueba ─────────────
@pytest.fixture(scope="module")
def entorno(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app
    from app.modulos.simulacion.servicio import servicio

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c, servicio
    ag.asistente.usar_cliente(None)


def _manana(servicio, hora):
    t = servicio.sim.ts() + timedelta(days=1)
    return t.replace(hour=hora, minute=0).strftime("%Y-%m-%dT%H:%M")


def test_flujo_sugerir_y_agendar(entorno):
    c, servicio = entorno
    tel = "+5212290000001"
    llm = LLMGuion([
        llamada("sugerir_horario", desde=_manana(servicio, 8), hasta=_manana(servicio, 11), tipo_carga="contenedor_40"),
    ])
    ag.asistente.usar_cliente(llm)
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": tel,
                                               "texto": "llego mañana a las 9 con un contenedor de 40"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    # una sola llamada al LLM: la respuesta se redacta con plantilla
    assert len(llm.recibido) == 1 and llm.turnos == []
    assert cuerpo["respuesta"].startswith("Estas son las mejores opciones:") and "1. *" in cuerpo["respuesta"]
    assert cuerpo["acciones"][0]["herramienta"] == "sugerir_horario"
    opcion = cuerpo["acciones"][0]["resultado"]["opciones"][0]

    # segundo mensaje: el historial incluye el primer intercambio (con la respuesta de plantilla)
    llm2 = LLMGuion([
        llamada("crear_cita", acceso_id=opcion["acceso_id"], inicio=opcion["inicio"], tipo_carga="contenedor_40"),
    ])
    ag.asistente.usar_cliente(llm2)
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": tel, "texto": "la 1"})
    cuerpo = r.json()
    cita = cuerpo["acciones"][0]["resultado"]
    assert "cita_id" in cita and cita["inicio"] == opcion["inicio"]
    assert cuerpo["respuesta"].startswith("Listo ✅") and f"#{cita['cita_id']}" in cuerpo["respuesta"]
    previos = llm2.recibido[0]["contenidos"]
    assert previos[0]["parts"][0]["text"].startswith("llego mañana")
    assert previos[-2]["role"] == "model" and previos[-2]["parts"][0]["text"].startswith("Estas son")
    assert previos[-1]["parts"][0]["text"] == "la 1"
    guardada = c.get(f"/api/citas/{cita['cita_id']}").json()
    assert guardada["origen"] == "asistente" and guardada["estado"] == "agendada"
    assert cita["cita_id"] in servicio.sim.citas


def test_solo_sus_propias_citas(entorno):
    c, servicio = entorno
    ajena = c.post("/api/citas", json={"telefono": "+522290000077", "acceso_id": "A1",
                                       "ventana_inicio": _manana(servicio, 13) + ":00-06:00",
                                       "ventana_fin": _manana(servicio, 13) + ":30-06:00", "tipo_carga": "granel"}).json()
    ag.asistente.usar_cliente(LLMGuion([llamada("cancelar_cita", cita_id=ajena["id"]), texto("No pude.")]))
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": "+522290000001", "texto": "cancela"})
    assert "error" in r.json()["acciones"][0]["resultado"]
    assert r.json()["respuesta"] == "No pude."  # con error, el LLM redacta la explicación
    assert c.get(f"/api/citas/{ajena['id']}").json()["estado"] == "agendada"


def test_mis_citas_y_cancelar(entorno):
    c, _ = entorno
    tel = "+522290000001"
    ag.asistente.usar_cliente(LLMGuion([llamada("mis_citas")]))
    mias = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": tel, "texto": "mis citas"}).json()
    lista = mias["acciones"][0]["resultado"]["citas"]
    assert len(lista) == 1 and mias["respuesta"].startswith("Tus citas:")
    ag.asistente.usar_cliente(LLMGuion([llamada("cancelar_cita", cita_id=lista[0]["cita_id"])]))
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": tel, "texto": "cancélala"}).json()
    assert r["acciones"][0]["resultado"]["estado"] == "cancelada" and r["respuesta"].startswith("Cancelé")


def test_falla_del_llm_responde_con_respaldo(entorno):
    c, _ = entorno

    class Roto:
        async def generar(self, *a):
            raise ErrorLLM("caído")

    ag.asistente.usar_cliente(Roto())
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": "+522290000002", "texto": "hola"})
    assert r.status_code == 200 and "problema" in r.json()["respuesta"]


def test_limite_de_pasos(entorno):
    c, _ = entorno
    # herramientas con error obligan a volver al LLM; tras MAX_PASOS rondas se responde con un mensaje fijo
    ag.asistente.usar_cliente(LLMGuion([llamada("cancelar_cita", cita_id=999999)] * ag.MAX_PASOS))
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": "+522290000003", "texto": "?"})
    assert r.status_code == 200 and len(r.json()["acciones"]) == ag.MAX_PASOS


def test_telefono_invalido(entorno):
    c, _ = entorno
    r = c.post("/api/asistente/mensaje", json={"canal": "web", "remitente": "12", "texto": "hola"})
    assert r.status_code == 422


def test_cliente_gemini_formato(monkeypatch):
    """El cliente arma la petición REST con la clave en el encabezado y lee candidates[0].content."""
    import asyncio

    import httpx

    from app.modulos.mensajeria.adaptadores.gemini import ClienteGemini

    capturado = {}

    def manejador(request: httpx.Request):
        capturado["url"], capturado["clave"] = str(request.url), request.headers.get("x-goog-api-key")
        capturado["cuerpo"] = request.read()
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "hola"}]}}]})

    transporte = httpx.MockTransport(manejador)
    original = httpx.AsyncClient

    class ClientePrueba(original):
        def __init__(self, *a, **k):
            k["transport"] = transporte
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", ClientePrueba)
    r = asyncio.run(ClienteGemini("CLAVE", "gemini-3.6-flash").generar(
        [{"role": "user", "parts": [{"text": "hola"}]}], "sistema", HERRAMIENTAS))
    assert r["parts"][0]["text"] == "hola"
    assert "gemini-3.6-flash:generateContent" in capturado["url"] and capturado["clave"] == "CLAVE"
    assert b"functionDeclarations" in capturado["cuerpo"] and b"systemInstruction" in capturado["cuerpo"]
    assert b'"thinkingLevel":"low"' in capturado["cuerpo"].replace(b" ", b"")


def _cliente_con(monkeypatch, manejador):
    import httpx

    original = httpx.AsyncClient

    class ClientePrueba(original):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(manejador)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", ClientePrueba)


def test_respaldo_si_el_principal_esta_saturado(monkeypatch):
    import asyncio
    import json as _json

    import httpx

    from app.modulos.mensajeria.adaptadores.gemini import ClienteGemini

    vistos = []

    def manejador(request):
        cuerpo = _json.loads(request.read())
        vistos.append((str(request.url).split("/models/")[1].split(":")[0], cuerpo))
        if "principal" in str(request.url):
            return httpx.Response(503, text="alta demanda")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    _cliente_con(monkeypatch, manejador)
    cli = ClienteGemini("K", "principal", modelo_respaldo="respaldo")
    turnos = [{"role": "model", "parts": [{"functionCall": {"name": "x", "args": {}}, "thoughtSignature": "FIRMA"}]}]
    r = asyncio.run(cli.generar(turnos, "s", []))
    assert r["parts"][0]["text"] == "ok" and cli.ultimo_modelo == "respaldo"
    assert [m for m, _ in vistos] == ["principal", "respaldo"]
    assert "thoughtSignature" in str(vistos[0][1]) and "thoughtSignature" not in str(vistos[1][1])
    assert turnos[0]["parts"][0]["thoughtSignature"] == "FIRMA"  # el original no se modifica


def test_timeout_pasa_al_respaldo_y_luego_falla(monkeypatch):
    import asyncio

    import httpx
    import pytest as _pytest

    from app.modulos.mensajeria.adaptadores.gemini import ClienteGemini

    llamadas = []

    def manejador(request):
        llamadas.append(1)
        raise httpx.ReadTimeout("lento", request=request)

    _cliente_con(monkeypatch, manejador)
    with _pytest.raises(ErrorLLM, match="no respondió"):
        asyncio.run(ClienteGemini("K", "a", modelo_respaldo="b").generar([], "s", []))
    assert len(llamadas) == 2


def test_error_400_no_usa_respaldo(monkeypatch):
    import asyncio

    import httpx
    import pytest as _pytest

    from app.modulos.mensajeria.adaptadores.gemini import ClienteGemini

    llamadas = []

    def manejador(request):
        llamadas.append(1)
        return httpx.Response(400, text="petición inválida")

    _cliente_con(monkeypatch, manejador)
    with _pytest.raises(ErrorLLM, match="400"):
        asyncio.run(ClienteGemini("K", "a", modelo_respaldo="b").generar([], "s", []))
    assert len(llamadas) == 1


def test_plantillas(sim):
    from app.modulos.mensajeria.asistente.agente import redactar

    t = redactar("sugerir_horario", {"opciones": [{"acceso_id": "A2", "caseta": "Caseta Paso del Toro",
                                                   "inicio": "2026-11-12T09:00", "espera_estimada_min": 3.4}]}, sim)
    assert "1. *09:00* · Caseta Paso del Toro (A2) · espera ~3 min" in t and "jue 12/11" in t
    assert redactar("sugerir_horario", {"opciones": []}, sim) is None
    assert "cerrada" in redactar("consultar_espera", {"casetas": [{"nombre": "X", "semaforo": "rojo", "abierta": False,
                                                                   "espera_actual_min": 99, "mejor_hora": "20:00"}]}, sim)


def test_formato_chat():
    from app.modulos.mensajeria.asistente.agente import formato_chat

    assert formato_chat("## Opciones\n1. **07:30** - A1\n__nota__") == "Opciones\n1. *07:30* - A1\n_nota_"


def test_request_canal():
    assert AsistenteRequest(canal=Canal.telegram, remitente="x", texto="y").canal == "telegram"
    assert datetime  # noqa: B018


def test_canal_web_desactivado_por_defecto(entorno, monkeypatch):
    """Sin la bandera, nadie puede hablar con el asistente haciéndose pasar por otro teléfono."""
    from app.nucleo.config import get_settings

    monkeypatch.setattr(get_settings(), "asistente_web_activo", False)
    r = entorno[0].post("/api/asistente/mensaje", json={"canal": "web", "remitente": "+522290000001", "texto": "hola"})
    assert r.status_code == 404
