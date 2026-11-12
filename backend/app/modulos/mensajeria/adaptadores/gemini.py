"""Cliente del LLM (Gemini, API REST `generateContent`) con llamadas a herramientas.

Se usa `httpx` directamente para no agregar dependencias. El formato de los turnos es el de Gemini:
`{"role": "user"|"model", "parts": [{"text": …} | {"functionCall": …} | {"functionResponse": …}]}`.
Los turnos del modelo se guardan tal cual llegan (incluida cualquier firma de pensamiento), porque
la API pide reenviarlos para conservar el contexto entre pasos con herramientas.
"""
from typing import Any

import httpx

from app.modulos.mensajeria.puertos import ErrorLLM

URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


def _sin_firmas(contenidos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copia de los turnos sin `thoughtSignature`: las firmas son del modelo que las generó."""
    return [{**t, "parts": [{k: v for k, v in p.items() if k != "thoughtSignature"} for p in t.get("parts", [])]}
            for t in contenidos]


class ClienteGemini:  # adaptador del puerto ModeloLenguaje
    """Llama al modelo principal y, si está saturado (429/5xx) o tarda demasiado, al modelo de respaldo."""

    def __init__(self, api_key: str, modelo: str, pensamiento: str = "low", timeout_s: float = 12.0,
                 modelo_respaldo: str = "") -> None:
        self.api_key, self.modelo, self.pensamiento = api_key, modelo, pensamiento
        self.timeout_s, self.modelo_respaldo = timeout_s, modelo_respaldo
        self.ultimo_modelo = modelo

    async def generar(
        self, contenidos: list[dict[str, Any]], sistema: str, herramientas: list[dict[str, Any]]
    ) -> dict[str, Any]:
        modelos = [self.modelo] + ([self.modelo_respaldo] if self.modelo_respaldo else [])
        errores = []
        for i, modelo in enumerate(modelos):
            try:
                turnos = contenidos if i == 0 else _sin_firmas(contenidos)
                contenido = await self._llamar(modelo, turnos, sistema, herramientas)
                self.ultimo_modelo = modelo
                return contenido
            except _Temporal as e:  # saturado o lento: se intenta el siguiente modelo
                errores.append(f"{modelo}: {e}")
        raise ErrorLLM(" | ".join(errores))

    async def _llamar(self, modelo: str, contenidos: list[dict[str, Any]], sistema: str,
                      herramientas: list[dict[str, Any]]) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": sistema}]},
            "contents": contenidos,
            "tools": [{"functionDeclarations": herramientas}],
        }
        if self.pensamiento:  # nivel de razonamiento de Gemini 3 (minimal | low | medium | high)
            cuerpo["generationConfig"] = {"thinkingConfig": {"thinkingLevel": self.pensamiento}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as http:
                r = await http.post(
                    URL_GEMINI.format(modelo=modelo),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=cuerpo,
                )
        except httpx.TimeoutException as e:
            raise _Temporal(f"no respondió en {self.timeout_s:.0f} s ({type(e).__name__})") from e
        except httpx.HTTPError as e:
            raise _Temporal(f"sin conexión ({type(e).__name__}): {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise _Temporal(f"respondió {r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise ErrorLLM(f"Gemini ({modelo}) respondió {r.status_code}: {r.text[:300]}")
        datos = r.json()
        try:
            contenido = datos["candidates"][0]["content"]
        except (KeyError, IndexError) as e:
            raise ErrorLLM(f"respuesta sin contenido: {str(datos)[:300]}") from e
        contenido.setdefault("role", "model")
        contenido.setdefault("parts", [])
        return contenido


class _Temporal(Exception):
    """Falla pasajera del proveedor (saturación, 5xx, tiempo agotado): amerita probar otro modelo."""
