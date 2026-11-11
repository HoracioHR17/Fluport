"""Planificador de Fluport: asigna a cada camión la franja de 30 min con menor carga prevista.

Lo usa el Mundo B y, más adelante, la API de citas (M3) para sugerir horarios.
"""
from collections import defaultdict

from app.sim.escenario import Escenario

FRANJA_MIN = 30


class Planificador:
    def __init__(self, esc: Escenario) -> None:
        self.esc = esc
        # (acceso_id, indice_franja) -> camiones agendados
        self.ocupacion: dict[tuple[str, int], int] = defaultdict(int)
        self.cerrados: set[str] = set()

    def capacidad_franja(self, acceso_id: str, factor_servicio: float = 1.0) -> float:
        acc = self.esc.acceso(acceso_id)
        return acc.capacidad_hora / factor_servicio * FRANJA_MIN / 60 * self.esc.ocupacion_objetivo_franja

    def carga(self, acceso_id: str, franja: int) -> float:
        return self.ocupacion[(acceso_id, franja)] / self.capacidad_franja(acceso_id)

    def candidatos(
        self, deseada: float, acceso_id: str | None, desde: float | None = None, hasta: float | None = None
    ) -> list[tuple[float, str, int]]:
        """Lista (puntaje, acceso, franja) ordenada; menor puntaje = mejor."""
        lo, hi = self.esc.ventana_reprogramacion_min
        desde = deseada + lo if desde is None else desde
        hasta = deseada + hi if hasta is None else hasta
        accesos = [acceso_id] if acceso_id and acceso_id not in self.cerrados else None
        if accesos is None:  # sin preferencia o acceso cerrado: cualquier acceso abierto
            accesos = [a.id for a in self.esc.accesos if a.id not in self.cerrados]
        res = []
        for f in range(int(max(desde, 0) // FRANJA_MIN), int(hasta // FRANJA_MIN) + 1):
            centro = f * FRANJA_MIN + FRANJA_MIN / 2
            for a in accesos:
                desplazamiento_h = abs(centro - deseada) / 60
                cambio_acceso = 0.0 if a == acceso_id else 0.3
                res.append((self.carga(a, f) + 0.15 * desplazamiento_h + cambio_acceso, a, f))
        res.sort()
        return res

    def asignar(self, deseada: float, acceso_id: str, prioritario: bool = False) -> tuple[str, float]:
        """Reserva la mejor franja y devuelve (acceso, minuto de inicio de la franja)."""
        if prioritario and acceso_id not in self.cerrados:
            f = int(deseada // FRANJA_MIN)  # la carga prioritaria conserva su horario
            self.ocupacion[(acceso_id, f)] += 1
            return acceso_id, deseada
        _, a, f = self.candidatos(deseada, acceso_id)[0]
        self.ocupacion[(a, f)] += 1
        return a, f * FRANJA_MIN

    def registrar(self, acceso_id: str, t: float) -> None:
        """Cuenta una llegada no planificada (camión que no sigue la sugerencia)."""
        self.ocupacion[(acceso_id, int(t // FRANJA_MIN))] += 1
