"""Generación de la demanda de camiones (idéntica para ambos mundos: números aleatorios comunes)."""
import math
import random
from dataclasses import dataclass

from app.modulos.simulacion.dominio.escenario import Escenario
from app.nucleo.contracts.enums import TipoCarga

MIN_DIA = 24 * 60


@dataclass(slots=True)
class CamionPlan:
    """Un camión con todos sus valores aleatorios ya sorteados.

    Los dos mundos reciben exactamente el mismo plan; solo cambia la política de llegada.
    """

    id: str
    acceso_id: str
    ruta_id: str
    tipo_carga: TipoCarga
    llegada_deseada: float  # minuto simulado en que llegaría sin Fluport
    ruta_min: float
    servicio_base: float  # minutos de revisión (antes del factor de clima)
    estancia_min: float
    retraso_min: float  # desvío respecto a la hora de cita (Mundo B)
    con_cita: bool
    no_show: bool  # solo aplica si tiene cita
    cumple: bool  # sigue la sugerencia de Fluport (solo si tiene cita)
    revision_aduanal: bool
    prioritario: bool
    cita_id: int | None = None
    cancelado: bool = False  # cita cancelada/reprogramada antes de salir: el camión no se presenta
    es_demo: bool = False
    origen: str = "base"  # base | buque | urgente | cita
    agencia_id: str | None = None  # agencia dueña del camión (vista de agencia)


def _lognormal(rng: random.Random, media: float, sigma: float) -> float:
    mu = math.log(media) - sigma**2 / 2
    return rng.lognormvariate(mu, sigma)


def _elegir(rng: random.Random, pesos: dict) -> object:
    claves = list(pesos)
    return rng.choices(claves, weights=[pesos[k] for k in claves], k=1)[0]


def crear_camion(
    esc: Escenario,
    rng: random.Random,
    id_: str,
    llegada: float,
    *,
    acceso_id: str | None = None,
    tipo_carga: TipoCarga | None = None,
    origen: str = "base",
    prioritario: bool | None = None,
) -> CamionPlan:
    if acceso_id is None:
        acceso_id = _elegir(rng, {a.id: a.participacion for a in esc.accesos})  # type: ignore[assignment]
    acc = esc.acceso(acceso_id)
    tipo = tipo_carga or _elegir(rng, esc.mezcla_carga)  # type: ignore[assignment]
    con_cita = rng.random() < esc.con_cita
    aduana = rng.random() < esc.revision_aduanal.prob
    estancia = rng.uniform(*esc.estancia_min) + (esc.revision_aduanal.extra_min if aduana else 0.0)
    return CamionPlan(
        id=id_,
        acceso_id=acc.id,
        ruta_id=rng.choice(acc.rutas).id,
        tipo_carga=tipo,
        llegada_deseada=llegada,
        ruta_min=rng.uniform(*esc.ruta_min),
        servicio_base=_lognormal(rng, acc.tiempo_servicio_min, esc.servicio_sigma),
        estancia_min=estancia,
        retraso_min=rng.gauss(0, esc.retraso_sigma_min),
        con_cita=con_cita,
        no_show=con_cita and rng.random() < esc.no_show,
        cumple=con_cita and rng.random() < esc.cumplimiento_sugerencia,
        revision_aduanal=aduana,
        prioritario=(tipo in esc.cargas_prioritarias) if prioritario is None else prioritario,
        origen=origen,
        agencia_id=esc.agencia_de(id_),
    )


def demanda_dia(esc: Escenario, semilla: int, dia: int) -> list[CamionPlan]:
    """Llegadas del día `dia` (Poisson no homogéneo por hora). Reproducible por (semilla, día)."""
    rng = random.Random(semilla * 10_007 + dia)
    perfil = esc.perfil_horario
    total_pesos = sum(perfil)
    camiones: list[CamionPlan] = []
    inicio_dia = dia * MIN_DIA
    for h in range(24):
        hora_real = (esc.inicio_hora + h) % 24  # el minuto 0 simulado corresponde a inicio_hora
        lam = esc.camiones_base_dia * perfil[hora_real] / total_pesos
        n = poisson(rng, lam)
        for _ in range(n):
            t = inicio_dia + h * 60 + rng.uniform(0, 60)
            camiones.append(crear_camion(esc, rng, f"T{dia:02d}-{len(camiones):04d}", t))
    camiones.sort(key=lambda c: c.llegada_deseada)
    return camiones


def ola_buque(
    esc: Escenario, rng: random.Random, prefijo: str, t_atraque: float, contenedores: int
) -> list[CamionPlan]:
    """Ola de demanda por un buque: camiones repartidos (triangular) en las horas siguientes."""
    n = int(contenedores * esc.buques.camiones_por_contenedor)
    a, b = esc.buques.ola_horas
    # moda temprana: la mayoría sale en el primer tercio de la ventana tras el atraque
    camiones = [
        crear_camion(
            esc, rng, f"{prefijo}-{i:04d}", t_atraque + 60 * rng.triangular(a, b, a + (b - a) / 3), origen="buque"
        )
        for i in range(n)
    ]
    camiones.sort(key=lambda c: c.llegada_deseada)
    return camiones


def poisson(rng: random.Random, lam: float) -> int:
    if lam > 30:  # aproximación normal para tasas altas
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1
