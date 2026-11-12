"""Acceso de los adaptadores de entrada (API, webhooks) a la operación del puerto.

La raíz de composición (`app/main.py`) registra quién implementa la operación y cómo se publican mensajes al
tablero en vivo; los módulos solo piden `operacion()` y `publicar()` sin saber que detrás está el simulador.
"""
from collections.abc import Callable

from app.nucleo.puertos import Operacion

def _sin_tablero(texto: str) -> None:
    """Publicador por defecto: no hay tableros conectados."""


_operacion: Callable[[], Operacion] | None = None
_publicar: Callable[[str], None] = _sin_tablero


def configurar(operacion: Callable[[], Operacion], publicar: Callable[[str], None]) -> None:
    global _operacion, _publicar
    _operacion, _publicar = operacion, publicar


def operacion() -> Operacion:
    """La operación vigente. Lanza la excepción del proveedor si aún no arranca (la API responde 503)."""
    if _operacion is None:
        raise RuntimeError("la operación no está configurada")
    return _operacion()


def publicar(texto: str) -> None:
    """Envía un mensaje (JSON) a los tableros conectados por WebSocket."""
    _publicar(texto)
