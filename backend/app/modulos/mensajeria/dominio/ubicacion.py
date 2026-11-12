"""Entradas cercanas a una ubicación (M5): distancia y estado actual de cada punto de acceso.

La distancia es en línea recta (fórmula del haversine); el tiempo de manejo se estima con un factor de rodeo y una
velocidad media (supuestos). La recomendación combina manejo + espera actual en la fila del Mundo B (con Fluport).
La ubicación del usuario no se guarda: solo se usa para este cálculo.
"""
from dataclasses import dataclass
from math import asin, cos, inf, radians, sin, sqrt

from app.nucleo.contracts.enums import EstadoAcceso, Mundo
from app.nucleo.puertos import Operacion

RADIO_TIERRA_KM = 6371.0
FACTOR_RUTA = 1.3  # SUPUESTO: la ruta por carretera es ~30 % más larga que la línea recta
VELOCIDAD_KMH = 35.0  # SUPUESTO: velocidad media de un tractocamión en la zona conurbada
LEJOS_KM = 60.0  # a partir de aquí el tiempo de manejo deja de ser confiable
GRAVEDAD = {"verde": 0, "amarillo": 1, "rojo": 2, "cerrada": 3}


@dataclass(frozen=True)
class EntradaCercana:
    acceso_id: str
    nombre: str
    entrada: str
    distancia_km: float
    manejo_min: float
    abierta: bool
    espera_min: float
    semaforo: str
    en_fila: int

    @property
    def estado(self) -> str:
        """verde | amarillo | rojo | cerrada"""
        return self.semaforo if self.abierta else "cerrada"

    @property
    def total_min(self) -> float:
        """Manejo + fila; infinito si está cerrada."""
        return self.manejo_min + self.espera_min if self.abierta else inf


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta entre dos puntos (haversine)."""
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_KM * asin(sqrt(a))


def coordenadas_validas(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


def cercanas(sim: Operacion, lat: float, lon: float) -> list[EntradaCercana]:
    """Todas las entradas ordenadas de la más cercana a la más lejana, con su estado actual."""
    estados = {e.acceso_id: e for e in sim.estado_accesos(Mundo.B)}
    res = []
    for a in sim.esc.accesos:
        e = estados[a.id]
        d = distancia_km(lat, lon, a.lat, a.lon)
        res.append(EntradaCercana(
            acceso_id=a.id, nombre=a.nombre, entrada=a.entrada, distancia_km=round(d, 1),
            manejo_min=round(d * FACTOR_RUTA / VELOCIDAD_KMH * 60, 1), abierta=e.estado == EstadoAcceso.abierto,
            espera_min=round(e.espera_min, 1), semaforo=e.semaforo.value, en_fila=e.en_fila,
        ))
    return sorted(res, key=lambda x: x.distancia_km)


def recomendada(lista: list[EntradaCercana]) -> EntradaCercana | None:
    """La entrada abierta con menor manejo + espera (None si todas están cerradas)."""
    abiertas = [x for x in lista if x.abierta]
    return min(abiertas, key=lambda x: (x.total_min, x.distancia_km)) if abiertas else None


def empeoro(antes: str | None, ahora: str) -> bool:
    """¿El estado pasó a uno más grave (p. ej. verde → rojo, o abierta → cerrada)?"""
    return antes is not None and GRAVEDAD[ahora] > GRAVEDAD[antes]
