"""Configuración común de las pruebas.

Las pruebas NO usan tu base `fluport` ni tu modelo entrenado:
- Si defines FLUPORT_TEST_DATABASE_URL (una base de prueba aparte, p. ej. `fluport_test`), las pruebas
  que necesitan PostgreSQL (citas) la usan: crean las tablas y las vacían antes de cada módulo.
- Si no, se apunta a una BD inexistente: el simulador funciona sin persistir y las pruebas de citas se omiten.
Se desactiva el entrenamiento automático. Debe ejecutarse antes de importar `app`.
"""
import os
from datetime import datetime, timedelta, timezone

TEST_DB = os.environ.get("FLUPORT_TEST_DATABASE_URL")
os.environ["FLUPORT_DATABASE_URL"] = TEST_DB or "postgresql+psycopg://nadie:nada@127.0.0.1:1/inexistente"
os.environ["FLUPORT_PRONOSTICO_AUTOENTRENAR"] = "false"
os.environ["FLUPORT_SIM_VELOCIDAD"] = "60"
os.environ["FLUPORT_ASISTENTE_WEB_ACTIVO"] = "true"  # las pruebas del asistente usan el canal HTTP
# Aísla las pruebas de tu .env: sin llaves reales nunca se llama a Gemini ni a Telegram.
for _var in ("LLM_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_WEBHOOK_SECRET"):
    os.environ[f"FLUPORT_{_var}"] = ""

import pytest  # noqa: E402

from app.modulos.simulacion.dominio.escenario import cargar_escenario  # noqa: E402
from app.modulos.simulacion.dominio.motor import Simulador  # noqa: E402

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


@pytest.fixture(scope="session", autouse=True)
def _crear_esquema_de_prueba():
    """Con BD de prueba, crea el esquema desde cero una vez por sesión de pruebas."""
    if TEST_DB:
        from app.nucleo.db.base import Base, engine
        from app.nucleo.db.models import Acceso

        assert Acceso.__tablename__  # importar los modelos registra todas las tablas
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    yield


@pytest.fixture(scope="session")
def esquema_bd():
    """Engine de la BD de prueba; omite la prueba si no hay BD de prueba."""
    if not TEST_DB:
        pytest.skip("define FLUPORT_TEST_DATABASE_URL para correr las pruebas con PostgreSQL")
    from app.nucleo.db.base import engine

    return engine


def vaciar_tablas(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as c:
        c.execute(text("TRUNCATE aviso, solicitud_alta, mensaje_asistente, cita, transportista, pronostico, evento_sim, "
                       "lectura_congestion, sim_corrida RESTART IDENTITY CASCADE"))
