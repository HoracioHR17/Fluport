"""Configuración central de Fluport (variables de entorno / .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FLUPORT_", extra="ignore")

    # Base de datos
    database_url: str = "postgresql+psycopg://fluport:fluport@localhost:5432/fluport"

    # Simulación
    sim_autostart: bool = True  # arrancar la simulación al iniciar la app
    sim_semilla: int = 42
    sim_velocidad: float = 60.0  # segundos simulados por segundo real (60 => 1 s real = 1 min simulado)
    sim_tick_seg: float = 1.0  # cada cuánto se emite un snapshot (segundos reales)
    sim_max_camiones_visibles: int = 300
    sim_cumplimiento_sugerencia: float = 0.70  # % de transportistas que siguen la cita sugerida (Mundo B)

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
    # WhatsApp con Twilio (Sandbox)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # número del Sandbox, p. ej. "whatsapp:+14155238886"
    twilio_webhook_url: str = ""  # URL pública EXACTA configurada en Twilio (para validar la firma)
    twilio_validar_firma: bool = True
    avisos_activos: bool = True  # avisos proactivos por WhatsApp

    # General
    zona_horaria: str = "America/Mexico_City"
    etiqueta_simulacion: str = "SIMULACIÓN"


@lru_cache
def get_settings() -> Settings:
    return Settings()
