"""Contratos: enums, validaciones de payloads y esquema de BD compilable para PostgreSQL."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.nucleo.contracts.enums import Semaforo, semaforo_de
from app.nucleo.contracts.schemas import CitaCreate, SimControl
from app.nucleo.db.base import Base
from app.nucleo.db.models import (
    Acceso,  # importar los modelos registra las tablas en Base.metadata
)

T = datetime(2026, 11, 12, 10, tzinfo=timezone(timedelta(hours=-6)))


@pytest.mark.parametrize("espera,esperado", [(0, "verde"), (29.9, "verde"), (30, "amarillo"),
                                            (90, "amarillo"), (90.1, "rojo")])
def test_semaforo(espera, esperado):
    assert semaforo_de(espera) == Semaforo(esperado)


def test_cita_valida():
    c = CitaCreate(telefono="2290000000", acceso_id="A1", ventana_inicio=T,
                   ventana_fin=T + timedelta(minutes=30), tipo_carga="contenedor_40")
    assert c.origen == "web"


def test_cita_con_ventana_invertida():
    with pytest.raises(ValidationError, match="posterior"):
        CitaCreate(telefono="1", acceso_id="A1", ventana_inicio=T, ventana_fin=T, tipo_carga="granel")


def test_cita_sin_transportista():
    with pytest.raises(ValidationError, match="telefono o transportista_id"):
        CitaCreate(acceso_id="A1", ventana_inicio=T, ventana_fin=T + timedelta(hours=1), tipo_carga="granel")


def test_control_de_simulacion():
    assert SimControl(accion="pause").accion == "pause"
    with pytest.raises(ValidationError):
        SimControl(accion="volar")
    with pytest.raises(ValidationError):
        SimControl(accion="velocidad", velocidad=0)


def test_esquema_compila_para_postgresql():
    assert Acceso.__tablename__ == "acceso"
    tablas = Base.metadata.sorted_tables
    assert {t.name for t in tablas} >= {"acceso", "cita", "lectura_congestion", "pronostico", "evento_sim"}
    for t in tablas:
        CreateTable(t).compile(dialect=postgresql.dialect())
