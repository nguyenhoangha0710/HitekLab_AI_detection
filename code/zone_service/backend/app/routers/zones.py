from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..access_control import AccessControl, Principal
from ..auth import principal_dependency
from ..database import Database
from ..models import RuleConfigOut, RuleConfigUpdate, ZoneCreate, ZoneOut, ZoneUpdate
from ..repositories.camera_repository import CameraRepository
from ..repositories.rule_config_repository import RuleConfigRepository
from ..repositories.zone_repository import ZoneRepository
from ..serializers import rule_config_out, zone_out


def create_zone_router(database: Database, access: Optional[AccessControl] = None) -> APIRouter:
    router = APIRouter(tags=["zones"])
    if access is None:
        from ..config import load_settings

        access = AccessControl(database, load_settings())
    current_principal = principal_dependency(access)

    @router.get("/api/cameras/{camera_id}/zones", response_model=List[ZoneOut])
    def list_zones(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)
            rows = ZoneRepository(connection, database).list_by_camera(camera_id)
            return [zone_out(row) for row in rows]

    @router.post("/api/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=201)
    def create_zone(camera_id: str, payload: ZoneCreate, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id, "admin")
            row = ZoneRepository(connection, database).create(camera_id, payload.dict())
            return zone_out(row)

    @router.put("/api/zones/{zone_id}", response_model=ZoneOut)
    def update_zone(zone_id: str, payload: ZoneUpdate, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_via(principal, connection, "zone", zone_id, "admin")
            row = ZoneRepository(connection, database).update(zone_id, payload.dict(exclude_unset=True))
            if row is None:
                raise HTTPException(status_code=404, detail="Zone not found")
            return zone_out(row)

    @router.get("/api/zones/{zone_id}/rules", response_model=List[RuleConfigOut])
    def list_zone_rules(zone_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_via(principal, connection, "zone", zone_id)
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
    def update_rule(rule_id: str, payload: RuleConfigUpdate, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_rule(principal, connection, rule_id, "admin")
            row = RuleConfigRepository(connection, database).update(rule_id, payload.dict(exclude_unset=True))
            if row is None:
                raise HTTPException(status_code=404, detail="Rule not found")
            return rule_config_out(row)

    @router.delete("/api/zones/{zone_id}", status_code=204)
    def delete_zone(zone_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_via(principal, connection, "zone", zone_id, "admin")
            if not ZoneRepository(connection, database).delete(zone_id):
                raise HTTPException(status_code=404, detail="Zone not found")
        return None

    return router
