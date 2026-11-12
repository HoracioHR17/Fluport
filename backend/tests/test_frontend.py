"""Frontend: las páginas y sus archivos estáticos se sirven desde la misma app (sin build ni npm)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("ruta,texto", [
    ("/agencia/", 'data-vista="agencia"'),
    ("/demo/", 'data-vista="demo"'),
    ("/publico/", "¿Cómo están las entradas al puerto?"),
])
def test_paginas(cliente, ruta, texto):
    r = cliente.get(ruta)
    assert r.status_code == 200 and texto in r.text and "SIMULACIÓN" in r.text


@pytest.mark.parametrize("ruta", [
    "/static/css/tokens.css", "/static/css/app.css", "/static/js/comun.js", "/static/js/tablero.js",
    "/static/js/publico.js", "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
    "/static/favicon.svg", "/static/vendor/qrcode/qrcode.js",
])
def test_estaticos(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_paginas_solo_usan_recursos_locales(cliente):
    """Ninguna página carga scripts o estilos de un CDN (funciona sin internet, salvo los mosaicos del mapa)."""
    for ruta in ("/agencia/", "/demo/", "/publico/"):
        html = cliente.get(ruta).text
        assert 'src="http' not in html and 'href="http' not in html


def test_operador_redirige_a_agencia(cliente):
    r = cliente.get("/operador/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/agencia/"


def test_publico_invita_al_bot(cliente):
    html = cliente.get("/publico/").text
    assert 'id="enlace-bot"' in html and "qrcode.js" in html
