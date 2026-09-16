import json
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..config import ZoneServiceSettings
from ..database import Database
from ..models import AiEventCreate, AiEventOut, AlertOut, EvidenceOut
from ..repositories.ai_event_repository import AiEventRepository
from ..repositories.alert_repository import AlertRepository
from ..repositories.evidence_repository import EvidenceRepository
from ..serializers import ai_event_out, alert_out, evidence_out, evidence_path
from ..services.evidence_capture_service import EvidenceCaptureService
from ..services.evidence_policy_service import should_capture_alert_evidence as _should_capture_alert_evidence
from ..services.evidence_storage_service import EvidenceStorageService
from ..services.evidence_video_request_service import request_video_evidence, video_storage_key


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
            repository = AlertRepository(connection, database)
            repository.resolve_stale(settings.alert_resolve_grace_seconds)
            rows = repository.list(camera_id=camera_id, limit=limit)
            return [alert_out(row) for row in rows]

    @router.post("/api/ai-events", response_model=AiEventOut, status_code=201)
    def upsert_ai_event(payload: AiEventCreate):
        with database.session() as connection:
            data = payload.dict()
            alert_repository = AlertRepository(connection, database)
            alert_repository.resolve_stale(settings.alert_resolve_grace_seconds)
            alert = alert_repository.upsert_for_violation(data)
            if alert is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            data["alert_id"] = str(alert["id"])
            row = AiEventRepository(connection, database).upsert(data)
            if row is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            _capture_snapshot_evidence(connection, database, settings, row, data)
            request_video_evidence(settings, row, data)
            return ai_event_out(row)

    @router.get("/api/evidence", response_model=List[EvidenceOut])
    def list_evidence(
        camera_id: Optional[str] = None,
        event_type: Optional[str] = None,
        evidence_type: Optional[str] = None,
        status: Optional[str] = None,
        from_time: Optional[str] = Query(None, alias="from"),
        to_time: Optional[str] = Query(None, alias="to"),
        zone_id: Optional[str] = None,
        object_type: Optional[str] = None,
        limit: int = Query(100, ge=1, le=500),
    ):
        with database.session() as connection:
            rows = EvidenceRepository(connection, database).list(
                camera_id=camera_id,
                event_type=event_type,
                evidence_type=evidence_type,
                status=status,
                from_time=from_time,
                to_time=to_time,
                zone_id=zone_id,
                object_type=object_type,
                limit=limit,
            )
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
            storage = EvidenceStorageService(settings)
            if storage.is_minio_enabled():
                try:
                    content, media_type = storage.read_bytes(row["storage_key"])
                except Exception:
                    raise HTTPException(status_code=404, detail="Evidence file not found")
                return Response(content=content, media_type=media_type)
            path = evidence_path(settings.evidence_dir, row["storage_key"])
            if path is None or not path.exists():
                raise HTTPException(status_code=404, detail="Evidence file not found")
            return FileResponse(str(path), media_type=row["mime_type"])

    @router.post("/api/evidence/video", response_model=EvidenceOut, status_code=201)
    async def create_video_evidence(metadata: str = Form(...), file: UploadFile = File(...)):
        try:
            payload = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid evidence metadata JSON")

        required_fields = ["ai_event_id", "alert_id", "camera_id", "captured_at"]
        missing = [field for field in required_fields if not payload.get(field)]
        if missing:
            raise HTTPException(status_code=400, detail="Missing fields: {}".format(", ".join(missing)))

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded evidence video is empty")

        storage_key = payload.get("storage_key") or video_storage_key(payload, file.filename)
        mime_type = file.content_type or "video/mp4"
        file_size = EvidenceStorageService(settings).save_bytes(storage_key, content, mime_type)

        with database.session() as connection:
            row = EvidenceRepository(connection, database).create(
                {
                    "ai_event_id": payload["ai_event_id"],
                    "alert_id": payload.get("alert_id"),
                    "camera_id": payload["camera_id"],
                    "evidence_type": payload.get("evidence_type", "video_clip"),
                    "storage_key": storage_key,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "frame_id": payload.get("frame_id"),
                    "sequence_number": payload.get("sequence_number"),
                    "captured_at": payload["captured_at"],
                    "started_at": payload.get("started_at"),
                    "ended_at": payload.get("ended_at"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "codec": payload.get("codec", "h264"),
                    "fps": payload.get("fps"),
                    "frame_width": payload.get("frame_width"),
                    "frame_height": payload.get("frame_height"),
                    "status": payload.get("status", "completed"),
                }
            )
            if row is None:
                raise HTTPException(status_code=404, detail="AI event not found")
            return evidence_out(row)

    return router


def _capture_snapshot_evidence(connection, database: Database, settings: ZoneServiceSettings, event_row, payload: dict) -> None:
    event_payload = payload.get("payload") or {}
    frame_id = event_payload.get("frame_id")
    repository = EvidenceRepository(connection, database)
    if not _should_capture_alert_evidence(repository, payload.get("alert_id"), payload, settings.evidence_interval_seconds):
        return
    if repository.exists_for_event(str(event_row["id"]), frame_id):
        return

    try:
        storage_key, file_size = EvidenceCaptureService(settings).capture_snapshot(
            payload["camera_id"], str(event_row["id"]), frame_id
        )
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
