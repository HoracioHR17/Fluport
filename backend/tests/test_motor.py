"""Motor: mundos A/B con la misma demanda, eventos, KPIs y snapshots."""
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


def test_ambos_mundos_reciben_la_misma_demanda(sim):
    sim.avanzar(24 * 60)
    a, b = sim.kpis(Mundo.A), sim.kpis(Mundo.B)
    assert a.camiones_atendidos > 1000
    # misma demanda; B puede diferir solo por reprogramaciones/no-shows (diferencia pequeña)
    assert abs(a.camiones_atendidos - b.camiones_atendidos) / a.camiones_atendidos < 0.1


def test_fluport_reduce_la_espera_en_un_dia_congestionado(esc):
    from app.modulos.simulacion.dominio.motor import Simulador

    esc.cumplimiento_sugerencia, esc.con_cita = 1.0, 1.0  # todos agendan y siguen la sugerencia
    s = Simulador(esc, 3, INICIO, eventos_auto=False)
    s.avanzar(2 * 24 * 60)
    assert s.kpis(Mundo.B).horas_camion_espera < s.kpis(Mundo.A).horas_camion_espera


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
    assert sim.clima == Clima.norte and sim.mundos[Mundo.A].factor_servicio > 1
    sim.avanzar(121)
    assert sim.clima == Clima.normal and sim.mundos[Mundo.A].factor_servicio == 1


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


def test_inyectar_cita_aparece_en_ambos_mundos(sim):
    sim.avanzar(60)
    cid = sim.inyectar_cita(5, "A3", INICIO.replace(hour=5, minute=30), TipoCarga.contenedor_40, es_demo=True)
    sim.avanzar(15)
    for m in sim.mundos.values():
        assert cid in m.camiones and m.camiones[cid].plan.es_demo


def test_lecturas_cada_5_minutos(sim):
    sim.avanzar(60)
    lecturas, _ = sim.vaciar_pendientes()
    # 2 mundos × 3 accesos por lectura; ~12 lecturas en una hora
    assert len(lecturas) % 6 == 0 and len(lecturas) >= 6 * 11


def test_comparacion_usa_factores_del_escenario(sim):
    sim.avanzar(12 * 60)
    ka, kb = sim.kpis(Mundo.A), sim.kpis(Mundo.B)
    c = sim.comparacion(ka, kb)
    horas = max(0.0, ka.horas_camion_espera - kb.horas_camion_espera)
    assert c.horas_ahorradas == pytest.approx(horas, abs=0.1)
    assert c.costo_mxn_evitado == pytest.approx(horas * sim.esc.impacto.costo_hora_camion_mxn, abs=40)


def test_snapshot_valido_y_con_tope(sim):
    sim.cfg.sim_max_camiones_visibles = 5
    sim.avanzar(8 * 60)
    snap = sim.snapshot()
    SimSnapshot.model_validate(snap.model_dump())
    assert set(snap.mundos) == {Mundo.A, Mundo.B}
    assert len(snap.mundos[Mundo.A].camiones) <= 5
    assert all(0 <= c.progreso <= 1 for c in snap.mundos[Mundo.B].camiones)


def test_publicador_recibe_eventos(sim):
    recibidos = []
    sim.publicador = recibidos.append
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.norte))
    sim.publicar_snapshot()
    assert '"tipo":"evento"' in recibidos[0] and '"tipo":"snapshot"' in recibidos[1]


def test_cierre_crea_cuello_de_botella_y_fluport_desvia(sim):
    """Sin Fluport los camiones se forman ante la barrera; con Fluport se desvían ya (y cargan las demás entradas)."""
    from app.nucleo.contracts.enums import EstadoCamion, Mundo

    sim.avanzar(6 * 60)  # 10:00, hora de mucho tráfico
    fila_b_antes = sum(len(a.en_fila) for a in sim.mundos[Mundo.B].accesos.values())
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A2"))
    sim.avanzar(60)
    a, b = sim.mundos[Mundo.A], sim.mundos[Mundo.B]
    # Mundo A: nadie pasa por la entrada cerrada y la fila crece
    assert len(a.accesos["A2"].en_fila) > 20 and a.atendidos_hora("A2") < 10 and a.espera_estimada("A2") > 30
    # Mundo B: nadie va ni espera en la entrada cerrada; la fila se reparte en las demás
    assert len(b.accesos["A2"].en_fila) == 0
    assert not [c for c in b.camiones.values() if c.acceso_id == "A2" and c.estado == EstadoCamion.en_ruta]
    assert sum(len(x.en_fila) for x in b.accesos.values()) > fila_b_antes
    # al reabrir, Fluport manda a la entrada reabierta a los últimos de las filas largas
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.reapertura, acceso_id="A2"))
    sim.avanzar(30)
    hacia_a2 = [c for c in b.camiones.values() if c.acceso_id == "A2" and c.estado in (EstadoCamion.en_ruta, EstadoCamion.en_fila)]
    assert hacia_a2 and b.atendidos_hora("A2") > 0
