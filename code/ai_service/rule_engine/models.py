from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .geometry import Point


# Nhom doi tuong: rule co object_type = "vehicle" se ap dung cho moi loai xe.
OBJECT_GROUPS = {
    "vehicle": {"car", "motorcycle", "bus", "truck"},
}

# rule_type noi bo (luu trong rule_config) -> event_type theo API contract.
CONTRACT_EVENT_TYPES = {
    "person_intrusion": "FORBIDDEN_ZONE_INTRUSION",
    "vehicle_intrusion": "FORBIDDEN_ZONE_INTRUSION",
    "loitering": "RESTRICTED_ZONE_LOITERING",
    "crowd_limit": "RESTRICTED_ZONE_CROWDING",
    "vehicle_stopping": "RESTRICTED_ZONE_VEHICLE_STOPPING",
}

CROWD_RULE_TYPES = {"crowd_limit"}


@dataclass(frozen=True)
class RuleConfig:
    id: str
    zone_id: str
    rule_type: str
    enabled: bool = True
    object_type: Optional[str] = None
    duration_threshold: Optional[float] = None
    people_threshold: Optional[int] = None
    confidence_threshold: Optional[float] = None
    use_active_time: bool = False
    active_start_time: Optional[str] = None
    active_end_time: Optional[str] = None

    @property
    def is_crowd_rule(self) -> bool:
        return self.rule_type in CROWD_RULE_TYPES

    def matches_object(self, class_name: Optional[str]) -> bool:
        if not self.object_type:
            return True
        wanted = str(self.object_type).lower()
        actual = str(class_name or "").lower()
        if wanted in OBJECT_GROUPS:
            return actual in OBJECT_GROUPS[wanted]
        return actual == wanted

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "RuleConfig":
        return cls(
            id=str(data["id"]),
            zone_id=str(data["zone_id"]),
            rule_type=str(data["rule_type"]),
            enabled=bool(data.get("enabled", True)),
            object_type=data.get("object_type") or None,
            duration_threshold=_optional_float(data.get("duration_threshold")),
            people_threshold=_optional_int(data.get("people_threshold")),
            confidence_threshold=_optional_float(data.get("confidence_threshold")),
            use_active_time=bool(data.get("use_active_time", False)),
            active_start_time=data.get("active_start_time") or None,
            active_end_time=data.get("active_end_time") or None,
        )


@dataclass(frozen=True)
class ZoneConfig:
    id: str
    camera_id: str
    name: str
    zone_type: str
    points: Tuple[Point, ...]
    frame_width: int
    frame_height: int
    enabled: bool = True
    rules: Tuple[RuleConfig, ...] = field(default_factory=tuple)

    @classmethod
    def from_api(cls, data: Dict[str, Any], rules: List[Dict[str, Any]]) -> "ZoneConfig":
        polygon = data.get("polygon") or {}
        raw_points = polygon.get("points", []) if isinstance(polygon, dict) else polygon
        points = tuple((float(p["x"]), float(p["y"])) for p in raw_points)
        return cls(
            id=str(data["id"]),
            camera_id=str(data["camera_id"]),
            name=str(data.get("name", "")),
            zone_type=str(data.get("zone_type", "")),
            points=points,
            frame_width=int(data.get("frame_width") or 0),
            frame_height=int(data.get("frame_height") or 0),
            enabled=bool(data.get("enabled", True)),
            rules=tuple(RuleConfig.from_api(rule) for rule in rules),
        )


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)
