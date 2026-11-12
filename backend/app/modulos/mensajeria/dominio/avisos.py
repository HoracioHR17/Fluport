"""Avisos proactivos por mensaje (Telegram o WhatsApp) (M5).

Cada ciclo se revisan las citas activas de transportistas con teléfono y se generan, una sola vez por cita:
- `turno_30min`: faltan 30 min (o menos) para su cita.
- `saturacion`: su caseta está cerrada o tendrá mucha espera a la hora de la cita; se ofrece la mejor alternativa.
El cálculo usa el simulador (se ejecuta en el event loop); leer y escribir la BD se hace aparte.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modulos.citas.servicio import ErrorCita, espera_estimada, sugerir
from app.nucleo.contracts.enums import EstadoCita
from app.nucleo.contracts.schemas import SugerenciaRequest
from app.nucleo.puertos import Operacion

ANTICIPACION_TURNO_MIN = 30
HORIZONTE_SATURACION_H = 3  # se avisa de congestión para citas en las próximas 3 h
ESPERA_AVISO_MIN = 45  # espera prevista que amerita avisar
MEJORA_MINIMA_MIN = 15  # la alternativa debe ahorrar al menos esto


@dataclass(frozen=True)
class CitaActiva:
    cita_id: int
    transportista_id: int
    telefono: str
    acceso_id: str
    inicio: datetime
    tipo_carga: str
    estado: EstadoCita
    telegram_chat_id: int | None = None


@dataclass
class AvisoNuevo:
    cita_id: int
    transportista_id: int
    telefono: str
    tipo: str
    mensaje: str
    telegram_chat_id: int | None = None


def _hora(dt: datetime) -> str:
    return f"{dt:%H:%M}"


def revisar(sim: Operacion, citas: list[CitaActiva], ya_enviados: set[tuple[int, str]]) -> list[AvisoNuevo]:
    ahora = sim.ts()
    nuevos: list[AvisoNuevo] = []
    for c in citas:
        nombre = sim.esc.acceso(c.acceso_id).nombre
        faltan = (c.inicio - ahora).total_seconds() / 60

        # 1) Recordatorio del turno
        if 0 <= faltan <= ANTICIPACION_TURNO_MIN and (c.cita_id, "turno_30min") not in ya_enviados:
            espera = espera_estimada(sim, c.acceso_id, c.inicio)
            nuevos.append(AvisoNuevo(c.cita_id, c.transportista_id, c.telefono, "turno_30min",
                                     f"⏰ En {faltan:.0f} min es tu turno: *{_hora(c.inicio)}* en *{nombre}* "
                                     f"(cita *#{c.cita_id}*). Espera prevista ~{espera:.0f} min.", c.telegram_chat_id))

        # 2) Caseta cerrada o saturada a la hora de la cita (solo citas que aún no salen)
        if (c.estado != EstadoCita.agendada or not (ANTICIPACION_TURNO_MIN < faltan <= HORIZONTE_SATURACION_H * 60)
                or (c.cita_id, "saturacion") in ya_enviados):
            continue
        cerrada = not sim.acceso_abierto(c.acceso_id)
        espera = espera_estimada(sim, c.acceso_id, c.inicio)
        if not cerrada and espera < ESPERA_AVISO_MIN:
            continue
        try:
            alternativas = sugerir(sim, SugerenciaRequest(
                desde=c.inicio - timedelta(hours=1), hasta=c.inicio + timedelta(hours=2),
                tipo_carga=c.tipo_carga, max_resultados=3))
        except ErrorCita:
            alternativas = []
        mejor = next((a for a in alternativas
                      if (a.acceso_id, a.inicio) != (c.acceso_id, c.inicio)
                      and (cerrada or a.espera_min_est <= espera - MEJORA_MINIMA_MIN)), None)
        motivo = "está *cerrada*" if cerrada else f"tendrá ~{espera:.0f} min de espera"
        texto = f"⚠️ Tu cita *#{c.cita_id}* de las *{_hora(c.inicio)}* en *{nombre}*: la caseta {motivo}."
        if mejor:
            alt = sim.esc.acceso(mejor.acceso_id).nombre
            texto += (f"\n¿La cambiamos a las *{_hora(mejor.inicio)}* en *{alt}* (~{mejor.espera_min_est:.0f} min)? "
                      "Responde *SÍ* para cambiarla.")
        else:
            texto += "\nResponde con otra hora si quieres cambiarla."
        nuevos.append(AvisoNuevo(c.cita_id, c.transportista_id, c.telefono, "saturacion", texto, c.telegram_chat_id))
    return nuevos
