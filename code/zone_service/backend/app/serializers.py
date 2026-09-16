import json
from pathlib import Path
from typing import Optional

from .models import AiEventOut, AlertOut, CameraOut, EvidenceOut, ReferenceFrameOut, RuleConfigOut, ZoneOut


def camera_out(row, edge_gateway_base_url: str) -> CameraOut:
    camera_id = str(row["id"])
    return CameraOut(
        id=camera_id,
        location_id=str(row["location_id"]),
        name=row["name"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        status=row["status"],
        live_stream_url="/api/cameras/{}/mjpeg".format(camera_id),
        latest_frame_url="/api/cameras/{}/latest.jpg".format(camera_id),
        detection_stream_url="/api/cameras/{}/detections/stream".format(camera_id),
        created_at=_stringify(row["created_at"]),
        updated_at=_stringify(row["updated_at"]),
    )


def reference_frame_out(row, public_image_url: str) -> ReferenceFrameOut:
    return ReferenceFrameOut(
        id=str(row["id"]),
        camera_id=str(row["camera_id"]),
        storage_key=row["storage_key"],
        mime_type=row["mime_type"],
        frame_width=row["frame_width"],
        frame_height=row["frame_height"],
        captured_at=_stringify(row["captured_at"]),
        created_at=_stringify(row["created_at"]),
        image_url=public_image_url,
    )


def zone_out(row) -> ZoneOut:
    return ZoneOut(
        id=str(row["id"]),
        camera_id=str(row["camera_id"]),
        name=row["name"],
        zone_type=row["zone_type"],
        polygon=_json_value(row["polygon"]),
        frame_width=row["frame_width"],
        frame_height=row["frame_height"],
        enabled=bool(row["enabled"]),
        created_at=_stringify(row["created_at"]),
        updated_at=_stringify(row["updated_at"]),
    )


def rule_config_out(row) -> RuleConfigOut:
    return RuleConfigOut(
        id=str(row["id"]),
        zone_id=str(row["zone_id"]),
        rule_type=row["rule_type"],
        enabled=bool(row["enabled"]),
        object_type=row["object_type"],
        duration_threshold=row["duration_threshold"],
        people_threshold=row["people_threshold"],
        confidence_threshold=row["confidence_threshold"],
        use_active_time=bool(row["use_active_time"]),
        active_start_time=_time_string(row["active_start_time"]),
        active_end_time=_time_string(row["active_end_time"]),
        created_at=_stringify(row["created_at"]),
        updated_at=_stringify(row["updated_at"]),
    )


def ai_event_out(row) -> AiEventOut:
    return AiEventOut(
        id=str(row["id"]),
        alert_id=_optional_string(row["alert_id"]),
        source_event_id=row["source_event_id"],
        camera_id=str(row["camera_id"]),
        zone_id=_optional_string(row["zone_id"]),
        rule_config_id=_optional_string(row["rule_config_id"]),
        event_type=row["event_type"],
        object_type=row["object_type"],
        track_id=row["track_id"],
        confidence=row["confidence"],
        lifecycle_status=row["lifecycle_status"],
        first_sequence_number=row["first_sequence_number"],
        last_sequence_number=row["last_sequence_number"],
        started_at=_stringify(row["started_at"]),
        last_seen_at=_stringify(row["last_seen_at"]),
        ended_at=_optional_time(row["ended_at"]),
        payload=_json_value(row["payload"]),
        created_at=_stringify(row["created_at"]),
        updated_at=_stringify(row["updated_at"]),
    )


def evidence_out(row) -> EvidenceOut:
    evidence_id = str(row["id"])
    return EvidenceOut(
        id=evidence_id,
        alert_id=_optional_string(row["alert_id"]),
        ai_event_id=str(row["ai_event_id"]),
        camera_id=str(row["camera_id"]),
        evidence_type=row["evidence_type"],
        storage_key=row["storage_key"],
        mime_type=row["mime_type"],
        file_size=row["file_size"],
        frame_id=row["frame_id"],
        sequence_number=row["sequence_number"],
        captured_at=_stringify(row["captured_at"]),
        started_at=_optional_time(row["started_at"]),
        ended_at=_optional_time(row["ended_at"]),
        duration_seconds=row["duration_seconds"],
        codec=row["codec"],
        fps=row["fps"],
        frame_width=row["frame_width"],
        frame_height=row["frame_height"],
        status=row["status"],
        created_at=_stringify(row["created_at"]),
        media_url="/api/evidence/{}/media".format(evidence_id),
    )


def alert_out(row) -> AlertOut:
    return AlertOut(
        id=str(row["id"]),
        dedup_key=row["dedup_key"],
        camera_id=str(row["camera_id"]),
        zone_id=_optional_string(row["zone_id"]),
        rule_config_id=_optional_string(row["rule_config_id"]),
        rule_type=row["rule_type"],
        object_type=row["object_type"],
        risk_level=row["risk_level"],
        lifecycle_status=row["lifecycle_status"],
        active_source_count=row["active_source_count"],
        first_sequence_number=row["first_sequence_number"],
        last_sequence_number=row["last_sequence_number"],
        started_at=_stringify(row["started_at"]),
        last_seen_at=_stringify(row["last_seen_at"]),
        ended_at=_optional_time(row["ended_at"]),
        payload=_json_value(row["payload"]),
        created_at=_stringify(row["created_at"]),
        updated_at=_stringify(row["updated_at"]),
    )


def reference_frame_path(reference_frame_dir: Path, storage_key: Optional[str]) -> Optional[Path]:
    if not storage_key:
        return None
    path = (reference_frame_dir / storage_key).resolve()
    root = reference_frame_dir.resolve()
    if root not in path.parents and path != root:
        return None
    return path


def evidence_path(evidence_dir: Path, storage_key: Optional[str]) -> Optional[Path]:
    if not storage_key:
        return None
    path = (evidence_dir / storage_key).resolve()
    root = evidence_dir.resolve()
    if root not in path.parents and path != root:
        return None
    return path


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _stringify(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _time_string(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def _optional_string(value) -> Optional[str]:
    return None if value is None else str(value)


def _optional_time(value) -> Optional[str]:
    return None if value is None else _stringify(value)
