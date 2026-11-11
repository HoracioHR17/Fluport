"""Variables de entrada del pronóstico, compartidas por el entrenamiento y la predicción en vivo.

Para cada acceso, en el instante t, se predice la espera en t + h (h = 30, 60, …, 720 min).
Una de las variables es una **proyección de fila por balance de flujo** (llegadas conocidas − capacidad),
que también sirve como pronóstico de respaldo cuando no hay modelo entrenado.
"""
from collections.abc import Sequence

import numpy as np
import pandas as pd

FRANJA_MIN = 30
PASO_LECTURA_MIN = 15
HORIZONTES = list(range(FRANJA_MIN, 12 * 60 + 1, FRANJA_MIN))  # 24 horizontes

COLUMNAS = [
    "acceso_idx", "mundo_idx", "h_min", "hora_obj", "dia_semana_obj",
    "fila_actual", "espera_actual", "llegadas_hora", "atendidos_hora",
    "norte_actual", "citas_franja_obj", "buques_obj", "espera_fluida_obj", "carriles", "servicio_min",
]


def capacidad_franja(carriles: int, servicio_min: float, factor: float = 1.0) -> float:
    """Camiones que un acceso puede atender en una franja de 30 min."""
    return carriles * FRANJA_MIN / (servicio_min * factor)


def espera_de_fila(fila: float, carriles: int, servicio_min: float, factor: float = 1.0) -> float:
    """Minutos que espera un camión al final de una fila de `fila` camiones."""
    return fila * servicio_min * factor / carriles


def proyeccion_fluida(fila0: float, llegadas: Sequence[float], capacidad: Sequence[float]) -> np.ndarray:
    """Fila al final de cada franja: q[k] = max(0, q[k−1] + llegadas[k] − capacidad[k])."""
    q, res = float(fila0), np.empty(len(llegadas))
    for k, (a, c) in enumerate(zip(llegadas, capacidad)):
        q = max(0.0, q + a - c)
        res[k] = q
    return res


def dataset_entrenamiento(lecturas: pd.DataFrame, accesos: dict[str, tuple[int, float]], factor_norte: float):
    """Convierte la serie de lecturas (cada 15 min) en filas (estado en t → espera en t+h).

    `accesos`: id → (carriles, minutos de servicio). Devuelve (X, y).
    """
    ids = sorted(accesos)
    filas: list[list[float]] = []
    objetivo: list[float] = []
    pasos_franja = FRANJA_MIN // PASO_LECTURA_MIN
    for (_, mundo, acc), g in lecturas.sort_values("ts_sim").groupby(["corrida_id", "mundo", "acceso_id"]):
        carriles, servicio = accesos[acc]
        ts = pd.to_datetime(g["ts_sim"]).reset_index(drop=True)
        fila = g["camiones_en_fila"].to_numpy(float)
        espera = g["espera_min"].to_numpy(float)
        lleg = g["llegadas_hora"].to_numpy(float)
        aten = g["atendidos_hora"].to_numpy(float)
        citas = g["citas_franja"].to_numpy(float)
        buques = g["buques_atracados"].to_numpy(float)
        norte = (g["clima"].astype(str) == "norte").to_numpy(float)
        n = len(g)
        max_paso = HORIZONTES[-1] // PASO_LECTURA_MIN
        for i in range(0, n - max_paso):
            factor = factor_norte if norte[i] else 1.0
            idx_franjas = [i + k * pasos_franja for k in range(1, len(HORIZONTES) + 1)]
            cap = capacidad_franja(carriles, servicio, factor)
            q = proyeccion_fluida(fila[i], citas[idx_franjas], [cap] * len(idx_franjas))
            for k, h in enumerate(HORIZONTES):
                j = idx_franjas[k]
                t_obj = ts[j]
                filas.append([
                    ids.index(acc), 0 if str(mundo) in ("A", "Mundo.A") else 1, h,
                    t_obj.hour + t_obj.minute / 60, t_obj.dayofweek,
                    fila[i], espera[i], lleg[i], aten[i], norte[i], citas[j], buques[j],
                    espera_de_fila(q[k], carriles, servicio, factor), carriles, servicio,
                ])
                objetivo.append(espera[j])
    return pd.DataFrame(filas, columns=COLUMNAS), np.asarray(objetivo)
