from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


class FrameMetadata(BaseModel):
    frame_id: str = Field(..., min_length=1)
    camera_id: str = Field(..., min_length=1)
    location_id: str = Field(..., min_length=1)
    source_type: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    timestamp: datetime
    captured_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    sequence_number: int = Field(..., ge=0)
    source_width: Optional[int] = Field(default=None, ge=1)
    source_height: Optional[int] = Field(default=None, ge=1)
    frame_width: int = Field(..., ge=1)
    frame_height: int = Field(..., ge=1)
    target_fps: Optional[float] = Field(default=None, gt=0)
    fps: Optional[float] = Field(default=None, gt=0)
    encoding: str = Field(..., min_length=1)
    tenant_id: Optional[str] = None

    @validator("source_type", "encoding")
    def normalize_uppercase(cls, value: str) -> str:
        return value.upper()


class FrameAcceptedResponse(BaseModel):
    frame_id: str
    camera_id: str
    status: str
    received_at: str
    image_width: int
    image_height: int
    queue_size: int
    dropped_frames: int
    correlation_id: Optional[str] = None


class CameraQueueSummary(BaseModel):
    camera_id: str
    location_id: str
    queue_size: int
    max_queue_size: int
    received_frames: int
    enqueued_frames: int
    dropped_frames: int
    consumed_frames: int
    last_enqueued_frame_id: Optional[str] = None
    last_consumed_frame_id: Optional[str] = None
    last_received_at: Optional[str] = None
    last_consumed_at: Optional[str] = None
    sequence_number: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class CameraFrameSummary(BaseModel):
    camera_id: str
    location_id: str
    last_frame_id: str
    last_received_at: str
    sequence_number: int
    frame_count: int
    image_width: int
    image_height: int
