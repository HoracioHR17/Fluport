"""Un mundo de simulación (SimPy): accesos con carriles, filas y camiones.

Mundo A (sin Fluport): cada camión llega a su hora deseada, fila FIFO, sin aviso de cierres.
Mundo B (con Fluport): llegada según la franja asignada por el planificador (si el camión cumple),
prioridad para carga refrigerada/peligrosa y desvío anticipado si su acceso está cerrado.
"""
from collections import deque
from dataclasses import dataclass, field

import simpy

from app.contracts.enums import EstadoAcceso, EstadoCamion, Mundo
from app.sim.demanda import CamionPlan
from app.sim.escenario import Escenario
from app.sim.planificador import Planificador

PRIORIDAD_CIERRE = -1000
DURACION_SALIDA = 10.0  # minutos que tarda en alejarse del acceso (animación de salida)


@dataclass(slots=True)
class CamionVivo:
    plan: CamionPlan
    acceso_id: str
    ruta_id: str
    estado: EstadoCamion = EstadoCamion.en_ruta
    t_salida: float = 0.0  # inicio del trayecto
    t_llegada: float = 0.0  # llegada prevista al acceso
    t_estado: float = 0.0  # cuándo entró al estado actual
    t_fila: float | None = None


@dataclass
class AccesoVivo:
    id: str
    carriles: int
    servicio_media: float
    recurso: simpy.PriorityResource
    estado: EstadoAcceso = EstadoAcceso.abierto
    en_fila: list[CamionVivo] = field(default_factory=list)
    en_revision: int = 0
    atendidos: deque = field(default_factory=deque)  # minutos de fin de servicio (última hora)
    llegadas: deque = field(default_factory=deque)  # minutos de llegada a la fila (última hora)
    bloqueos: list = field(default_factory=list)  # peticiones que ocupan los carriles al cerrar


class MundoSim:
    def __init__(self, mundo: Mundo, esc: Escenario) -> None:
        self.mundo = mundo
        self.esc = esc
        self.env = simpy.Environment()
        self.factor_servicio = 1.0
        self.accesos: dict[str, AccesoVivo] = {
            a.id: AccesoVivo(a.id, a.carriles, a.tiempo_servicio_min, simpy.PriorityResource(self.env, a.carriles))
            for a in esc.accesos
        }
        self.planificador = Planificador(esc) if mundo == Mundo.B else None
        self.camiones: dict[str, CamionVivo] = {}
        # Métricas acumuladas
        self.esperas_total = 0.0
        self.espera_max = 0.0
        self.atendidos = 0
        self.pico_fila = 0

    # ───────────── Altas de camiones ─────────────
    def agregar(self, planes: list[CamionPlan]) -> None:
        for p in planes:
            if self.mundo == Mundo.B:
                if p.cita_id is not None:  # cita real del asistente/API: ya trae su horario
                    acceso, t = p.acceso_id, p.llegada_deseada
                    self.planificador.registrar(acceso, t)
                elif p.con_cita and p.cumple:
                    acceso, base = self.planificador.asignar(p.llegada_deseada, p.acceso_id, p.prioritario)
                    # dentro de la franja: desfase pseudoaleatorio (fijo por camión) + impuntualidad
                    t = base if p.prioritario else base + (p.llegada_deseada % 30) + p.retraso_min
                else:
                    acceso, t = p.acceso_id, p.llegada_deseada
                    self.planificador.registrar(acceso, t)
                if p.no_show:
                    continue  # reservó franja pero no se presenta
            else:
                if p.no_show:
                    continue
                acceso, t = p.acceso_id, p.llegada_deseada
            ruta = p.ruta_id if acceso == p.acceso_id else self.esc.acceso(acceso).rutas[0].id
            self.env.process(self._camion(p, acceso, ruta, max(t, self.env.now)))

    # ───────────── Proceso de cada camión ─────────────
    def _camion(self, p: CamionPlan, acceso_id: str, ruta_id: str, t_llegada: float):
        salida = max(self.env.now, t_llegada - p.ruta_min)
        yield self.env.timeout(salida - self.env.now)
        c = CamionVivo(p, acceso_id, ruta_id, t_salida=self.env.now, t_llegada=t_llegada, t_estado=self.env.now)
        self.camiones[p.id] = c
        yield self.env.timeout(max(0.0, t_llegada - self.env.now))

        acc = self.accesos[c.acceso_id]
        if self.mundo == Mundo.B and acc.estado == EstadoAcceso.cerrado:
            acc = self._mejor_acceso_abierto() or acc  # Fluport avisó del cierre: se desvía
            c.acceso_id = acc.id
            c.ruta_id = self.esc.acceso(acc.id).rutas[0].id

        c.estado, c.t_fila, c.t_estado = EstadoCamion.en_fila, self.env.now, self.env.now
        acc.en_fila.append(c)
        acc.llegadas.append(self.env.now)
        prioridad = 0 if (self.mundo == Mundo.B and p.prioritario) else 1
        with acc.recurso.request(priority=prioridad) as req:
            yield req
            acc.en_fila.remove(c)
            espera = self.env.now - c.t_fila
            self.esperas_total += espera
            self.espera_max = max(self.espera_max, espera)
            c.estado, c.t_estado = EstadoCamion.en_revision, self.env.now
            acc.en_revision += 1
            yield self.env.timeout(p.servicio_base * self.factor_servicio)
            acc.en_revision -= 1
        self.atendidos += 1
        acc.atendidos.append(self.env.now)
        c.estado, c.t_estado = EstadoCamion.dentro, self.env.now
        yield self.env.timeout(p.estancia_min)
        c.estado, c.t_estado = EstadoCamion.saliendo, self.env.now
        yield self.env.timeout(DURACION_SALIDA)
        del self.camiones[p.id]

    # ───────────── Eventos ─────────────
    def cerrar(self, acceso_id: str) -> None:
        acc = self.accesos[acceso_id]
        if acc.estado == EstadoAcceso.cerrado:
            return
        acc.estado = EstadoAcceso.cerrado
        acc.bloqueos = [acc.recurso.request(priority=PRIORIDAD_CIERRE) for _ in range(acc.carriles)]
        if self.planificador:
            self.planificador.cerrados.add(acceso_id)

    def reabrir(self, acceso_id: str) -> None:
        acc = self.accesos[acceso_id]
        if acc.estado == EstadoAcceso.abierto:
            return
        for req in acc.bloqueos:
            if req.triggered:
                acc.recurso.release(req)
            else:
                req.cancel()
        acc.bloqueos = []
        acc.estado = EstadoAcceso.abierto
        if self.planificador:
            self.planificador.cerrados.discard(acceso_id)

    # ───────────── Lecturas ─────────────
    def espera_estimada(self, acceso_id: str) -> float:
        """Minutos que esperaría un camión que llegara ahora (fila / capacidad efectiva)."""
        acc = self.accesos[acceso_id]
        throughput_min = acc.carriles / (acc.servicio_media * self.factor_servicio)
        return round((len(acc.en_fila) + 0.5 * acc.en_revision / acc.carriles) / throughput_min, 1)

    def atendidos_hora(self, acceso_id: str) -> int:
        acc = self.accesos[acceso_id]
        while acc.atendidos and acc.atendidos[0] < self.env.now - 60:
            acc.atendidos.popleft()
        return len(acc.atendidos)

    def llegadas_hora(self, acceso_id: str) -> int:
        acc = self.accesos[acceso_id]
        while acc.llegadas and acc.llegadas[0] < self.env.now - 60:
            acc.llegadas.popleft()
        return len(acc.llegadas)

    def progreso(self, c: CamionVivo) -> float:
        """0..1 sobre la ruta: avanza en_ruta, 1 en fila/revisión/dentro, regresa al salir."""
        now = self.env.now
        if c.estado == EstadoCamion.en_ruta:
            dur = c.t_llegada - c.t_salida
            return 1.0 if dur <= 0 else min(1.0, max(0.0, (now - c.t_salida) / dur))
        if c.estado == EstadoCamion.saliendo:
            return max(0.0, 1 - (now - c.t_estado) / DURACION_SALIDA)
        return 1.0

    def esperas_en_curso(self) -> float:
        return sum(self.env.now - c.t_fila for a in self.accesos.values() for c in a.en_fila if c.t_fila is not None)

    def fila_total(self) -> int:
        return sum(len(a.en_fila) for a in self.accesos.values())

    def _mejor_acceso_abierto(self) -> AccesoVivo | None:
        abiertos = [a for a in self.accesos.values() if a.estado == EstadoAcceso.abierto]
        return min(abiertos, key=lambda a: self.espera_estimada(a.id), default=None)

    def avanzar(self, hasta: float) -> None:
        if hasta > self.env.now:
            self.env.run(until=hasta)
        self.pico_fila = max(self.pico_fila, self.fila_total())
