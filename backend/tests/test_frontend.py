"""Frontend: las páginas y sus archivos estáticos se sirven desde la misma app (sin build ni npm)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("ruta,texto", [
    ("/operador/", "Tablero del operador"),
    ("/publico/", "¿Cómo están las casetas?"),
])
def test_paginas(cliente, ruta, texto):
    r = cliente.get(ruta)
    assert r.status_code == 200 and texto in r.text and "SIMULACIÓN" in r.text


@pytest.mark.parametrize("ruta", [
    "/static/css/tokens.css", "/static/css/app.css", "/static/js/comun.js", "/static/js/operador.js",
    "/static/js/publico.js", "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
    "/static/favicon.svg",
])
def test_estaticos(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_paginas_solo_usan_recursos_locales(cliente):
    """Ninguna página carga scripts o estilos de un CDN (funciona sin internet, salvo los mosaicos del mapa)."""
    for ruta in ("/operador/", "/publico/"):
        html = cliente.get(ruta).text
        assert 'src="http' not in html and 'href="http' not in html
