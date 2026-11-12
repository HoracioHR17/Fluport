"""Servicio en vivo: ejecuta el simulador dentro del event loop de FastAPI y emite un snapshot por tick.

El servicio no conoce a los demás módulos: en cada etapa llama a sus `Ganchos` (puertos de salida), que la raíz de
composición (`app/main.py`) conecta con citas, mensajería y pronóstico.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.modulos.simulacion.adaptadores.persistencia_pg import Persistencia
from app.modulos.simulacion.dominio.escenario import Escenario, escenario_actual
from app.modulos.simulacion.dominio.motor import Simulador
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import EstadoSim, TipoCorrida
from app.nucleo.contracts.schemas import (
    EventoCreate,
    EventoOut,
    SimControl,
    SimEstadoOut,
)
from app.nucleo.db.base import engine

log = logging.getLogger("fluport.sim")


@dataclass
class Ganchos:
    """Lo que otros módulos hacen en cada etapa de la simulación. Por defecto, nada."""

    citas_por_reinyectar: Callable[[datetime], list[dict]] = lambda ahora: []  # al iniciar o reiniciar
    sincronizar_citas: Callable[[list[tuple[int, str]], datetime], None] = lambda cambios, ahora: None  # al escribir
    ciclo_avisos: Callable[[Simulador, Callable[[str], None]], Awaitable[object]] | None = None  # cada 5 ticks
    pronostico: Callable[[Simulador], list] | None = None  # pronóstico vigente, para guardarlo
    hay_modelo: Callable[[], bool] = lambda: True
    entrenar_modelo: Callable[[], None] | None = None  # entrena y carga el modelo (en un hilo)


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
        self._t_pronostico_guardado = -1e9
        self._entrenando: asyncio.Task | None = None
        self.ganchos = Ganchos()

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
        if corrida_id:
            pendientes = await asyncio.to_thread(self._citas_por_reinyectar)
            for c in pendientes:  # la inyección modifica el simulador: se hace en el event loop
                self.sim.inyectar_cita(**c)
            if pendientes:
                log.info("Citas activas reinyectadas en la simulación: %d", len(pendientes))
        self._t_pronostico_guardado = -1e9
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle(), name="fluport-sim")
        self._autoentrenar()
        log.info("Simulación iniciada: corrida=%s semilla=%s inicio=%s", corrida_id, semilla, inicio)

    def _autoentrenar(self) -> None:
        """Si no hay modelo de pronóstico, lo entrena en segundo plano (mientras tanto se usa balance de flujo)."""
        entrenar = self.ganchos.entrenar_modelo
        if entrenar is None or self.ganchos.hay_modelo() or not self.cfg.pronostico_autoentrenar:
            return
        if self._entrenando and not self._entrenando.done():
            return

        async def _tarea() -> None:
            try:
                log.info("No hay modelo de pronóstico: entrenando en segundo plano…")
                await asyncio.to_thread(entrenar)
            except Exception:  # noqa: BLE001
                log.exception("Falló el entrenamiento automático; se mantiene el balance de flujo")

        self._entrenando = asyncio.create_task(_tarea(), name="fluport-entrenamiento")

    async def _avisos(self, sim: Simulador) -> None:
        """Avisos proactivos a los transportistas (requiere BD)."""
        ciclo = self.ganchos.ciclo_avisos
        if ciclo is None or not (self.cfg.avisos_activos and self.persistencia.activa and sim.corrida_id):
            return
        try:
            await ciclo(sim, self.publicar)
        except Exception:  # noqa: BLE001  (los avisos nunca detienen la simulación)
            log.exception("Error en el ciclo de avisos")

    async def _guardar_pronostico(self, sim: Simulador) -> None:
        if self.ganchos.pronostico is None or sim.t - self._t_pronostico_guardado < self.cfg.pronostico_guardar_cada_min:
            return
        self._t_pronostico_guardado = sim.t
        pron = self.ganchos.pronostico(sim)
        if self.persistencia.activa and sim.corrida_id:
            await asyncio.to_thread(self.persistencia.guardar_pronosticos, pron)

    async def detener(self) -> None:
        if self._entrenando and not self._entrenando.done():
            self._entrenando.cancel()
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
                    await self._avisos(sim)
                await self._guardar_pronostico(sim)
            except Exception:  # noqa: BLE001
                log.exception("Error en el tick %s", sim.tick)

    async def _finalizar(self) -> None:
        await self._escribir()
        if self.sim and self.persistencia.activa:
            await asyncio.to_thread(self.persistencia.finalizar_corrida, self.sim.corrida_id)

    def _citas_por_reinyectar(self) -> list[dict]:
        try:
            return self.ganchos.citas_por_reinyectar(self.sim.ts())
        except Exception:  # noqa: BLE001
            log.exception("No se pudieron leer las citas activas")
            return []

    def _sincronizar_citas(self, cambios: list[tuple[int, str]], ahora: datetime) -> None:
        try:
            self.ganchos.sincronizar_citas(cambios, ahora)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo sincronizar el estado de las citas")

    async def _escribir(self) -> None:
        if self.sim and self.persistencia.activa and self.sim.corrida_id:
            lecturas, eventos = self.sim.vaciar_pendientes()
            await asyncio.to_thread(self.persistencia.guardar, lecturas, eventos)
            await asyncio.to_thread(self._sincronizar_citas, self.sim.vaciar_cambios_cita(), self.sim.ts())
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

