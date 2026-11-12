"""Bot de Telegram de Fluport: identifica al transportista por su teléfono y lo conecta con el asistente.

Flujo:
1. Chat nuevo → se le pide compartir su número con el botón de contacto de Telegram.
2. Comparte su propio contacto → se registra (`transportista.telegram_chat_id`) y queda identificado.
3. Mensajes de texto → asistente (el mismo del canal web de pruebas) → respuesta en el chat.

Ubicación: cualquiera (con o sin alta) puede tocar «📍 Entradas cerca de mí» o enviar su ubicación y recibe las entradas
más cercanas con su estado actual y cuál le conviene. Si comparte su ubicación *en tiempo real*, el bot le avisa cuando
su mejor entrada cambia o empeora (se satura o se cierra). La ubicación vive solo en memoria y no se guarda en la BD.

Enlace de agencia: `t.me/<bot>?start=AG01` abre el chat con `/start AG01`; si el transportista aún no tiene
agencia, queda ligado a esa.

Operación real (`telegram_solo_registrados`, activo por defecto): solo se vinculan números que una agencia dio de
alta. Si un número sin alta comparte su contacto, el bot le envía la solicitud a su agencia: si Fluport tiene una
sola agencia (la demo: Tiburones Ecover Logistics) va directo a ella; si hay varias, le pregunta a cuál pertenece
(botones o texto libre) o usa la del enlace con el que llegó. La agencia
la aprueba o la rechaza en su panel y el bot le avisa. Las citas que asigna la agencia son obligatorias: el bot solo
avisa (no se confirman con SÍ / NO); si el transportista pide cancelarla, se le avisa a la agencia para que decida.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.agencias import servicio as agencias
from app.modulos.citas.servicio import ErrorCita, espera_estimada, normalizar_telefono
from app.modulos.mensajeria.adaptadores import telegram
from app.modulos.mensajeria.asistente.agente import asistente, guardar_turnos
from app.modulos.mensajeria.dominio import ubicacion
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import Canal, EstadoCita
from app.nucleo.contracts.schemas import AsistenteRequest
from app.nucleo.db.base import SessionLocal
from app.nucleo.db.models import Agencia, Cita, Transportista
from app.nucleo.puertos import Operacion

log = logging.getLogger("fluport.telegram")

BIENVENIDA = ("¡Hola! Soy el asistente de *FLUPORT* para las entradas al puerto de Veracruz.\n"
              "Para ver y agendar tus citas, comparte tu número con el botón de abajo.\n"
              "¿Solo quieres saber qué entrada te conviene? Toca *📍 Entradas cerca de mí*.")
REGISTRADO = ("Listo ✅ Ya te identifiqué con el número terminado en {fin}.\n"
              "Escríbeme, por ejemplo: _llego mañana a las 9 con un contenedor de 40_ o _¿cómo está la fila?_\n"
              "Toca *📍 Entradas cerca de mí* para ver cuál te conviene desde donde estás.")
CONTACTO_AJENO = "Por seguridad solo puedo registrar *tu propio* número. Usa el botón para compartirlo."
LIGADO = "Quedaste ligado a la agencia *{nombre}*; ahí verán tus citas y tu camión."
PEDIR_AGENCIA = ("Tu número aún no está dado de alta en Fluport. ¿A qué *agencia* perteneces?\n"
                 "Elige una de la lista o escribe su nombre y le envío tu solicitud de alta.")
AGENCIA_NO_ENCONTRADA = "No encontré esa agencia. Elige una de la lista o escribe su nombre como aparece."
SOLICITUD_ENVIADA = ("Listo 📨 Envié tu solicitud de alta a *{nombre}*. Te aviso aquí en cuanto la revisen.")
SOLICITUD_PENDIENTE = "Tu solicitud con *{nombre}* sigue en revisión. Te aviso aquí en cuanto respondan."
UBICACION_INVALIDA = "No pude leer esa ubicación. Inténtalo de nuevo con el botón 📍."
EN_VIVO = ("\n📡 Te sigo en tiempo real: te aviso aquí si tu mejor entrada cambia, se satura o se cierra.")
SUGERIR_EN_VIVO = ("\nTip: comparte tu *ubicación en tiempo real* (📎 → Ubicación) y te aviso si tu mejor entrada "
                   "cambia o se satura en el camino.")
ICONO = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴", "cerrada": "⛔"}
ESTADO_TXT = {"verde": "fluye", "amarillo": "lento", "rojo": "saturado", "cerrada": "cerrada"}


class NoRegistrado(Exception):
    """El número no fue dado de alta por ninguna agencia."""


# ───────────────────────────── Ubicación ─────────────────────────────
MAX_CERCANAS = 3
AVISO_MIN_S = 180  # entre avisos de seguimiento en vivo (segundos reales), para no saturar el chat


@dataclass
class Seguimiento:
    """Ubicación en tiempo real de un chat (solo en memoria)."""
    lat: float
    lon: float
    hasta: float  # time.monotonic() en que termina la ubicación en tiempo real
    mejor: str | None = None
    estado: str | None = None
    avisado: float = 0.0
    cita_aviso: tuple[int, str] | None = None  # (cita, entrada sugerida) del último aviso de cuello de botella
    cita_avisado: float = 0.0


_en_vivo: dict[int, Seguimiento] = {}


def texto_cercanas(sim: Operacion, lat: float, lon: float, en_vivo: bool) -> tuple[str, ubicacion.EntradaCercana | None]:
    """Mensaje con las entradas más cercanas, su estado y la recomendada."""
    lista = ubicacion.cercanas(sim, lat, lon)
    mejor = ubicacion.recomendada(lista)
    lineas = [f"📍 *Entradas más cercanas a ti* ({sim.ts():%H:%M}):"]
    for i, x in enumerate(lista[:MAX_CERCANAS], 1):
        espera = f"espera ~{x.espera_min:.0f} min" if x.abierta else "sin paso"
        lineas.append(f"{i}. {ICONO[x.estado]} *{x.nombre}* · {x.distancia_km:.1f} km · {ESTADO_TXT[x.estado]}, {espera}")
    if mejor is None:
        lineas.append("⛔ Todas las entradas están cerradas por ahora. Te aviso cuando reabran si sigues compartiendo.")
    else:
        lejos = "" if mejor.distancia_km <= ubicacion.LEJOS_KM else " (estás lejos: el tiempo de manejo es aproximado)"
        eta, _ = _llegada(sim, mejor)
        lineas.append(f"👉 Te conviene *{mejor.nombre}*: llegas ~{eta:%H:%M}, ~{mejor.total_min:.0f} min entre manejo y fila{lejos}.")
    lineas.append(EN_VIVO if en_vivo else SUGERIR_EN_VIVO)
    return "\n".join(lineas), mejor


# ───────────── Cuello de botella en ruta (transportista con cita que comparte su ubicación en vivo) ─────────────
ESPERA_CUELLO_MIN = 45  # espera prevista al llegar que se considera cuello de botella (igual que los avisos)
MEJORA_MIN = 15  # la otra entrada debe ahorrar al menos esto entre manejo y fila


@dataclass(frozen=True)
class CitaEnCurso:
    cita_id: int
    acceso_id: str
    telefono: str


def cita_en_curso(sim: Operacion, chat_id: int) -> CitaEnCurso | None:
    """Próxima cita activa del transportista de este chat (None si no tiene, no está registrado o no hay BD)."""
    try:
        with SessionLocal() as db:
            t = transportista_de_chat(db, chat_id)
            if t is None:
                return None
            c = db.scalar(select(Cita).where(Cita.transportista_id == t.id,
                                             Cita.estado.in_((EstadoCita.agendada, EstadoCita.en_ruta)),
                                             Cita.ventana_fin >= sim.ts())
                          .order_by(Cita.ventana_inicio).limit(1))
            return CitaEnCurso(c.id, c.acceso_id, t.telefono) if c else None
    except Exception:  # noqa: BLE001  (sin BD: solo se ofrece la entrada más conveniente)
        return None


def _llegada(sim: Operacion, x: ubicacion.EntradaCercana) -> tuple[datetime, float]:
    """Hora estimada de llegada a la entrada (tiempo simulado) y espera prevista en su fila a esa hora."""
    eta = sim.ts() + timedelta(minutes=x.manejo_min)
    return eta, espera_estimada(sim, x.acceso_id, eta)


def texto_cuello_de_botella(sim: Operacion, lat: float, lon: float, cita: CitaEnCurso) -> tuple[str, str] | None:
    """Si la entrada de su cita tiene cuello de botella (cerrada o espera >= 45 min al llegar) y otra le ahorra
    tiempo, el mensaje con la nueva entrada y su ETA. Devuelve (texto, entrada sugerida) o None."""
    lista = ubicacion.cercanas(sim, lat, lon)
    propia = next((x for x in lista if x.acceso_id == cita.acceso_id), None)
    if propia is None:
        return None
    eta_p, espera_p = _llegada(sim, propia)
    if propia.abierta and espera_p < ESPERA_CUELLO_MIN:
        return None
    total_p = propia.manejo_min + espera_p if propia.abierta else float("inf")
    mejor, eta_m, espera_m, total_m = None, None, 0.0, float("inf")
    for x in lista:
        if x.acceso_id == propia.acceso_id or not x.abierta:
            continue
        eta, espera = _llegada(sim, x)
        if x.manejo_min + espera < total_m:
            mejor, eta_m, espera_m, total_m = x, eta, espera, x.manejo_min + espera
    if mejor is None or total_m > total_p - MEJORA_MIN:
        return None
    motivo = ("está *cerrada*" if not propia.abierta
              else f"tendrá ~{espera_p:.0f} min de fila cuando llegues (~{eta_p:%H:%M})")
    pasas = eta_m + timedelta(minutes=espera_m)
    texto = (f"⚠️ *Cuello de botella* en *{propia.nombre}* (tu cita *#{cita.cita_id}*): {motivo}.\n"
             f"👉 Te conviene *{mejor.nombre}*: llegas ~*{eta_m:%H:%M}* ({mejor.distancia_km:.1f} km, "
             f"~{mejor.manejo_min:.0f} min de camino), esperas ~{espera_m:.0f} min y pasas ~{pasas:%H:%M}.\n"
             f"Responde *SÍ* y cambio tu cita a {mejor.nombre} (misma hora).")
    return texto, mejor.acceso_id


def _coordenadas(loc: dict[str, Any]) -> tuple[float, float] | None:
    try:
        lat, lon = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lon) if ubicacion.coordenadas_validas(lat, lon) else None


async def atender_ubicacion(sim: Operacion, chat_id: int, loc: dict[str, Any], editado: bool) -> str | None:
    """Ubicación puntual o en tiempo real (el primer mensaje o sus actualizaciones)."""
    coords = _coordenadas(loc)
    if coords is None:
        if not editado:
            await telegram.enviar(chat_id, UBICACION_INVALIDA)
            return UBICACION_INVALIDA
        return None
    lat, lon = coords
    vivo = loc.get("live_period")
    if editado:  # actualización de una ubicación en tiempo real: solo se avisa si algo cambió
        s = _en_vivo.get(chat_id)
        if s is None:
            return None
        s.lat, s.lon = lat, lon
        return await revisar_seguimiento(sim, chat_id, s)
    texto, mejor = texto_cercanas(sim, lat, lon, en_vivo=bool(vivo))
    if vivo:
        _en_vivo[chat_id] = Seguimiento(lat, lon, time.monotonic() + float(vivo),
                                        mejor.acceso_id if mejor else None, mejor.estado if mejor else "cerrada",
                                        time.monotonic())
    else:
        _en_vivo.pop(chat_id, None)
    await telegram.enviar(chat_id, texto)
    if vivo:  # si va en camino a una cita con cuello de botella, se le avisa de inmediato
        aviso = await _avisar_cuello(sim, chat_id, _en_vivo[chat_id])
        if aviso:
            return texto + "\n\n" + aviso
    return texto


async def _avisar_cuello(sim: Operacion, chat_id: int, s: Seguimiento) -> str | None:
    """Aviso de cuello de botella en la entrada de su cita (una vez por entrada sugerida y como máximo cada 3 min)."""
    cita = await asyncio.to_thread(cita_en_curso, sim, chat_id)
    if cita is None:
        return None
    r = texto_cuello_de_botella(sim, s.lat, s.lon, cita)
    if r is None:
        s.cita_aviso = None  # sin cuello de botella: si vuelve a aparecer, se avisa otra vez
        return None
    texto, sugerida = r
    ahora = time.monotonic()
    if s.cita_aviso == (cita.cita_id, sugerida) or ahora - s.cita_avisado < AVISO_MIN_S:
        return None
    s.cita_aviso, s.cita_avisado = (cita.cita_id, sugerida), ahora
    await telegram.enviar(chat_id, texto)
    # queda en el historial del asistente: un "SÍ" posterior cambia la cita a la entrada sugerida
    await asyncio.to_thread(_guardar_aviso, cita.telefono, texto)
    return texto


def _guardar_aviso(telefono: str, texto: str) -> None:
    try:
        with SessionLocal() as db:
            guardar_turnos(db, Canal.telegram, telefono, [{"role": "model", "parts": [{"text": texto}]}])
    except Exception:  # noqa: BLE001
        log.warning("No se pudo guardar el aviso de cuello de botella en el historial")


async def revisar_seguimiento(sim: Operacion, chat_id: int, s: Seguimiento) -> str | None:
    """Avisa si la mejor entrada para esta ubicación cambió o empeoró desde el último aviso."""
    ahora = time.monotonic()
    if ahora > s.hasta:
        _en_vivo.pop(chat_id, None)
        return None
    aviso = await _avisar_cuello(sim, chat_id, s)  # con cita: se vigila la entrada de su cita
    if aviso:
        return aviso
    mejor = ubicacion.recomendada(ubicacion.cercanas(sim, s.lat, s.lon))
    nuevo_id, nuevo_estado = (mejor.acceso_id, mejor.estado) if mejor else (None, "cerrada")
    cambio = nuevo_id != s.mejor
    peor = nuevo_id == s.mejor and ubicacion.empeoro(s.estado, nuevo_estado)
    if not (cambio or peor) or ahora - s.avisado < AVISO_MIN_S:
        if not (cambio or peor):
            s.estado = nuevo_estado  # mejoras silenciosas: se actualiza la referencia
        return None
    if mejor is None:
        texto = "⛔ Todas las entradas cerca de ti se cerraron. Te aviso cuando reabran."
    elif cambio:
        antes = sim.esc.acceso(s.mejor).nombre if s.mejor else "ninguna"
        eta, _ = _llegada(sim, mejor)
        texto = (f"🔁 Ahora te conviene *{mejor.nombre}* ({mejor.distancia_km:.1f} km, espera ~{mejor.espera_min:.0f} min): "
                 f"llegas ~{eta:%H:%M}, ~{mejor.total_min:.0f} min en total, en lugar de {antes}.")
    else:
        texto = (f"⚠️ *{mejor.nombre}* pasó a *{ESTADO_TXT[nuevo_estado]}* (espera ~{mejor.espera_min:.0f} min). "
                 "Sigue siendo tu mejor opción por cercanía.")
    s.mejor, s.estado, s.avisado = nuevo_id, nuevo_estado, ahora
    await telegram.enviar(chat_id, texto)
    return texto


async def revisar_en_vivo(sim: Operacion) -> None:
    """Revisa a todos los que comparten ubicación en tiempo real (aunque no se muevan, la fila cambia)."""
    for chat_id, s in list(_en_vivo.items()):
        try:
            await revisar_seguimiento(sim, chat_id, s)
        except Exception:  # noqa: BLE001  (un chat con error no detiene a los demás)
            log.exception("Error al revisar la ubicación en vivo de un chat")


# código de agencia recibido con /start antes de que el chat comparta su número
_agencia_pendiente: dict[int, str] = {}


def codigo_agencia(db: Session, texto: str) -> Agencia | None:
    """Agencia del parámetro de `/start AG01` (None si no viene o no existe)."""
    partes = texto.split(maxsplit=1)
    if len(partes) < 2:
        return None
    return db.get(Agencia, partes[1].strip().upper())


def transportista_de_chat(db: Session, chat_id: int) -> Transportista | None:
    return db.scalar(select(Transportista).where(Transportista.telegram_chat_id == chat_id))


def registrar_contacto(db: Session, chat_id: int, telefono: str, nombre: str | None,
                       agencia_id: str | None = None) -> Transportista:
    """Liga el chat con el transportista de ese teléfono (lo crea si no existe) y, si viene, con su agencia."""
    tel = normalizar_telefono(telefono)
    anterior = transportista_de_chat(db, chat_id)
    if anterior is not None and anterior.telefono != tel:
        anterior.telegram_chat_id = None  # el chat cambió de número
        db.flush()
    t = db.scalar(select(Transportista).where(Transportista.telefono == tel))
    if t is None:
        if get_settings().telegram_solo_registrados:
            raise NoRegistrado(tel)
        t = Transportista(alias=nombre or f"Transportista {tel[-4:]}", telefono=tel, es_demo=True)
        db.add(t)
    t.telegram_chat_id = chat_id
    if agencia_id is None and t.agencia_id is None and (unica := agencias.agencia_unica(db)) is not None:
        agencia_id = unica.id  # con una sola agencia, todo transportista nuevo es de ella
    if agencia_id is not None and t.agencia_id is None:  # la agencia que lo dio de alta no se reemplaza
        t.agencia_id = agencia_id
    db.commit()
    return t


async def procesar_update(sim: Operacion, update: dict[str, Any]) -> str | None:
    """Atiende una actualización de Telegram. Devuelve el texto enviado (útil en pruebas)."""
    editado = "message" not in update and "edited_message" in update
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if chat_id is None or (msg.get("chat") or {}).get("type") not in (None, "private"):
        return None  # solo chats privados
    remitente_id = (msg.get("from") or {}).get("id")

    if "location" in msg:  # no requiere alta: es información pública del estado de las entradas
        return await atender_ubicacion(sim, chat_id, msg["location"], editado)
    if editado:
        return None  # otras ediciones (p. ej. un texto corregido) no se atienden

    if "contact" in msg:
        contacto = msg["contact"]
        if contacto.get("user_id") != remitente_id:
            await telegram.enviar(chat_id, CONTACTO_AJENO, telegram.TECLADO_CONTACTO)
            return CONTACTO_AJENO
        enlace = _agencia_pendiente.pop(chat_id, None)
        try:
            with SessionLocal() as db:
                t = registrar_contacto(db, chat_id, contacto.get("phone_number", ""), contacto.get("first_name"),
                                       enlace)
                fin = (t.telefono or "")[-4:]
                agencia = t.agencia.nombre if t.agencia else None
        except ErrorCita:
            await telegram.enviar(chat_id, "No pude leer ese número. Inténtalo de nuevo con el botón.",
                                  telegram.TECLADO_CONTACTO)
            return None
        except NoRegistrado as e:
            return await _solicitar_alta(chat_id, str(e), contacto.get("first_name"), enlace)
        texto = REGISTRADO.format(fin=fin) + ("\n" + LIGADO.format(nombre=agencia) if agencia else "")
        await telegram.enviar(chat_id, texto, telegram.TECLADO_UBICACION)
        return texto

    texto_usuario = (msg.get("text") or "").strip()
    with SessionLocal() as db:
        t = transportista_de_chat(db, chat_id)
        agencia = codigo_agencia(db, texto_usuario) if texto_usuario.startswith("/start") else None
        if t is None:
            solicitud = agencias.solicitud_abierta(db, chat_id)
            if solicitud is not None:
                return await _seguir_solicitud(db, chat_id, solicitud, texto_usuario, agencia)
        if t is None or texto_usuario.startswith("/start"):
            if t is None:
                if agencia is not None:
                    _agencia_pendiente[chat_id] = agencia.id
                await telegram.enviar(chat_id, BIENVENIDA, telegram.TECLADO_CONTACTO)
                return BIENVENIDA
            texto = REGISTRADO.format(fin=(t.telefono or "")[-4:])
            if agencia is not None and t.agencia_id is None:
                t.agencia_id = agencia.id
                db.commit()
                texto += "\n" + LIGADO.format(nombre=agencia.nombre)
            await telegram.enviar(chat_id, texto)
            return texto
        if not texto_usuario:
            return None
        r = await asistente.responder(db, sim, AsistenteRequest(canal=Canal.telegram, remitente=t.telefono,
                                                                  texto=texto_usuario))
    await telegram.enviar(chat_id, r.respuesta)
    return r.respuesta


async def _solicitar_alta(chat_id: int, telefono: str, nombre: str | None, agencia_id: str | None) -> str:
    """Número sin alta: abre una solicitud; con enlace de agencia va directo a ella, si no se pregunta cuál."""
    with SessionLocal() as db:
        s = agencias.abrir_solicitud(db, chat_id, telefono, nombre, agencia_id)
        if s.estado == "pendiente":
            texto = SOLICITUD_ENVIADA.format(nombre=s.agencia.nombre)
            await telegram.enviar(chat_id, texto, telegram.QUITAR_TECLADO)
            return texto
        opciones = agencias.nombres_agencias(db)
    await telegram.enviar(chat_id, PEDIR_AGENCIA, telegram.teclado_opciones(opciones))
    return PEDIR_AGENCIA


async def _seguir_solicitud(db: Session, chat_id: int, s, texto: str, agencia: Agencia | None) -> str:
    """Mensajes de un chat con solicitud abierta: elegir agencia o informar que sigue en revisión."""
    if s.estado == "pendiente":
        respuesta = SOLICITUD_PENDIENTE.format(nombre=s.agencia.nombre)
        await telegram.enviar(chat_id, respuesta)
        return respuesta
    elegida = agencia or (agencias.buscar_agencia(db, texto) if texto and not texto.startswith("/") else None)
    if elegida is None:
        await telegram.enviar(chat_id, AGENCIA_NO_ENCONTRADA, telegram.teclado_opciones(agencias.nombres_agencias(db)))
        return AGENCIA_NO_ENCONTRADA
    agencias.elegir_agencia(db, s, elegida)
    respuesta = SOLICITUD_ENVIADA.format(nombre=elegida.nombre)
    await telegram.enviar(chat_id, respuesta, telegram.QUITAR_TECLADO)
    return respuesta


class PollingTelegram:
    """Lee mensajes del bot con long polling (no requiere URL pública ni túnel)."""

    def __init__(self) -> None:
        self._tarea: asyncio.Task | None = None
        self._offset: int | None = None
        self._en_curso: set[asyncio.Task] = set()  # referencias a mensajes en atención

    def iniciar(self, obtener_sim) -> None:
        if self._tarea is None or self._tarea.done():
            self._tarea = asyncio.create_task(self._bucle(obtener_sim), name="fluport-telegram")

    async def detener(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self, obtener_sim) -> None:
        try:
            await telegram.quitar_webhook()
        except Exception:  # noqa: BLE001
            log.warning("No se pudo quitar el webhook de Telegram")
        log.info("Bot de Telegram escuchando (long polling)")
        while True:
            try:
                for upd in await telegram.obtener_actualizaciones(self._offset):
                    self._offset = upd["update_id"] + 1
                    sim = obtener_sim()
                    if sim is not None:
                        t = asyncio.create_task(self._atender(sim, upd))
                        self._en_curso.add(t)
                        t.add_done_callback(self._en_curso.discard)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (red caída, token inválido…): reintenta sin tumbar la app
                log.warning("Polling de Telegram: %s", e)
                await asyncio.sleep(5)

    async def _atender(self, sim: Operacion, upd: dict[str, Any]) -> None:
        try:
            await procesar_update(sim, upd)
        except Exception:  # noqa: BLE001
            log.exception("Error al atender un mensaje de Telegram")


polling = PollingTelegram()
