"""Motor: operación con Fluport, eventos, KPIs y snapshots."""
import pytest

from app.nucleo.contracts.enums import (
    Clima,
    EstadoAcceso,
    Mundo,
    TipoCarga,
    TipoEventoSim,
)
from app.nucleo.contracts.schemas import EventoCreate, SimSnapshot
from tests.conftest import INICIO


def test_un_solo_mundo_con_fluport_atiende_la_demanda(sim):
    sim.avanzar(24 * 60)
    assert set(sim.mundos) == {Mundo.B}
    assert sim.kpis(Mundo.B).camiones_atendidos > 1000


def test_reloj_y_marcas_de_tiempo(sim):
    sim.avanzar(90)
    assert sim.ts() == INICIO.replace(hour=5, minute=30)
    assert sim.a_minuto(sim.ts()) == pytest.approx(90)


def test_evento_cierre_y_reapertura(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    assert all(m.accesos["A2"].estado == EstadoAcceso.cerrado for m in sim.mundos.values())
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.reapertura, acceso_id="A2"))
    assert all(m.accesos["A2"].estado == EstadoAcceso.abierto for m in sim.mundos.values())


def test_evento_con_acceso_invalido(sim):
    with pytest.raises(ValueError):
        sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="ZZ"))


def test_norte_cambia_clima_y_termina_solo(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.norte, payload={"duracion_h": 2}))
    assert sim.clima == Clima.norte and sim.mundos[Mundo.B].factor_servicio > 1
    sim.avanzar(121)
    assert sim.clima == Clima.normal and sim.mundos[Mundo.B].factor_servicio == 1


def test_buque_agrega_camiones(sim):
    antes = sum(sim.demanda_conocida.values())
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.buque_atraca, payload={"contenedores": 1000}))
    assert sum(sim.demanda_conocida.values()) - antes == int(1000 * sim.esc.buques.camiones_por_contenedor)


def test_carga_urgente_es_prioritaria(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.carga_urgente, acceso_id="A1", payload={"camiones": 3}))
    sim.avanzar(120)
    urgentes = [c for c in sim.mundos[Mundo.B].camiones.values() if c.plan.origen == "urgente"]
    assert urgentes and all(c.plan.prioritario for c in urgentes)


def test_eventos_quedan_registrados(sim):
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.personalizado, payload={"giro": "x"}))
    assert sim.eventos_recientes[0].tipo == TipoEventoSim.personalizado
    _, eventos = sim.vaciar_pendientes()
    assert len(eventos) == 1


def test_inyectar_cita_aparece_en_la_operacion(sim):
    sim.avanzar(60)
    cid = sim.inyectar_cita(5, "A3", INICIO.replace(hour=5, minute=30), TipoCarga.contenedor_40, es_demo=True)
    sim.avanzar(15)
    for m in sim.mundos.values():
        assert cid in m.camiones and m.camiones[cid].plan.es_demo


def test_lecturas_cada_5_minutos(sim):
    sim.avanzar(60)
    lecturas, _ = sim.vaciar_pendientes()
    # un renglón por entrada en cada lectura; ~12 lecturas en una hora
    assert len(lecturas) % 6 == 0 and len(lecturas) >= 6 * 11


def test_snapshot_valido_y_con_tope(sim):
    sim.cfg.sim_max_camiones_visibles = 5
    sim.avanzar(8 * 60)
    snap = sim.snapshot()
    SimSnapshot.model_validate(snap.model_dump())
    assert set(snap.mundos) == {Mundo.B}
    assert len(snap.mundos[Mundo.B].camiones) <= 5
    assert all(0 <= c.progreso <= 1 for c in snap.mundos[Mundo.B].camiones)


def test_publicador_recibe_eventos(sim):
    recibidos = []
    sim.publicador = recibidos.append
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.norte))
    sim.publicar_snapshot()
    assert '"tipo":"evento"' in recibidos[0] and '"tipo":"snapshot"' in recibidos[1]


def test_cierre_crea_cuello_de_botella_y_fluport_desvia(sim):
    """Con Fluport, al cerrar una entrada los camiones se desvían ya (y cargan las demás entradas)."""
    from app.nucleo.contracts.enums import EstadoCamion, Mundo

    sim.avanzar(6 * 60)  # 10:00, hora de mucho tráfico
    fila_b_antes = sum(len(a.en_fila) for a in sim.mundos[Mundo.B].accesos.values())
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    sim.avanzar(60)
    b = sim.mundos[Mundo.B]
    # nadie va ni espera en la entrada cerrada; la fila se reparte en las demás
    assert len(b.accesos["A2"].en_fila) == 0
    assert not [c for c in b.camiones.values() if c.acceso_id == "A2" and c.estado == EstadoCamion.en_ruta]
    assert sum(len(x.en_fila) for x in b.accesos.values()) > fila_b_antes
    # al reabrir, Fluport manda a la entrada reabierta a los últimos de las filas largas
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.reapertura, acceso_id="A2"))
    sim.avanzar(30)
    hacia_a2 = [c for c in b.camiones.values() if c.acceso_id == "A2" and c.estado in (EstadoCamion.en_ruta, EstadoCamion.en_fila)]
    assert hacia_a2 and b.atendidos_hora("A2") > 0
