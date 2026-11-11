"""Servicio en vivo: ejecuta el simulador dentro del event loop de FastAPI y emite un snapshot por tick."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.contracts.enums import EstadoSim, TipoCorrida
from app.contracts.schemas import EventoCreate, EventoOut, SimControl, SimEstadoOut
from app.db.base import engine
from app.sim.escenario import Escenario, escenario_actual
from app.sim.motor import Simulador
from app.sim.persistencia import Persistencia

log = logging.getLogger("fluport.sim")


class SimNoIniciada(Exception):
    """La API recibió una petición antes de que el simulador arrancara (se responde 503)."""
TICKS_POR_ESCRITURA = 5


def inicio_por_defecto(esc: Escenario) -> datetime:
    """Hoy a la hora de arranque del escenario, en hora de Veracruz."""
    ahora = datetime.now(ZoneInfo(get_settings().zona_horaria))
    return ahora.replace(hour=esc.inicio_hora, minute=0, second=0, microsecond=0)


class ServicioSim:
    def __init__(self) -> None:
        self.cfg = get_settings()
        self.esc = escenario_actual()
        self.persistencia = Persistencia(engine)
        self.sim: Simulador | None = None
        self._tarea: asyncio.Task | None = None
        self._suscriptores: set[asyncio.Queue] = set()  # sobreviven a un reset del simulador

    # ───────────── Ciclo de vida ─────────────
    async def iniciar(self, semilla: int | None = None) -> None:
        semilla = self.cfg.sim_semilla if semilla is None else semilla
        inicio = inicio_por_defecto(self.esc)
        corrida_id = 0
        if await asyncio.to_thread(self.persistencia.disponible):
            await asyncio.to_thread(self.persistencia.sembrar_accesos, self.esc)
            corrida_id = await asyncio.to_thread(
                self.persistencia.crear_corrida, TipoCorrida.vivo, semilla, inicio, self.cfg.sim_velocidad,
                self.esc.model_dump(mode="json"),
            )
        self.sim = Simulador(self.esc, semilla, inicio, self.cfg.sim_velocidad, corrida_id=corrida_id)
        self.sim.publicador = self.publicar
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle(), name="fluport-sim")
        log.info("Simulación iniciada: corrida=%s semilla=%s inicio=%s", corrida_id, semilla, inicio)

    async def detener(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
        await self._finalizar()

    async def _bucle(self) -> None:
        tick_seg = self.cfg.sim_tick_seg
        while True:
            await asyncio.sleep(tick_seg)
            sim = self.sim
            if sim is None:
                continue
            try:
                if sim.estado == EstadoSim.corriendo:
                    sim.avanzar(tick_seg * sim.velocidad / 60)  # velocidad = segundos simulados por segundo real
                sim.publicar_snapshot()
                if sim.tick % TICKS_POR_ESCRITURA == 0:
                    await self._escribir()
            except Exception:  # noqa: BLE001
                log.exception("Error en el tick %s", sim.tick)

    async def _finalizar(self) -> None:
        await self._escribir()
        if self.sim and self.persistencia.activa:
            await asyncio.to_thread(self.persistencia.finalizar_corrida, self.sim.corrida_id)

    async def _escribir(self) -> None:
        if self.sim and self.persistencia.activa and self.sim.corrida_id:
            lecturas, eventos = self.sim.vaciar_pendientes()
            await asyncio.to_thread(self.persistencia.guardar, lecturas, eventos)
        elif self.sim:
            self.sim.vaciar_pendientes()

    # ───────────── Pub/Sub para WebSocket ─────────────
    def suscribir(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._suscriptores.add(q)
        return q

    def desuscribir(self, q: asyncio.Queue) -> None:
        self._suscriptores.discard(q)

    def publicar(self, texto: str) -> None:
        for q in list(self._suscriptores):
            if q.full():  # cliente lento: se descarta el mensaje más viejo
                q.get_nowait()
            q.put_nowait(texto)

    # ───────────── Operaciones expuestas a la API ─────────────
    def requerir(self) -> Simulador:
        if self.sim is None:
            raise SimNoIniciada("La simulación no está iniciada")
        return self.sim

    async def control(self, body: SimControl) -> SimEstadoOut:
        sim = self.requerir()
        if body.accion == "play":
            sim.estado = EstadoSim.corriendo
        elif body.accion == "pause":
            sim.estado = EstadoSim.pausada
        elif body.accion == "velocidad":
            if body.velocidad is None:
                raise ValueError("falta 'velocidad'")
            sim.velocidad = body.velocidad
        elif body.accion == "reset":
            await self._finalizar()
            await self.iniciar(body.semilla if body.semilla is not None else sim.semilla)
        return self.requerir().estado_out()

    def evento(self, body: EventoCreate) -> EventoOut:
        return self.requerir().aplicar_evento(body)

    def avanzar_minutos(self, minutos: float) -> None:
        """Solo para pruebas: adelanta el reloj sin esperar ticks reales."""
        self.requerir().avanzar(minutos)


servicio = ServicioSim()

