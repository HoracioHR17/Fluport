"""SMS: adaptador del puerto NotificadorPort para transportistas sin smartphone.

Proveedores (FLUPORT_SMS_PROVEEDOR):
- `android`: un celular Android del equipo con la app SMS Gateway; su API recibe
  POST {url} {"message": ..., "phoneNumbers": [...]} con autenticación básica y envía el SMS con la SIM del celular.
- `twilio`: API REST de Twilio (POST /Accounts/{SID}/Messages.json).
- `adb`: un Android conectado por USB a la laptop; con ADB se abre su app de Mensajes con el número y el texto y
  se toca el botón Enviar (se usa cuando el sistema del celular bloquea los SMS enviados por otras apps).
- `vonage`: SMS API de Vonage (POST https://rest.nexmo.com/sms/json); en cuenta de prueba solo envía a números
  verificados y agrega "[FREE SMS DEMO, TEST MESSAGE]" al texto.
Se usa `httpx`; no se agrega ninguna biblioteca. Nunca lanza excepciones: los fallos se devuelven como (False, motivo).
"""
import asyncio
import logging
import re
import shlex
import shutil
from pathlib import Path

import httpx

from app.modulos.mensajeria.dominio.sms import normalizar_sms
from app.nucleo.config import get_settings

log = logging.getLogger("fluport.sms")
TWILIO = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
VONAGE = "https://rest.nexmo.com/sms/json"
REMITENTE_VONAGE = "Fluport"  # remitente alfanumérico si no se configura un número


def _ruta_adb() -> str | None:
    """`adb` configurado, el del PATH o el del SDK de Android Studio."""
    s = get_settings()
    for candidato in (s.sms_adb_ruta, shutil.which("adb"), str(Path.home() / "Android/Sdk/platform-tools/adb")):
        if candidato and Path(candidato).expanduser().is_file():
            return str(Path(candidato).expanduser())
    return None


def configurado() -> bool:
    s = get_settings()
    if s.sms_proveedor == "adb":
        return _ruta_adb() is not None
    if s.sms_proveedor == "android":
        return bool(s.sms_url and s.sms_usuario and s.sms_clave)
    if s.sms_proveedor == "twilio":
        return bool(s.sms_usuario and s.sms_clave and s.sms_remitente)
    if s.sms_proveedor == "vonage":
        return bool(s.sms_usuario and s.sms_clave)
    return False


async def _android(http: httpx.AsyncClient, telefono: str, texto: str) -> tuple[bool, str]:
    s = get_settings()
    r = await http.post(s.sms_url, json={"message": texto, "phoneNumbers": [telefono]},
                        auth=(s.sms_usuario, s.sms_clave))
    if r.status_code >= 400:
        return False, f"gateway HTTP {r.status_code}: {r.text[:120]}"
    try:
        return True, str(r.json().get("id", "aceptado"))
    except ValueError:
        return True, "aceptado"


async def _twilio(http: httpx.AsyncClient, telefono: str, texto: str) -> tuple[bool, str]:
    s = get_settings()
    r = await http.post(TWILIO.format(sid=s.sms_usuario), data={"To": telefono, "From": s.sms_remitente, "Body": texto},
                        auth=(s.sms_usuario, s.sms_clave))
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    if r.status_code >= 400:
        return False, f"Twilio HTTP {r.status_code}: {cuerpo.get('message', r.text[:120])}"
    return True, str(cuerpo.get("sid", "aceptado"))


async def _vonage(http: httpx.AsyncClient, telefono: str, texto: str) -> tuple[bool, str]:
    """Vonage responde HTTP 200 aun si rechaza el SMS: el resultado está en messages[0].status ("0" = aceptado)."""
    s = get_settings()
    r = await http.post(VONAGE, data={"api_key": s.sms_usuario, "api_secret": s.sms_clave,
                                      "from": s.sms_remitente or REMITENTE_VONAGE,
                                      "to": telefono.lstrip("+"), "text": texto})
    try:
        mensaje = (r.json().get("messages") or [{}])[0]
    except ValueError:
        return False, f"Vonage HTTP {r.status_code}: {r.text[:120]}"
    if r.status_code >= 400 or mensaje.get("status") != "0":
        return False, f"Vonage {mensaje.get('status', r.status_code)}: {mensaje.get('error-text', r.text[:120])}"
    return True, str(mensaje.get("message-id", "aceptado"))


# ───────────── ADB: la app de Mensajes del celular envía el SMS ─────────────
_candado_adb = asyncio.Lock()  # un SMS a la vez: cada envío usa la pantalla del celular
BOTON_ENVIAR = re.compile(r"(send|enviar|envia)", re.I)
NODO = re.compile(r"<node [^>]*>")
ATRIBUTO = re.compile(r'([\w-]+)="([^"]*)"')


async def _adb(*args: str, timeout: float = 10) -> tuple[int, str]:
    s = get_settings()
    cmd = [_ruta_adb() or "adb", *(["-s", s.sms_adb_serial] if s.sms_adb_serial else []), *args]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        salida, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return -1, "adb no respondió"
    return proc.returncode or 0, salida.decode(errors="replace")


def boton_enviar(xml: str) -> tuple[int, int] | None:
    """Centro del botón Enviar en el volcado de `uiautomator`.

    Puntaje por coincidencia: id (3) > descripción (2) > texto (1); se ignoran campos de texto y nodos deshabilitados.
    Con empate gana el último (el botón suele estar al final de la barra de redacción)."""
    mejor, puntos = None, 0
    for nodo in NODO.findall(xml):
        a = dict(ATRIBUTO.findall(nodo))
        limites = re.findall(r"\d+", a.get("bounds", ""))
        if a.get("enabled") == "false" or "EditText" in a.get("class", "") or len(limites) != 4:
            continue
        p = max((peso for clave, peso in (("resource-id", 3), ("content-desc", 2), ("text", 1))
                 if BOTON_ENVIAR.search(a.get(clave, ""))), default=0)
        if p and p >= puntos:
            x1, y1, x2, y2 = map(int, limites)
            mejor, puntos = ((x1 + x2) // 2, (y1 + y2) // 2), p
    return mejor


async def _enviar_adb(telefono: str, texto: str) -> tuple[bool, str]:
    """Abre Mensajes con el SMS listo (intent SENDTO), localiza Enviar y lo toca."""
    s = get_settings()
    async with _candado_adb:
        await _adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        codigo, salida = await _adb("shell", "am", "start", "-a", "android.intent.action.SENDTO",
                                    "-d", shlex.quote(f"sms:{telefono}"), "--es", "sms_body", shlex.quote(texto),
                                    "--ez", "exit_on_sent", "true")
        if codigo != 0 or "Error" in salida:
            return False, f"adb: no se pudo abrir Mensajes ({salida.strip()[:120]})"
        await asyncio.sleep(s.sms_adb_espera_s)
        punto = None
        if s.sms_adb_tap:  # coordenadas fijas "x,y" si la detección automática no encuentra el botón
            x, y = (int(v) for v in s.sms_adb_tap.split(","))
            punto = (x, y)
        else:
            await _adb("shell", "uiautomator", "dump", "/sdcard/fluport_ui.xml", timeout=15)
            _, xml = await _adb("shell", "cat", "/sdcard/fluport_ui.xml")
            punto = boton_enviar(xml)
        if punto is None:
            return False, "adb: no se encontró el botón Enviar (configura FLUPORT_SMS_ADB_TAP=x,y)"
        codigo, salida = await _adb("shell", "input", "tap", str(punto[0]), str(punto[1]))
        if codigo != 0:
            return False, f"adb: no se pudo tocar Enviar ({salida.strip()[:120]})"
        await asyncio.sleep(1.0)
        await _adb("shell", "input", "keyevent", "KEYCODE_HOME")  # deja el celular listo para el siguiente
        return True, f"adb: enviado desde Mensajes (toque en {punto[0]},{punto[1]})"


PROVEEDORES = {"android": _android, "twilio": _twilio, "vonage": _vonage}


async def enviar(telefono: str, texto: str) -> tuple[bool, str]:
    """Envía un SMS de máximo 160 caracteres GSM-7 a `telefono` (E.164, +52…)."""
    if not configurado():
        return False, "SMS no está configurado"
    if not telefono or not telefono.startswith("+"):
        return False, "teléfono sin formato E.164"
    texto = normalizar_sms(texto)
    if get_settings().sms_proveedor == "adb":
        try:
            ok, detalle = await _enviar_adb(telefono, texto)
        except Exception as e:  # noqa: BLE001 - un fallo del canal nunca debe detener la simulación
            log.exception("SMS por adb: error inesperado")
            return False, f"adb: error inesperado ({type(e).__name__})"
        if not ok:
            log.error("SMS por adb no enviado: %s", detalle)
        return ok, detalle
    proveedor = PROVEEDORES.get(get_settings().sms_proveedor, _android)
    try:
        async with httpx.AsyncClient(timeout=get_settings().sms_timeout_s) as http:
            ok, detalle = await proveedor(http, telefono, texto)
    except httpx.HTTPError as e:
        log.error("SMS sin conexión con el proveedor: %s", e)
        return False, f"sin conexión con el gateway SMS ({type(e).__name__})"
    except Exception as e:  # noqa: BLE001 - un fallo del canal nunca debe detener la simulación
        log.exception("SMS: error inesperado")
        return False, f"error inesperado ({type(e).__name__})"
    if not ok:
        log.error("SMS rechazado: %s", detalle)
    return ok, detalle


class SmsAdapter:
    """Adaptador del puerto NotificadorPort para SMS."""

    def configurado(self) -> bool:
        return configurado()

    async def enviar(self, destino, texto: str) -> tuple[bool, str]:
        return await enviar(str(destino), texto)
