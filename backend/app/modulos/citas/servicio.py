"""Lógica de citas (M3): sugerir horarios, agendar, reprogramar, cancelar y medir cumplimiento.

Las horas de las citas están en **tiempo simulado** (el reloj del simulador).
Cada cita creada o reprogramada se inyecta en el simulador (llega en su ventana en el Mundo B).
"""
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.pronostico.pronosticador import pronosticador
from app.nucleo.corredores import rodeo_min
from app.nucleo.colas import FRANJA_MIN
from app.nucleo.contracts.enums import EstadoCita, Mundo, OrigenCita, semaforo_de
from app.nucleo.contracts.schemas import (
    CitaCreate,
    CitaOut,
    CitaReprogramar,
    ResumenCitas,
    Sugerencia,
    SugerenciaRequest,
)
from app.nucleo.db.base import SessionLocal
from app.nucleo.db.models import Agencia, Cita, Transportista
from app.nucleo.puertos import Operacion

ACTIVAS = (EstadoCita.agendada, EstadoCita.en_ruta)
TRAMO_EMPATE_MIN = 5.0  # al ordenar sugerencias, esperas dentro del mismo tramo de 5 min empatan


class ErrorCita(Exception):
    """Error de negocio con su código HTTP."""

    def __init__(self, codigo: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def normalizar_telefono(tel: str) -> str:
    """'+52 229 123 4567' → '+522291234567' (formato de la BD).

    Los celulares de México pueden llegar como +521 + 10 dígitos (formato móvil anterior que aún comparten
    algunas apps, incluido el contacto de Telegram) o +52 + 10 dígitos: ambos se guardan como +52 + 10 dígitos
    para que sean el mismo transportista.
    """
    digitos = re.sub(r"\D", "", tel)
    if len(digitos) < 10:
        raise ErrorCita(422, "teléfono inválido")
    if len(digitos) == 13 and digitos.startswith("521"):
        digitos = "52" + digitos[3:]
    elif len(digitos) == 10:  # número nacional sin lada de país: se asume México (E.164 +52)
        digitos = "52" + digitos
    return "+" + digitos


# ───────────────────────────── Estimación de espera ─────────────────────────────
def espera_estimada(sim: Operacion, acceso_id: str, inicio: datetime) -> float:
    """Espera prevista para llegar a `acceso_id` en `inicio` (Mundo B).

    Dentro de 12 h usa el pronóstico; más allá, la carga agendada por el planificador vs. la capacidad.
    """
    pron = pronosticador.espera_en(sim, acceso_id, inicio, Mundo.B)
    if pron is not None:
        return pron
    return sim.espera_por_agenda(acceso_id, inicio)


def sugerir(sim: Operacion, req: SugerenciaRequest) -> list[Sugerencia]:
    """Los mejores horarios (franjas de 30 min) dentro de [desde, hasta]: menor espera prevista primero."""
    ahora = sim.ts()
    desde = max(req.desde, ahora)
    if req.hasta <= desde:
        raise ErrorCita(422, "la ventana solicitada ya pasó en el reloj de la simulación")
    abiertos = [a.id for a in sim.esc.accesos if sim.acceso_abierto(a.id)]
    if req.acceso_id is not None:
        sim.esc.acceso(req.acceso_id)  # KeyError → 404 en la API
        accesos = [req.acceso_id] if req.acceso_id in abiertos else abiertos
    else:
        accesos = abiertos
    if not accesos:
        raise ErrorCita(409, "no hay accesos abiertos")

    # corredor de origen: el que dijo o el de la entrada pedida; otro corredor cobra el rodeo (manejo extra)
    origen = req.origen or (sim.esc.acceso(req.acceso_id).entrada if req.acceso_id else None)
    f_ini = int(sim.a_minuto(desde) // FRANJA_MIN)
    f_fin = int(sim.a_minuto(req.hasta) // FRANJA_MIN)
    centro = req.desde + (req.hasta - req.desde) / 2
    # (puntaje, distancia a lo pedido, acceso, inicio, espera)
    candidatos: list[tuple[float, float, str, datetime, float]] = []
    for f in range(f_ini, f_fin + 1):
        inicio = sim.ts(f * FRANJA_MIN)
        if inicio + timedelta(minutes=FRANJA_MIN) <= desde or inicio >= req.hasta:
            continue
        for a in accesos:
            espera = espera_estimada(sim, a, inicio)
            cambio = 5.0 if req.acceso_id and a != req.acceso_id else 0.0  # preferencia leve por el acceso pedido
            cambio += rodeo_min(origen, sim.esc.acceso(a).entrada)
            # desempate: la franja más cercana a la hora que mencionó el transportista (centro de la ventana)
            # o, si no dio hora, la más próxima
            ref = desde if req.preferencia == "temprano" else centro
            distancia = abs((inicio - ref).total_seconds()) / 3600
            candidatos.append((espera + cambio, distancia, a, inicio, espera))
    if not candidatos:
        raise ErrorCita(422, "ventana demasiado corta")
    pico = max(c[4] for c in candidatos)
    # esperas que difieren menos de 5 min se consideran iguales: decide la cercanía a la hora pedida
    candidatos.sort(key=lambda c: (round(c[0] / TRAMO_EMPATE_MIN), c[1], c[0]))
    cfg = sim.cfg
    return [
        Sugerencia(
            acceso_id=a, inicio=inicio, fin=inicio + timedelta(minutes=req.duracion_min),
            espera_min_est=round(espera, 1),
            semaforo=semaforo_de(espera, cfg.semaforo_amarillo_min, cfg.semaforo_rojo_min),
            ahorro_vs_pico_min=round(pico - espera, 1),
        )
        for _, _, a, inicio, espera in candidatos[: req.max_resultados]
    ]


# ───────────────────────────── Persistencia ─────────────────────────────
def _transportista(db: Session, telefono: str | None, transportista_id: int | None, alias: str | None,
                   agencia_id: str | None = None) -> Transportista:
    if transportista_id is not None:
        t = db.get(Transportista, transportista_id)
        if t is None:
            raise ErrorCita(404, f"transportista {transportista_id} no existe")
        return t
    tel = normalizar_telefono(telefono or "")
    t = db.scalar(select(Transportista).where(Transportista.telefono == tel))
    if t is None:
        if agencia_id is not None and db.get(Agencia, agencia_id) is None:
            raise ErrorCita(404, f"agencia {agencia_id} no existe")
        t = Transportista(alias=alias or f"Transportista {tel[-4:]}", telefono=tel, es_demo=True,
                          agencia_id=agencia_id)
        db.add(t)
        db.flush()
    return t


def _validar_ventana(sim: Operacion, acceso_id: str, inicio: datetime) -> None:
    try:
        sim.esc.acceso(acceso_id)
    except KeyError:
        raise ErrorCita(404, f"acceso {acceso_id} no existe") from None
    if not sim.acceso_abierto(acceso_id):
        raise ErrorCita(409, f"el acceso {acceso_id} está cerrado")
    if inicio < sim.ts() - timedelta(minutes=FRANJA_MIN):
        raise ErrorCita(422, "la ventana ya pasó en el reloj de la simulación")


def crear(db: Session, sim: Operacion, body: CitaCreate, cita_anterior_id: int | None = None) -> CitaOut:
    _validar_ventana(sim, body.acceso_id, body.ventana_inicio)
    t = _transportista(db, body.telefono, body.transportista_id, body.alias, body.agencia_id)
    cita = Cita(
        transportista_id=t.id, acceso_id=body.acceso_id, ventana_inicio=body.ventana_inicio,
        ventana_fin=body.ventana_fin, tipo_carga=body.tipo_carga,
        prioridad=1 if body.tipo_carga in sim.esc.cargas_prioritarias else 0,
        estado=EstadoCita.agendada, origen=body.origen,
        espera_estimada_min=espera_estimada(sim, body.acceso_id, body.ventana_inicio),
        cita_anterior_id=cita_anterior_id,
        # la cita que asigna la agencia es obligatoria para el transportista: queda en firme sin pedirle confirmación
        confirmada_en=datetime.now().astimezone() if body.origen == OrigenCita.web else None,
    )
    db.add(cita)
    db.flush()
    sim.inyectar_cita(cita.id, cita.acceso_id, cita.ventana_inicio, cita.tipo_carga, es_demo=t.es_demo,
                      agencia_id=t.agencia_id)
    db.commit()
    return CitaOut.model_validate(cita)


def obtener(db: Session, cita_id: int) -> Cita:
    cita = db.get(Cita, cita_id)
    if cita is None:
        raise ErrorCita(404, f"cita {cita_id} no existe")
    return cita


def listar(
    db: Session, telefono: str | None = None, transportista_id: int | None = None,
    acceso_id: str | None = None, estado: EstadoCita | None = None, limite: int = 100,
    agencia_id: str | None = None,
) -> list[CitaOut]:
    q = select(Cita).order_by(Cita.ventana_inicio).limit(limite)
    if agencia_id is not None:
        q = q.where(Cita.transportista_id.in_(select(Transportista.id).where(Transportista.agencia_id == agencia_id)))
    if telefono is not None:
        q = q.join(Transportista).where(Transportista.telefono == normalizar_telefono(telefono))
    if transportista_id is not None:
        q = q.where(Cita.transportista_id == transportista_id)
    if acceso_id is not None:
        q = q.where(Cita.acceso_id == acceso_id)
    if estado is not None:
        q = q.where(Cita.estado == estado)
    return [CitaOut.model_validate(c) for c in db.scalars(q)]


def reprogramar(db: Session, sim: Operacion, cita_id: int, body: CitaReprogramar) -> CitaOut:
    """Crea una cita nueva ligada a la anterior y marca la original como reprogramada."""
    original = obtener(db, cita_id)
    if original.estado != EstadoCita.agendada:
        raise ErrorCita(409, f"solo se reprograman citas agendadas (estado actual: {original.estado.value})")
    if not sim.cancelar_cita(original.id) and sim.tiene_cita(original.id):
        raise ErrorCita(409, "el camión ya va en camino")
    original.estado = EstadoCita.reprogramada
    nueva = CitaCreate(
        transportista_id=original.transportista_id, acceso_id=body.acceso_id or original.acceso_id,
        ventana_inicio=body.ventana_inicio, ventana_fin=body.ventana_fin,
        tipo_carga=original.tipo_carga, origen=original.origen,
    )
    try:
        return crear(db, sim, nueva, cita_anterior_id=original.id)
    except ErrorCita:
        db.rollback()
        raise


def cancelar(db: Session, sim: Operacion, cita_id: int) -> CitaOut:
    cita = obtener(db, cita_id)
    if cita.estado not in ACTIVAS:
        raise ErrorCita(409, f"la cita no está activa (estado: {cita.estado.value})")
    if not sim.cancelar_cita(cita.id) and sim.tiene_cita(cita.id):
        raise ErrorCita(409, "el camión ya va en camino")
    cita.estado = EstadoCita.cancelada
    db.commit()
    return CitaOut.model_validate(cita)


def resumen(db: Session, agencia_id: str | None = None) -> ResumenCitas:
    q = select(Cita)
    if agencia_id is not None:
        q = q.join(Transportista).where(Transportista.agencia_id == agencia_id)
    citas = list(db.scalars(q))
    por_estado = Counter(c.estado for c in citas)
    cumplidas, faltas = por_estado[EstadoCita.cumplida], por_estado[EstadoCita.no_show]
    return ResumenCitas(
        total=len(citas),
        por_estado={e: por_estado.get(e, 0) for e in EstadoCita},
        cumplimiento_pct=round(100 * cumplidas / (cumplidas + faltas), 1) if cumplidas + faltas else 0.0,
        por_acceso=dict(Counter(c.acceso_id for c in citas)),
    )


def aplicar_cambios(db: Session, cambios: list[tuple[int, str]]) -> None:
    """Actualiza en la BD el estado de citas según lo ocurrido en el simulador (en_ruta, cumplida)."""
    for cita_id, estado in cambios:
        cita = db.get(Cita, cita_id)
        if cita is not None and cita.estado in ACTIVAS:
            cita.estado = EstadoCita(estado)
    db.commit()


def marcar_no_shows(db: Session, ahora: datetime, tolerancia_min: float = 60) -> int:
    """Citas agendadas cuya ventana terminó hace más de `tolerancia_min` sin que el camión saliera."""
    limite = ahora - timedelta(minutes=tolerancia_min)
    vencidas = list(db.scalars(select(Cita).where(Cita.estado == EstadoCita.agendada, Cita.ventana_fin < limite)))
    for c in vencidas:
        c.estado = EstadoCita.no_show
    db.commit()
    return len(vencidas)


def citas_por_reinyectar(db: Session, ahora: datetime) -> list[dict]:
    """Citas activas cuya ventana aún no pasa (para volver a inyectarlas tras un reset del simulador)."""
    res = []
    for c in db.scalars(select(Cita).where(Cita.estado.in_(ACTIVAS), Cita.ventana_fin >= ahora)):
        t = db.get(Transportista, c.transportista_id)
        c.estado = EstadoCita.agendada
        res.append(dict(cita_id=c.id, acceso_id=c.acceso_id, inicio=c.ventana_inicio, tipo_carga=c.tipo_carga,
                        es_demo=bool(t and t.es_demo), agencia_id=t.agencia_id if t else None))
    db.commit()
    return res


# ───────────────────────────── Ganchos de la operación ─────────────────────────────
def reinyectar_desde_bd(ahora: datetime) -> list[dict]:
    """Citas activas por volver a registrar en la operación tras un reinicio (gancho de la simulación)."""
    with SessionLocal() as db:
        return citas_por_reinyectar(db, ahora)


def sincronizar_desde_operacion(cambios: list[tuple[int, str]], ahora: datetime) -> None:
    """Aplica los cambios de estado que reportó la operación y marca las faltas (gancho de la simulación)."""
    with SessionLocal() as db:
        if cambios:
            aplicar_cambios(db, cambios)
        marcar_no_shows(db, ahora)
