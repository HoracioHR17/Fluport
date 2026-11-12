"""Agencias: reparto de camiones simulados, flota por agencia, filtros de la API, enlace del bot y contingencia."""
from collections import Counter
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.modulos.mensajeria import bot_telegram as bot
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.publico.servicio import zonas
from app.nucleo.contracts.enums import EstadoCamion, Mundo, TipoCarga, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate
from tests.conftest import vaciar_tablas

TEL = "+522290007001"


# ───────────── Simulación (sin BD) ─────────────
def test_escenario_trae_una_sola_agencia(esc):
    assert [(a.id, a.nombre) for a in esc.agencias] == [("AG01", "Tiburones Ecover Logistics")]


def test_reparto_fijo_y_proporcional(esc):
    assert esc.agencia_de("T00-0001") == esc.agencia_de("T00-0001")  # determinista por id
    conteo = Counter(esc.agencia_de(f"T00-{i:04d}") for i in range(12000))
    parte = esc.agencias[0].participacion
    assert abs(conteo["AG01"] / 12000 - parte) < 0.03
    assert set(conteo) == {"AG01", None}  # el resto son camiones de otros transportistas


def test_snapshot_trae_agencia_y_flota(sim):
    sim.avanzar(6 * 60)  # 10:00: hay camiones en ruta y en fila
    mb = sim.snapshot().mundos[Mundo.B]
    assert mb.camiones and all(c.agencia_id in {"AG01", None} for c in mb.camiones)
    assert set(mb.flota) == {"AG01"}
    # la flota cuenta todos los camiones activos, no solo los dibujados
    ms = sim.mundos[Mundo.B]
    en_fila = sum(1 for c in ms.camiones.values() if c.estado == EstadoCamion.en_fila)
    assert sum(f.en_fila for f in mb.flota.values()) == en_fila
    assert sum(f.atendidos for f in mb.flota.values()) == ms.atendidos


def test_cita_hereda_la_agencia_del_transportista(sim):
    sim.inyectar_cita(9001, "A1", sim.ts() + timedelta(hours=1), TipoCarga.contenedor_40, agencia_id="AG01")
    sim.inyectar_cita(9002, "A1", sim.ts() + timedelta(hours=1), TipoCarga.contenedor_40)
    assert sim.citas[9001].agencia_id == "AG01" and sim.citas[9002].agencia_id is None


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
    assert [(a["id"], a["nombre"]) for a in r] == [("AG01", "Tiburones Ecover Logistics")]


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
    assert cliente.get("/api/citas?agencia_id=XX99").json() == []
    assert cliente.get("/api/citas/resumen?agencia_id=AG01").json()["total"] == 1
    assert cliente.get("/api/citas/resumen?agencia_id=XX99").json()["total"] == 0
    assert cliente.get("/api/avisos?agencia_id=AG01").status_code == 200
    # el camión de la cita aparece en la simulación como de la agencia
    from app.modulos.simulacion.servicio import servicio

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


def test_alta_de_transportista(cliente):
    r = cliente.post("/api/agencias/AG01/transportistas",
                     json={"alias": "Lupe Ramos", "telefono": "+522290007003", "placas": "xkl-45-21"})
    assert r.status_code == 201 and r.json()["placas"] == "XKL-45-21" and r.json()["telegram"] is False
    # el mismo número dado de alta otra vez actualiza al transportista (no lo duplica)
    otra = cliente.post("/api/agencias/AG01/transportistas", json={"alias": "Lupe Ramos", "telefono": "+522290007003",
                                                                   "placas": "xkl-45-21"})
    assert otra.status_code == 201 and otra.json()["id"] == r.json()["id"]
    assert cliente.post("/api/agencias/XX99/transportistas", json={"alias": "Xavier", "telefono": "+522290007004"}).status_code == 404


def test_bot_solo_vincula_numeros_dados_de_alta(cliente, monkeypatch):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.db.base import SessionLocal

    async def falso(chat_id, texto, teclado=None):
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    sim = servicio.sim
    # un número sin alta no se vincula: con una sola agencia, su solicitud va directo a ella
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007999", "user_id": 888000333}, chat=888000333))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Tiburones Ecover Logistics")
    with SessionLocal() as db:
        assert bot.transportista_de_chat(db, 888000333) is None
    # el que dio de alta la agencia se vincula a ella
    chat = 888000222
    assert cliente.portal.call(bot.procesar_update, sim, _msg("/start AG01")) == bot.BIENVENIDA
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007003", "user_id": chat, "first_name": "Lupe"}))
    assert "Tiburones Ecover Logistics" in r
    with SessionLocal() as db:
        t = bot.transportista_de_chat(db, chat)
        assert t.agencia_id == "AG01" and t.alias == "Lupe Ramos"


def test_cita_asignada_es_obligatoria_y_solo_se_avisa(cliente, monkeypatch):
    """La agencia asigna la cita: el chofer recibe el aviso, no se le pide SÍ / NO y queda en firme."""
    from app.modulos.mensajeria.servicio import notificar_asignacion
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.db.base import SessionLocal

    enviados = []

    async def falso(chat_id, texto, teclado=None):
        enviados.append((chat_id, texto))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    from app.nucleo.config import get_settings

    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    sim, chat = servicio.sim, 888000222
    with SessionLocal() as db:
        tid = bot.transportista_de_chat(db, chat).id

    r = cliente.post("/api/citas", json={"transportista_id": tid, "acceso_id": "A1", "origen": "web",
                                         "ventana_inicio": _ts(cliente, 3), "ventana_fin": _ts(cliente, 3.5),
                                         "tipo_carga": "contenedor_40"})
    assert r.status_code == 201
    cita = r.json()
    assert cita["confirmada_en"] is not None  # obligatoria desde que se asigna
    cliente.portal.call(notificar_asignacion, sim, cita["id"], lambda _: None)
    assert enviados[-1][0] == chat and "Nueva cita" in enviados[-1][1] and "SÍ" not in enviados[-1][1]
    # la agencia la ve asignada
    citas = {c["id"]: c for c in cliente.get("/api/citas?agencia_id=AG01").json()}
    assert citas[cita["id"]]["confirmada_en"] is not None


def test_buscar_agencia_por_nombre_o_codigo(cliente):
    from app.modulos.agencias.servicio import agencia_unica, buscar_agencia
    from app.nucleo.db.base import SessionLocal

    with SessionLocal() as db:
        assert buscar_agencia(db, "ag01").id == "AG01"
        assert buscar_agencia(db, "Tiburones Ecover Logistics").id == "AG01"
        assert buscar_agencia(db, "tiburones").id == "AG01"
        assert buscar_agencia(db, "Transportes Pérez") is None
        assert agencia_unica(db).id == "AG01"


def test_solicitud_de_alta_desde_el_bot(cliente, monkeypatch):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.config import get_settings
    from app.nucleo.db.base import SessionLocal

    enviados = []

    async def falso(chat_id, texto, teclado=None):
        enviados.append((chat_id, texto, teclado))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    sim, chat = servicio.sim, 888000444
    contacto = {"phone_number": "5212290007444", "user_id": chat, "first_name": "Toño"}

    # sin alta: con una sola agencia no se pregunta cuál; la solicitud va directo a ella
    r = cliente.portal.call(bot.procesar_update, sim, _msg(contacto=contacto, chat=chat))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Tiburones Ecover Logistics")
    r = cliente.portal.call(bot.procesar_update, sim, _msg("¿ya?", chat=chat))
    assert "sigue en revisión" in r

    # la agencia la ve en su panel
    pend = cliente.get("/api/agencias/AG01/solicitudes").json()
    toño = [p for p in pend if p["telefono_fin"] == "7444"]
    assert [(p["nombre"], p["telefono_fin"]) for p in toño] == [("Toño", "7444")]
    sid = toño[0]["id"]
    assert cliente.post(f"/api/agencias/XX99/solicitudes/{sid}/aprobar").status_code == 404

    # aprueba: queda dado de alta, ligado al chat, y el bot le avisa
    r = cliente.post(f"/api/agencias/AG01/solicitudes/{sid}/aprobar", json={"placas": "abc-12-34"})
    assert r.status_code == 200 and r.json()["telegram"] is True and r.json()["placas"] == "ABC-12-34"
    assert cliente.post(f"/api/agencias/AG01/solicitudes/{sid}/aprobar").status_code == 409
    with SessionLocal() as db:
        t = bot.transportista_de_chat(db, chat)
        assert t.agencia_id == "AG01" and t.alias == "Toño"
    assert any(c == chat and "aprobó tu alta" in txt for c, txt, _ in enviados)
    assert all(p["telefono_fin"] != "7444" for p in cliente.get("/api/agencias/AG01/solicitudes").json())


def test_solicitud_se_puede_rechazar_y_volver_a_enviar(cliente, monkeypatch):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.config import get_settings

    enviados = []

    async def falso(chat_id, texto, teclado=None):
        enviados.append((chat_id, texto))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    sim, chat = servicio.sim, 888000555
    cliente.portal.call(bot.procesar_update, sim, _msg("/start AG01", chat=chat))
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007555", "user_id": chat}, chat=chat))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Tiburones Ecover Logistics")
    sid = [p for p in cliente.get("/api/agencias/AG01/solicitudes").json() if p["telefono_fin"] == "7555"][0]["id"]
    r = cliente.post(f"/api/agencias/AG01/solicitudes/{sid}/rechazar")
    assert r.status_code == 200 and r.json()["estado"] == "rechazada"
    assert any(c == chat and "no aprobó" in txt for c, txt in enviados)
    # puede volver a compartir su número y enviar una nueva solicitud
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007555", "user_id": chat}, chat=chat))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Tiburones Ecover Logistics")
