"""Escritura del simulador en PostgreSQL. Si la BD no está disponible, el simulador sigue sin persistir."""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, insert, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.modulos.simulacion.dominio.escenario import Escenario
from app.nucleo.contracts.enums import EstadoSim, TipoCorrida
from app.nucleo.db import models as m

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
        """Inserta/actualiza los accesos y agencias del escenario (las FKs de lecturas y citas dependen de ellos)."""
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
            if esc.agencias:  # las agencias de la demo también vienen del escenario
                ag = pg_insert(m.Agencia).values([dict(id=a.id, nombre=a.nombre) for a in esc.agencias])
                c.execute(ag.on_conflict_do_update(index_elements=[m.Agencia.id], set_={"nombre": ag.excluded.nombre}))
                # agencias que ya no están en el escenario: sus transportistas y solicitudes pasan a la primera
                # agencia vigente y luego se borran (así no quedan choferes ligados a una agencia que no existe)
                ids, destino = [a.id for a in esc.agencias], esc.agencias[0].id
                c.execute(update(m.Transportista).where(m.Transportista.agencia_id.not_in(ids)).values(agencia_id=destino))
                c.execute(update(m.SolicitudAlta).where(m.SolicitudAlta.agencia_id.not_in(ids)).values(agencia_id=destino))
                c.execute(delete(m.Agencia).where(m.Agencia.id.not_in(ids)))

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

    def guardar_pronosticos(self, pronosticos: list) -> None:
        """Guarda una tanda de `PronosticoOut` (una fila por acceso y franja)."""
        filas = [
            dict(acceso_id=p.acceso_id, generado_en=p.generado_en, franja_inicio=f.inicio, espera_min=f.espera_min,
                 semaforo=f.semaforo, modelo_version=p.modelo_version)
            for p in pronosticos for f in p.franjas
        ]
        if filas and self.activa:
            try:
                with self.engine.begin() as c:
                    c.execute(insert(m.Pronostico), filas)
            except Exception as e:  # noqa: BLE001
                log.error("Error al guardar pronósticos: %s", e)

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
