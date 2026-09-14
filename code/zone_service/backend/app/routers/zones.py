from typing import List

from fastapi import APIRouter, HTTPException

from ..database import Database
from ..models import RuleConfigOut, RuleConfigUpdate, ZoneCreate, ZoneOut, ZoneUpdate
from ..repositories.camera_repository import CameraRepository
from ..repositories.rule_config_repository import RuleConfigRepository
from ..repositories.zone_repository import ZoneRepository
from ..serializers import rule_config_out, zone_out


def create_zone_router(database: Database) -> APIRouter:
    router = APIRouter(tags=["zones"])

    @router.get("/api/cameras/{camera_id}/zones", response_model=List[ZoneOut])
    def list_zones(camera_id: str):
        with database.session() as connection:
            if CameraRepository(connection, database).get_camera(camera_id) is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            rows = ZoneRepository(connection, database).list_by_camera(camera_id)
            return [zone_out(row) for row in rows]

    @router.post("/api/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=201)
    def create_zone(camera_id: str, payload: ZoneCreate):
        with database.session() as connection:
            if CameraRepository(connection, database).get_camera(camera_id) is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            row = ZoneRepository(connection, database).create(camera_id, payload.dict())
            return zone_out(row)

    @router.put("/api/zones/{zone_id}", response_model=ZoneOut)
    def update_zone(zone_id: str, payload: ZoneUpdate):
        with database.session() as connection:
            row = ZoneRepository(connection, database).update(zone_id, payload.dict(exclude_unset=True))
            if row is None:
                raise HTTPException(status_code=404, detail="Zone not found")
            return zone_out(row)

    @router.get("/api/zones/{zone_id}/rules", response_model=List[RuleConfigOut])
    def list_zone_rules(zone_id: str):
        with database.session() as connection:
            zone = ZoneRepository(connection, database).get(zone_id)
            if zone is None:
                raise HTTPException(status_code=404, detail="Zone not found")
            repository = RuleConfigRepository(connection, database)
            rows = repository.list_by_zone(zone_id)
            if not rows:
                repository.create_defaults_for_zone(zone)
                rows = repository.list_by_zone(zone_id)
            return [rule_config_out(row) for row in rows]

    @router.put("/api/rules/{rule_id}", response_model=RuleConfigOut)
    def update_rule(rule_id: str, payload: RuleConfigUpdate):
        with database.session() as connection:
            row = RuleConfigRepository(connection, database).update(rule_id, payload.dict(exclude_unset=True))
            if row is None:
                raise HTTPException(status_code=404, detail="Rule not found")
            return rule_config_out(row)

    @router.delete("/api/zones/{zone_id}", status_code=204)
    def delete_zone(zone_id: str):
        with database.session() as connection:
            if not ZoneRepository(connection, database).delete(zone_id):
                raise HTTPException(status_code=404, detail="Zone not found")
        return None

    return router
