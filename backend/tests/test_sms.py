"""Avisos por SMS para transportistas sin smartphone (giro del reto)."""
import asyncio

import pytest

from app.modulos.mensajeria.dominio.sms import LIMITE_SMS, normalizar_sms, sms


def test_normalizar_quita_acentos_enie_y_emojis():
    assert normalizar_sms("⏰ Señor, *cita* en Caseta Peñón: ¿llegarás?") == "Senor, cita en Caseta Penon: llegaras?"


def test_normalizar_una_linea_y_160_caracteres():
    texto = normalizar_sms("línea uno\nlínea dos " + "palabra " * 60)
    assert "\n" not in texto and len(texto) <= LIMITE_SMS and texto.endswith("...")


def test_sms_es_ascii_y_lleva_prefijo():
    t = sms("Cita #12 08:40 en San Julián · espera ~15 min")
    assert t.startswith("FLUPORT: ") and t.isascii() and len(t) <= LIMITE_SMS


def test_adaptador_sms_no_lanza_si_no_esta_configurado():
    from app.modulos.mensajeria.adaptadores.sms import SmsAdapter

    ok, detalle = asyncio.run(SmsAdapter().enviar("+522291234567", "hola"))
    assert not ok and "no está configurado" in detalle


def test_adaptador_sms_android(monkeypatch):
    """Con el gateway configurado envía el JSON esperado, ya normalizado a GSM-7."""
    import httpx

    from app.modulos.mensajeria.adaptadores import sms as adaptador
    from app.nucleo.config import get_settings

    s = get_settings()
    for k, v in {"sms_proveedor": "android", "sms_url": "http://celular:8080/message", "sms_usuario": "u",
                 "sms_clave": "c"}.items():
        monkeypatch.setattr(s, k, v)
    vistos = []

    def responder(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(202, json={"id": "abc"})

    real = httpx.AsyncClient
    monkeypatch.setattr(adaptador.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(responder), **kw))
    ok, detalle = asyncio.run(adaptador.enviar("+522291234567", "Cita en Peñón ⏰"))
    assert ok and detalle == "abc"
    import json

    cuerpo = json.loads(vistos[0].content)
    assert cuerpo == {"message": "Cita en Penon", "phoneNumbers": ["+522291234567"]}


def test_adaptador_sms_error_de_red_no_lanza(monkeypatch):
    import httpx

    from app.modulos.mensajeria.adaptadores import sms as adaptador
    from app.nucleo.config import get_settings

    s = get_settings()
    for k, v in {"sms_proveedor": "android", "sms_url": "http://celular:8080/message", "sms_usuario": "u",
                 "sms_clave": "c"}.items():
        monkeypatch.setattr(s, k, v)

    def caido(req):
        raise httpx.ConnectError("sin red")

    real = httpx.AsyncClient
    monkeypatch.setattr(adaptador.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(caido), **kw))
    ok, detalle = asyncio.run(adaptador.enviar("+522291234567", "hola"))
    assert not ok and "sin conexión" in detalle


def test_aviso_sms_usa_telefono_y_texto_corto():
    from app.modulos.mensajeria.dominio.avisos import AvisoNuevo

    a = AvisoNuevo(1, 2, "+522291234567", "cita_asignada", "*Nueva cita* ⏰", 999, "sms", sms("Cita #1"))
    assert a.destino == "+522291234567" and a.texto == "FLUPORT: Cita #1"
    t = AvisoNuevo(1, 2, "+522291234567", "cita_asignada", "*Nueva cita*", 999)
    assert t.destino == 999 and t.texto == "*Nueva cita*"


@pytest.mark.parametrize("entrada,esperado", [("229 123 4567", "+522291234567"), ("+52 1 229 123 4567", "+522291234567"),
                                               ("+52 229 123 4567", "+522291234567")])
def test_telefono_nacional_se_guarda_en_e164(entrada, esperado):
    from app.modulos.citas.servicio import normalizar_telefono

    assert normalizar_telefono(entrada) == esperado


def test_adaptador_sms_vonage(monkeypatch):
    """Vonage: envía el número sin "+" y toma el resultado de messages[0].status."""
    import httpx
    from urllib.parse import parse_qs

    from app.modulos.mensajeria.adaptadores import sms as adaptador
    from app.nucleo.config import get_settings

    s = get_settings()
    for k, v in {"sms_proveedor": "vonage", "sms_usuario": "key", "sms_clave": "secret", "sms_remitente": ""}.items():
        monkeypatch.setattr(s, k, v)
    vistos, respuesta = [], {"messages": [{"status": "0", "message-id": "m1"}]}

    def responder(req: httpx.Request) -> httpx.Response:
        vistos.append(parse_qs(req.content.decode()))
        return httpx.Response(200, json=respuesta)

    real = httpx.AsyncClient
    monkeypatch.setattr(adaptador.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(responder), **kw))
    assert asyncio.run(adaptador.enviar("+522291234567", "Cita")) == (True, "m1")
    assert vistos[0]["to"] == ["522291234567"] and vistos[0]["from"] == ["Fluport"]
    respuesta = {"messages": [{"status": "29", "error-text": "Non White-listed Destination - rejected"}]}
    ok, detalle = asyncio.run(adaptador.enviar("+522291234567", "Cita"))
    assert not ok and "29" in detalle and "White-listed" in detalle


def test_boton_enviar_en_volcado_de_pantalla():
    from app.modulos.mensajeria.adaptadores.sms import boton_enviar

    xml = ('<hierarchy><node text="Hola" resource-id="com.app:id/compose" bounds="[0,1800][900,1900]" enabled="true"/>'
           '<node text="" content-desc="Enviar SMS" resource-id="com.app:id/send_button" enabled="true" '
           'bounds="[950,1800][1050,1900]"/></hierarchy>')
    assert boton_enviar(xml) == (1000, 1850)
    assert boton_enviar("<hierarchy/>") is None
