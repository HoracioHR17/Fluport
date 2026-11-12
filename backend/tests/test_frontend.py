"""Frontend: las páginas y sus archivos estáticos se sirven desde la misma app (sin build ni npm)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("ruta,texto", [
    ("/agencia/", 'data-pantalla="resumen"'),
    ("/agencia/flota/", 'data-pantalla="flota"'),
    ("/agencia/citas/", 'data-pantalla="citas"'),
    ("/agencia/transportistas/", 'data-pantalla="transportistas"'),
    ("/agencia/avisos/", 'data-pantalla="avisos"'),
    ("/demo/", 'data-vista="demo"'),
    ("/publico/", "¿Cómo están las entradas al puerto?"),
])
def test_paginas(cliente, ruta, texto):
    r = cliente.get(ruta)
    assert r.status_code == 200 and texto in r.text and 'id="etiqueta"' not in r.text  # sin etiqueta SIMULACIÓN


@pytest.mark.parametrize("ruta", [
    "/static/css/tokens.css", "/static/css/app.css", "/static/js/comun.js", "/static/js/demo.js",
    "/static/js/publico.js", "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
    "/static/favicon.svg", "/static/vendor/qrcode/qrcode.js", "/static/js/agencia.js", "/static/css/ui.css",
    "/static/js/graficas.js",
])
def test_estaticos(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_paginas_solo_usan_recursos_locales(cliente):
    """Ninguna página carga scripts o estilos de un CDN (funciona sin internet, salvo los mosaicos del mapa)."""
    for ruta in ("/agencia/", "/agencia/flota/", "/agencia/citas/", "/agencia/transportistas/", "/agencia/avisos/", "/demo/", "/publico/"):
        html = cliente.get(ruta).text
        assert 'src="http' not in html and 'href="http' not in html


def test_operador_redirige_a_agencia(cliente):
    r = cliente.get("/operador/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/agencia/"


def test_publico_invita_al_bot(cliente):
    html = cliente.get("/publico/").text
    assert 'id="enlace-bot"' in html and "qrcode.js" in html


def test_mapas_limitados_al_puerto():
    """Los mapas usan el mapa común, que no deja salir de la zona del puerto de Veracruz."""
    from pathlib import Path

    js = Path(__file__).resolve().parents[2] / "frontend" / "static" / "js"
    graficas = (js / "graficas.js").read_text(encoding="utf-8")
    assert "maxBounds: lim" in graficas and "maxBoundsViscosity: 1" in graficas and "setMinZoom" in graficas
    for f in ("publico.js", "agencia.js", "demo.js"):
        codigo = (js / f).read_text(encoding="utf-8")
        assert "F.mapaPuerto(" in codigo and "L.map(" not in codigo, f


def test_paginas_piden_estaticos_con_version(cliente):
    """Las páginas agregan ?v=<huella> a sus CSS y JS para que la caché nunca sirva una versión vieja."""
    import re

    r = cliente.get("/publico/")
    assert r.headers["cache-control"] == "no-cache"
    assert re.search(r'src="/static/js/publico\.js\?v=[0-9a-f]{10}"', r.text)
    assert re.search(r'href="/static/css/ui\.css\?v=[0-9a-f]{10}"', r.text)
    assert cliente.get("/static/js/publico.js?v=x").status_code == 200


def test_versionar_no_toca_otros_recursos():
    from app.main import versionar

    html = '<link href="/static/favicon.svg"><script src="/static/js/a.js"></script>'
    assert versionar(html, "abc") == '<link href="/static/favicon.svg"><script src="/static/js/a.js?v=abc"></script>'
