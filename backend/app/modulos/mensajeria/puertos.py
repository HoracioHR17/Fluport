"""Puertos de la mensajería: cómo habla Fluport con los transportistas y con el modelo de lenguaje.

Adaptadores actuales (`adaptadores/`): Telegram y SMS como canales de aviso (`NotificadorPort`), Gemini como modelo
de lenguaje. Agregar otro canal o proveedor es escribir un adaptador que cumpla el puerto; el asistente y los avisos
no cambian.
"""
from typing import Any, Protocol


class ErrorLLM(Exception):
    """El proveedor del modelo de lenguaje respondió con error o con un formato inesperado."""


class ModeloLenguaje(Protocol):
    async def generar(
        self, contenidos: list[dict[str, Any]], sistema: str, herramientas: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Devuelve el siguiente turno del modelo: {"role": "model", "parts": [...]}."""


class NotificadorPort(Protocol):
    """Canal por el que se avisa a un transportista. Nunca lanza excepciones: un fallo se devuelve como
    (False, motivo) para que el aviso quede registrado con error sin interrumpir la simulación."""

    def configurado(self) -> bool:
        """Si el canal tiene credenciales para enviar."""

    async def enviar(self, destino: Any, texto: str) -> tuple[bool, str]:
        """Envía `texto` a `destino` (chat de Telegram o teléfono E.164). Devuelve (enviado, detalle)."""


CanalMensajeria = NotificadorPort  # nombre anterior del puerto
