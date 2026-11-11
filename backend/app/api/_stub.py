"""Helper para endpoints aún no implementados (contrato congelado, implementación pendiente)."""
from fastapi import HTTPException


def pendiente(modulo: str) -> HTTPException:
    return HTTPException(status_code=501, detail=f"Pendiente de implementar en {modulo}")
