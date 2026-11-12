"""Configuración central de Fluport (variables de entorno / .env)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_BACKEND = Path(__file__).resolve().parents[2]  # carpeta backend/ (datos, modelos, .env)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FLUPORT_", extra="ignore")

    # Base de datos
    database_url: str = "postgresql+psycopg://fluport:fluport@localhost:5432/fluport"

    # Simulación
    sim_autostart: bool = True  # arrancar la simulación al iniciar la app
    sim_semilla: int = 42
    sim_velocidad: float = 60.0  # segundos simulados por segundo real (60 => 1 s real = 1 min simulado)
    sim_tick_seg: float = 1.0  # cada cuánto se emite un snapshot (segundos reales)
    sim_max_camiones_visibles: int = 600

    # Semáforo (minutos de espera) según la identidad visual: Fluye < 30 · Lento 30–90 · Saturado > 90
    semaforo_amarillo_min: float = 30.0
    semaforo_rojo_min: float = 90.0

    # Pronóstico
    pronostico_autoentrenar: bool = True  # entrenar al arrancar si no existe modelos/pronostico.joblib
    pronostico_guardar_cada_min: float = 60.0  # minutos simulados entre pronósticos guardados en la BD

    # Asistente IA / mensajería
    llm_api_key: str = ""
    llm_modelo: str = "gemini-3.6-flash"  # Gemini API (generateContent)
    llm_pensamiento: str = "low"  # thinkingLevel de Gemini 3: minimal | low | medium | high ("" = el del modelo)
    llm_historial_min: float = 30.0  # minutos de conversación previa que recuerda el asistente
    llm_timeout_s: float = 12.0  # tiempo máximo de espera por modelo (principal y respaldo)
    llm_modelo_respaldo: str = "gemini-3.5-flash-lite"  # se usa si el principal está saturado o tarda ("" = sin respaldo)
    avisos_activos: bool = True  # avisos proactivos por Telegram
    # Telegram (bot creado con @BotFather)
    telegram_token: str = ""
    telegram_modo: str = "polling"  # polling (sin URL pública) | webhook | off
    # /api/asistente/mensaje no autentica al remitente: solo para pruebas locales, nunca en una URL pública
    asistente_web_activo: bool = False
    telegram_solo_registrados: bool = True  # el bot solo vincula números que una agencia dio de alta
    telegram_webhook_secret: str = ""  # valor de X-Telegram-Bot-Api-Secret-Token en modo webhook

    # General
    zona_horaria: str = "America/Mexico_City"
    etiqueta_simulacion: str = "SIMULACIÓN"


@lru_cache
def get_settings() -> Settings:
    return Settings()
