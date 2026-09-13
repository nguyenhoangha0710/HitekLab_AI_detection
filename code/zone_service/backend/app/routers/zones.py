from typing import List

from fastapi import APIRouter, HTTPException

from ..database import Database
from ..models import ZoneCreate, ZoneOut, ZoneUpdate
from ..repositories.camera_repository import CameraRepository
from ..repositories.zone_repository import ZoneRepository
from ..serializers import zone_out


def create_zone_router(database: Database) -> APIRouter:
    router = APIRouter(tags=["zones"])

    @router.get("/api/cameras/{camera_id}/zones", response_model=List[ZoneOut])
    def list_zones(camera_id: str):
        with database.session() as connection:
            if CameraRepository(connection).get_camera(camera_id) is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            rows = ZoneRepository(connection).list_by_camera(camera_id)
            return [zone_out(row) for row in rows]

    @router.post("/api/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=201)
    def create_zone(camera_id: str, payload: ZoneCreate):
        with database.session() as connection:
            if CameraRepository(connection).get_camera(camera_id) is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            row = ZoneRepository(connection).create(camera_id, payload.dict())
            return zone_out(row)

    @router.put("/api/zones/{zone_id}", response_model=ZoneOut)
    def update_zone(zone_id: str, payload: ZoneUpdate):
        with database.session() as connection:
            row = ZoneRepository(connection).update(zone_id, payload.dict(exclude_unset=True))
            if row is None:
                raise HTTPException(status_code=404, detail="Zone not found")
            return zone_out(row)

    @router.delete("/api/zones/{zone_id}", status_code=204)
    def delete_zone(zone_id: str):
        with database.session() as connection:
            if not ZoneRepository(connection).delete(zone_id):
                raise HTTPException(status_code=404, detail="Zone not found")
        return None

    return router
