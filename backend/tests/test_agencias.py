"""Agencias: reparto de camiones simulados, flota por agencia, filtros de la API, enlace del bot y contingencia."""
from collections import Counter
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modulos.mensajeria import bot_telegram as bot
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.publico.servicio import zonas
from app.nucleo.contracts.enums import EstadoCamion, Mundo, TipoCarga, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate
from tests.conftest import vaciar_tablas

TEL = "+522290007001"


# ───────────── Simulación (sin BD) ─────────────
def test_escenario_trae_agencias(esc):
    assert [a.id for a in esc.agencias] == ["AG01", "AG02", "AG03", "AG04", "AG05", "AG06"]


def test_reparto_fijo_y_proporcional(esc):
    assert esc.agencia_de("T00-0001") == esc.agencia_de("T00-0001")  # determinista por id
    conteo = Counter(esc.agencia_de(f"T00-{i:04d}") for i in range(12000))
    total = sum(a.participacion for a in esc.agencias)
    for a in esc.agencias:
        assert abs(conteo[a.id] / 12000 - a.participacion / total) < 0.03


def test_snapshot_trae_agencia_y_flota(sim):
    sim.avanzar(6 * 60)  # 10:00: hay camiones en ruta y en fila
    mb = sim.snapshot().mundos[Mundo.B]
    assert mb.camiones and all(c.agencia_id in {"AG01", "AG02", "AG03", "AG04", "AG05", "AG06"} for c in mb.camiones)
    assert set(mb.flota) == {"AG01", "AG02", "AG03", "AG04", "AG05", "AG06"}
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
    assert [a["id"] for a in r] == ["AG01", "AG02", "AG03", "AG04", "AG05", "AG06"] and r[0]["nombre"]


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
    r = cliente.post("/api/agencias/AG02/transportistas",
                     json={"alias": "Lupe Ramos", "telefono": "+522290007003", "placas": "xkl-45-21"})
    assert r.status_code == 201 and r.json()["placas"] == "XKL-45-21" and r.json()["telegram"] is False
    otra = cliente.post("/api/agencias/AG03/transportistas", json={"alias": "Otra", "telefono": "+522290007003"})
    assert otra.status_code == 409
    assert cliente.post("/api/agencias/XX99/transportistas", json={"alias": "Xavier", "telefono": "+522290007004"}).status_code == 404


def test_bot_solo_vincula_numeros_dados_de_alta(cliente, monkeypatch):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.db.base import SessionLocal

    async def falso(chat_id, texto, teclado=None):
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    sim = servicio.sim
    # un número sin alta no se vincula: el bot le pregunta su agencia
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007999", "user_id": 888000333}, chat=888000333))
    assert r == bot.PEDIR_AGENCIA
    with SessionLocal() as db:
        assert bot.transportista_de_chat(db, 888000333) is None
    # el que dio de alta AG02 se vincula a AG02; un enlace de otra agencia no lo cambia
    chat = 888000222
    assert cliente.portal.call(bot.procesar_update, sim, _msg("/start AG03")) == bot.BIENVENIDA
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007003", "user_id": chat, "first_name": "Lupe"}))
    assert "Consorcio Aduanero del Atlántico" in r
    cliente.portal.call(bot.procesar_update, sim, _msg("/start AG03"))
    with SessionLocal() as db:
        t = bot.transportista_de_chat(db, chat)
        assert t.agencia_id == "AG02" and t.alias == "Lupe Ramos"


def test_cita_asignada_se_confirma_o_rechaza_en_el_bot(cliente, monkeypatch):
    from app.modulos.mensajeria.servicio import notificar_asignacion
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.db.base import SessionLocal
    from app.nucleo.db.models import Aviso, Cita

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

    def asignar(horas):
        r = cliente.post("/api/citas", json={"transportista_id": tid, "acceso_id": "A1", "origen": "web",
                                             "ventana_inicio": _ts(cliente, horas), "ventana_fin": _ts(cliente, horas + 0.5),
                                             "tipo_carga": "contenedor_40"})
        assert r.status_code == 201
        cita = r.json()
        cliente.portal.call(notificar_asignacion, sim, cita["id"], lambda _: None)
        return cita

    c1 = asignar(3)
    assert enviados[-1][0] == chat and "Nueva cita" in enviados[-1][1] and "SÍ" in enviados[-1][1]
    r = cliente.portal.call(bot.procesar_update, sim, _msg("Sí"))
    assert r.startswith("Cita confirmada")
    with SessionLocal() as db:
        assert db.get(Cita, c1["id"]).confirmada_en is not None
    c2 = asignar(5)
    assert cliente.portal.call(bot.procesar_update, sim, _msg("no")) == bot.RECHAZADA
    with SessionLocal() as db:
        assert db.get(Cita, c2["id"]).confirmada_en is None
        assert db.scalar(select(Aviso.tipo).where(Aviso.cita_id == c2["id"], Aviso.tipo == "cita_rechazada"))
    # la agencia ve la cita confirmada
    citas = {c["id"]: c for c in cliente.get("/api/citas?agencia_id=AG02").json()}
    assert citas[c1["id"]]["confirmada_en"] is not None and citas[c2["id"]]["confirmada_en"] is None


def test_buscar_agencia_por_nombre_o_codigo(cliente):
    from app.modulos.agencias.servicio import buscar_agencia
    from app.nucleo.db.base import SessionLocal

    with SessionLocal() as db:
        assert buscar_agencia(db, "ag05").id == "AG05"
        assert buscar_agencia(db, "Grupo Aduanal Altamar").id == "AG04"
        assert buscar_agencia(db, "altamar").id == "AG04"
        assert buscar_agencia(db, "  atlántico ").id == "AG02"
        assert buscar_agencia(db, "agencia aduanal") is None  # ambigua / genérica
        assert buscar_agencia(db, "Transportes Pérez") is None


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

    # sin alta: pregunta la agencia con botones de las agencias
    assert cliente.portal.call(bot.procesar_update, sim, _msg(contacto=contacto, chat=chat)) == bot.PEDIR_AGENCIA
    botones = [b[0]["text"] for b in enviados[-1][2]["keyboard"]]
    assert "Grupo Aduanal Altamar" in botones and len(botones) == 6
    # nombre que no existe → vuelve a preguntar; nombre parcial → solicitud a esa agencia
    assert cliente.portal.call(bot.procesar_update, sim, _msg("Transportes Pérez", chat=chat)) == bot.AGENCIA_NO_ENCONTRADA
    r = cliente.portal.call(bot.procesar_update, sim, _msg("altamar", chat=chat))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Grupo Aduanal Altamar")
    r = cliente.portal.call(bot.procesar_update, sim, _msg("¿ya?", chat=chat))
    assert "sigue en revisión" in r

    # la agencia la ve en su panel (y otra agencia no)
    pend = cliente.get("/api/agencias/AG04/solicitudes").json()
    assert [(p["nombre"], p["telefono_fin"]) for p in pend] == [("Toño", "7444")]
    assert cliente.get("/api/agencias/AG01/solicitudes").json() == []
    sid = pend[0]["id"]
    assert cliente.post(f"/api/agencias/AG01/solicitudes/{sid}/aprobar").status_code == 404

    # aprueba: queda dado de alta, ligado al chat, y el bot le avisa
    r = cliente.post(f"/api/agencias/AG04/solicitudes/{sid}/aprobar", json={"placas": "abc-12-34"})
    assert r.status_code == 200 and r.json()["telegram"] is True and r.json()["placas"] == "ABC-12-34"
    assert cliente.post(f"/api/agencias/AG04/solicitudes/{sid}/aprobar").status_code == 409
    with SessionLocal() as db:
        t = bot.transportista_de_chat(db, chat)
        assert t.agencia_id == "AG04" and t.alias == "Toño"
    assert any(c == chat and "aprobó tu alta" in txt for c, txt, _ in enviados)
    assert cliente.get("/api/agencias/AG04/solicitudes").json() == []


def test_solicitud_con_enlace_va_directo_y_se_puede_rechazar(cliente, monkeypatch):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.config import get_settings

    enviados = []

    async def falso(chat_id, texto, teclado=None):
        enviados.append((chat_id, texto))
        return True, "1"

    monkeypatch.setattr(telegram, "enviar", falso)
    monkeypatch.setattr(get_settings(), "telegram_token", "123:ABC")
    sim, chat = servicio.sim, 888000555
    cliente.portal.call(bot.procesar_update, sim, _msg("/start AG06", chat=chat))
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007555", "user_id": chat}, chat=chat))
    assert r == bot.SOLICITUD_ENVIADA.format(nombre="Agencia Aduanal Horizonte")
    sid = cliente.get("/api/agencias/AG06/solicitudes").json()[0]["id"]
    r = cliente.post(f"/api/agencias/AG06/solicitudes/{sid}/rechazar")
    assert r.status_code == 200 and r.json()["estado"] == "rechazada"
    assert any(c == chat and "no aprobó" in txt for c, txt in enviados)
    # puede volver a compartir su número y elegir otra agencia
    r = cliente.portal.call(bot.procesar_update, sim,
                            _msg(contacto={"phone_number": "5212290007555", "user_id": chat}, chat=chat))
    assert r == bot.PEDIR_AGENCIA
