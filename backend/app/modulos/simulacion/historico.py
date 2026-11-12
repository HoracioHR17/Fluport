"""Genera un histórico simulado (sin esperar ticks reales) para entrenar el modelo de predicción (M2).

Uso:  python -m app.modulos.simulacion.historico --dias 14 --semilla 100
"""
import argparse
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modulos.simulacion.adaptadores.persistencia_pg import Persistencia
from app.modulos.simulacion.dominio.escenario import escenario_actual
from app.modulos.simulacion.dominio.motor import Simulador
from app.nucleo.config import get_settings
from app.nucleo.contracts.enums import TipoCorrida
from app.nucleo.db.base import engine

log = logging.getLogger("fluport.historico")


def generar(
    dias: int, semilla: int, intervalo_min: float = 15.0, persistir: bool = True
) -> tuple[int, list[dict[str, Any]]]:
    """Simula `dias` días a máxima velocidad. Devuelve (id de corrida o 0, lecturas).

    Si `persistir` y PostgreSQL está disponible, guarda corrida, lecturas y eventos.
    """
    esc = escenario_actual()
    pers = Persistencia(engine)
    guardar = persistir and pers.disponible()
    zona = ZoneInfo(get_settings().zona_horaria)
    # el histórico termina "ayer" para no traslaparse con la corrida en vivo
    inicio = (datetime.now(zona) - timedelta(days=dias + 1)).replace(
        hour=esc.inicio_hora, minute=0, second=0, microsecond=0
    )
    corrida = 0
    if guardar:
        pers.sembrar_accesos(esc)
        corrida = pers.crear_corrida(TipoCorrida.historico, semilla, inicio, 0, esc.model_dump(mode="json"))
    sim = Simulador(esc, semilla, inicio, corrida_id=corrida, intervalo_lectura_min=intervalo_min)
    t0, todas = time.perf_counter(), []
    for dia in range(dias):
        for _ in range(int(24 * 60 / intervalo_min)):
            sim.avanzar(intervalo_min)
        lecturas, eventos = sim.vaciar_pendientes()
        if guardar:
            pers.guardar_lecturas(lecturas)
            pers.guardar_eventos(eventos)
        todas.extend(lecturas)
        log.info("día %d/%d · %d lecturas · %.1fs", dia + 1, dias, len(todas), time.perf_counter() - t0)
    if guardar:
        pers.finalizar_corrida(corrida)
    return corrida, todas


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--semilla", type=int, default=100)
    ap.add_argument("--intervalo", type=float, default=15.0, help="minutos simulados entre lecturas")
    a = ap.parse_args()
    corrida, lecturas = generar(a.dias, a.semilla, a.intervalo)
    print(f"Corrida histórica {corrida} generada ({a.dias} días, semilla {a.semilla}, {len(lecturas)} lecturas).")


if __name__ == "__main__":
    main()
