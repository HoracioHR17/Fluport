"""Escritura del simulador en PostgreSQL. Si la BD no está disponible, el simulador sigue sin persistir."""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import insert, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.contracts.enums import EstadoSim, TipoCorrida
from app.db import models as m
from app.sim.escenario import Escenario

log = logging.getLogger("fluport.sim")


class Persistencia:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.activa = True

    def disponible(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("PostgreSQL no disponible, simulación sin persistencia: %s", e)
            self.activa = False
            return False

    def sembrar_accesos(self, esc: Escenario) -> None:
        """Inserta/actualiza los accesos del escenario (las FKs de lecturas y citas dependen de ellos)."""
        filas = [
            dict(
                id=a.id, nombre=a.nombre, zona=a.zona, lat=a.lat, lon=a.lon, carriles=a.carriles,
                tiempo_servicio_min=a.tiempo_servicio_min, capacidad_hora=a.capacidad_hora,
            )
            for a in esc.accesos
        ]
        stmt = pg_insert(m.Acceso).values(filas)
        stmt = stmt.on_conflict_do_update(
            index_elements=[m.Acceso.id],
            set_={k: stmt.excluded[k] for k in filas[0] if k != "id"},
        )
        with self.engine.begin() as c:
            c.execute(stmt)

    def crear_corrida(
        self, tipo: TipoCorrida, semilla: int, inicio: datetime, velocidad: float, parametros: dict[str, Any]
    ) -> int:
        with self.engine.begin() as c:
            return c.execute(
                insert(m.SimCorrida)
                .values(tipo=tipo, semilla=semilla, inicio_sim=inicio, velocidad=velocidad,
                        estado=EstadoSim.corriendo, parametros=parametros)
                .returning(m.SimCorrida.id)
            ).scalar_one()

    def finalizar_corrida(self, corrida_id: int) -> None:
        if corrida_id and self.activa:
            with self.engine.begin() as c:
                c.execute(update(m.SimCorrida).where(m.SimCorrida.id == corrida_id).values(estado=EstadoSim.detenida))

    def guardar_lecturas(self, filas: list[dict[str, Any]]) -> None:
        if filas and self.activa:
            with self.engine.begin() as c:
                c.execute(insert(m.LecturaCongestion), filas)

    def guardar_eventos(self, filas: list[dict[str, Any]]) -> None:
        if filas and self.activa:
            with self.engine.begin() as c:
                c.execute(insert(m.EventoSim), filas)

    def guardar(self, lecturas: list[dict[str, Any]], eventos: list[dict[str, Any]]) -> None:
        try:
            self.guardar_lecturas(lecturas)
            self.guardar_eventos(eventos)
        except Exception as e:  # noqa: BLE001  (la demo no debe caerse por la BD)
            log.error("Error al persistir %d lecturas / %d eventos: %s", len(lecturas), len(eventos), e)
