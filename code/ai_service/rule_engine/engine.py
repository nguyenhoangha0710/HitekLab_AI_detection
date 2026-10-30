import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from .geometry import Point, bbox_area, distance, foot_point, point_in_polygon, scale_point
from .models import CONTRACT_EVENT_TYPES, RuleConfig, ZoneConfig


@dataclass(frozen=True)
class RuleEngineSettings:
    # State cua 1 track bi xoa neu khong thay lai sau so giay nay.
    state_expire_seconds: float = 5.0
    # Track moi xuat hien gan vi tri track cu (trong grace) duoc coi la cung doi tuong
    # -> giu nguyen thoi gian dung, tranh reset khi ByteTrack doi ID.
    reattach_grace_seconds: float = 3.0
    reattach_distance_px: float = 80.0
    reattach_min_area_ratio: float = 0.5
    reattach_max_area_ratio: float = 2.0
    # Gui lai event dang active moi N giay. Risk Engine cua Backend coi nguon AI con
    # hoat dong trong 3 giay ke tu event cuoi -> phai < 3s (mac dinh 1s).
    heartbeat_seconds: float = 1.0
    # Mui gio dung de so khung gio active cua rule (Viet Nam = UTC+7).
    timezone_offset_hours: float = 7.0
    model_name: str = "yolo11n"
    tracker_name: str = "bytetrack"


@dataclass
class _ViolationState:
    camera_id: str
    location_id: Optional[str]
    zone_id: str
    rule_id: str
    track_key: str
    object_type: str
    first_seen: float
    last_seen: float
    first_sequence_number: Optional[int]
    started_at: str
    last_sequence_number: Optional[int] = None
    last_foot_point: Optional[Point] = None
    last_bbox: Optional[List[float]] = None
    confidence: Optional[float] = None
    detection: Optional[dict] = None
    object_count: int = 0
    objects: List[dict] = field(default_factory=list)
    reattached_from: Optional[str] = None
    source_event_id: Optional[str] = None
    last_published_at: Optional[float] = None
    publish_count: int = 0


class RuleEngine:
    """Danh gia zone rule tren ket qua detection + tracking cua tung frame.

    Rule ho tro (rule_type trong bang rule_config):
      - person_intrusion / vehicle_intrusion / loitering / vehicle_stopping:
        doi tuong (theo track) o trong zone >= duration_threshold giay.
        duration_threshold = 0 -> canh bao ngay khi vao zone.
      - crowd_limit: so track trong zone >= people_threshold lien tuc
        >= duration_threshold giay.
    Moi rule con loc theo object_type, confidence_threshold va khung gio active
    (dung cho "xuat hien ngoai khung gio quy dinh").

    Thoi gian tinh theo `captured_at` cua frame (khong theo dong ho may chu).
    """

    def __init__(self, config_provider, publisher, settings: Optional[RuleEngineSettings] = None) -> None:
        self.config_provider = config_provider
        self.publisher = publisher
        self.settings = settings or RuleEngineSettings()
        self._lock = threading.Lock()
        self._track_states: Dict[str, Dict[str, _ViolationState]] = {}
        self._crowd_states: Dict[str, Dict[str, _ViolationState]] = {}
        self._stats = {"frames": 0, "events_published": 0}

    # ------------------------------------------------------------------ public
    def process(self, result: dict) -> dict:
        """Xu ly 1 frame result. Tra ve dict gan vao response cua AI Service.

        Ham cung gan `foot_point` va `zone_ids` vao tung detection trong `result`.
        """
        camera_id = str(result.get("camera_id") or "")
        detections = result.get("detections") or []
        if not camera_id:
            return {"enabled": True, "violations": [], "zones_loaded": 0}

        now = _frame_epoch_seconds(result.get("captured_at"))
        local_minutes = self._local_minutes(now)
        frame_size = (int(result.get("frame_width") or 0), int(result.get("frame_height") or 0))
        zones = [zone for zone in self.config_provider.get(camera_id) if zone.enabled and len(zone.points) >= 3]

        with self._lock:
            self._stats["frames"] += 1
            track_states = self._track_states.setdefault(camera_id, {})
            crowd_states = self._crowd_states.setdefault(camera_id, {})
            seen_keys: Set[str] = set()
            crowd_members: Dict[str, Tuple[ZoneConfig, RuleConfig, List[dict]]] = {}
            violations: List[dict] = []

            for index, detection in enumerate(detections):
                bbox = detection.get("bbox_xyxy") or [0, 0, 0, 0]
                point = foot_point(bbox)
                detection["foot_point"] = {"x": round(point[0], 1), "y": round(point[1], 1)}
                matched_zone_ids: List[str] = []
                track_key = _track_key(detection, result, index)

                for zone in zones:
                    zone_point = scale_point(point, frame_size, (zone.frame_width, zone.frame_height))
                    if not point_in_polygon(zone_point, zone.points):
                        continue
                    matched_zone_ids.append(zone.id)
                    for rule in zone.rules:
                        if not self._rule_applies(rule, detection, local_minutes):
                            continue
                        if rule.is_crowd_rule:
                            key = "{}|{}".format(zone.id, rule.id)
                            crowd_members.setdefault(key, (zone, rule, []))[2].append(
                                _object_summary(detection, point, None, track_key)
                            )
                            continue
                        if rule.duration_threshold is None:
                            continue
                        violation = self._update_track_rule(
                            track_states, seen_keys, camera_id, result, zone, rule, detection, track_key, point, now
                        )
                        if violation is not None:
                            violations.append(violation)

                detection["zone_ids"] = matched_zone_ids

            violations.extend(self._update_crowd_rules(crowd_states, crowd_members, camera_id, result, now))
            self._expire(track_states, seen_keys, now)

        return {
            "enabled": True,
            "zones_loaded": len(zones),
            "violations": violations,
        }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stats": dict(self._stats),
                "active_track_states": {cam: len(states) for cam, states in self._track_states.items()},
                "active_crowd_states": {cam: len(states) for cam, states in self._crowd_states.items()},
            }

    def reset(self, camera_id: Optional[str] = None) -> None:
        with self._lock:
            if camera_id is None:
                self._track_states.clear()
                self._crowd_states.clear()
            else:
                self._track_states.pop(camera_id, None)
                self._crowd_states.pop(camera_id, None)

    # ----------------------------------------------------------- track rules
    def _update_track_rule(
        self,
        track_states: Dict[str, _ViolationState],
        seen_keys: Set[str],
        camera_id: str,
        result: dict,
        zone: ZoneConfig,
        rule: RuleConfig,
        detection: dict,
        track_key: str,
        point: Point,
        now: float,
    ) -> Optional[dict]:
        key = "{}|{}|{}".format(zone.id, rule.id, track_key)
        seen_keys.add(key)
        state = track_states.get(key)
        if state is None:
            state = self._reattach(track_states, seen_keys, zone, rule, detection, track_key, point, now)
            if state is not None:
                track_states[key] = state
        if state is None:
            state = _ViolationState(
                camera_id=camera_id,
                location_id=result.get("location_id"),
                zone_id=zone.id,
                rule_id=rule.id,
                track_key=track_key,
                object_type=str(detection.get("class_name") or "object"),
                first_seen=now,
                last_seen=now,
                first_sequence_number=_optional_int(result.get("sequence_number")),
                started_at=_iso(now),
            )
            track_states[key] = state

        state.track_key = track_key
        state.last_seen = now
        state.last_sequence_number = _optional_int(result.get("sequence_number"))
        state.last_foot_point = point
        state.last_bbox = list(detection.get("bbox_xyxy") or [])
        state.confidence = _optional_float(detection.get("confidence"))
        state.detection = detection
        elapsed = now - state.first_seen
        state.objects = [_object_summary(detection, point, elapsed, track_key)]
        state.object_count = 1

        if elapsed < float(rule.duration_threshold or 0):
            return None
        self._maybe_publish(state, zone, rule, result, now)
        return _violation_summary(state, zone, rule, elapsed)

    def _reattach(
        self,
        track_states: Dict[str, _ViolationState],
        seen_keys: Set[str],
        zone: ZoneConfig,
        rule: RuleConfig,
        detection: dict,
        track_key: str,
        point: Point,
        now: float,
    ) -> Optional[_ViolationState]:
        bbox = detection.get("bbox_xyxy")
        if not bbox:
            return None
        current_area = bbox_area(bbox)
        class_name = str(detection.get("class_name") or "object")
        best_key = None
        best_distance = float("inf")
        for key, candidate in track_states.items():
            if key in seen_keys:
                continue
            if candidate.zone_id != zone.id or candidate.rule_id != rule.id:
                continue
            if candidate.object_type != class_name or candidate.track_key == track_key:
                continue
            if now - candidate.last_seen > self.settings.reattach_grace_seconds:
                continue
            if candidate.last_foot_point is None or not candidate.last_bbox:
                continue
            previous_area = bbox_area(candidate.last_bbox)
            if previous_area <= 0 or current_area <= 0:
                continue
            ratio = current_area / previous_area
            if not (self.settings.reattach_min_area_ratio <= ratio <= self.settings.reattach_max_area_ratio):
                continue
            gap = distance(candidate.last_foot_point, point)
            if gap <= self.settings.reattach_distance_px and gap < best_distance:
                best_key = key
                best_distance = gap
        if best_key is None:
            return None
        state = track_states.pop(best_key)
        state.reattached_from = state.track_key
        return state

    # ----------------------------------------------------------- crowd rules
    def _update_crowd_rules(
        self,
        crowd_states: Dict[str, _ViolationState],
        crowd_members: Dict[str, Tuple[ZoneConfig, RuleConfig, List[dict]]],
        camera_id: str,
        result: dict,
        now: float,
    ) -> List[dict]:
        violations: List[dict] = []
        active_keys: Set[str] = set()
        for key, (zone, rule, members) in crowd_members.items():
            if rule.people_threshold is None or rule.duration_threshold is None:
                continue
            count = len({member["track_key"] for member in members})
            if count < int(rule.people_threshold):
                continue
            active_keys.add(key)
            state = crowd_states.get(key)
            if state is None:
                state = _ViolationState(
                    camera_id=camera_id,
                    location_id=result.get("location_id"),
                    zone_id=zone.id,
                    rule_id=rule.id,
                    track_key="",
                    object_type=rule.object_type or "person",
                    first_seen=now,
                    last_seen=now,
                    first_sequence_number=_optional_int(result.get("sequence_number")),
                    started_at=_iso(now),
                )
                crowd_states[key] = state
            state.last_seen = now
            state.last_sequence_number = _optional_int(result.get("sequence_number"))
            state.object_count = count
            state.track_key = "{} objects".format(count)
            state.objects = members
            state.confidence = min((m["confidence"] for m in members if m["confidence"] is not None), default=None)
            elapsed = now - state.first_seen
            if elapsed < float(rule.duration_threshold):
                continue
            self._maybe_publish(state, zone, rule, result, now)
            violations.append(_violation_summary(state, zone, rule, elapsed))

        # Crowd duoi nguong -> reset (giong hanh vi cu o frontend).
        for key in list(crowd_states.keys()):
            if key not in active_keys:
                del crowd_states[key]
        return violations

    # --------------------------------------------------------------- helpers
    def _rule_applies(self, rule: RuleConfig, detection: dict, local_minutes: int) -> bool:
        if not rule.enabled:
            return False
        if not rule.matches_object(detection.get("class_name")):
            return False
        if rule.confidence_threshold is not None:
            if float(detection.get("confidence") or 0.0) < rule.confidence_threshold:
                return False
        if rule.use_active_time and not is_in_active_window(rule.active_start_time, rule.active_end_time, local_minutes):
            return False
        return True

    def _expire(self, track_states: Dict[str, _ViolationState], seen_keys: Set[str], now: float) -> None:
        for key in list(track_states.keys()):
            if key in seen_keys:
                continue
            if now - track_states[key].last_seen > self.settings.state_expire_seconds:
                del track_states[key]

    def _local_minutes(self, epoch_seconds: float) -> int:
        local = datetime.fromtimestamp(epoch_seconds, timezone.utc) + timedelta(hours=self.settings.timezone_offset_hours)
        return local.hour * 60 + local.minute

    def _maybe_publish(self, state: _ViolationState, zone: ZoneConfig, rule: RuleConfig, result: dict, now: float) -> None:
        if state.last_published_at is not None and now - state.last_published_at < self.settings.heartbeat_seconds:
            return
        if state.source_event_id is None:
            state.source_event_id = "|".join(
                [
                    state.camera_id,
                    zone.id,
                    rule.id,
                    state.track_key if not rule.is_crowd_rule else "crowd",
                    str(state.first_sequence_number if state.first_sequence_number is not None else "unknown"),
                ]
            )
        state.last_published_at = now
        state.publish_count += 1
        self._stats["events_published"] += 1
        self.publisher.publish(self._build_event(state, zone, rule, result, now))

    def _build_event(self, state: _ViolationState, zone: ZoneConfig, rule: RuleConfig, result: dict, now: float) -> dict:
        elapsed = round(now - state.first_seen, 2)
        detection = state.detection if not rule.is_crowd_rule else None
        contract_objects = [
            {
                "track_id": obj.get("track_id"),
                "object_type": str(obj.get("class_name") or "").upper(),
                "confidence": obj.get("confidence"),
                "bbox": obj.get("bbox"),
                "foot_point": obj.get("foot_point"),
                "dwell_time_seconds": obj.get("dwell_time_seconds"),
                "direction": (obj.get("motion") or {}).get("direction"),
                "speed_px_s": (obj.get("motion") or {}).get("speed_px_s"),
            }
            for obj in state.objects
        ]
        return {
            "source_event_id": state.source_event_id,
            "camera_id": state.camera_id,
            "zone_id": zone.id,
            "rule_config_id": rule.id,
            "event_type": rule.rule_type,
            "object_type": state.object_type,
            "track_id": state.track_key,
            "confidence": state.confidence,
            "lifecycle_status": "active",
            "first_sequence_number": state.first_sequence_number,
            "last_sequence_number": state.last_sequence_number,
            "started_at": state.started_at,
            "last_seen_at": _iso(now),
            "payload": {
                "camera_id": state.camera_id,
                "location_id": state.location_id,
                "frame_id": result.get("frame_id"),
                "sequence_number": result.get("sequence_number"),
                "frame_width": result.get("frame_width"),
                "frame_height": result.get("frame_height"),
                "zone_name": zone.name,
                "zone_type": zone.zone_type,
                "rule_type": rule.rule_type,
                "elapsed_seconds": int(round(elapsed)),
                "object_count": state.object_count,
                "reattached_from": state.reattached_from,
                "heartbeat_index": state.publish_count,
                "detection": (
                    {
                        "class_name": detection.get("class_name"),
                        "confidence": detection.get("confidence"),
                        "bbox_xyxy": detection.get("bbox_xyxy"),
                        "track_id": detection.get("track_id"),
                        "motion": detection.get("motion"),
                    }
                    if detection
                    else None
                ),
                # Khung du lieu theo API_CONTRACT_AND_CONVENTIONS.md muc 6 de
                # Event & Risk Engine dung sau nay.
                "contract": {
                    "event_source": "AI",
                    "event_type": CONTRACT_EVENT_TYPES.get(rule.rule_type, rule.rule_type.upper()),
                    "timestamp": _iso(now),
                    "objects": contract_objects,
                    "metadata": {
                        "model_name": self.settings.model_name,
                        "tracker": self.settings.tracker_name,
                        "rule_name": "{}_v1".format(rule.rule_type),
                    },
                },
            },
        }


# ------------------------------------------------------------------ utilities
def is_in_active_window(start: Optional[str], end: Optional[str], current_minutes: int) -> bool:
    if not start or not end:
        return False
    start_minutes = _time_to_minutes(start)
    end_minutes = _time_to_minutes(end)
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def _time_to_minutes(value: str) -> int:
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1] if len(parts) > 1 else 0)


def _track_key(detection: dict, result: dict, index: int) -> str:
    class_name = detection.get("class_name") or "object"
    track_id = detection.get("track_id")
    if track_id is not None:
        return "{}-{}".format(class_name, track_id)
    return "{}-{}-{}".format(class_name, result.get("sequence_number"), index)


def _object_summary(detection: dict, point: Point, dwell_seconds: Optional[float], track_key: str) -> dict:
    bbox = detection.get("bbox_xyxy") or [0, 0, 0, 0]
    return {
        "track_key": track_key,
        "track_id": detection.get("track_id"),
        "class_name": detection.get("class_name"),
        "confidence": _optional_float(detection.get("confidence")),
        "bbox": {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]},
        "foot_point": {"x": round(point[0], 1), "y": round(point[1], 1)},
        "dwell_time_seconds": round(dwell_seconds, 2) if dwell_seconds is not None else None,
        "motion": detection.get("motion"),
    }


def _violation_summary(state: _ViolationState, zone: ZoneConfig, rule: RuleConfig, elapsed: float) -> dict:
    return {
        "key": "{}|{}|{}|{}".format(state.camera_id, zone.id, rule.id, state.track_key if not rule.is_crowd_rule else "crowd"),
        "source_event_id": state.source_event_id,
        "camera_id": state.camera_id,
        "zone_id": zone.id,
        "zone_name": zone.name,
        "rule_config_id": rule.id,
        "rule_type": rule.rule_type,
        "event_type": CONTRACT_EVENT_TYPES.get(rule.rule_type, rule.rule_type.upper()),
        "object_type": state.object_type,
        "track_id": state.track_key,
        "object_count": state.object_count,
        "elapsed_seconds": round(elapsed, 1),
        "sequence_number": state.last_sequence_number,
        "direction": ((state.detection or {}).get("motion") or {}).get("direction") if not rule.is_crowd_rule else None,
    }


def _frame_epoch_seconds(captured_at) -> float:
    if captured_at:
        text = str(captured_at).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return time.time()


def _iso(epoch_seconds: float) -> str:
    value = datetime.fromtimestamp(epoch_seconds, timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _optional_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
