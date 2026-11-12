"""Acceso de los adaptadores de entrada (API, webhooks) a la operación del puerto.

La raíz de composición (`app/main.py`) registra quién implementa la operación y cómo se publican mensajes al
tablero en vivo; los módulos solo piden `operacion()` y `publicar()` sin saber que detrás está el simulador.
"""
import asyncio
from collections.abc import Callable

from app.nucleo.puertos import Operacion

def _sin_tablero(texto: str) -> None:
    """Publicador por defecto: no hay tableros conectados."""


_operacion: Callable[[], Operacion] | None = None
_publicar: Callable[[str], None] = _sin_tablero
_suscribir: Callable[[], asyncio.Queue] | None = None
_desuscribir: Callable[[asyncio.Queue], None] | None = None


def configurar(operacion: Callable[[], Operacion], publicar: Callable[[str], None],
               suscribir: Callable[[], asyncio.Queue] | None = None,
               desuscribir: Callable[[asyncio.Queue], None] | None = None) -> None:
    global _operacion, _publicar, _suscribir, _desuscribir
    _operacion, _publicar, _suscribir, _desuscribir = operacion, publicar, suscribir, desuscribir


def operacion() -> Operacion:
    """La operación vigente. Lanza la excepción del proveedor si aún no arranca (la API responde 503)."""
    if _operacion is None:
        raise RuntimeError("la operación no está configurada")
    return _operacion()


def publicar(texto: str) -> None:
    """Envía un mensaje (JSON) a los tableros conectados por WebSocket."""
    _publicar(texto)


def suscribir() -> asyncio.Queue:
    """Cola con los mensajes del stream en vivo (los mismos que recibe /ws/sim)."""
    if _suscribir is None:
        raise RuntimeError("el stream en vivo no está configurado")
    return _suscribir()


def desuscribir(cola: asyncio.Queue) -> None:
    if _desuscribir is not None:
        _desuscribir(cola)
