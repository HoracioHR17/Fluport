"""API completa con el simulador corriendo (sin PostgreSQL: la app debe funcionar igual)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_DB


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def test_salud(cliente):
    r = cliente.get("/api/salud").json()
    assert r["estado"] == "ok" and r["bd"] is bool(TEST_DB) and r["simulador"] == "corriendo"


def test_raiz_redirige_al_tablero(cliente):
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/operador/"


def test_accesos_y_rutas(cliente):
    accesos = cliente.get("/api/accesos").json()
    assert [a["id"] for a in accesos] == ["A1", "A2", "A3"]
    geo = cliente.get("/api/accesos/rutas").json()
    assert geo["type"] == "FeatureCollection"
    assert {f["geometry"]["type"] for f in geo["features"]} == {"Point", "LineString"}


def test_estado_por_mundo(cliente):
    for mundo in ("A", "B"):
        estado = cliente.get("/api/accesos/estado", params={"mundo": mundo}).json()
        assert len(estado) == 3 and all(e["semaforo"] in ("verde", "amarillo", "rojo") for e in estado)


def test_control_pausa_y_velocidad(cliente):
    assert cliente.post("/api/sim/control", json={"accion": "pause"}).json()["estado"] == "pausada"
    t1 = cliente.get("/api/sim/snapshot").json()["ts_sim"]
    time.sleep(1.3)
    assert cliente.get("/api/sim/snapshot").json()["ts_sim"] == t1
    assert cliente.post("/api/sim/control", json={"accion": "velocidad", "velocidad": 120}).json()["velocidad"] == 120
    assert cliente.post("/api/sim/control", json={"accion": "velocidad"}).status_code == 422
    assert cliente.post("/api/sim/control", json={"accion": "play"}).json()["estado"] == "corriendo"


def test_eventos(cliente):
    r = cliente.post("/api/sim/eventos", json={"tipo": "cierre_acceso", "acceso_id": "A3"})
    assert r.status_code == 201
    estado = {e["acceso_id"]: e for e in cliente.get("/api/accesos/estado").json()}
    assert estado["A3"]["estado"] == "cerrado" and estado["A3"]["semaforo"] == "rojo"
    assert cliente.post("/api/sim/eventos", json={"tipo": "reapertura", "acceso_id": "A3"}).status_code == 201
    assert cliente.post("/api/sim/eventos", json={"tipo": "cierre_acceso", "acceso_id": "ZZ"}).status_code == 422
    assert cliente.post("/api/sim/eventos", json={"tipo": "inventado"}).status_code == 422


def test_kpis(cliente):
    k = cliente.get("/api/sim/kpis").json()
    assert set(k) == {"ts_sim", "A", "B", "comparacion"}


def test_pronostico(cliente):
    todos = cliente.get("/api/pronostico").json()
    assert len(todos) == 3 and all(len(p["franjas"]) == 24 for p in todos)
    uno = cliente.get("/api/pronostico", params={"acceso_id": "A2", "horas": 2}).json()
    assert len(uno) == 1 and len(uno[0]["franjas"]) == 4
    assert cliente.get("/api/pronostico", params={"acceso_id": "ZZ"}).status_code == 404
    assert "version" in cliente.get("/api/pronostico/modelo").json()


def test_websocket_snapshot_inicial_y_eventos(cliente):
    with cliente.websocket_connect("/ws/sim") as ws:
        m = json.loads(ws.receive_text())
        assert m["tipo"] == "snapshot" and m["data"]["etiqueta"] == "SIMULACIÓN"
        cliente.post("/api/sim/eventos", json={"tipo": "personalizado", "payload": {"x": 1}})
        tipos = {json.loads(ws.receive_text())["tipo"] for _ in range(4)}
        assert "evento" in tipos


def test_reset_cambia_semilla(cliente):
    r = cliente.post("/api/sim/control", json={"accion": "reset", "semilla": 9}).json()
    assert r["semilla"] == 9 and r["estado"] == "corriendo"


def test_webhook_whatsapp_verificacion(cliente):
    ok = cliente.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "fluport-verify",
                                                  "hub.challenge": "42"})
    assert ok.text == "42"
    mal = cliente.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                                   "hub.challenge": "42"})
    assert mal.status_code == 403
