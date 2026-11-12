"""Pronóstico: balance de flujo, dataset, entrenamiento y predicción en vivo."""
import numpy as np
import pandas as pd
import pytest

from app.modulos.pronostico.dominio.features import (
    COLUMNAS,
    HORIZONTES,
    capacidad_franja,
    dataset_entrenamiento,
    espera_de_fila,
    proyeccion_fluida,
)
from app.modulos.pronostico.pronosticador import VERSION_RESPALDO, Pronosticador
from app.nucleo.contracts.enums import Mundo, TipoEventoSim
from app.nucleo.contracts.schemas import EventoCreate


def test_proyeccion_fluida():
    q = proyeccion_fluida(10, [5, 5, 30, 0], [10, 10, 10, 10])
    assert list(q) == [5, 0, 20, 10]


def test_capacidad_y_espera():
    assert capacidad_franja(4, 4.0) == 30
    assert espera_de_fila(8, 4, 4.0) == 8.0
    assert espera_de_fila(8, 4, 4.0, factor=2) == 16.0


def test_dataset_sin_fuga_de_futuro(sim):
    sim.avanzar(30 * 60)
    lecturas, _ = sim.vaciar_pendientes()
    df = pd.DataFrame(lecturas)
    df["mundo"], df["clima"] = df["mundo"].astype(str), df["clima"].astype(str)
    acc = {a.id: (a.carriles, a.tiempo_servicio_min) for a in sim.esc.accesos}
    x, y = dataset_entrenamiento(df, acc, sim.esc.norte.factor_servicio)
    assert list(x.columns) == COLUMNAS and len(x) == len(y) > 0
    assert set(x["h_min"]) == set(HORIZONTES)
    assert (y >= 0).all()


def test_respaldo_sin_modelo(sim, monkeypatch):
    p = Pronosticador()
    p.paquete = None  # sin modelo: balance de flujo
    sim.avanzar(6 * 60)
    res = p.calcular(sim, Mundo.B)
    assert len(res) == 6
    assert all(r.modelo_version == VERSION_RESPALDO and len(r.franjas) == len(HORIZONTES) for r in res)
    assert all(f.espera_min >= 0 for r in res for f in r.franjas)


def test_cierre_sube_el_pronostico_inmediato(sim):
    p = Pronosticador()
    p.paquete = None
    sim.avanzar(8 * 60)
    antes = next(r for r in p.calcular(sim, Mundo.A) if r.acceso_id == "A1").franjas[1].espera_min
    sim.aplicar_evento(EventoCreate(tipo=TipoEventoSim.cierre_acceso, acceso_id="A1"))
    despues = next(r for r in p.calcular(sim, Mundo.A) if r.acceso_id == "A1").franjas[1].espera_min
    assert despues > antes


def test_cache_y_espera_en(sim):
    p = Pronosticador()
    p.paquete = None
    sim.avanzar(60)
    r1 = p.obtener(sim)
    assert p.obtener(sim) is r1  # no recalcula antes de 15 min simulados
    sim.avanzar(16)
    assert p.obtener(sim) is not r1
    cuando = r1[0].franjas[2].inicio
    assert p.espera_en(sim, "A1", cuando) is not None


@pytest.mark.lento
def test_entrenamiento_corto_y_prediccion(sim, tmp_path):
    """Entrena con pocos días en un archivo temporal (no toca backend/modelos/)."""
    import joblib

    from app.modulos.pronostico.entrenar import entrenar

    ruta = tmp_path / "m.joblib"
    met = entrenar(dias=3, semilla=5, persistir=False, ruta=ruta)
    assert ruta.exists() and met["mae_modelo_min"] >= 0
    p = Pronosticador()
    p.paquete = joblib.load(ruta)
    sim.avanzar(10 * 60)
    res = p.calcular(sim, Mundo.B)
    assert res[0].modelo_version.startswith("hgb-")
    assert np.all([f.espera_min >= 0 for r in res for f in r.franjas])
