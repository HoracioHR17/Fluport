"""Demanda: reproducible, con las proporciones del escenario y reglas de cita coherentes."""
import random
from collections import Counter

from app.modulos.simulacion.dominio.demanda import (
    MIN_DIA,
    crear_camion,
    demanda_dia,
    ola_buque,
    poisson,
)
from app.nucleo.contracts.enums import TipoCarga


def test_misma_semilla_y_dia_dan_la_misma_demanda(esc):
    a, b = demanda_dia(esc, 7, 0), demanda_dia(esc, 7, 0)
    assert [(c.id, c.llegada_deseada, c.servicio_base) for c in a] == [
        (c.id, c.llegada_deseada, c.servicio_base) for c in b
    ]


def test_dias_distintos_dan_demandas_distintas(esc):
    assert [c.llegada_deseada % MIN_DIA for c in demanda_dia(esc, 7, 0)][:20] != [
        c.llegada_deseada % MIN_DIA for c in demanda_dia(esc, 7, 1)
    ][:20]


def test_llegadas_dentro_del_dia_y_ordenadas(esc):
    d = demanda_dia(esc, 3, 2)
    tiempos = [c.llegada_deseada for c in d]
    assert tiempos == sorted(tiempos)
    assert all(2 * MIN_DIA <= t < 3 * MIN_DIA for t in tiempos)


def test_volumen_diario_cercano_al_escenario(esc):
    media = sum(len(demanda_dia(esc, s, 0)) for s in range(10)) / 10
    assert abs(media - esc.camiones_base_dia) / esc.camiones_base_dia < 0.05


def test_proporciones_de_cita_y_carga(esc):
    camiones = [c for s in range(5) for c in demanda_dia(esc, s, 0)]
    n = len(camiones)
    assert abs(sum(c.con_cita for c in camiones) / n - esc.con_cita) < 0.03
    tipos = Counter(c.tipo_carga for c in camiones)
    assert abs(tipos[TipoCarga.peligroso] / n - esc.mezcla_carga[TipoCarga.peligroso]) < 0.03


def test_sin_cita_no_hay_no_show_ni_cumplimiento(esc):
    for c in demanda_dia(esc, 11, 0):
        if not c.con_cita:
            assert not c.no_show and not c.cumple


def test_carga_prioritaria(esc):
    rng = random.Random(1)
    assert crear_camion(esc, rng, "x", 0, tipo_carga=TipoCarga.refrigerado).prioritario
    assert not crear_camion(esc, rng, "y", 0, tipo_carga=TipoCarga.granel).prioritario


def test_revision_aduanal_alarga_la_estancia(esc):
    esc.revision_aduanal.prob = 1.0
    c = crear_camion(esc, random.Random(2), "x", 0)
    assert c.revision_aduanal and c.estancia_min >= esc.estancia_min[0] + esc.revision_aduanal.extra_min


def test_ola_de_buque(esc):
    ola = ola_buque(esc, random.Random(3), "B", 100.0, 1000)
    assert len(ola) == int(1000 * esc.buques.camiones_por_contenedor)
    a, b = esc.buques.ola_horas
    assert all(100 + 60 * a <= c.llegada_deseada <= 100 + 60 * b for c in ola)


def test_poisson_media():
    rng = random.Random(0)
    assert abs(sum(poisson(rng, 1.1) for _ in range(5000)) / 5000 - 1.1) < 0.1
