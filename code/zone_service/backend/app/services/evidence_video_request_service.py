import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import ZoneServiceSettings
from .evidence_policy_service import parse_time

LOGGER = logging.getLogger(__name__)


def request_video_evidence(settings: ZoneServiceSettings, event_row, payload: dict) -> None:
    if not settings.evidence_video_enabled:
        return

    event_payload = payload.get("payload") or {}
    request_payload = {
        "ai_event_id": str(event_row["id"]),
        "alert_id": payload.get("alert_id"),
        "camera_id": payload["camera_id"],
        "frame_id": event_payload.get("frame_id"),
        "sequence_number": payload.get("last_sequence_number"),
        "captured_at": payload.get("last_seen_at") or payload["started_at"],
        "pre_seconds": settings.evidence_video_pre_seconds,
        "post_seconds": settings.evidence_video_post_seconds,
        "fps": settings.evidence_video_fps,
        "upload_url": settings.evidence_video_upload_url,
    }
    url = "{}/api/evidence-recordings".format(settings.edge_gateway_base_url)
    body = json.dumps(request_payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(request, timeout=1).read()
    except Exception as exc:
        # Khong lam hong luong su kien, nhung phai de lai dau vet de biet vi sao khong co clip.
        LOGGER.warning(
            "EVIDENCE_VIDEO_REQUEST_FAILED ai_event_id=%s camera=%s url=%s error=%s",
            request_payload["ai_event_id"],
            request_payload["camera_id"],
            url,
            exc,
        )
        return
    LOGGER.info("EVIDENCE_VIDEO_REQUESTED ai_event_id=%s camera=%s", request_payload["ai_event_id"], request_payload["camera_id"])


def video_storage_key(payload: dict, filename: Optional[str]) -> str:
    ai_event_id = safe_path_part(str(payload["ai_event_id"]))
    camera_id = safe_path_part(str(payload["camera_id"]))
    captured_at = parse_time(payload.get("captured_at")) or datetime.now(timezone.utc)
    suffix = Path(filename or "clip.mp4").suffix or ".mp4"
    return "evidence/{}/{}/{:04d}/{:02d}/{:02d}/{}/clip{}".format(
        safe_path_part(str(payload.get("tenant_id") or "default")),
        camera_id,
        captured_at.year,
        captured_at.month,
        captured_at.day,
        ai_event_id,
        suffix,
    )


def safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
