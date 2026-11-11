"""Configuración común de las pruebas.

Las pruebas NO usan tu PostgreSQL ni tu modelo entrenado: se apunta a una BD inexistente
(el simulador sigue funcionando sin persistir) y se desactiva el entrenamiento automático.
Debe ejecutarse antes de importar `app`, por eso las variables se fijan aquí.
"""
import os
from datetime import datetime, timedelta, timezone

os.environ["FLUPORT_DATABASE_URL"] = "postgresql+psycopg://nadie:nada@127.0.0.1:1/inexistente"
os.environ["FLUPORT_PRONOSTICO_AUTOENTRENAR"] = "false"
os.environ["FLUPORT_SIM_VELOCIDAD"] = "60"

import pytest  # noqa: E402

from app.sim.escenario import cargar_escenario  # noqa: E402
from app.sim.motor import Simulador  # noqa: E402

TZ = timezone(timedelta(hours=-6))
INICIO = datetime(2026, 11, 12, 4, 0, tzinfo=TZ)


@pytest.fixture
def esc():
    """Escenario real del proyecto (copia nueva por prueba para poder modificarla)."""
    return cargar_escenario()


@pytest.fixture
def sim(esc):
    """Simulador sin eventos automáticos (resultados deterministas y fáciles de razonar)."""
    return Simulador(esc, semilla=42, inicio=INICIO, eventos_auto=False)
