"""Uoc luong huong di chuyen cua tung doi tuong dua tren lich su tracking.

Voi moi `track_id` (theo tung camera), luu vi tri chan (foot point = diem giua
canh duoi bbox) va thoi gian `captured_at` trong `window_seconds` gan nhat.
Vector dich chuyen = vi tri hien tai - vi tri cu nhat trong cua so.

Ket qua gan vao detection["motion"]:
    {
      "direction": "left",        # 8 huong hoac "stationary" / "unknown"
      "angle_deg": 178.4,         # 0 = sang phai, 90 = di len (ra xa camera), nguoc chieu kim dong ho
      "speed_px_s": 41.2,         # toc do tren khung hinh (pixel/giay)
      "dx": -40.9, "dy": 1.2,     # dich chuyen trong cua so (pixel, truc y huong xuong)
      "window_seconds": 1.0       # khoang thoi gian thuc dung de tinh
    }

Toa do anh: truc y huong xuong, nen "up" nghia la di len tren khung hinh,
voi camera dat cao nhin xuong thuong tuong ung voi di ra xa camera; "down" la lai gan.
"""

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

DIRECTIONS = ("right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right")
STATIONARY = "stationary"
UNKNOWN = "unknown"

# Ky hieu mui ten de hien thi tren dashboard/log.
DIRECTION_ARROWS = {
    "right": "→",
    "up-right": "↗",
    "up": "↑",
    "up-left": "↖",
    "left": "←",
    "down-left": "↙",
    "down": "↓",
    "down-right": "↘",
    STATIONARY: "•",
    UNKNOWN: "",
}


@dataclass(frozen=True)
class MotionSettings:
    # Do dai cua so lich su dung de tinh huong (giay).
    window_seconds: float = 1.0
    # Can it nhat ty le nay cua cua so co du lieu thi moi bao huong (tranh nhieu khi moi xuat hien).
    min_history_ratio: float = 0.5
    # Nho hon nguong nay (ty le chieu rong khung hinh / giay) thi coi la dung yen.
    # 0.02 voi khung 640px ~ 12.8 px/s.
    stationary_speed_ratio: float = 0.02
    # Xoa lich su track khong xuat hien qua so giay nay.
    track_expire_seconds: float = 5.0


class MotionEstimator:
    """Luu lich su vi tri theo (camera_id, track) va tinh huong cho moi frame."""

    def __init__(self, settings: Optional[MotionSettings] = None) -> None:
        self.settings = settings or MotionSettings()
        self._history: Dict[str, Dict[str, Deque[Tuple[float, float, float]]]] = {}

    def update(self, result: dict) -> None:
        """Gan detection["motion"] cho moi detection trong frame result."""
        camera_id = str(result.get("camera_id") or "")
        detections = result.get("detections") or []
        now = frame_epoch_seconds(result.get("captured_at"))
        frame_width = float(result.get("frame_width") or 0) or 640.0
        camera_history = self._history.setdefault(camera_id, {})
        seen = set()

        for detection in detections:
            track_id = detection.get("track_id")
            if track_id is None:
                detection["motion"] = _motion_dict(UNKNOWN)
                continue
            key = "{}-{}".format(detection.get("class_name") or "object", track_id)
            seen.add(key)
            x, y = _foot_point(detection.get("bbox_xyxy") or [0, 0, 0, 0])
            history = camera_history.setdefault(key, deque())
            if history and now < history[-1][0]:
                history.clear()  # video lap lai / dong ho lui -> bat dau lai
            history.append((now, x, y))
            while len(history) > 1 and now - history[0][0] > self.settings.window_seconds:
                history.popleft()
            detection["motion"] = self._estimate(history, frame_width)

        for key in list(camera_history.keys()):
            if key in seen:
                continue
            last_time = camera_history[key][-1][0] if camera_history[key] else 0.0
            if now - last_time > self.settings.track_expire_seconds or now < last_time:
                del camera_history[key]

    def reset(self, camera_id: Optional[str] = None) -> None:
        if camera_id is None:
            self._history.clear()
        else:
            self._history.pop(camera_id, None)

    def _estimate(self, history: Deque[Tuple[float, float, float]], frame_width: float) -> dict:
        if len(history) < 2:
            return _motion_dict(UNKNOWN)
        t0, x0, y0 = history[0]
        t1, x1, y1 = history[-1]
        elapsed = t1 - t0
        if elapsed < self.settings.window_seconds * self.settings.min_history_ratio or elapsed <= 0:
            return _motion_dict(UNKNOWN)
        dx, dy = x1 - x0, y1 - y0
        speed = math.hypot(dx, dy) / elapsed
        angle = math.degrees(math.atan2(-dy, dx)) % 360.0
        if speed < self.settings.stationary_speed_ratio * frame_width:
            direction = STATIONARY
        else:
            direction = direction_from_angle(angle)
        return _motion_dict(direction, angle, speed, dx, dy, elapsed)


def direction_from_angle(angle_deg: float) -> str:
    """0 do = phai, 90 = len. Chia 8 goc 45 do, moi huong lech +-22.5 do."""
    index = int(((angle_deg % 360.0) + 22.5) // 45.0) % 8
    return DIRECTIONS[index]


def frame_epoch_seconds(captured_at) -> float:
    if captured_at:
        text = str(captured_at).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    import time

    return time.time()


def _foot_point(bbox: List[float]) -> Tuple[float, float]:
    x1, _, x2, y2 = (float(v) for v in bbox)
    return (x1 + x2) / 2.0, y2


def _motion_dict(direction: str, angle=None, speed=None, dx=None, dy=None, window=None) -> dict:
    return {
        "direction": direction,
        "angle_deg": round(angle, 1) if angle is not None else None,
        "speed_px_s": round(speed, 1) if speed is not None else None,
        "dx": round(dx, 1) if dx is not None else None,
        "dy": round(dy, 1) if dy is not None else None,
        "window_seconds": round(window, 2) if window is not None else None,
    }
