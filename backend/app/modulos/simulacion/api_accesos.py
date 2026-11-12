"""Accesos y su estado actual (M1)."""
from fastapi import APIRouter, Query

from app.modulos.simulacion.servicio import servicio
from app.nucleo.contracts.enums import Mundo
from app.nucleo.contracts.schemas import AccesoEstado, AccesoOut

router = APIRouter(prefix="/api/accesos", tags=["accesos"])


@router.get("", response_model=list[AccesoOut])
async def listar_accesos() -> list[AccesoOut]:
    sim = servicio.requerir()
    estados = {a.id: a.estado for a in sim.mundos[Mundo.B].accesos.values()}
    return [
        AccesoOut(
            id=a.id, nombre=a.nombre, zona=a.zona, lat=a.lat, lon=a.lon, carriles=a.carriles,
            tiempo_servicio_min=a.tiempo_servicio_min, capacidad_hora=a.capacidad_hora, estado=estados[a.id],
            entrada=a.entrada,
        )
        for a in sim.esc.accesos
    ]


@router.get("/rutas")
async def rutas() -> dict:
    """GeoJSON (FeatureCollection) con los accesos (Point) y sus rutas (LineString, coordenadas [lon, lat]).

    `CamionEstado.progreso` (0..1) se mide sobre la LineString con el mismo `ruta_id`.
    """
    esc = servicio.requerir().esc
    feats: list[dict] = []
    for a in esc.accesos:
        feats.append({"type": "Feature", "id": a.id, "geometry": {"type": "Point", "coordinates": [a.lon, a.lat]},
                      "properties": {"tipo": "acceso", "acceso_id": a.id, "nombre": a.nombre, "zona": a.zona}})
        for r in a.rutas:
            feats.append({"type": "Feature", "id": r.id,
                          "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in r.coords]},
                          "properties": {"tipo": "ruta", "ruta_id": r.id, "acceso_id": a.id}})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/estado", response_model=list[AccesoEstado])
async def estado_accesos(mundo: Mundo = Query(Mundo.B)) -> list[AccesoEstado]:
    return servicio.requerir().estado_accesos(mundo)
