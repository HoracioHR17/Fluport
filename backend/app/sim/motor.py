"""Motor de simulación: avanza los mundos A y B en paralelo, aplica eventos y produce snapshots/KPIs."""
import logging
import random
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.config import get_settings
from app.contracts.enums import (
    Clima,
    EstadoAcceso,
    EstadoCamion,
    EstadoSim,
    Mundo,
    TipoCarga,
    TipoEventoSim,
    semaforo_de,
)
from app.contracts.schemas import (
    AccesoEstado,
    CamionEstado,
    EventoCreate,
    EventoOut,
    Kpis,
    KpisComparacion,
    KpisResponse,
    MundoEstado,
    SimEstadoOut,
    SimSnapshot,
    WsEvento,
    WsSnapshot,
)
from app.sim.demanda import MIN_DIA, CamionPlan, crear_camion, demanda_dia, ola_buque, poisson
from app.sim.escenario import Escenario
from app.sim.mundo import MundoSim

log = logging.getLogger("fluport.sim")
VISIBLES = (EstadoCamion.en_ruta, EstadoCamion.en_fila, EstadoCamion.en_revision, EstadoCamion.saliendo)


class Simulador:
    def __init__(
        self,
        esc: Escenario,
        semilla: int,
        inicio: datetime,
        velocidad: float = 60.0,
        corrida_id: int = 0,
        eventos_auto: bool = True,
        intervalo_lectura_min: float = 5.0,
    ) -> None:
        self.cfg = get_settings()
        self.esc, self.semilla, self.inicio, self.velocidad = esc, semilla, inicio, velocidad
        self.corrida_id = corrida_id
        self.eventos_auto, self.intervalo_lectura = eventos_auto, intervalo_lectura_min
        self.mundos = {Mundo.A: MundoSim(Mundo.A, esc), Mundo.B: MundoSim(Mundo.B, esc)}
        self.t = 0.0
        self.tick = 0
        self.estado = EstadoSim.corriendo
        self.clima = Clima.normal
        self.fin_norte: float | None = None
        self.dias_generados = -1
        self.programados: list[tuple[float, EventoCreate]] = []  # eventos automáticos futuros
        self.olas: list[tuple[float, float]] = []  # (inicio, fin) de olas por buque
        self.demanda_conocida: dict[tuple[str, int], int] = defaultdict(int)  # (acceso, franja 30') -> camiones
        self.eventos_recientes: deque[EventoOut] = deque(maxlen=15)
        self.lecturas_pendientes: list[dict[str, Any]] = []
        self.eventos_pendientes: list[dict[str, Any]] = []
        self._ultima_lectura = 0.0  # la primera lectura ocurre al minuto `intervalo_lectura`
        self._seq_evento = 0
        self._rng_eventos = random.Random(semilla + 7919)
        self.publicador: Callable[[str], None] | None = None  # lo asigna el servicio en vivo
        self._asegurar_demanda()

    # ───────────── Tiempo ─────────────
    def ts(self, t: float | None = None) -> datetime:
        return self.inicio + timedelta(minutes=self.t if t is None else t)

    def a_minuto(self, dt: datetime) -> float:
        return (dt - self.inicio).total_seconds() / 60

    # ───────────── Demanda ─────────────
    def _alimentar(self, planes: list[CamionPlan]) -> None:
        for p in planes:
            self.demanda_conocida[(p.acceso_id, int(p.llegada_deseada // 30))] += 1
        for mundo in self.mundos.values():
            mundo.agregar(planes)

    def _asegurar_demanda(self) -> None:
        """Mantiene generado el día actual y el siguiente (las citas se conocen con un día de anticipación)."""
        dia_actual = int(self.t // MIN_DIA)
        while self.dias_generados < dia_actual + 1:
            self.dias_generados += 1
            d = self.dias_generados
            self._alimentar(demanda_dia(self.esc, self.semilla, d))
            if self.eventos_auto:
                self._programar_eventos_dia(d)

    def _programar_eventos_dia(self, d: int) -> None:
        rng = random.Random(self.semilla * 31 + d)
        b = self.esc.buques
        for i in range(poisson(rng, b.por_dia_media)):
            t = d * MIN_DIA + rng.uniform(0, MIN_DIA)
            cont = rng.randint(*b.contenedores)
            self._alimentar(ola_buque(self.esc, rng, f"B{d:02d}{i}", t, cont))  # demanda conocida por adelantado
            self.olas.append((t + 60 * b.ola_horas[0], t + 60 * b.ola_horas[1]))
            self.programados.append(
                (t, EventoCreate(tipo=TipoEventoSim.buque_atraca, payload={"contenedores": cont, "auto": True}))
            )
        if rng.random() < self.esc.norte.prob_dia:
            t = d * MIN_DIA + rng.uniform(0, MIN_DIA)
            dur = rng.uniform(*self.esc.norte.duracion_rango_h)
            self.programados.append(
                (t, EventoCreate(tipo=TipoEventoSim.norte, payload={"auto": True, "duracion_h": round(dur, 1)}))
            )
        self.programados.sort(key=lambda x: x[0])

    # ───────────── Avance ─────────────
    def avanzar(self, dt_min: float) -> None:
        objetivo = self.t + dt_min
        while self.programados and self.programados[0][0] <= objetivo:
            t_ev, ev = self.programados.pop(0)
            self._mover(t_ev)
            self.aplicar_evento(ev, generar_ola=False)
        if self.fin_norte is not None and self.fin_norte <= objetivo:
            self._mover(self.fin_norte)
            self._terminar_norte()
        self._mover(objetivo)
        self.tick += 1

    def _mover(self, t: float) -> None:
        """Avanza el reloj hasta `t`, deteniéndose en cada lectura (una cada `intervalo_lectura` minutos)."""
        while self.t < t:
            paso = min(t, self._ultima_lectura + self.intervalo_lectura)
            self.t = paso
            self._asegurar_demanda()
            for mundo in self.mundos.values():
                mundo.avanzar(paso)
            if paso >= self._ultima_lectura + self.intervalo_lectura - 1e-9:
                self._registrar_lecturas()
                self._ultima_lectura = paso

    def _registrar_lecturas(self) -> None:
        ts = self.ts()
        franja = int(self.t // 30)
        olas = sum(1 for a, b in self.olas if a <= self.t <= b)
        for mundo, ms in self.mundos.items():
            for acc_id in ms.accesos:
                self.lecturas_pendientes.append(dict(
                    corrida_id=self.corrida_id, mundo=mundo, acceso_id=acc_id, ts_sim=ts,
                    camiones_en_fila=len(ms.accesos[acc_id].en_fila),
                    espera_min=ms.espera_estimada(acc_id),
                    llegadas_hora=ms.llegadas_hora(acc_id),
                    atendidos_hora=ms.atendidos_hora(acc_id),
                    buques_atracados=olas,
                    citas_franja=self.demanda_conocida[(acc_id, franja)],
                    clima=self.clima,
                ))

    def vaciar_pendientes(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Entrega (y limpia) lecturas y eventos por escribir en la BD."""
        lecturas, self.lecturas_pendientes = self.lecturas_pendientes, []
        eventos, self.eventos_pendientes = self.eventos_pendientes, []
        return lecturas, eventos

    # ───────────── Eventos ─────────────
    def aplicar_evento(self, ev: EventoCreate, generar_ola: bool = True) -> EventoOut:
        p = dict(ev.payload)
        if ev.tipo in (TipoEventoSim.cierre_acceso, TipoEventoSim.reapertura):
            if ev.acceso_id not in self.mundos[Mundo.A].accesos:
                raise ValueError(f"acceso_id inválido: {ev.acceso_id}")
            for mundo in self.mundos.values():
                (mundo.cerrar if ev.tipo == TipoEventoSim.cierre_acceso else mundo.reabrir)(ev.acceso_id)
        elif ev.tipo == TipoEventoSim.buque_atraca and generar_ola:
            cont = int(p.setdefault("contenedores", 800))
            self._seq_evento += 1
            self._alimentar(ola_buque(self.esc, self._rng_eventos, f"BM{self._seq_evento:03d}", self.t, cont))
            b = self.esc.buques
            self.olas.append((self.t + 60 * b.ola_horas[0], self.t + 60 * b.ola_horas[1]))
        elif ev.tipo == TipoEventoSim.norte:
            dur = float(p.setdefault("duracion_h", self.esc.norte.duracion_h))
            factor = float(p.setdefault("factor_servicio", self.esc.norte.factor_servicio))
            self.clima, self.fin_norte = Clima.norte, self.t + dur * 60
            for mundo in self.mundos.values():
                mundo.factor_servicio = factor
        elif ev.tipo == TipoEventoSim.carga_urgente:
            n = int(p.setdefault("camiones", 10))
            tipo = TipoCarga(p.setdefault("tipo_carga", TipoCarga.refrigerado))
            self._seq_evento += 1
            planes = [
                crear_camion(self.esc, self._rng_eventos, f"U{self._seq_evento:03d}-{i:03d}",
                             self.t + self._rng_eventos.uniform(20, 90), acceso_id=ev.acceso_id,
                             tipo_carga=tipo, origen="urgente", prioritario=True)
                for i in range(n)
            ]
            self._alimentar(planes)
        self._seq_evento += 1
        out = EventoOut(id=self._seq_evento, tipo=ev.tipo, acceso_id=ev.acceso_id, ts_sim=self.ts(), payload=p)
        self.eventos_recientes.appendleft(out)
        self.eventos_pendientes.append(
            dict(corrida_id=self.corrida_id, tipo=ev.tipo, acceso_id=ev.acceso_id, ts_sim=out.ts_sim, payload=p)
        )
        self._publicar(WsEvento(data=out))
        return out

    def _terminar_norte(self) -> None:
        self.clima, self.fin_norte = Clima.normal, None
        for mundo in self.mundos.values():
            mundo.factor_servicio = 1.0

    # ───────────── Citas (M3) ─────────────
    def inyectar_cita(
        self, cita_id: int, acceso_id: str, inicio: datetime, tipo_carga: TipoCarga, es_demo: bool = False
    ) -> str:
        """Agrega a ambos mundos el camión de una cita real (en B llega en su ventana)."""
        rng = random.Random(cita_id)
        plan = crear_camion(self.esc, rng, f"C{cita_id:05d}", max(self.t, self.a_minuto(inicio)),
                            acceso_id=acceso_id, tipo_carga=tipo_carga, origen="cita")
        plan.cita_id, plan.es_demo, plan.con_cita, plan.no_show, plan.cumple = cita_id, es_demo, True, False, True
        self._alimentar([plan])
        return plan.id

    # ───────────── KPIs ─────────────
    def kpis(self, mundo: Mundo) -> Kpis:
        ms = self.mundos[mundo]
        horas = (ms.esperas_total + ms.esperas_en_curso()) / 60
        return Kpis(
            espera_prom_min=round(ms.esperas_total / ms.atendidos, 1) if ms.atendidos else 0.0,
            espera_max_min=round(ms.espera_max, 1),
            horas_camion_espera=round(horas, 1),
            camiones_atendidos=ms.atendidos,
            pico_fila=ms.pico_fila,
        )

    def comparacion(self, ka: Kpis | None = None, kb: Kpis | None = None) -> KpisComparacion:
        ka, kb = ka or self.kpis(Mundo.A), kb or self.kpis(Mundo.B)
        horas = max(0.0, ka.horas_camion_espera - kb.horas_camion_espera)
        imp = self.esc.impacto
        diesel = horas * imp.diesel_ralenti_l_h

        def pct(a: float, b: float) -> float:
            return round(100 * (a - b) / a, 1) if a > 0 else 0.0

        return KpisComparacion(
            horas_ahorradas=round(horas, 1),
            diesel_l_evitado=round(diesel, 1),
            costo_mxn_evitado=round(horas * imp.costo_hora_camion_mxn, 0),  # costo integral de la hora parada
            co2_kg_evitado=round(diesel * imp.co2_kg_por_l, 1),
            reduccion_espera_pct=pct(ka.espera_prom_min, kb.espera_prom_min),
            reduccion_pico_fila_pct=pct(ka.pico_fila, kb.pico_fila),
        )

    def kpis_response(self) -> KpisResponse:
        ka, kb = self.kpis(Mundo.A), self.kpis(Mundo.B)
        return KpisResponse(ts_sim=self.ts(), A=ka, B=kb, comparacion=self.comparacion(ka, kb))

    # ───────────── Snapshots ─────────────
    def estado_accesos(self, mundo: Mundo) -> list[AccesoEstado]:
        ms = self.mundos[mundo]
        res = []
        for acc_id, a in ms.accesos.items():
            espera = ms.espera_estimada(acc_id)
            sem = semaforo_de(espera, self.cfg.semaforo_amarillo_min, self.cfg.semaforo_rojo_min)
            res.append(AccesoEstado(
                acceso_id=acc_id, estado=a.estado, en_fila=len(a.en_fila), en_revision=a.en_revision,
                espera_min=espera, semaforo="rojo" if a.estado == EstadoAcceso.cerrado else sem,
                atendidos_hora=ms.atendidos_hora(acc_id),
            ))
        return res

    def _mundo_estado(self, mundo: Mundo) -> MundoEstado:
        ms = self.mundos[mundo]
        visibles = [c for c in ms.camiones.values() if c.estado in VISIBLES]
        visibles.sort(key=lambda c: (not c.plan.es_demo, c.estado != EstadoCamion.en_fila))
        tope = self.cfg.sim_max_camiones_visibles
        return MundoEstado(
            camiones=[
                CamionEstado(id=c.plan.id, acceso_id=c.acceso_id, ruta_id=c.ruta_id, progreso=round(ms.progreso(c), 3),
                             estado=c.estado, tipo_carga=c.plan.tipo_carga, cita_id=c.plan.cita_id,
                             es_demo=c.plan.es_demo)
                for c in visibles[:tope]
            ],
            camiones_ocultos=max(0, len(visibles) - tope),
            accesos=self.estado_accesos(mundo),
            kpis=self.kpis(mundo),
        )

    def snapshot(self) -> SimSnapshot:
        ma, mb = self._mundo_estado(Mundo.A), self._mundo_estado(Mundo.B)
        return SimSnapshot(
            corrida_id=self.corrida_id, tick=self.tick, ts_sim=self.ts(), velocidad=self.velocidad,
            estado=self.estado, clima=self.clima, mundos={Mundo.A: ma, Mundo.B: mb},
            comparacion=self.comparacion(ma.kpis, mb.kpis), eventos_recientes=list(self.eventos_recientes),
            etiqueta=self.cfg.etiqueta_simulacion,
        )

    def estado_out(self) -> SimEstadoOut:
        return SimEstadoOut(corrida_id=self.corrida_id, estado=self.estado, velocidad=self.velocidad,
                            semilla=self.semilla, ts_sim=self.ts())

    # ───────────── Publicación (WebSocket) ─────────────
    def _publicar(self, msg: WsSnapshot | WsEvento) -> None:
        if self.publicador is not None:
            self.publicador(msg.model_dump_json())

    def publicar_snapshot(self) -> SimSnapshot:
        snap = self.snapshot()
        self._publicar(WsSnapshot(data=snap))
        return snap
