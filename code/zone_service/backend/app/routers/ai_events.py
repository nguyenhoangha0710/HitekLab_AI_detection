import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..config import ZoneServiceSettings
from ..database import Database
from ..models import AiEventCreate, AiEventOut, AlertOut, EvidenceOut
from ..repositories.ai_event_repository import AiEventRepository
from ..repositories.alert_repository import AlertRepository
from ..repositories.camera_repository import CameraRepository
from ..repositories.evidence_repository import EvidenceRepository
from ..serializers import ai_event_out, alert_out, evidence_out, evidence_path
from ..services.evidence_capture_service import EvidenceCaptureService
from ..services.evidence_policy_service import should_capture_alert_evidence as _should_capture_alert_evidence
from ..services.evidence_storage_service import EvidenceStorageService
from ..services.backend_event_client import BackendEventClient
from ..services.evidence_video_request_service import request_video_evidence, video_storage_key


LOGGER = logging.getLogger(__name__)


def build_backend_client(settings: ZoneServiceSettings) -> BackendEventClient:
    return BackendEventClient(
        base_url=settings.backend_base_url,
        client_id=settings.backend_client_id,
        client_secret=settings.backend_client_secret,
        timeout_seconds=settings.backend_timeout_seconds,
    )


def create_ai_event_router(
    database: Database,
    settings: ZoneServiceSettings,
    backend_client: Optional[BackendEventClient] = None,
) -> APIRouter:
    router = APIRouter(tags=["ai-events"])
    use_backend = settings.alert_mode == "backend"
    if use_backend and backend_client is None:
        backend_client = build_backend_client(settings)

    @router.get("/api/integration/backend")
    def backend_integration_status():
        """Trang thai ket noi Backend API: so event da gui, alertId nhan ve, loi gan nhat."""
        if not use_backend:
            return {"alert_mode": settings.alert_mode, "enabled": False}
        return {"alert_mode": settings.alert_mode, "enabled": True, **backend_client.status()}

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
        data = payload.dict()
        if use_backend:
            row = _upsert_via_backend(database, settings, backend_client, data)
        else:
            row = _upsert_with_local_alert(database, settings, data)
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


def _capture_snapshot_evidence(connection, database: Database, settings: ZoneServiceSettings, event_row, payload: dict) -> bool:
    """Chup snapshot cho alert neu dung policy. Tra ve True neu vua tao evidence moi."""
    event_payload = payload.get("payload") or {}
    frame_id = event_payload.get("frame_id")
    repository = EvidenceRepository(connection, database)
    if not _should_capture_alert_evidence(
        repository, payload.get("alert_id"), payload, settings.evidence_interval_seconds, str(event_row["id"])
    ):
        return False
    if repository.exists_for_event(str(event_row["id"]), frame_id):
        return False

    try:
        storage_key, file_size = EvidenceCaptureService(settings).capture_snapshot(
            payload["camera_id"], str(event_row["id"]), frame_id
        )
    except Exception:
        return False

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
    return True


def _upsert_with_local_alert(database: Database, settings: ZoneServiceSettings, data: dict):
    """ALERT_MODE=local: Zone Service tu gom alert (che do chay thu khong co Backend)."""
    with database.session() as connection:
        event_repository = AiEventRepository(connection, database)
        # AI Service gui lai cung source_event_id dinh ky (heartbeat) khi vi pham
        # con keo dai -> chi cap nhat last_seen, khong dem thanh nguon moi.
        is_new_source = event_repository.get_by_source_event_id(data["source_event_id"]) is None
        alert_repository = AlertRepository(connection, database)
        alert_repository.resolve_stale(settings.alert_resolve_grace_seconds)
        alert = alert_repository.upsert_for_violation(data, is_new_source=is_new_source)
        if alert is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        data["alert_id"] = str(alert["id"])
        row = event_repository.upsert(data)
        if row is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        # Clip video chi xin khi vua chup snapshot moi (theo EVIDENCE_INTERVAL_SECONDS),
        # tranh moi heartbeat lai ghi 1 clip.
        if _capture_snapshot_evidence(connection, database, settings, row, data):
            request_video_evidence(settings, row, data)
        return row


def _upsert_via_backend(database: Database, settings: ZoneServiceSettings, backend_client, data: dict):
    """ALERT_MODE=backend: ghi ai_event -> commit -> POST Backend /api/v1/events -> gan alertId.

    Phai commit ai_event truoc khi goi Backend, vi Backend doc ai_event tu database
    (neu chua commit se nhan loi AI_EVENT_NOT_FOUND).
    """
    data["alert_id"] = None
    # 1) Ghi ai_event va commit.
    with database.session() as connection:
        camera = CameraRepository(connection, database).get_camera(data["camera_id"])
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        row = AiEventRepository(connection, database).upsert(data)
        if row is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        area_id = str(camera["location_id"])

    # 2) Goi Backend (ngoai transaction). Loi Backend khong lam hong ai_event da luu.
    result = backend_client.send_event(build_backend_event_payload(row, data, area_id))

    # 3) Gan alertId (neu co) va xu ly bang chung.
    with database.session() as connection:
        event_repository = AiEventRepository(connection, database)
        alert_id = result.alert_id if result.ok else None
        if alert_id:
            try:
                with _savepoint(connection, database):
                    AlertRepository(connection, database).ensure_backend_alert(alert_id, data)
                    row = event_repository.set_alert_id(str(row["id"]), alert_id)
                    EvidenceRepository(connection, database).attach_alert(str(row["id"]), alert_id)
            except Exception as exc:
                LOGGER.warning("BACKEND_ALERT_LINK_FAILED ai_event_id=%s alert_id=%s error=%s", row["id"], alert_id, exc)
                alert_id = None
                row = event_repository.get(str(row["id"]))
        elif row["alert_id"]:
            alert_id = str(row["alert_id"])

        data["alert_id"] = alert_id
        if _capture_snapshot_evidence(connection, database, settings, row, data):
            request_video_evidence(settings, row, data)
        return row


def build_backend_event_payload(row, data: dict, area_id: str) -> Dict[str, Any]:
    """Payload POST /api/v1/events theo thong nhat voi nhom Backend.

    event_type khong gui: Backend tu doc tu ai_event.event_type.
    """
    return {
        "cameraId": str(row["camera_id"]),
        "areaId": area_id,
        "objectType": data.get("object_type") or "person",
        "confidence": _event_confidence(data),
        "occurredAt": _iso_text(data.get("last_seen_at") or data["started_at"]),
        "aiEventId": str(row["id"]),
    }


def _event_confidence(data: dict) -> float:
    if data.get("confidence") is not None:
        return float(data["confidence"])
    detection = (data.get("payload") or {}).get("detection") or {}
    if detection.get("confidence") is not None:
        return float(detection["confidence"])
    objects = ((data.get("payload") or {}).get("contract") or {}).get("objects") or []
    values = [float(obj["confidence"]) for obj in objects if obj.get("confidence") is not None]
    # crowd_limit: lay confidence thap nhat trong nhom; khong co thi coi la chac chan.
    return min(values) if values else 1.0


def _iso_text(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class _savepoint:
    """SAVEPOINT de loi khoa ngoai khi gan alertId khong lam hong ca transaction."""

    def __init__(self, connection, database: Database) -> None:
        self.connection = connection
        self.database = database

    def __enter__(self):
        self.connection.execute("SAVEPOINT backend_alert_link")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.connection.execute("RELEASE SAVEPOINT backend_alert_link")
        else:
            self.connection.execute("ROLLBACK TO SAVEPOINT backend_alert_link")
            self.connection.execute("RELEASE SAVEPOINT backend_alert_link")
        return False

