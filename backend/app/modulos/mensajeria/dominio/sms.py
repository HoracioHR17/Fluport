"""Texto de los avisos por SMS: alfabeto GSM-7 y un solo mensaje de 160 caracteres.

Con un solo carácter fuera de GSM-7 (acentos, ñ, emojis) el celular manda el SMS en UCS-2 y el límite baja a
70 caracteres por mensaje; por eso se quitan acentos, la ñ pasa a n y se descarta lo que no sea GSM-7.
"""
import unicodedata

LIMITE_SMS = 160
PREFIJO = "FLUPORT: "

# alfabeto básico GSM 03.38 (cada uno ocupa 1 de los 160 caracteres)
_GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# signos que no son GSM-7 pero tienen equivalente simple
_EQUIVALENTES = {"¿": "", "¡": "", "·": "-", "–": "-", "—": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'",
                 "~": "aprox ", "*": "", "_": " ", "\n": " ", "\r": " ", "\t": " "}


def normalizar_sms(texto: str, limite: int = LIMITE_SMS) -> str:
    """Convierte `texto` a GSM-7 sin acentos ni ñ, en una línea, y lo recorta a `limite` caracteres.

    Se quitan los diacríticos (á→a, ñ→n, ü→u), se reemplazan signos tipográficos, se descartan emojis y cualquier
    carácter fuera de GSM-7 y se compactan los espacios. Si no cabe, se corta en la última palabra completa y se
    termina en "...".
    """
    salida = []
    for c in texto:
        c = _EQUIVALENTES.get(c, c)
        for d in unicodedata.normalize("NFD", c):
            if unicodedata.category(d) == "Mn":  # acento combinante
                continue
            if d in _GSM7 and d not in "¿¡ÄÖÑÜäöñüàèéùìòÇÅåÉ":  # solo ASCII imprimible (más legible en celulares básicos)
                salida.append(d)
    limpio = " ".join("".join(salida).split())
    if len(limpio) <= limite:
        return limpio
    corte = limpio[: limite - 3].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return corte + "..."


def sms(texto: str) -> str:
    """Aviso listo para enviar: prefijo de la marca + texto normalizado a un solo SMS."""
    return normalizar_sms(PREFIJO + texto)
