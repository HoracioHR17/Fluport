"""Mundo de simulación: ciclo de vida del camión, prioridad, cierres y desvíos."""
import random

from app.modulos.simulacion.dominio.demanda import crear_camion
from app.modulos.simulacion.dominio.mundo import MundoSim
from app.nucleo.contracts.enums import EstadoAcceso, EstadoCamion, Mundo, TipoCarga


def _camion(esc, id_, t, acceso="A1", **kw):
    c = crear_camion(esc, random.Random(hash(id_) % 1000), id_, t, acceso_id=acceso, **kw)
    c.no_show, c.con_cita, c.cumple = False, False, False
    return c


def test_ciclo_de_vida_completo(esc):
    m = MundoSim(Mundo.A, esc)
    c = _camion(esc, "T1", 60)
    m.agregar([c])
    m.avanzar(60 - c.ruta_min + 1)
    assert m.camiones["T1"].estado == EstadoCamion.en_ruta
    assert 0 < m.progreso(m.camiones["T1"]) < 1
    m.avanzar(60 + c.servicio_base / 2)
    assert m.camiones["T1"].estado == EstadoCamion.en_revision
    m.avanzar(60 + c.servicio_base + 1)
    assert m.camiones["T1"].estado == EstadoCamion.dentro
    m.avanzar(60 + c.servicio_base + c.estancia_min + 60)
    assert "T1" not in m.camiones and m.atendidos == 1


def test_no_show_no_llega(esc):
    m = MundoSim(Mundo.A, esc)
    c = _camion(esc, "T1", 10)
    c.no_show = True
    m.agregar([c])
    m.avanzar(500)
    assert m.atendidos == 0


def test_fila_y_espera_cuando_llegan_mas_que_los_carriles(esc):
    m = MundoSim(Mundo.A, esc)
    m.agregar([_camion(esc, f"T{i}", 100) for i in range(20)])
    m.avanzar(100.5)
    a1 = m.accesos["A1"]
    carriles = esc.acceso("A1").carriles
    assert a1.en_revision == carriles and len(a1.en_fila) == 20 - carriles
    assert m.espera_estimada("A1") > 0


def test_mundo_b_atiende_primero_la_carga_prioritaria(esc):
    m = MundoSim(Mundo.B, esc)
    normales = [_camion(esc, f"N{i}", 100, tipo_carga=TipoCarga.granel) for i in range(10)]
    urgente = _camion(esc, "U", 100.2, tipo_carga=TipoCarga.refrigerado)
    m.agregar(normales + [urgente])
    m.avanzar(100.3)
    assert m.camiones["U"].estado == EstadoCamion.en_fila
    m.avanzar(100 + max(c.servicio_base for c in normales[:4]) + 0.01)
    assert m.camiones["U"].estado != EstadoCamion.en_fila  # pasó antes que los 6 normales que esperaban


def test_cierre_bloquea_y_reapertura_libera(esc):
    m = MundoSim(Mundo.A, esc)
    m.cerrar("A1")
    assert m.accesos["A1"].estado == EstadoAcceso.cerrado
    m.agregar([_camion(esc, f"T{i}", 50) for i in range(5)])
    m.avanzar(120)
    assert m.atendidos == 0 and len(m.accesos["A1"].en_fila) == 5
    m.reabrir("A1")
    m.avanzar(200)
    assert m.atendidos == 5


def test_mundo_b_desvia_si_su_acceso_esta_cerrado(esc):
    m = MundoSim(Mundo.B, esc)
    m.cerrar("A1")
    m.agregar([_camion(esc, "T1", 50)])
    m.avanzar(50.1)
    assert m.camiones["T1"].acceso_id != "A1"


def test_factor_de_norte_alarga_el_servicio(esc):
    normal, norte = MundoSim(Mundo.A, esc), MundoSim(Mundo.A, esc)
    norte.factor_servicio = 2.0
    for m in (normal, norte):
        m.agregar([_camion(esc, f"T{i}", 10) for i in range(30)])
        m.avanzar(40)
    assert norte.atendidos < normal.atendidos
