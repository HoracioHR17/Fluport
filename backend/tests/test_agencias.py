"""Agencias: reparto de camiones simulados, flota por agencia, filtros de la API, enlace del bot y contingencia."""
from collections import Counter
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.contracts.enums import EstadoCamion, Mundo, TipoCarga, TipoEventoSim
from app.contracts.schemas import EventoCreate
from app.messaging import bot_telegram as bot
from app.messaging import telegram
from app.publico.servicio import zonas
from tests.conftest import vaciar_tablas

TEL = "+522290007001"


# ───────────── Simulación (sin BD) ─────────────
def test_escenario_trae_agencias(esc):
    assert [a.id for a in esc.agencias] == ["AG01", "AG02", "AG03"]


def test_reparto_fijo_y_proporcional(esc):
    assert esc.agencia_de("T00-0001") == esc.agencia_de("T00-0001")  # determinista por id
    conteo = Counter(esc.agencia_de(f"T00-{i:04d}") for i in range(6000))
    total = sum(a.participacion for a in esc.agencias)
    for a in esc.agencias:
        assert abs(conteo[a.id] / 6000 - a.participacion / total) < 0.03


def test_snapshot_trae_agencia_y_flota(sim):
    sim.avanzar(6 * 60)  # 10:00: hay camiones en ruta y en fila
    mb = sim.snapshot().mundos[Mundo.B]
    assert mb.camiones and all(c.agencia_id in {"AG01", "AG02", "AG03"} for c in mb.camiones)
    assert set(mb.flota) == {"AG01", "AG02", "AG03"}
    # la flota cuenta todos los camiones activos, no solo los dibujados
    ms = sim.mundos[Mundo.B]
    en_fila = sum(1 for c in ms.camiones.values() if c.estado == EstadoCamion.en_fila)
    assert sum(f.en_fila for f in mb.flota.values()) == en_fila
    assert sum(f.atendidos for f in mb.flota.values()) == ms.atendidos


def test_cita_hereda_la_agencia_del_transportista(sim):
    sim.inyectar_cita(9001, "A1", sim.ts() + timedelta(hours=1), TipoCarga.contenedor_40, agencia_id="AG02")
    sim.inyectar_cita(9002, "A1", sim.ts() + timedelta(hours=1), TipoCarga.contenedor_40)
    assert sim.citas[9001].agencia_id == "AG02" and sim.citas[9002].agencia_id is None


def test_contingencia_publica(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.norte, payload={"duracion_h": 12}))
    z = {x.acceso_id: x for x in zonas(sim)}
    assert z["A2"].contingencia == "cerrada" and not z["A2"].abierto
    assert z["A1"].contingencia in {"normal", "lenta", "saturada"} and all(x.norte for x in z.values())


# ───────────── API y bot (PostgreSQL de prueba) ─────────────
@pytest.fixture(scope="module")
def cliente(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c


def _ts(c, horas: float) -> str:
    from datetime import datetime

    ahora = datetime.fromisoformat(c.get("/api/sim/estado").json()["ts_sim"])
    return (ahora + timedelta(hours=horas)).isoformat()


def test_listar_agencias(cliente):
    r = cliente.get("/api/agencias").json()
    assert [a["id"] for a in r] == ["AG01", "AG02", "AG03"] and r[0]["nombre"]


def test_cita_de_agencia_y_filtros(cliente):
    r = cliente.post("/api/citas", json={"telefono": TEL, "agencia_id": "AG01", "acceso_id": "A1",
                                         "ventana_inicio": _ts(cliente, 2), "ventana_fin": _ts(cliente, 2.5),
                                         "tipo_carga": "contenedor_40"})
    assert r.status_code == 201
    cita = r.json()
    ts = cliente.get("/api/agencias/AG01/transportistas").json()
    assert len(ts) == 1 and ts[0]["telefono_fin"] == "7001" and ts[0]["citas_activas"] == 1
    assert "telefono" not in ts[0]  # el número completo no se expone
    assert [c["id"] for c in cliente.get("/api/citas?agencia_id=AG01").json()] == [cita["id"]]
    assert cliente.get("/api/citas?agencia_id=AG02").json() == []
    assert cliente.get("/api/citas/resumen?agencia_id=AG01").json()["total"] == 1
    assert cliente.get("/api/citas/resumen?agencia_id=AG02").json()["total"] == 0
    assert cliente.get("/api/avisos?agencia_id=AG01").status_code == 200
    # el camión de la cita aparece en la simulación como de la agencia
    from app.sim.servicio import servicio

    assert servicio.sim.citas[cita["id"]].agencia_id == "AG01"


def test_agencia_inexistente(cliente):
    assert cliente.get("/api/agencias/XX99/transportistas").status_code == 404
    r = cliente.post("/api/citas", json={"telefono": "+522290007002", "agencia_id": "XX99", "acceso_id": "A1",
                                         "ventana_inicio": _ts(cliente, 2), "ventana_fin": _ts(cliente, 2.5),
                                         "tipo_carga": "contenedor_40"})
    assert r.status_code == 404


def _msg(texto=None, contacto=None, chat=888000222):
    m = {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}}
    if texto is not None:
        m["text"] = texto
    if contacto is not None:
        m["contact"] = contacto
    return {"update_id": 1, "message": m}


def test_enlace_de_agencia_en_el_bot(cliente, monkeypatch):
    from app.db.base import SessionLocal
    from app.sim.servicio import servicio

    async def falso(chat_id, texto, teclado=None):
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    sim, chat = servicio.sim, 888000222
    assert cliente.portal.call(bot.procesar_update, sim, _msg("/start AG02")) == bot.BIENVENIDA
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007003", "user_id": chat, "first_name": "Lupe"}))
    assert "Logística Sotavento" in r
    with SessionLocal() as db:
        assert bot.transportista_de_chat(db, chat).agencia_id == "AG02"
    # ya registrado: un enlace de otra agencia lo cambia de agencia; un código inválido no
    assert "Fletes Jarochos" in cliente.portal.call(bot.procesar_update, sim, _msg("/start ag03"))
    cliente.portal.call(bot.procesar_update, sim, _msg("/start NOEXISTE"))
    with SessionLocal() as db:
        assert bot.transportista_de_chat(db, chat).agencia_id == "AG03"
