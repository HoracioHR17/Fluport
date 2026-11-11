"""Entrena el modelo de pronóstico de espera con un histórico simulado.

Uso:  python -m app.prediction.entrenar --dias 14 --semilla 100
Guarda el modelo en backend/modelos/pronostico.joblib.
"""
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from app.prediction.features import COLUMNAS, dataset_entrenamiento
from app.sim.escenario import escenario_actual
from app.sim.historico import generar

log = logging.getLogger("fluport.prediccion")
RUTA_MODELO = Path(__file__).resolve().parents[2] / "modelos" / "pronostico.joblib"
DIAS_PRUEBA = 3


def entrenar(dias: int = 14, semilla: int = 100, persistir: bool = True, ruta: Path = RUTA_MODELO) -> dict:
    t0 = time.perf_counter()
    esc = escenario_actual()
    corrida, lecturas = generar(dias + DIAS_PRUEBA, semilla, persistir=persistir)
    df = pd.DataFrame(lecturas)
    df["mundo"] = df["mundo"].astype(str).str.replace("Mundo.", "", regex=False)
    df["clima"] = df["clima"].astype(str).str.replace("Clima.", "", regex=False)
    accesos = {a.id: (a.carriles, a.tiempo_servicio_min) for a in esc.accesos}

    # separación temporal: los últimos días se reservan para evaluar (no se mezclan con el entrenamiento)
    corte = pd.to_datetime(df["ts_sim"]).max() - pd.Timedelta(days=DIAS_PRUEBA)
    ts = pd.to_datetime(df["ts_sim"])
    x_ent, y_ent = dataset_entrenamiento(df[ts <= corte], accesos, esc.norte.factor_servicio)
    x_pru, y_pru = dataset_entrenamiento(df[ts > corte], accesos, esc.norte.factor_servicio)

    modelo = HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
        categorical_features=[COLUMNAS.index("acceso_idx"), COLUMNAS.index("mundo_idx")], random_state=0,
    )
    # el modelo aprende la CORRECCIÓN sobre la proyección por balance de flujo (residuo):
    # así puede extrapolar en situaciones extremas (p. ej. norte) que los árboles solos no alcanzan
    modelo.fit(x_ent, y_ent - x_ent["espera_fluida_obj"])
    pred = np.clip(modelo.predict(x_pru) + x_pru["espera_fluida_obj"], 0, None)
    mae_modelo = float(np.mean(np.abs(pred - y_pru)))
    mae_fluido = float(np.mean(np.abs(x_pru["espera_fluida_obj"] - y_pru)))
    mae_persistencia = float(np.mean(np.abs(x_pru["espera_actual"] - y_pru)))
    congestion = y_pru >= 20  # error cuando importa: esperas de 20 min o más (semáforo amarillo/rojo)
    mae_congestion = float(np.mean(np.abs(pred[congestion] - y_pru[congestion]))) if congestion.any() else 0.0

    version = f"hgb-{datetime.now():%Y%m%d%H%M}-s{semilla}"
    metricas = {
        "version": version, "corrida_id": corrida, "dias_entrenamiento": dias, "dias_prueba": DIAS_PRUEBA,
        "filas_entrenamiento": len(x_ent), "filas_prueba": len(x_pru),
        "mae_modelo_min": round(mae_modelo, 1), "mae_modelo_congestion_min": round(mae_congestion, 1),
        "pct_prueba_congestion": round(100 * float(congestion.mean()), 1), "mae_balance_flujo_min": round(mae_fluido, 1),
        "mae_persistencia_min": round(mae_persistencia, 1), "segundos": round(time.perf_counter() - t0, 1),
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modelo": modelo, "columnas": COLUMNAS, "objetivo": "residuo_sobre_balance_flujo", "accesos": sorted(accesos), "metricas": metricas}, ruta)
    log.info("Modelo %s guardado: %s", version, metricas)
    return metricas


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--semilla", type=int, default=100)
    ap.add_argument("--sin-bd", action="store_true", help="no guardar el histórico en PostgreSQL")
    a = ap.parse_args()
    m = entrenar(a.dias, a.semilla, persistir=not a.sin_bd)
    print(f"Modelo {m['version']}: error medio {m['mae_modelo_min']} min, "
          f"{m['mae_modelo_congestion_min']} min con espera ≥ 20 ({m['pct_prueba_congestion']} % de casos) "
          f"(balance de flujo {m['mae_balance_flujo_min']}, persistencia {m['mae_persistencia_min']}).")


if __name__ == "__main__":
    main()
