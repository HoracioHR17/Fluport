"""Asistente de citas (M4): entiende lenguaje natural y actúa con herramientas sobre la API de citas.

Flujo por mensaje: historial del remitente + mensaje → LLM → (herramientas → LLM)* → respuesta en texto.
El asistente solo puede ver y modificar las citas del teléfono que escribe.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.citas import servicio as citas
from app.modulos.citas.servicio import ErrorCita, normalizar_telefono
from app.modulos.mensajeria.adaptadores.gemini import ClienteGemini
from app.modulos.mensajeria.puertos import ErrorLLM, ModeloLenguaje
from app.modulos.pronostico.pronosticador import pronosticador
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import Canal, EstadoAviso, EstadoCita, Mundo, OrigenCita, TipoCarga
from app.nucleo.contracts.schemas import (
    AccionAsistente,
    AsistenteRequest,
    AsistenteResponse,
    CitaCreate,
    CitaReprogramar,
    SugerenciaRequest,
)
from app.nucleo.db.models import Aviso, Cita, MensajeAsistente, Transportista
from app.nucleo.puertos import Operacion

log = logging.getLogger("fluport.asistente")
MAX_PASOS = 5  # rondas máximas de herramientas por mensaje
MAX_HISTORIAL = 20  # turnos previos que se envían al LLM
DURACION_CITA_MIN = 30
CARGAS = [t.value for t in TipoCarga]

HERRAMIENTAS: list[dict[str, Any]] = [
    {
        "name": "consultar_espera",
        "description": "Espera actual y pronóstico de las próximas horas por caseta. Úsala si preguntan cómo está la fila.",
        "parameters": {"type": "object", "properties": {
            "acceso_id": {"type": "string", "description": "Id de la entrada (A1…A6). Omitir para todas."}}},
    },
    {
        "name": "sugerir_horario",
        "description": "Busca los 3 horarios con menor espera prevista dentro de una ventana de llegada.",
        "parameters": {"type": "object", "properties": {
            "desde": {"type": "string", "description": "Inicio de la ventana, AAAA-MM-DDTHH:MM (hora de Veracruz)"},
            "hasta": {"type": "string", "description": "Fin de la ventana, AAAA-MM-DDTHH:MM (hora de Veracruz)"},
            "tipo_carga": {"type": "string", "enum": CARGAS},
            "acceso_id": {"type": "string", "description": "Caseta preferida (opcional)"},
            "sin_hora": {"type": "boolean", "description": "true si el transportista no indicó hora"},
        }, "required": ["desde", "hasta", "tipo_carga"]},
    },
    {
        "name": "crear_cita",
        "description": "Agenda una cita de 30 min para el transportista que escribe. Solo después de que confirme el horario.",
        "parameters": {"type": "object", "properties": {
            "acceso_id": {"type": "string"},
            "inicio": {"type": "string", "description": "AAAA-MM-DDTHH:MM (hora de Veracruz)"},
            "tipo_carga": {"type": "string", "enum": CARGAS},
        }, "required": ["acceso_id", "inicio", "tipo_carga"]},
    },
    {
        "name": "reprogramar_cita",
        "description": ("Cambia la caseta, el horario o ambos de una cita agendada del transportista. Para cambiar solo "
                        "la caseta (p. ej. ya no entra por el norte sino por el sur), manda acceso_id y omite inicio: "
                        "se conserva la hora."),
        "parameters": {"type": "object", "properties": {
            "cita_id": {"type": "integer"},
            "inicio": {"type": "string", "description": "AAAA-MM-DDTHH:MM (hora de Veracruz). Omitir para conservar la hora."},
            "acceso_id": {"type": "string", "description": "Caseta nueva. Omitir para conservar la caseta."},
        }, "required": ["cita_id"]},
    },
    {
        "name": "cancelar_cita",
        "description": "Cancela una cita activa del transportista.",
        "parameters": {"type": "object", "properties": {"cita_id": {"type": "integer"}}, "required": ["cita_id"]},
    },
    {
        "name": "mis_citas",
        "description": "Lista las citas activas del transportista que escribe.",
        "parameters": {"type": "object", "properties": {}},
    },
]


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def entradas(sim: Operacion) -> dict[str, list[str]]:
    """Puntos de acceso agrupados por corredor de llegada (norte, sur, urbana) con su espera actual."""
    espera = {e.acceso_id: e for e in sim.estado_accesos(Mundo.B)}
    res: dict[str, list[str]] = {"norte": [], "sur": [], "urbana": []}
    for a in sim.esc.accesos:
        e = espera.get(a.id)
        ahora = "cerrada" if e and e.estado.value != "abierto" else f"~{e.espera_min:.0f} min" if e else "sin dato"
        res[a.entrada].append(f"{a.id} ({a.nombre}, {ahora})")
    return res


def instrucciones(sim: Operacion) -> str:
    ahora = sim.ts()
    casetas = "; ".join(f"{a.id} = {a.nombre} ({a.zona})" for a in sim.esc.accesos)
    por_entrada = "; ".join(f"entrada {k}: {', '.join(v)}" for k, v in entradas(sim).items() if v)
    return (
        "Eres el asistente de citas de FLUPORT para transportistas del puerto de Veracruz. "
        "Respondes por Telegram: en español, breve (máximo 6 líneas), cordial y claro, sin tecnicismos. "
        "Formato de Telegram: negritas con UN asterisco (*07:30*), nunca Markdown doble (**, #, tablas).\n"
        f"Fecha y hora actual (hora de Veracruz): {DIAS[ahora.weekday()]} {ahora:%Y-%m-%d %H:%M}. "
        f"Entradas al puerto (puntos de acceso; el usuario puede llamarlas casetas): {casetas}.\n"
        f"Entradas por corredor: {por_entrada}.\n"
        f"Tipos de carga válidos: {', '.join(CARGAS)} (\"contenedor de 40\" = contenedor_40).\n"
        "Reglas:\n"
        "1. Para agendar: si el usuario da una hora aproximada, busca con sugerir_horario una ventana de 3 horas "
        "CENTRADA en esa hora (p. ej. 9:00 → 07:30 a 10:30) y ofrece las 3 opciones numeradas con caseta, hora y "
        "espera estimada. "
        "Si NO da hora, busca con sugerir_horario desde la hora actual hasta 12 horas después (lo que cubre el "
        "pronóstico), con sin_hora=true, y ofrece las 3 opciones con menor espera; no le preguntes la hora. "
        "Agenda con crear_cita SOLO cuando el usuario elija una opción o confirme.\n"
        "2. Si falta el tipo de carga, pregúntalo antes de buscar.\n"
        "3. Usa siempre fechas completas AAAA-MM-DDTHH:MM; \"mañana\" es el día siguiente a la fecha actual.\n"
        "4. Para cambiar o cancelar, usa mis_citas para obtener el número de cita si no lo sabes.\n"
        "5. Nunca inventes horarios, esperas ni números de cita: usa solo lo que devuelvan las herramientas.\n"
        "6. Tú sugieres; la terminal conserva el control. Si algo falla, explícalo en una línea y ofrece alternativa.\n"
        "7. Si el usuario responde SÍ a un aviso tuyo que propone cambiar su cita, usa reprogramar_cita con el número "
        "de cita, la hora y la caseta propuestas en ese aviso.\n"
        "8. Si el transportista avisa que cambió de entrada o de ruta (p. ej. \"ya no entro por el norte, voy por el "
        "sur\" o \"mejor llego por Santa Fe\"), cambia su cita con reprogramar_cita a un punto de esa entrada "
        "conservando la hora (omite inicio), salvo que también pida otra hora. Si ese corredor tiene varios puntos, "
        "elige el abierto con menor espera actual de la lista de entradas por corredor. Si tiene varias citas activas y no queda claro cuál, pregúntale cuál.\n"
        "9. Tu agencia se entera automáticamente de los cambios y cancelaciones que hagas por aquí; dilo si preguntan.\n"
        "10. Si pregunta qué entrada le queda más cerca o cuál le conviene desde donde está, pídele que toque el botón "
        "*📍 Entradas cerca de mí* o que comparta su ubicación en tiempo real (📎 → Ubicación) para avisarle en el camino; "
        "no adivines su ubicación."
    )


# ───────────────────────────── Ejecución de herramientas ─────────────────────────────
class Herramientas:
    def __init__(self, db: Session, sim: Operacion, telefono: str, origen: OrigenCita) -> None:
        self.db, self.sim, self.telefono, self.origen = db, sim, telefono, origen
        self.zona = ZoneInfo(get_settings().zona_horaria)

    def _fecha(self, texto: str) -> datetime:
        dt = datetime.fromisoformat(str(texto).strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=self.zona)

    def _mi_cita(self, cita_id: int) -> Cita:
        cita = citas.obtener(self.db, int(cita_id))
        dueno = self.db.get(Transportista, cita.transportista_id)
        if dueno is None or dueno.telefono != self.telefono:
            raise ErrorCita(404, f"no encontré la cita {cita_id} a tu nombre")
        return cita

    def ejecutar(self, nombre: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            metodo = getattr(self, f"h_{nombre}", None)
            if metodo is None:
                return {"error": f"herramienta desconocida: {nombre}"}
            return metodo(**(args or {}))
        except ErrorCita as e:
            return {"error": e.mensaje}
        except (ValueError, TypeError, KeyError) as e:
            return {"error": f"datos inválidos: {e}"}

    def h_consultar_espera(self, acceso_id: str | None = None) -> dict[str, Any]:
        estados = {e.acceso_id: e for e in self.sim.estado_accesos(Mundo.B)}
        res = []
        for p in pronosticador.obtener(self.sim, Mundo.B):
            if acceso_id and p.acceso_id != acceso_id:
                continue
            e = estados[p.acceso_id]
            mejor = min(p.franjas, key=lambda f: f.espera_min) if p.franjas else None
            res.append({
                "acceso_id": p.acceso_id, "nombre": self.sim.esc.acceso(p.acceso_id).nombre,
                "abierta": e.estado.value == "abierto", "espera_actual_min": e.espera_min, "semaforo": e.semaforo.value,
                "proximas_horas": [{"hora": f"{f.inicio:%H:%M}", "espera_min": f.espera_min} for f in p.franjas[:12:2]],
                "mejor_hora": f"{mejor.inicio:%H:%M}" if mejor else None,
            })
        return {"casetas": res}

    def h_sugerir_horario(self, desde: str, hasta: str, tipo_carga: str, acceso_id: str | None = None,
                          sin_hora: bool = False) -> dict:
        req = SugerenciaRequest(desde=self._fecha(desde), hasta=self._fecha(hasta), tipo_carga=tipo_carga,
                                acceso_id=acceso_id or None, preferencia="temprano" if sin_hora else "centro")
        try:
            sug = citas.sugerir(self.sim, req)
        except KeyError:
            return {"error": f"la caseta {acceso_id} no existe"}
        return {"opciones": [
            {"acceso_id": s.acceso_id, "caseta": self.sim.esc.acceso(s.acceso_id).nombre,
             "inicio": s.inicio.strftime("%Y-%m-%dT%H:%M"), "espera_estimada_min": s.espera_min_est,
             "ahorro_vs_peor_hora_min": s.ahorro_vs_pico_min}
            for s in sug
        ]}

    def h_crear_cita(self, acceso_id: str, inicio: str, tipo_carga: str) -> dict[str, Any]:
        ini = self._fecha(inicio)
        c = citas.crear(self.db, self.sim, CitaCreate(
            telefono=self.telefono, acceso_id=acceso_id, ventana_inicio=ini,
            ventana_fin=ini + timedelta(minutes=DURACION_CITA_MIN), tipo_carga=tipo_carga, origen=self.origen))
        return {"cita_id": c.id, "acceso_id": c.acceso_id, "caseta": self.sim.esc.acceso(c.acceso_id).nombre,
                "inicio": c.ventana_inicio.astimezone(self.zona).strftime("%Y-%m-%dT%H:%M"),
                "espera_estimada_min": c.espera_estimada_min}

    def _hora(self, dt: datetime) -> str:
        return f"{dt.astimezone(self.zona):%d/%m %H:%M}"

    def _avisar_agencia(self, t: Transportista, cita_id: int, tipo: str, mensaje: str) -> bool:
        """Deja el cambio del transportista en los avisos del panel de su agencia (no se envía por Telegram)."""
        if t.agencia_id is None:
            return False
        self.db.add(Aviso(transportista_id=t.id, cita_id=cita_id, canal=Canal.telegram, tipo=tipo, mensaje=mensaje,
                          estado=EstadoAviso.enviado, enviado_en=datetime.now().astimezone()))
        self.db.commit()
        return True

    def h_reprogramar_cita(self, cita_id: int, inicio: str | None = None,
                           acceso_id: str | None = None) -> dict[str, Any]:
        original = self._mi_cita(cita_id)
        if not inicio and not acceso_id:
            return {"error": "indica la caseta nueva, la hora nueva o ambas"}
        antes_acceso, antes_ini = original.acceso_id, original.ventana_inicio
        if inicio:
            ini = self._fecha(inicio)
            fin = ini + timedelta(minutes=DURACION_CITA_MIN)
        else:  # solo cambia la caseta: se conserva la ventana
            ini, fin = original.ventana_inicio, original.ventana_fin
        if (acceso_id or antes_acceso) == antes_acceso and ini == antes_ini:
            return {"error": f"la cita {cita_id} ya está en esa caseta y a esa hora"}
        c = citas.reprogramar(self.db, self.sim, int(cita_id), CitaReprogramar(
            acceso_id=acceso_id or None, ventana_inicio=ini, ventana_fin=fin))
        nueva = self.db.get(Cita, c.id)
        nueva.confirmada_en = datetime.now().astimezone()  # la pidió el propio transportista: ya está confirmada
        self.db.commit()
        t = nueva.transportista
        esc = self.sim.esc
        avisada = self._avisar_agencia(t, c.id, "cambio_chofer",
                             f"{t.alias} cambió su cita #{cita_id} ({esc.acceso(antes_acceso).nombre}, "
                             f"{self._hora(antes_ini)}) → cita #{c.id}: {esc.acceso(c.acceso_id).nombre}, "
                             f"{self._hora(c.ventana_inicio)}.")
        return {"cita_id": c.id, "cita_anterior_id": c.cita_anterior_id, "acceso_id": c.acceso_id,
                "acceso_anterior_id": antes_acceso, "agencia_avisada": avisada,
                "inicio": c.ventana_inicio.astimezone(self.zona).strftime("%Y-%m-%dT%H:%M"),
                "espera_estimada_min": c.espera_estimada_min}

    def h_cancelar_cita(self, cita_id: int) -> dict[str, Any]:
        cita = self._mi_cita(cita_id)
        acceso, ini = cita.acceso_id, cita.ventana_inicio
        c = citas.cancelar(self.db, self.sim, int(cita_id))
        t = self.db.get(Transportista, c.transportista_id)
        avisada = self._avisar_agencia(t, c.id, "cancelacion_chofer",
                             f"{t.alias} canceló su cita #{c.id} ({self.sim.esc.acceso(acceso).nombre}, "
                             f"{self._hora(ini)}); reasígnala si hace falta.")
        return {"cita_id": c.id, "estado": c.estado.value, "agencia_avisada": avisada}

    def h_mis_citas(self) -> dict[str, Any]:
        activas = [c for c in citas.listar(self.db, telefono=self.telefono)
                   if c.estado in (EstadoCita.agendada, EstadoCita.en_ruta)]
        return {"citas": [
            {"cita_id": c.id, "acceso_id": c.acceso_id, "caseta": self.sim.esc.acceso(c.acceso_id).nombre,
             "inicio": c.ventana_inicio.astimezone(self.zona).strftime("%Y-%m-%dT%H:%M"),
             "tipo_carga": c.tipo_carga.value, "estado": c.estado.value}
            for c in activas
        ]}


DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _cuando(iso: str) -> str:
    """'2026-11-12T09:00' → 'jue 12/11 a las 09:00'."""
    dt = datetime.fromisoformat(iso)
    return f"{DIAS_CORTOS[dt.weekday()]} {dt:%d/%m} a las {dt:%H:%M}"


def redactar(herramienta: str, r: dict[str, Any], sim: Operacion) -> str | None:
    """Respuesta del chat con plantilla para resultados sin error. None = que la redacte el LLM."""
    if herramienta == "sugerir_horario":
        ops = r.get("opciones") or []
        if not ops:
            return None
        lineas = ["Estas son las mejores opciones:"]
        for i, o in enumerate(ops, 1):
            lineas.append(f"{i}. *{o['inicio'][11:16]}* · {o['caseta']} ({o['acceso_id']}) · espera ~{o['espera_estimada_min']:.0f} min")
        lineas.append(f"Para el {_cuando(ops[0]['inicio']).rsplit(' a las', 1)[0]}. Responde con el número de la opción para agendarla.")
        return "\n".join(lineas)
    if herramienta == "crear_cita":
        return (f"Listo ✅ Tu cita *#{r['cita_id']}* quedó el *{_cuando(r['inicio'])}* en *{r['caseta']}*.\n"
                f"Espera estimada: ~{(r.get('espera_estimada_min') or 0):.0f} min. Te aviso por aquí si algo cambia.")
    if herramienta == "reprogramar_cita":
        nombre = sim.esc.acceso(r["acceso_id"]).nombre
        antes = r.get("acceso_anterior_id")
        caseta = f" (antes {sim.esc.acceso(antes).nombre})" if antes and antes != r["acceso_id"] else ""
        return (f"Cambié tu cita: ahora es la *#{r['cita_id']}*, el *{_cuando(r['inicio'])}* en *{nombre}*{caseta}.\n"
                f"Espera estimada: ~{(r.get('espera_estimada_min') or 0):.0f} min."
                + (" Ya le avisé a tu agencia." if r.get("agencia_avisada") else ""))
    if herramienta == "cancelar_cita":
        aviso = " y le avisé a tu agencia" if r.get("agencia_avisada") else ""
        return f"Cancelé tu cita *#{r['cita_id']}*{aviso}. Si necesitas otra, dime día, hora y tipo de carga."
    if herramienta == "mis_citas":
        lista = r.get("citas") or []
        if not lista:
            return "No tienes citas activas. ¿Quieres agendar una? Dime día, hora y tipo de carga."
        return "Tus citas:\n" + "\n".join(
            f"• *#{c['cita_id']}* · {_cuando(c['inicio'])} · {sim.esc.acceso(c['acceso_id']).nombre}" for c in lista)
    if herramienta == "consultar_espera":
        estado = {"verde": "🟢 Fluye", "amarillo": "🟡 Lento", "rojo": "🔴 Saturado"}
        lineas = [f"Así están las casetas ({sim.ts():%H:%M}):"]
        for c in r.get("casetas") or []:
            cerrada = "" if c["abierta"] else " · *cerrada*"
            mejor = f" · mejor hora {c['mejor_hora']}" if c.get("mejor_hora") else ""
            lineas.append(f"{estado[c['semaforo']]} · {c['nombre']}: {c['espera_actual_min']:.0f} min{cerrada}{mejor}")
        return "\n".join(lineas)
    return None


def formato_chat(texto: str) -> str:
    """Convierte Markdown común al Markdown de Telegram: **x** → *x*, __x__ → _x_, sin encabezados #."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto, flags=re.S)
    texto = re.sub(r"__(.+?)__", r"_\1_", texto, flags=re.S)
    texto = re.sub(r"^\s{0,3}#{1,6}\s*", "", texto, flags=re.M)
    return texto.strip()


# ───────────────────────────── Historial ─────────────────────────────
def cargar_historial(db: Session, canal: Canal, remitente: str) -> list[dict[str, Any]]:
    """Turnos recientes del remitente (los últimos `llm_historial_min` minutos reales, máximo MAX_HISTORIAL)."""
    desde = datetime.now(ZoneInfo(get_settings().zona_horaria)) - timedelta(minutes=get_settings().llm_historial_min)
    filas = db.scalars(
        select(MensajeAsistente)
        .where(MensajeAsistente.canal == canal, MensajeAsistente.remitente == remitente,
               MensajeAsistente.creado_en >= desde)
        .order_by(MensajeAsistente.id.desc()).limit(MAX_HISTORIAL)
    ).all()
    turnos = [f.contenido for f in reversed(filas)]

    def es_texto(t: dict[str, Any], rol: str) -> bool:
        partes = t.get("parts", [])
        return t.get("role") == rol and bool(partes) and all("text" in p for p in partes)

    # el historial debe empezar con texto del usuario; se descartan restos de herramientas al inicio
    while turnos and not (es_texto(turnos[0], "user") or es_texto(turnos[0], "model")):
        turnos.pop(0)
    if turnos and es_texto(turnos[0], "model"):  # p. ej. un aviso automático: se conserva con su contexto
        turnos.insert(0, {"role": "user", "parts": [{"text": "(Fluport te envió un aviso automático)"}]})
    return turnos


def guardar_turnos(db: Session, canal: Canal, remitente: str, turnos: list[dict[str, Any]]) -> None:
    for t in turnos:
        db.add(MensajeAsistente(canal=canal, remitente=remitente, rol=t.get("role", "user"), contenido=t))
    db.commit()


# ───────────────────────────── Agente ─────────────────────────────
class Asistente:
    def __init__(self, cliente: ModeloLenguaje | None = None) -> None:
        self._cliente = cliente

    @property
    def cliente(self) -> ModeloLenguaje | None:
        if self._cliente is not None:
            return self._cliente
        cfg = get_settings()
        if not cfg.llm_api_key:
            return None
        return ClienteGemini(cfg.llm_api_key, cfg.llm_modelo, cfg.llm_pensamiento, timeout_s=cfg.llm_timeout_s,
                             modelo_respaldo=cfg.llm_modelo_respaldo)

    def usar_cliente(self, cliente: ModeloLenguaje | None) -> None:
        """Permite inyectar un cliente (pruebas) o volver al configurado con `None`."""
        self._cliente = cliente

    async def responder(self, db: Session, sim: Operacion, req: AsistenteRequest) -> AsistenteResponse:
        telefono = normalizar_telefono(req.remitente)
        origen = OrigenCita.telegram if req.canal == Canal.telegram else OrigenCita.asistente
        cliente = self.cliente
        if cliente is None:
            return self._sin_llm(sim)

        herramientas = Herramientas(db, sim, telefono, origen)
        historial = cargar_historial(db, req.canal, telefono)
        nuevos: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": req.texto}]}]
        acciones: list[AccionAsistente] = []
        sistema = instrucciones(sim)
        try:
            for _ in range(MAX_PASOS):
                turno = await cliente.generar(historial + nuevos, sistema, HERRAMIENTAS)
                nuevos.append(turno)
                llamadas = [p["functionCall"] for p in turno.get("parts", []) if "functionCall" in p]
                if not llamadas:
                    texto = formato_chat("\n".join(p["text"] for p in turno.get("parts", []) if p.get("text")))
                    guardar_turnos(db, req.canal, telefono, nuevos)
                    return AsistenteResponse(respuesta=texto or "¿Me lo puedes repetir, por favor?", acciones=acciones)
                respuestas, textos = [], []
                for ll in llamadas:
                    nombre = ll.get("name", "")
                    resultado = herramientas.ejecutar(nombre, ll.get("args") or {})
                    acciones.append(AccionAsistente(herramienta=nombre, resultado=resultado))
                    respuestas.append({"functionResponse": {"name": nombre, "response": resultado}})
                    textos.append(redactar(nombre, resultado, sim) if "error" not in resultado else None)
                nuevos.append({"role": "user", "parts": respuestas})
                if all(textos):
                    # resultado claro: la respuesta se redacta con plantilla, sin otra llamada al LLM (la mitad de tiempo)
                    texto = "\n\n".join(textos)
                    nuevos.append({"role": "model", "parts": [{"text": texto}]})
                    guardar_turnos(db, req.canal, telefono, nuevos)
                    return AsistenteResponse(respuesta=texto, acciones=acciones)
            guardar_turnos(db, req.canal, telefono, nuevos)
            return AsistenteResponse(respuesta="Necesito un poco más de detalle. ¿Qué día, a qué hora y con qué carga llegas?",
                                     acciones=acciones)
        except ErrorLLM as e:
            log.error("Fallo del LLM: %s", e)
            db.rollback()
            return AsistenteResponse(
                respuesta="Tengo un problema para procesar tu mensaje. Mientras tanto:\n" + self._sin_llm(sim).respuesta,
                acciones=acciones,
            )

    def _sin_llm(self, sim: Operacion) -> AsistenteResponse:
        """Respaldo sin LLM: estado de las casetas en texto."""
        lineas = [f"FLUPORT · estado a las {sim.ts():%H:%M}"]
        estado = {"verde": "🟢 Fluye", "amarillo": "🟡 Lento", "rojo": "🔴 Saturado"}
        for e in sim.estado_accesos(Mundo.B):
            nombre = sim.esc.acceso(e.acceso_id).nombre
            lineas.append(f"{estado[e.semaforo.value]} · {nombre}: {e.espera_min:.0f} min")
        lineas.append("Para agendar una cita usa el tablero web.")
        return AsistenteResponse(respuesta="\n".join(lineas), acciones=[])


asistente = Asistente()

