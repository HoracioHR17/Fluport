"""Corredores de llegada al puerto y minutos de rodeo entre ellos.

Cada entrada pertenece a un corredor (`Acceso.entrada`): norte (Xalapa/Cardel por la MEX-140 y el bulevar portuario),
sur (Córdoba y Paso del Toro por San Julián y Santa Fe) o urbana (por la ciudad). Un camión que viene por un corredor no
debe mandarse a una entrada de otro sin cobrar el rodeo: así la decisión toma en cuenta de dónde viene.
"""
# SUPUESTO: minutos extra de manejo para cambiar de corredor (por validar con el equipo de Datos)
_RODEO = {
    frozenset({"norte", "urbana"}): 20.0,
    frozenset({"sur", "urbana"}): 20.0,
    frozenset({"norte", "sur"}): 45.0,
}
CORREDORES = ("norte", "sur", "urbana")


def rodeo_min(origen: str | None, destino: str | None) -> float:
    """Minutos extra por llegar a una entrada del corredor `destino` viniendo por `origen` (0 si es el mismo o se
    desconoce el origen)."""
    if not origen or not destino or origen == destino:
        return 0.0
    return _RODEO.get(frozenset({origen, destino}), 30.0)
