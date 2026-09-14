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


class RuleConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    object_type: Optional[str] = Field(None, max_length=80)
    duration_threshold: Optional[int] = Field(None, ge=0)
    people_threshold: Optional[int] = Field(None, ge=0)
    confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    use_active_time: Optional[bool] = None
    active_start_time: Optional[str] = Field(None, max_length=8)
    active_end_time: Optional[str] = Field(None, max_length=8)


class RuleConfigOut(BaseModel):
    id: str
    zone_id: str
    rule_type: str
    enabled: bool
    object_type: Optional[str] = None
    duration_threshold: Optional[int] = None
    people_threshold: Optional[int] = None
    confidence_threshold: Optional[float] = None
    use_active_time: bool
    active_start_time: Optional[str] = None
    active_end_time: Optional[str] = None
    created_at: str
    updated_at: str
