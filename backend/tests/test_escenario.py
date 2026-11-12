"""Escenario: el archivo de datos se valida y los valores derivados son correctos."""
import json
import math

import pytest
from pydantic import ValidationError

from app.modulos.simulacion.dominio.escenario import RUTA_ESCENARIO, Escenario


def _datos():
    d = json.loads(RUTA_ESCENARIO.read_text(encoding="utf-8"))
    d.pop("_nota", None)
    return d


def test_escenario_del_proyecto_es_valido(esc):
    assert len(esc.accesos) == 3
    assert {a.id for a in esc.accesos} == {"A1", "A2", "A3"}


def test_capacidad_por_hora(esc):
    a1 = esc.acceso("A1")  # 4 carriles, 3.9 min
    assert a1.capacidad_hora == int(4 * 60 / 3.9)


def test_perfil_horario_suma_100_y_respeta_franjas(esc):
    perfil = esc.perfil_horario
    assert len(perfil) == 24
    assert math.isclose(sum(perfil), 1.0, abs_tol=1e-9)
    # 28 % entre 10 y 14 h repartido en 4 horas
    assert math.isclose(perfil[11], 0.28 / 4)


def test_franjas_que_no_suman_100_se_rechazan():
    d = _datos()
    d["llegadas_por_franja"][0]["pct"] = 0.50
    with pytest.raises(ValidationError, match="100"):
        Escenario.model_validate(d)


def test_ids_de_acceso_repetidos_se_rechazan():
    d = _datos()
    d["accesos"][1]["id"] = d["accesos"][0]["id"]
    with pytest.raises(ValidationError, match="repetidos"):
        Escenario.model_validate(d)


def test_carriles_en_cero_se_rechazan():
    d = _datos()
    d["accesos"][0]["carriles"] = 0
    with pytest.raises(ValidationError):
        Escenario.model_validate(d)


def test_factor_de_norte(esc):
    # atender 30 % menos ⇒ cada camión tarda 1/0.7
    assert math.isclose(esc.norte.factor_servicio, 1 / 0.7)


def test_sigma_del_retraso(esc):
    # Normal(0, σ) con E|X| = 20 min
    assert math.isclose(esc.retraso_sigma_min * math.sqrt(2 / math.pi), esc.retraso_promedio_min)


def test_demanda_base_segun_si_incluye_buques(esc):
    esc.camiones_dia_incluye_buques = False
    assert esc.camiones_base_dia == esc.camiones_dia
    esc.camiones_dia_incluye_buques = True
    assert math.isclose(esc.camiones_base_dia, esc.camiones_dia - esc.camiones_buque_dia)
