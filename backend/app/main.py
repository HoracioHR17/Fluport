"""Raíz de composición: arma la aplicación y conecta los módulos con sus adaptadores.

Una sola app FastAPI sirve la API, el WebSocket y el frontend estático (monolito modular). Aquí, y solo aquí, se
decide qué implementa cada puerto: la operación del puerto es el simulador; los ganchos de la simulación llaman a
citas, mensajería y pronóstico.
"""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.modulos.agencias import api as agencias
from app.modulos.citas import api as citas
from app.modulos.citas.servicio import reinyectar_desde_bd, sincronizar_desde_operacion
from app.modulos.mensajeria import api as asistente
from app.modulos.mensajeria.bot_telegram import polling
from app.modulos.mensajeria.servicio import ciclo_avisos
from app.modulos.pronostico import api as pronostico
from app.modulos.pronostico.pronosticador import entrenar_y_cargar, pronosticador
from app.modulos.publico import api as publico
from app.modulos.simulacion import api as sim
from app.modulos.simulacion import api_accesos as accesos
from app.modulos.simulacion.servicio import Ganchos, SimNoIniciada, servicio
from app.nucleo import dependencias
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import EstadoSim, Mundo
from app.nucleo.contracts.schemas import Salud
from app.nucleo.db.base import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ───────────── Puertos → adaptadores ─────────────
dependencias.configurar(operacion=servicio.requerir, publicar=servicio.publicar)
servicio.ganchos = Ganchos(
    citas_por_reinyectar=reinyectar_desde_bd,
    sincronizar_citas=sincronizar_desde_operacion,
    ciclo_avisos=ciclo_avisos,
    pronostico=lambda sim: pronosticador.obtener(sim, Mundo.B),
    hay_modelo=lambda: pronosticador.paquete is not None,
    entrenar_modelo=entrenar_y_cargar,
)

VERSION = "0.1.0"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def ciclo_vida(_: FastAPI) -> AsyncIterator[None]:
    cfg = get_settings()
    if cfg.sim_autostart:
        await servicio.iniciar()
    if cfg.telegram_token and cfg.telegram_modo == "polling":
        polling.iniciar(lambda: servicio.sim)
    yield
    await polling.detener()
    await servicio.detener()


app = FastAPI(title="Fluport API", version=VERSION, description="Datos sintéticos · SIMULACIÓN", lifespan=ciclo_vida)


@app.exception_handler(SimNoIniciada)
async def _sim_no_iniciada(_: Request, exc: SimNoIniciada) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})

for r in (accesos, pronostico, citas, sim, asistente, publico, agencias):
    app.include_router(r.router)


@app.get("/api/salud", response_model=Salud, tags=["salud"])
def salud() -> Salud:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        bd = True
    except Exception:
        bd = False
    estado = servicio.sim.estado if servicio.sim else EstadoSim.detenida
    return Salud(bd=bd, simulador=estado, version=VERSION)


@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    return RedirectResponse("/publico/")


@app.get("/operador", include_in_schema=False)
@app.get("/operador/", include_in_schema=False)
def operador() -> RedirectResponse:
    """Ruta anterior del tablero: ahora es la vista de agencia."""
    return RedirectResponse("/agencia/")


app.mount("/agencia", StaticFiles(directory=FRONTEND / "agencia", html=True, check_dir=False), name="agencia")
app.mount("/demo", StaticFiles(directory=FRONTEND / "demo", html=True, check_dir=False), name="demo")
app.mount("/publico", StaticFiles(directory=FRONTEND / "publico", html=True, check_dir=False), name="publico")
app.mount("/static", StaticFiles(directory=FRONTEND / "static", check_dir=False), name="static")
