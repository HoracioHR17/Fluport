"""Vista pública para vecinos (M7): semáforo actual y horas pico previstas por caseta.

Solo expone información agregada de tráfico; nunca citas, transportistas ni la comparación A/B.
`contingencia` resume el estado de cada entrada (normal, lenta, saturada o cerrada) y `norte` el clima.
Se usa el Mundo B (operación con Fluport).
"""
from datetime import timedelta

from app.modulos.pronostico.pronosticador import pronosticador
from app.nucleo.colas import FRANJA_MIN
from app.nucleo.contracts.enums import Clima, EstadoAcceso, Mundo, Semaforo
from app.nucleo.contracts.schemas import HoraPico, PronosticoOut, ZonaPublica
from app.nucleo.puertos import Operacion

GRAVEDAD = {Semaforo.verde: 0, Semaforo.amarillo: 1, Semaforo.rojo: 2}
CONTINGENCIA = {Semaforo.verde: "normal", Semaforo.amarillo: "lenta", Semaforo.rojo: "saturada"}


def horas_pico(p: PronosticoOut) -> list[HoraPico]:
    """Une franjas consecutivas con semáforo amarillo o rojo en intervalos."""
    picos: list[HoraPico] = []
    actual: HoraPico | None = None
    for f in p.franjas:
        fin = f.inicio + timedelta(minutes=FRANJA_MIN)
        if f.semaforo == Semaforo.verde:
            actual = None
            continue
        if actual is not None and actual.fin == f.inicio:
            actual.fin = fin
            actual.espera_max_min = max(actual.espera_max_min, f.espera_min)
            if GRAVEDAD[f.semaforo] > GRAVEDAD[actual.semaforo]:
                actual.semaforo = f.semaforo
        else:
            actual = HoraPico(inicio=f.inicio, fin=fin, semaforo=f.semaforo, espera_max_min=f.espera_min)
            picos.append(actual)
    return picos


def snapshot_publico(sim: Operacion) -> dict:
    """Estado instantáneo de las entradas para la vista pública, con la misma forma que el snapshot del simulador
    (`{"tipo": "snapshot", "data": {"ts_sim", "clima", "mundos": {"B": {"accesos": [...]}}}}`) pero sin camiones,
    agencias, citas, avisos ni la comparación A/B."""
    return {"tipo": "snapshot", "data": {
        "ts_sim": sim.ts().isoformat(), "clima": sim.clima.value,
        "mundos": {"B": {"accesos": [e.model_dump(mode="json") for e in sim.estado_accesos(Mundo.B)]}},
    }}


def zonas(sim: Operacion) -> list[ZonaPublica]:
    estados = {e.acceso_id: e for e in sim.estado_accesos(Mundo.B)}
    pron = {p.acceso_id: p for p in pronosticador.obtener(sim, Mundo.B)}
    res = []
    for a in sim.esc.accesos:
        e, p = estados[a.id], pron[a.id]
        futuras = [f for f in p.franjas if f.inicio >= sim.ts()]  # el pronóstico en caché puede tener franjas ya pasadas
        mejor = min(futuras, key=lambda f: (f.espera_min, f.inicio)) if futuras else None
        abierto = e.estado == EstadoAcceso.abierto
        res.append(ZonaPublica(
            acceso_id=a.id, nombre=a.nombre, zona=a.zona, semaforo=e.semaforo, espera_min=e.espera_min,
            abierto=abierto, en_fila=e.en_fila, horas_pico=horas_pico(p),
            contingencia=CONTINGENCIA[e.semaforo] if abierto else "cerrada", norte=sim.clima == Clima.norte,
            mejor_hora=mejor.inicio if mejor else None, actualizado_en=sim.ts(), etiqueta=sim.cfg.etiqueta_simulacion,
        ))
    return res
