"""Operación simulada con Fluport (SimPy): accesos con carriles, filas y camiones.

Llegada según la franja asignada por el planificador (si el camión cumple),
prioridad para carga refrigerada/peligrosa y aviso de cierres: en cuanto una entrada se cierra, los camiones que van
hacia ella o están en su fila se desvían a la entrada abierta con menos espera (con el tiempo extra del rodeo), lo que
carga las demás entradas.
"""
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field

import simpy

from app.modulos.simulacion.dominio.demanda import CamionPlan
from app.modulos.simulacion.dominio.escenario import Escenario
from app.modulos.simulacion.dominio.planificador import Planificador
from app.nucleo.contracts.enums import EstadoAcceso, EstadoCamion, Mundo

PRIORIDAD_CIERRE = -1000
DURACION_SALIDA = 10.0  # minutos que tarda en alejarse del acceso (animación de salida)
DESVIO_MIN = 15.0  # SUPUESTO: minutos de rodeo para llegar a otra entrada cuando la suya se cierra


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
    espera_previa: float = 0.0  # minutos que ya esperó en la fila de una entrada que se cerró
    proceso: object = None  # proceso SimPy del camión (para avisarle de un cierre mientras está en fila)
    desvio_a: str | None = None  # entrada a la que Fluport le sugirió cambiarse (al reabrir otra)


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
        self.planificador = Planificador(esc)
        self.camiones: dict[str, CamionVivo] = {}
        # notificación de cambios de estado de camiones con cita
        self.al_cambiar_cita: Callable[[int, str], None] | None = None
        # Métricas acumuladas
        self.esperas_total = 0.0
        self.espera_max = 0.0
        self.atendidos = 0
        self.pico_fila = 0
        # Por agencia (vista de agencia): esperas acumuladas, camiones que ya pasaron la fila y atendidos
        self.esperas_agencia: Counter[str] = Counter()
        self.filas_agencia: Counter[str] = Counter()
        self.atendidos_agencia: Counter[str] = Counter()

    # ───────────── Altas de camiones ─────────────
    def agregar(self, planes: list[CamionPlan]) -> None:
        for p in planes:
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
            ruta = p.ruta_id if acceso == p.acceso_id else self.esc.acceso(acceso).rutas[0].id
            self.env.process(self._camion(p, acceso, ruta, max(t, self.env.now)))

    # ───────────── Proceso de cada camión ─────────────
    def _camion(self, p: CamionPlan, acceso_id: str, ruta_id: str, t_llegada: float):
        salida = max(self.env.now, t_llegada - p.ruta_min)
        yield self.env.timeout(salida - self.env.now)
        if p.cancelado:
            return
        if self.accesos[acceso_id].estado == EstadoAcceso.cerrado:
            destino = self._mejor_acceso_abierto()  # sale ya avisado del cierre: va directo a otra entrada
            if destino is not None:
                acceso_id, ruta_id = destino.id, self.esc.acceso(destino.id).rutas[0].id
        c = CamionVivo(p, acceso_id, ruta_id, t_salida=self.env.now, t_llegada=t_llegada, t_estado=self.env.now,
                       proceso=self.env.active_process)
        self.camiones[p.id] = c
        self._notificar_cita(p, "en_ruta")
        prioridad = 0 if p.prioritario else 1
        while True:
            # en camino (si Fluport lo desvía mientras maneja, su llegada se recorre)
            while c.t_llegada > self.env.now:
                yield self.env.timeout(c.t_llegada - self.env.now)
            acc = self.accesos[c.acceso_id]
            if acc.estado == EstadoAcceso.cerrado and self._desviar(c):
                continue  # Fluport avisó del cierre: maneja a otra entrada
            c.estado, c.t_fila, c.t_estado = EstadoCamion.en_fila, self.env.now, self.env.now
            acc.en_fila.append(c)
            acc.llegadas.append(self.env.now)
            try:
                with acc.recurso.request(priority=prioridad) as req:
                    yield req
                    acc.en_fila.remove(c)
                    espera = self.env.now - c.t_fila + c.espera_previa
                    self.esperas_total += espera
                    self.espera_max = max(self.espera_max, espera)
                    if p.agencia_id:
                        self.esperas_agencia[p.agencia_id] += espera
                        self.filas_agencia[p.agencia_id] += 1
                    c.estado, c.t_estado = EstadoCamion.en_revision, self.env.now
                    self._notificar_cita(p, "cumplida")
                    acc.en_revision += 1
                    yield self.env.timeout(p.servicio_base * self.factor_servicio)
                    acc.en_revision -= 1
                break
            except simpy.Interrupt:
                # Fluport le avisó (su entrada se cerró o reabrió otra con menos fila): sale de la fila y se desvía
                if c in acc.en_fila:
                    acc.en_fila.remove(c)
                c.espera_previa += self.env.now - c.t_fila
                c.t_fila = None
                if not self._desviar(c):  # no hay otra entrada abierta: se vuelve a formar en la misma
                    c.estado, c.t_salida, c.t_llegada = EstadoCamion.en_ruta, self.env.now, self.env.now
        self.atendidos += 1
        if p.agencia_id:
            self.atendidos_agencia[p.agencia_id] += 1
        acc.atendidos.append(self.env.now)
        c.estado, c.t_estado = EstadoCamion.dentro, self.env.now
        yield self.env.timeout(p.estancia_min)
        c.estado, c.t_estado = EstadoCamion.saliendo, self.env.now
        yield self.env.timeout(DURACION_SALIDA)
        del self.camiones[p.id]

    def _desviar(self, c: CamionVivo) -> bool:
        """Manda el camión a la entrada abierta con menos espera, con el tiempo del rodeo. False si no hay ninguna."""
        sugerido = self.accesos.get(c.desvio_a) if c.desvio_a else None
        c.desvio_a = None
        destino = sugerido if sugerido is not None and sugerido.estado == EstadoAcceso.abierto else self._mejor_acceso_abierto()
        if destino is None:
            return False
        restante = max(0.0, c.t_llegada - self.env.now) if c.estado == EstadoCamion.en_ruta else 0.0
        c.acceso_id, c.ruta_id = destino.id, self.esc.acceso(destino.id).rutas[0].id
        c.estado, c.t_estado, c.t_salida = EstadoCamion.en_ruta, self.env.now, self.env.now
        c.t_llegada = self.env.now + max(restante, DESVIO_MIN)
        return True

    def _notificar_cita(self, p: CamionPlan, estado: str) -> None:
        if p.cita_id is not None and self.al_cambiar_cita is not None:
            self.al_cambiar_cita(p.cita_id, estado)

    # ───────────── Eventos ─────────────
    def cerrar(self, acceso_id: str) -> None:
        acc = self.accesos[acceso_id]
        if acc.estado == EstadoAcceso.cerrado:
            return
        acc.estado = EstadoAcceso.cerrado
        # la barrera ocupa los carriles en cuanto los liberan los camiones que ya estaban en revisión
        acc.bloqueos = [acc.recurso.request(priority=PRIORIDAD_CIERRE) for _ in range(acc.carriles)]
        if self.planificador:
            self.planificador.cerrados.add(acceso_id)
        if any(a.estado == EstadoAcceso.abierto for a in self.accesos.values()):
            # Fluport avisa del cierre: quienes iban hacia esa entrada o estaban en su fila se desvían ya
            for c in list(self.camiones.values()):
                if c.acceso_id != acceso_id:
                    continue
                if c.estado == EstadoCamion.en_ruta:
                    self._desviar(c)
                elif c.estado == EstadoCamion.en_fila and c.proceso is not None and c.proceso.is_alive:
                    c.proceso.interrupt("cierre")

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
        self._rebalancear(acc)

    def _rebalancear(self, destino: AccesoVivo) -> None:
        """Al reabrir una entrada, Fluport sugiere cambiarse a los últimos de las filas largas mientras les convenga
        (su espera actual es mayor que la de la entrada reabierta más el rodeo)."""
        def capacidad(a: AccesoVivo) -> float:  # camiones por minuto
            return a.carriles / (a.servicio_media * self.factor_servicio)

        llegan = len(destino.en_fila)
        for a in sorted(self.accesos.values(), key=lambda x: -len(x.en_fila)):
            if a is destino or a.estado != EstadoAcceso.abierto:
                continue
            cola = list(a.en_fila)
            while cola and len(cola) / capacidad(a) > llegan / capacidad(destino) + DESVIO_MIN:
                c = cola.pop()  # el último de la fila
                if c.proceso is not None and c.proceso.is_alive:
                    c.desvio_a = destino.id
                    c.proceso.interrupt("reapertura")
                    llegan += 1

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
