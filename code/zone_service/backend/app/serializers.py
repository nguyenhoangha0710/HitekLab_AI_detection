import json
from pathlib import Path
from typing import Optional

from .models import CameraOut, ReferenceFrameOut, RuleConfigOut, ZoneOut


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


def reference_frame_path(reference_frame_dir: Path, storage_key: Optional[str]) -> Optional[Path]:
    if not storage_key:
        return None
    path = (reference_frame_dir / storage_key).resolve()
    root = reference_frame_dir.resolve()
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
