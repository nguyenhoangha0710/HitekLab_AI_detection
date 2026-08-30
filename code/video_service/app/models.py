from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict

from .time_utils import to_iso_utc


@dataclass(frozen=True)
class FrameMetadata:
    frame_id: str
    camera_id: str
    location_id: str
    source_type: str
    source_url: str
    timestamp: datetime
    captured_at: datetime
    received_at: datetime
    sequence_number: int
    source_width: int
    source_height: int
    frame_width: int
    frame_height: int
    target_fps: float
    encoding: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = to_iso_utc(self.timestamp)
        data["captured_at"] = to_iso_utc(self.captured_at)
        data["received_at"] = to_iso_utc(self.received_at)
        return data


@dataclass(frozen=True)
class FramePacket:
    metadata: FrameMetadata
    image_bytes: bytes


@dataclass(frozen=True)
class CameraRuntimeStatus:
    camera_id: str
    status: str
    last_seen_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["last_seen_at"] = to_iso_utc(self.last_seen_at)
        return data
