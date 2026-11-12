"""Pronóstico en vivo: espera esperada por acceso en las próximas 12 h, en franjas de 30 min.

Usa el modelo entrenado si existe (balance de flujo + corrección aprendida); si no, solo el balance de flujo.
"""
import logging
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from app.modulos.pronostico.dominio.features import (
    COLUMNAS,
    FRANJA_MIN,
    HORIZONTES,
    capacidad_franja,
    espera_de_fila,
    proyeccion_fluida,
)
from app.modulos.pronostico.entrenar import RUTA_MODELO
from app.modulos.simulacion.dominio.escenario import escenario_actual
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import Clima, EstadoAcceso, Mundo, semaforo_de
from app.nucleo.contracts.schemas import FranjaPronostico, PronosticoOut
from app.nucleo.puertos import EstadoOperacion

log = logging.getLogger("fluport.prediccion")
VERSION_RESPALDO = "balance-flujo-v1"


class Pronosticador:
    def __init__(self) -> None:
        self.cfg = get_settings()
        self.paquete: dict | None = None
        self.cache: dict[Mundo, list[PronosticoOut]] = {}
        self.t_cache: float = -1e9
        self.cargar()

    # ───────────── Modelo ─────────────
    def cargar(self) -> bool:
        if RUTA_MODELO.exists():
            try:
                paquete = joblib.load(RUTA_MODELO)
                actuales = sorted(a.id for a in escenario_actual().accesos)
                if paquete.get("accesos") != actuales:
                    # el modelo se entrenó con otras entradas: se descarta para que se reentrene con las actuales
                    log.warning("El modelo se entrenó con %s y el escenario tiene %s: se usa balance de flujo hasta "
                                "reentrenar", paquete.get("accesos"), actuales)
                    self.paquete = None
                    return False
                self.paquete = paquete
                log.info("Modelo de pronóstico cargado: %s", self.paquete["metricas"]["version"])
                return True
            except Exception:  # noqa: BLE001
                log.exception("No se pudo cargar %s; se usa balance de flujo", RUTA_MODELO)
        self.paquete = None
        return False

    @property
    def version(self) -> str:
        return self.paquete["metricas"]["version"] if self.paquete else VERSION_RESPALDO

    @property
    def metricas(self) -> dict | None:
        return self.paquete["metricas"] if self.paquete else None

    # ───────────── Predicción ─────────────
    def calcular(self, sim: EstadoOperacion, mundo: Mundo) -> list[PronosticoOut]:
        ms = sim.mundos[mundo]
        franja0 = int(sim.t // FRANJA_MIN)
        norte = sim.clima == Clima.norte
        factor = ms.factor_servicio
        ids = [a.id for a in sim.esc.accesos]
        res: list[PronosticoOut] = []
        for acc in sim.esc.accesos:
            av = ms.accesos[acc.id]
            # llegadas conocidas por franja: las agendadas por el planificador de Fluport
            fuente = ms.planificador.ocupacion if ms.planificador else sim.demanda_conocida
            llegadas = [fuente[(acc.id, franja0 + k)] for k in range(1, len(HORIZONTES) + 1)]
            cap = capacidad_franja(acc.carriles, acc.tiempo_servicio_min, factor)
            capacidades = [cap] * len(HORIZONTES)
            if av.estado == EstadoAcceso.cerrado:  # supuesto: sigue cerrado al menos la próxima hora
                capacidades[0] = capacidades[1] = 0.0
            q = proyeccion_fluida(len(av.en_fila), llegadas, capacidades)
            fluida = np.array([espera_de_fila(x, acc.carriles, acc.tiempo_servicio_min, factor) for x in q])
            esperas = fluida
            if self.paquete:
                filas = []
                for k, h in enumerate(HORIZONTES):
                    t_obj = sim.ts(sim.t + h)
                    franja = franja0 + k + 1
                    filas.append([
                        ids.index(acc.id), 1, h, t_obj.hour + t_obj.minute / 60,
                        t_obj.weekday(), len(av.en_fila), ms.espera_estimada(acc.id), ms.llegadas_hora(acc.id),
                        ms.atendidos_hora(acc.id), float(norte), sim.demanda_conocida[(acc.id, franja)],
                        sum(1 for a, b in sim.olas if a <= sim.t + h <= b), fluida[k], acc.carriles,
                        acc.tiempo_servicio_min,
                    ])
                x = pd.DataFrame(filas, columns=COLUMNAS)
                esperas = np.clip(self.paquete["modelo"].predict(x) + fluida, 0, None)
            res.append(PronosticoOut(
                acceso_id=acc.id, generado_en=sim.ts(), modelo_version=self.version, franja_min=FRANJA_MIN,
                franjas=[
                    FranjaPronostico(
                        inicio=sim.ts((franja0 + k + 1) * FRANJA_MIN), espera_min=round(float(e), 1),
                        semaforo=semaforo_de(float(e), self.cfg.semaforo_amarillo_min, self.cfg.semaforo_rojo_min),
                    )
                    for k, e in enumerate(esperas)
                ],
            ))
        return res

    def obtener(self, sim: EstadoOperacion, mundo: Mundo = Mundo.B, max_edad_min: float = 15.0) -> list[PronosticoOut]:
        """Pronóstico con caché: se recalcula si pasaron más de `max_edad_min` minutos simulados."""
        if sim.t - self.t_cache >= max_edad_min or mundo not in self.cache or self.t_cache > sim.t:
            self.cache = {m: self.calcular(sim, m) for m in Mundo}
            self.t_cache = sim.t
        return self.cache[mundo]

    def espera_en(self, sim: EstadoOperacion, acceso_id: str, cuando: datetime, mundo: Mundo = Mundo.B) -> float | None:
        """Espera pronosticada para un acceso en un instante (para sugerir horarios en M3)."""
        for p in self.obtener(sim, mundo):
            if p.acceso_id == acceso_id:
                for f in p.franjas:
                    if f.inicio <= cuando < f.inicio + pd.Timedelta(minutes=FRANJA_MIN):
                        return f.espera_min
        return None


pronosticador = Pronosticador()


def entrenar_y_cargar() -> None:
    """Entrena el modelo con datos históricos, lo carga y descarta la caché (gancho de la simulación)."""
    from app.modulos.pronostico.entrenar import (
        entrenar,  # el entrenamiento pesa: se importa solo si hace falta
    )

    entrenar()
    pronosticador.cargar()
    pronosticador.t_cache = -1e9
