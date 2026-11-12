"""Vista pública (M7): horas pico agregadas y sin datos de operación."""
from datetime import timedelta

from fastapi.testclient import TestClient

from app.modulos.publico.servicio import horas_pico, zonas
from app.nucleo.contracts.enums import Semaforo, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate, FranjaPronostico, PronosticoOut
from tests.conftest import INICIO


def _pron(semaforos: list[str]) -> PronosticoOut:
    esperas = {"verde": 5.0, "amarillo": 40.0, "rojo": 120.0}
    return PronosticoOut(
        acceso_id="A1", generado_en=INICIO, modelo_version="x",
        franjas=[FranjaPronostico(inicio=INICIO + timedelta(minutes=30 * i), espera_min=esperas[s], semaforo=s)
                 for i, s in enumerate(semaforos)],
    )


def test_horas_pico_unen_franjas_consecutivas():
    picos = horas_pico(_pron(["verde", "amarillo", "rojo", "amarillo", "verde", "amarillo", "verde"]))
    assert len(picos) == 2
    assert picos[0].inicio == INICIO + timedelta(minutes=30) and picos[0].fin == INICIO + timedelta(minutes=120)
    assert picos[0].semaforo == Semaforo.rojo and picos[0].espera_max_min == 120
    assert picos[1].semaforo == Semaforo.amarillo


def test_sin_congestion_no_hay_horas_pico():
    assert horas_pico(_pron(["verde"] * 6)) == []


def test_zonas_desde_el_simulador(sim):
    sim.avanzar(6 * 60)
    z = zonas(sim)
    assert [x.acceso_id for x in z] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert all(x.abierto and x.mejor_hora is not None and x.etiqueta == "SIMULACIÓN" for x in z)


def test_caseta_cerrada_en_rojo(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    a2 = next(x for x in zonas(sim) if x.acceso_id == "A2")
    assert not a2.abierto and a2.semaforo == Semaforo.rojo


def test_api_publica_sin_datos_de_operacion():
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/publico/zonas")
        assert r.status_code == 200 and len(r.json()) == 6
        texto = r.text.lower()
        for prohibido in ("telefono", "transportista", "cita", "comparacion", "mundo"):
            assert prohibido not in texto


def test_snapshot_publico_solo_trae_las_entradas(sim):
    from app.modulos.publico.servicio import snapshot_publico

    sim.avanzar(6 * 60)
    s = snapshot_publico(sim)
    assert s["tipo"] == "snapshot" and set(s["data"]) == {"ts_sim", "clima", "mundos"}
    assert set(s["data"]["mundos"]) == {"B"} and set(s["data"]["mundos"]["B"]) == {"accesos"}
    assert len(s["data"]["mundos"]["B"]["accesos"]) == 6


def test_websocket_publico_sin_camiones_ni_avisos():
    import json

    from app.main import app

    with TestClient(app) as c, c.websocket_connect("/ws/publico") as ws:
        m = json.loads(ws.receive_text())
        assert m["tipo"] == "snapshot" and set(m["data"]["mundos"]["B"]) == {"accesos"}
        texto = json.dumps(m).lower()
        for prohibido in ("camiones", "agencia", "cita", "comparacion", "telefono"):
            assert prohibido not in texto
        assert c.get("/api/publico/snapshot").json()["tipo"] == "snapshot"


def test_mejor_hora_nunca_es_pasada(sim):
    """Aunque el pronóstico esté en caché (hasta 15 min simulados), la mejor hora es igual o posterior a ahora."""
    sim.avanzar(6 * 60)
    zonas(sim)  # llena la caché del pronóstico
    sim.avanzar(14)
    assert all(x.mejor_hora is None or x.mejor_hora >= sim.ts() for x in zonas(sim))
