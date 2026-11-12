"""Citas (M3): sugerencias sin BD; ciclo completo de citas con PostgreSQL de prueba."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.modulos.citas import servicio as citas
from app.modulos.citas.servicio import ErrorCita, normalizar_telefono
from app.nucleo.contracts.enums import Mundo, TipoCarga, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate, SugerenciaRequest
from tests.conftest import INICIO, vaciar_tablas

TEL = "+52 229 000 0001"


# ───────────── Sin BD ─────────────
def test_normalizar_telefono():
    assert normalizar_telefono("+52 229 123 4567") == "+522291234567"
    assert normalizar_telefono("229-123-4567") == "+2291234567"
    assert normalizar_telefono("+5212291234567") == "+522291234567"  # celular MX con el "1" extra
    with pytest.raises(ErrorCita):
        normalizar_telefono("123")


def test_sugerencias_ordenadas_y_dentro_de_la_ventana(sim):
    sim.avanzar(4 * 60)  # 08:00
    req = SugerenciaRequest(desde=INICIO.replace(hour=9), hasta=INICIO.replace(hour=15), tipo_carga="contenedor_40")
    s = citas.sugerir(sim, req)
    assert len(s) == 3
    assert [round(x.espera_min_est / 5) for x in s] == sorted(round(x.espera_min_est / 5) for x in s)
    assert all(req.desde - timedelta(minutes=30) < x.inicio < req.hasta for x in s)
    assert all(x.ahorro_vs_pico_min >= 0 for x in s)


def test_sugerencias_empatadas_prefieren_el_centro_de_la_ventana(sim):
    """Entre las franjas con la menor espera (mismo tramo de 5 min), gana la más cercana a la hora pedida."""
    req = SugerenciaRequest(acceso_id="A1", desde=INICIO.replace(hour=7, minute=30),
                            hasta=INICIO.replace(hour=10, minute=30), tipo_carga="granel")
    s = citas.sugerir(sim, req)
    centro = req.desde + (req.hasta - req.desde) / 2
    mejores = [x for x in s if round(x.espera_min_est / 5) == round(s[0].espera_min_est / 5)]
    assert all(abs(s[0].inicio - centro) <= abs(x.inicio - centro) for x in mejores)


def test_sin_hora_las_empatadas_prefieren_la_mas_proxima(sim):
    """Si el transportista no dio hora, entre esperas similares gana la franja más próxima."""
    req = SugerenciaRequest(acceso_id="A1", desde=INICIO.replace(hour=7, minute=30),
                            hasta=INICIO.replace(hour=10, minute=30), tipo_carga="granel", preferencia="temprano")
    s = citas.sugerir(sim, req)
    assert s[0].inicio.hour == 7 and s[0].inicio.minute == 30 and s[0].espera_min_est < 5


def test_sugerencias_evitan_acceso_cerrado(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    req = SugerenciaRequest(acceso_id="A2", desde=INICIO.replace(hour=6), hasta=INICIO.replace(hour=9),
                            tipo_carga="granel", max_resultados=5)
    assert all(x.acceso_id != "A2" for x in citas.sugerir(sim, req))


def test_sugerencias_ventana_pasada(sim):
    sim.avanzar(10 * 60)
    req = SugerenciaRequest(desde=INICIO.replace(hour=5), hasta=INICIO.replace(hour=6), tipo_carga="granel")
    with pytest.raises(ErrorCita):
        citas.sugerir(sim, req)


def test_cancelar_cita_en_simulador(sim):
    sim.inyectar_cita(1, "A1", INICIO.replace(hour=10), TipoCarga.granel)
    assert sim.cancelar_cita(1) and 1 not in sim.citas
    sim.avanzar(8 * 60)
    assert all("C00001" not in m.camiones for m in sim.mundos.values())
    assert sim.mundos[Mundo.B].atendidos >= 0


def test_cita_notifica_en_ruta_y_cumplida(sim):
    sim.inyectar_cita(2, "A1", INICIO.replace(hour=5), TipoCarga.granel)
    sim.avanzar(3 * 60)
    estados = [e for cid, e in sim.vaciar_cambios_cita() if cid == 2]
    assert estados == ["en_ruta", "cumplida"]


# ───────────── Con PostgreSQL de prueba ─────────────
@pytest.fixture(scope="module")
def cliente(esquema_bd):
    vaciar_tablas(esquema_bd)
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/sim/control", json={"accion": "pause"})
        yield c


def _ts(c, horas: float) -> str:
    """Instante simulado `horas` después del reloj actual."""
    from datetime import datetime

    ahora = datetime.fromisoformat(c.get("/api/sim/estado").json()["ts_sim"])
    return (ahora + timedelta(hours=horas)).isoformat()


def _crear(c, horas=2.0, acceso="A1", tipo="contenedor_40", tel=TEL):
    return c.post("/api/citas", json={"telefono": tel, "acceso_id": acceso, "ventana_inicio": _ts(c, horas),
                                      "ventana_fin": _ts(c, horas + 0.5), "tipo_carga": tipo})


def test_crear_cita(cliente):
    from app.modulos.simulacion.servicio import servicio

    r = _crear(cliente)
    assert r.status_code == 201, r.text
    cita = r.json()
    assert cita["estado"] == "agendada" and cita["prioridad"] == 0 and cita["espera_estimada_min"] is not None
    assert cita["id"] in servicio.sim.citas


def test_carga_prioritaria(cliente):
    assert _crear(cliente, tipo="refrigerado").json()["prioridad"] == 1


def test_listar_y_obtener(cliente):
    mias = cliente.get("/api/citas", params={"telefono": "+522290000001"}).json()
    assert len(mias) >= 2
    assert cliente.get(f"/api/citas/{mias[0]['id']}").json()["id"] == mias[0]["id"]
    assert cliente.get("/api/citas/99999").status_code == 404


def test_errores_al_crear(cliente):
    assert _crear(cliente, acceso="ZZ").status_code == 404
    assert _crear(cliente, horas=-5).status_code == 422
    assert _crear(cliente, tel="12").status_code == 422
    cliente.post("/api/sim/eventos", json={"tipo": "cierre_acceso", "acceso_id": "A3"})
    assert _crear(cliente, acceso="A3").status_code == 409
    cliente.post("/api/sim/eventos", json={"tipo": "reapertura", "acceso_id": "A3"})


def test_reprogramar(cliente):
    original = _crear(cliente, horas=3).json()
    r = cliente.patch(f"/api/citas/{original['id']}", json={"acceso_id": "A2", "ventana_inicio": _ts(cliente, 5),
                                                           "ventana_fin": _ts(cliente, 5.5)})
    assert r.status_code == 200, r.text
    nueva = r.json()
    assert nueva["cita_anterior_id"] == original["id"] and nueva["acceso_id"] == "A2"
    assert cliente.get(f"/api/citas/{original['id']}").json()["estado"] == "reprogramada"
    # la original ya no se puede reprogramar
    assert cliente.patch(f"/api/citas/{original['id']}", json={"ventana_inicio": _ts(cliente, 6),
                                                              "ventana_fin": _ts(cliente, 6.5)}).status_code == 409


def test_cancelar(cliente):
    from app.modulos.simulacion.servicio import servicio

    cita = _crear(cliente, horas=4).json()
    r = cliente.delete(f"/api/citas/{cita['id']}")
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    assert cita["id"] not in servicio.sim.citas
    assert cliente.delete(f"/api/citas/{cita['id']}").status_code == 409


def test_sugerencias_api(cliente):
    r = cliente.post("/api/citas/sugerencias", json={"desde": _ts(cliente, 1), "hasta": _ts(cliente, 6),
                                                     "tipo_carga": "granel"})
    assert r.status_code == 200 and len(r.json()) == 3
    assert cliente.post("/api/citas/sugerencias", json={"acceso_id": "ZZ", "desde": _ts(cliente, 1),
                                                        "hasta": _ts(cliente, 2), "tipo_carga": "granel"}
                        ).status_code == 404
    assert cliente.post("/api/citas/sugerencias", json={"desde": _ts(cliente, 2), "hasta": _ts(cliente, 1),
                                                        "tipo_carga": "granel"}).status_code == 422


def test_cumplimiento(cliente):
    from app.modulos.simulacion.servicio import servicio
    from app.nucleo.db.base import SessionLocal

    cita = _crear(cliente, horas=0.6, acceso="A2").json()
    servicio.avanzar_minutos(150)
    with SessionLocal() as db:
        citas.aplicar_cambios(db, servicio.sim.vaciar_cambios_cita())
    assert cliente.get(f"/api/citas/{cita['id']}").json()["estado"] == "cumplida"
    res = cliente.get("/api/citas/resumen").json()
    assert res["total"] >= 5 and res["por_estado"]["cumplida"] >= 1 and res["cumplimiento_pct"] > 0
    assert set(res["por_acceso"]) <= {"A1", "A2", "A3"}


def test_reset_reinyecta_citas_activas(cliente):
    from app.modulos.simulacion.servicio import servicio

    cita = _crear(cliente, horas=2).json()
    cliente.post("/api/sim/control", json={"accion": "reset", "semilla": 3})
    cliente.post("/api/sim/control", json={"accion": "pause"})
    assert cita["id"] in servicio.sim.citas
