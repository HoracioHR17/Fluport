"""Fórmulas de filas compartidas por la simulación, el pronóstico y las citas.

La operación se planea en franjas de 30 min; una fila de `fila` camiones en una caseta con `carriles` carriles y
`servicio_min` minutos de revisión por camión tarda `fila · servicio / carriles` minutos en desahogarse.
"""
FRANJA_MIN = 30


def capacidad_franja(carriles: int, servicio_min: float, factor: float = 1.0) -> float:
    """Camiones que un acceso puede atender en una franja de 30 min."""
    return carriles * FRANJA_MIN / (servicio_min * factor)


def espera_de_fila(fila: float, carriles: int, servicio_min: float, factor: float = 1.0) -> float:
    """Minutos que espera un camión al final de una fila de `fila` camiones."""
    return fila * servicio_min * factor / carriles
