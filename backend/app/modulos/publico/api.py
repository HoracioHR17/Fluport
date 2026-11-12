"""Vista pública para vecinos (M7): sin datos de operación."""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.modulos.publico.servicio import snapshot_publico
from app.modulos.publico.servicio import zonas as calcular_zonas
from app.nucleo.contracts.schemas import ZonaPublica
from app.nucleo.dependencias import desuscribir, operacion, suscribir

router = APIRouter(tags=["publico"])
log = logging.getLogger("fluport.ws")


@router.get("/api/publico/zonas", response_model=list[ZonaPublica])
async def zonas() -> list[ZonaPublica]:
    """Semáforo actual, horas pico de las próximas 12 h y mejor hora para circular, por entrada."""
    return calcular_zonas(operacion())


@router.get("/api/publico/snapshot")
async def snapshot() -> dict:
    """Estado instantáneo de las entradas (respaldo por sondeo de /ws/publico)."""
    return snapshot_publico(operacion())


@router.websocket("/ws/publico")
async def ws_publico(ws: WebSocket) -> None:
    """Stream público: en cada tick del simulador manda solo el estado de las entradas.

    A diferencia de /ws/sim, nunca envía camiones, agencias, citas, avisos ni eventos internos.
    """
    await ws.accept()
    cola = suscribir()
    try:
        await ws.send_text(json.dumps(snapshot_publico(operacion())))  # estado inicial
        while True:
            mensaje = await cola.get()
            if '"tipo":"snapshot"' in mensaje[:60]:  # un tick nuevo: se manda el resumen público
                await ws.send_text(json.dumps(snapshot_publico(operacion())))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:  # noqa: BLE001  (p. ej. la simulación aún no arranca)
        log.warning("WebSocket público cerrado por un error", exc_info=True)
    finally:
        desuscribir(cola)
