import json
from pathlib import Path
from typing import Optional

from .models import CameraOut, ReferenceFrameOut, ZoneOut


def camera_out(row, edge_gateway_base_url: str) -> CameraOut:
    camera_id = row["id"]
    return CameraOut(
        id=camera_id,
        location_id=row["location_id"],
        name=row["name"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        status=row["status"],
        live_stream_url="/api/cameras/{}/mjpeg".format(camera_id),
        latest_frame_url="/api/cameras/{}/latest.jpg".format(camera_id),
        detection_stream_url="/api/cameras/{}/detections/stream".format(camera_id),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def reference_frame_out(row, public_image_url: str) -> ReferenceFrameOut:
    return ReferenceFrameOut(
        id=row["id"],
        camera_id=row["camera_id"],
        storage_key=row["storage_key"],
        mime_type=row["mime_type"],
        frame_width=row["frame_width"],
        frame_height=row["frame_height"],
        captured_at=row["captured_at"],
        created_at=row["created_at"],
        image_url=public_image_url,
    )


def zone_out(row) -> ZoneOut:
    return ZoneOut(
        id=row["id"],
        camera_id=row["camera_id"],
        name=row["name"],
        zone_type=row["zone_type"],
        polygon=json.loads(row["polygon"]),
        frame_width=row["frame_width"],
        frame_height=row["frame_height"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def reference_frame_path(reference_frame_dir: Path, storage_key: Optional[str]) -> Optional[Path]:
    if not storage_key:
        return None
    path = (reference_frame_dir / storage_key).resolve()
    root = reference_frame_dir.resolve()
    if root not in path.parents and path != root:
        return None
    return path
