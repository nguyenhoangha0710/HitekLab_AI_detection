from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class Polygon(BaseModel):
    points: List[Point] = Field(..., min_items=3)


class CameraOut(BaseModel):
    id: str
    location_id: str
    name: str
    source_type: str
    source_url: str
    status: str
    live_stream_url: str
    latest_frame_url: str
    detection_stream_url: str
    created_at: str
    updated_at: str


class ReferenceFrameOut(BaseModel):
    id: str
    camera_id: str
    storage_key: str
    mime_type: str
    frame_width: int
    frame_height: int
    captured_at: str
    created_at: str
    image_url: str


class ZoneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    zone_type: str = Field("restricted_area", min_length=1, max_length=80)
    polygon: Polygon
    frame_width: int = Field(..., gt=0)
    frame_height: int = Field(..., gt=0)
    enabled: bool = True


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    zone_type: Optional[str] = Field(None, min_length=1, max_length=80)
    polygon: Optional[Polygon] = None
    frame_width: Optional[int] = Field(None, gt=0)
    frame_height: Optional[int] = Field(None, gt=0)
    enabled: Optional[bool] = None


class ZoneOut(BaseModel):
    id: str
    camera_id: str
    name: str
    zone_type: str
    polygon: Dict[str, Any]
    frame_width: int
    frame_height: int
    enabled: bool
    created_at: str
    updated_at: str
