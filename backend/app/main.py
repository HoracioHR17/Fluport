"""Punto de entrada: una sola app FastAPI sirve API, WebSocket y frontend estático."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import accesos, asistente, citas, pronostico, publico, sim
from app.contracts.enums import EstadoSim
from app.contracts.schemas import Salud
from app.db.base import engine

VERSION = "0.1.0"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Fluport API", version=VERSION, description="Datos sintéticos · SIMULACIÓN")

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
    return Salud(bd=bd, simulador=EstadoSim.detenida, version=VERSION)


@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    return RedirectResponse("/operador/")


app.mount("/operador", StaticFiles(directory=FRONTEND / "operador", html=True, check_dir=False), name="operador")
app.mount("/publico", StaticFiles(directory=FRONTEND / "publico", html=True, check_dir=False), name="publico")
app.mount("/static", StaticFiles(directory=FRONTEND / "static", check_dir=False), name="static")
