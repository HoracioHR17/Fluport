"""Punto de entrada: una sola app FastAPI sirve API, WebSocket y frontend estático."""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import accesos, asistente, citas, pronostico, publico, sim
from app.config import get_settings
from app.contracts.enums import EstadoSim
from app.contracts.schemas import Salud
from app.db.base import engine
from app.messaging.bot_telegram import polling
from app.sim.servicio import SimNoIniciada, servicio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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

for r in (accesos, pronostico, citas, sim, asistente, publico):
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
    return RedirectResponse("/operador/")


app.mount("/operador", StaticFiles(directory=FRONTEND / "operador", html=True, check_dir=False), name="operador")
app.mount("/publico", StaticFiles(directory=FRONTEND / "publico", html=True, check_dir=False), name="publico")
app.mount("/static", StaticFiles(directory=FRONTEND / "static", check_dir=False), name="static")
