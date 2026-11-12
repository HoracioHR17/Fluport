"""Enumeraciones compartidas por BD, API y WebSocket (contrato M0)."""
from enum import StrEnum


class EstadoAcceso(StrEnum):
    abierto = "abierto"
    cerrado = "cerrado"


class TipoCarga(StrEnum):
    contenedor_20 = "contenedor_20"
    contenedor_40 = "contenedor_40"
    refrigerado = "refrigerado"
    peligroso = "peligroso"
    granel = "granel"
    carga_general = "carga_general"


class EstadoCita(StrEnum):
    agendada = "agendada"
    en_ruta = "en_ruta"
    cumplida = "cumplida"
    no_show = "no_show"
    reprogramada = "reprogramada"
    cancelada = "cancelada"


class OrigenCita(StrEnum):
    web = "web"
    telegram = "telegram"
    asistente = "asistente"
    simulador = "simulador"


class Mundo(StrEnum):
    B = "B"  # operación con Fluport (llegada según cita sugerida); único mundo simulado


class EstadoCamion(StrEnum):
    en_ruta = "en_ruta"
    en_fila = "en_fila"
    en_revision = "en_revision"
    dentro = "dentro"
    saliendo = "saliendo"


class Semaforo(StrEnum):
    verde = "verde"
    amarillo = "amarillo"
    rojo = "rojo"


class EstadoBuque(StrEnum):
    programado = "programado"
    atracado = "atracado"
    zarpado = "zarpado"


class TipoEventoSim(StrEnum):
    buque_atraca = "buque_atraca"
    norte = "norte"
    cierre_acceso = "cierre_acceso"
    reapertura = "reapertura"
    carga_urgente = "carga_urgente"
    personalizado = "personalizado"  # reservado para el giro del jueves


class EstadoSim(StrEnum):
    corriendo = "corriendo"
    pausada = "pausada"
    detenida = "detenida"


class TipoCorrida(StrEnum):
    vivo = "vivo"
    historico = "historico"


class Canal(StrEnum):
    telegram = "telegram"
    web = "web"
    sms = "sms"  # avisos para transportistas sin smartphone (solo salida)


class CanalAviso(StrEnum):
    """Canal por el que la agencia decide avisarle a cada transportista."""

    telegram = "telegram"
    sms = "sms"


class EstadoAviso(StrEnum):
    pendiente = "pendiente"
    enviado = "enviado"
    fallido = "fallido"


class Clima(StrEnum):
    normal = "normal"
    lluvia = "lluvia"
    norte = "norte"


def semaforo_de(espera_min: float, amarillo: float = 30.0, rojo: float = 90.0) -> Semaforo:
    """Regla única del semáforo: verde (Fluye) < 30 min · amarillo (Lento) 30–90 · rojo (Saturado) > 90."""
    if espera_min < amarillo:
        return Semaforo.verde
    if espera_min <= rojo:
        return Semaforo.amarillo
    return Semaforo.rojo
