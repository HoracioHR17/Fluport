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

    # Semáforo (minutos de espera)
    semaforo_amarillo_min: float = 20.0
    semaforo_rojo_min: float = 45.0

    # Pronóstico
    pronostico_autoentrenar: bool = True  # entrenar al arrancar si no existe modelos/pronostico.joblib
    pronostico_guardar_cada_min: float = 60.0  # minutos simulados entre pronósticos guardados en la BD

    # Asistente IA / mensajería
    llm_api_key: str = ""
    llm_modelo: str = "claude-sonnet-5-5"
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = "fluport-verify"
    telegram_token: str = ""

    # General
    zona_horaria: str = "America/Mexico_City"
    etiqueta_simulacion: str = "SIMULACIÓN"


@lru_cache
def get_settings() -> Settings:
    return Settings()
