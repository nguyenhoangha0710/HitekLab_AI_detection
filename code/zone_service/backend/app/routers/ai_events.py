from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import ZoneServiceSettings
from ..database import Database
from ..models import AiEventCreate, AiEventOut, AlertOut, EvidenceOut
from ..repositories.ai_event_repository import AiEventRepository
from ..repositories.alert_repository import AlertRepository
from ..repositories.evidence_repository import EvidenceRepository
from ..serializers import ai_event_out, alert_out, evidence_out, evidence_path
from ..services.evidence_capture_service import EvidenceCaptureService


def create_ai_event_router(database: Database, settings: ZoneServiceSettings) -> APIRouter:
    router = APIRouter(tags=["ai-events"])

    @router.get("/api/ai-events", response_model=List[AiEventOut])
    def list_ai_events(camera_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)):
        with database.session() as connection:
            rows = AiEventRepository(connection, database).list(camera_id=camera_id, limit=limit)
            return [ai_event_out(row) for row in rows]

    @router.get("/api/alerts", response_model=List[AlertOut])
    def list_alerts(camera_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)):
        with database.session() as connection:
            rows = AlertRepository(connection, database).list(camera_id=camera_id, limit=limit)
            return [alert_out(row) for row in rows]

    @router.post("/api/ai-events", response_model=AiEventOut, status_code=201)
    def upsert_ai_event(payload: AiEventCreate):
        with database.session() as connection:
            data = payload.dict()
            alert = AlertRepository(connection, database).upsert_for_violation(data)
            if alert is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            data["alert_id"] = str(alert["id"])
            row = AiEventRepository(connection, database).upsert(data)
            if row is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            _capture_snapshot_evidence(connection, database, settings, row, data)
            return ai_event_out(row)

    @router.get("/api/evidence", response_model=List[EvidenceOut])
    def list_evidence(camera_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)):
        with database.session() as connection:
            rows = EvidenceRepository(connection, database).list(camera_id=camera_id, limit=limit)
            return [evidence_out(row) for row in rows]

    @router.get("/api/ai-events/{ai_event_id}/evidence", response_model=List[EvidenceOut])
    def list_event_evidence(ai_event_id: str):
        with database.session() as connection:
            rows = EvidenceRepository(connection, database).list_by_event(ai_event_id)
            return [evidence_out(row) for row in rows]

    @router.get("/api/evidence/{evidence_id}/media")
    def get_evidence_media(evidence_id: str):
        with database.session() as connection:
            row = EvidenceRepository(connection, database).get(evidence_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Evidence not found")
            path = evidence_path(settings.evidence_dir, row["storage_key"])
            if path is None or not path.exists():
                raise HTTPException(status_code=404, detail="Evidence file not found")
            return FileResponse(str(path), media_type=row["mime_type"])

    return router


def _capture_snapshot_evidence(connection, database: Database, settings: ZoneServiceSettings, event_row, payload: dict) -> None:
    event_payload = payload.get("payload") or {}
    frame_id = event_payload.get("frame_id")
    repository = EvidenceRepository(connection, database)
    if repository.exists_for_alert(payload.get("alert_id")):
        return
    if repository.exists_for_event(str(event_row["id"]), frame_id):
        return

    try:
        storage_key, file_size = EvidenceCaptureService(
            settings.edge_gateway_base_url,
            settings.evidence_dir,
        ).capture_snapshot(payload["camera_id"], str(event_row["id"]), frame_id)
    except Exception:
        return

    repository.create(
        {
            "ai_event_id": str(event_row["id"]),
            "alert_id": payload.get("alert_id"),
            "camera_id": payload["camera_id"],
            "evidence_type": "snapshot",
            "storage_key": storage_key,
            "mime_type": "image/jpeg",
            "file_size": file_size,
            "frame_id": frame_id,
            "sequence_number": payload.get("last_sequence_number"),
            "captured_at": payload.get("last_seen_at") or payload["started_at"],
        }
    )
