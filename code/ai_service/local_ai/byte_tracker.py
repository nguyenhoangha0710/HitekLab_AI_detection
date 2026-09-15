from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional, Set, Tuple


BBox = Tuple[float, float, float, float]


@dataclass
class Track:
    track_id: int
    class_name: str
    bbox: BBox
    sequence_number: int


class CameraByteTracker:
    """Tracker cho tung camera, uu tien Ultralytics BYTETracker that.

    Neu moi truong chua cai dependency `lap`, module tu dong fallback sang IoU
    tracker nhe de service khong bi crash. Khi chay docker/env chuan co `lap`,
    ByteTrack dung Kalman + lost-track buffer de giu ID on dinh hon khi bi che.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_missing_frames: int = 45,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.5,
        match_thresh: float = 0.8,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_missing_frames = max_missing_frames
        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.new_track_thresh = new_track_thresh
        self.match_thresh = match_thresh
        self._next_track_id = 1
        self._tracks: Dict[int, Track] = {}
        self._byte_tracker = self._build_byte_tracker()
        self.method = "ultralytics_bytetrack" if self._byte_tracker is not None else "bytetrack_iou_fallback"

    def update(self, detections: List[dict], sequence_number: int) -> List[dict]:
        if self._byte_tracker is not None:
            return self._update_with_ultralytics_bytetrack(detections)
        return self._update_with_iou_fallback(detections, sequence_number)

    def _build_byte_tracker(self):
        import importlib.util

        if importlib.util.find_spec("lap") is None:
            return None
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
        except Exception:
            return None

        args = SimpleNamespace(
            track_high_thresh=self.track_high_thresh,
            track_low_thresh=self.track_low_thresh,
            new_track_thresh=self.new_track_thresh,
            track_buffer=self.max_missing_frames,
            match_thresh=self.match_thresh,
            fuse_score=True,
        )
        return BYTETracker(args)

    def _update_with_ultralytics_bytetrack(self, detections: List[dict]) -> List[dict]:
        if not detections:
            self._byte_tracker.update(_ByteTrackDetections([]))
            return []

        tracked_rows = self._byte_tracker.update(_ByteTrackDetections(detections))
        tracked_detections: List[dict] = []
        for row in tracked_rows:
            if len(row) < 4:
                continue
            track_id = int(row[-4])
            detection_index = int(row[-1])
            if detection_index < 0 or detection_index >= len(detections):
                continue
            tracked = dict(detections[detection_index])
            tracked["track_id"] = track_id
            tracked["track_label"] = "{}-{}".format(tracked.get("class_name", "object"), track_id)
            tracked["tracking_method"] = "ultralytics_bytetrack"
            tracked_detections.append(tracked)

        tracked_detections.sort(key=lambda item: item.get("track_id", 0))
        return tracked_detections

    def _update_with_iou_fallback(self, detections: List[dict], sequence_number: int) -> List[dict]:
        self._drop_stale_tracks(sequence_number)
        unmatched_track_ids = set(self._tracks.keys())
        tracked_detections: List[dict] = []

        for detection in sorted(detections, key=lambda item: float(item.get("confidence", 0)), reverse=True):
            bbox = _bbox_tuple(detection.get("bbox_xyxy", [0, 0, 0, 0]))
            class_name = str(detection.get("class_name", "object"))
            matched_track_id = self._match_track(bbox, class_name, unmatched_track_ids)

            if matched_track_id is None:
                matched_track_id = self._next_track_id
                self._next_track_id += 1
            else:
                unmatched_track_ids.discard(matched_track_id)

            self._tracks[matched_track_id] = Track(
                track_id=matched_track_id,
                class_name=class_name,
                bbox=bbox,
                sequence_number=sequence_number,
            )
            tracked = dict(detection)
            tracked["track_id"] = matched_track_id
            tracked["track_label"] = "{}-{}".format(class_name, matched_track_id)
            tracked["tracking_method"] = "bytetrack_iou_fallback"
            tracked_detections.append(tracked)

        tracked_detections.sort(key=lambda item: item.get("track_id", 0))
        return tracked_detections

    def _match_track(self, bbox: BBox, class_name: str, candidate_track_ids: Set[int]) -> Optional[int]:
        best_track_id = None
        best_iou = 0.0
        for track_id in candidate_track_ids:
            track = self._tracks[track_id]
            if track.class_name != class_name:
                continue
            score = _iou(bbox, track.bbox)
            if score > best_iou:
                best_iou = score
                best_track_id = track_id

        if best_track_id is None or best_iou < self.iou_threshold:
            return None
        return best_track_id

    def _drop_stale_tracks(self, sequence_number: int) -> None:
        stale_ids = [
            track_id
            for track_id, track in self._tracks.items()
            if sequence_number - track.sequence_number > self.max_missing_frames
        ]
        for track_id in stale_ids:
            self._tracks.pop(track_id, None)


class MultiCameraByteTracker:
    """Quan ly mot tracker rieng cho moi camera."""

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_missing_frames: int = 45,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.5,
        match_thresh: float = 0.8,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_missing_frames = max_missing_frames
        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.new_track_thresh = new_track_thresh
        self.match_thresh = match_thresh
        self._trackers: Dict[str, CameraByteTracker] = {}

    def update(self, camera_id: str, detections: List[dict], sequence_number: int) -> List[dict]:
        tracker = self._trackers.setdefault(
            camera_id,
            CameraByteTracker(
                iou_threshold=self.iou_threshold,
                max_missing_frames=self.max_missing_frames,
                track_high_thresh=self.track_high_thresh,
                track_low_thresh=self.track_low_thresh,
                new_track_thresh=self.new_track_thresh,
                match_thresh=self.match_thresh,
            ),
        )
        return tracker.update(detections, sequence_number)

    def method_for_camera(self, camera_id: str) -> str:
        tracker = self._trackers.get(camera_id)
        return tracker.method if tracker is not None else "not_initialized"


class _ByteTrackDetections:
    """Adapter toi thieu cho Ultralytics BYTETracker.

    BYTETracker can object co xywh/xyxy/conf/cls va boolean indexing. Ta build
    object nay tu bbox JSON cua local YOLO de khong phai phu thuoc vao Results.
    """

    def __init__(self, detections: List[dict]) -> None:
        import numpy as np

        self._detections = list(detections)
        xyxy = []
        xywh = []
        conf = []
        cls = []
        for index, detection in enumerate(self._detections):
            x1, y1, x2, y2 = _bbox_tuple(detection.get("bbox_xyxy", [0, 0, 0, 0]))
            xyxy.append([x1, y1, x2, y2])
            xywh.append([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, index])
            conf.append(float(detection.get("confidence", 0.0)))
            cls.append(float(detection.get("class_id", 0)))

        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape((-1, 4))
        self.xywh = np.asarray(xywh, dtype=np.float32).reshape((-1, 5))
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, index):
        import numpy as np

        if isinstance(index, (list, tuple)):
            index = np.asarray(index)
        subset = object.__new__(_ByteTrackDetections)
        subset._detections = []
        subset.xyxy = self.xyxy[index]
        subset.xywh = self.xywh[index]
        subset.conf = self.conf[index]
        subset.cls = self.cls[index]
        if subset.xyxy.ndim == 1:
            subset.xyxy = subset.xyxy.reshape((1, -1))
            subset.xywh = subset.xywh.reshape((1, -1))
            subset.conf = subset.conf.reshape((1,))
            subset.cls = subset.cls.reshape((1,))
        return subset


def _bbox_tuple(value) -> BBox:
    x1, y1, x2, y2 = value
    return float(x1), float(y1), float(x2), float(y2)


def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0
