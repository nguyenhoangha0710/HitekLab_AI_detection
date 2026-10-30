import unittest
from datetime import datetime, timedelta, timezone

from local_ai.motion import MotionEstimator, MotionSettings, direction_from_angle
from rule_engine import InMemoryPublisher, RuleEngine, StaticConfigProvider, ZoneConfig
from rule_engine.models import RuleConfig

BASE = datetime(2026, 10, 30, 3, 0, 0, tzinfo=timezone.utc)


def frame(seconds, detections, camera="cam-1", width=640):
    return {
        "camera_id": camera,
        "frame_id": "f-{}".format(seconds),
        "sequence_number": int(seconds * 10),
        "captured_at": (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
        "frame_width": width,
        "frame_height": 360,
        "detections": detections,
    }


def person(track_id, foot_x, foot_y):
    return {"class_name": "person", "confidence": 0.9, "track_id": track_id,
            "bbox_xyxy": [foot_x - 20, foot_y - 100, foot_x + 20, foot_y]}


def run(estimator, positions, step=0.2, track_id=1, camera="cam-1"):
    """positions: danh sach (x, y) chan theo thoi gian; tra ve motion cua frame cuoi."""
    last = None
    for index, (x, y) in enumerate(positions):
        det = person(track_id, x, y)
        estimator.update(frame(index * step, [det], camera=camera))
        last = det["motion"]
    return last


class DirectionFromAngleTests(unittest.TestCase):
    def test_eight_sectors(self):
        cases = {0: "right", 44: "up-right", 90: "up", 135: "up-left", 180: "left",
                 225: "down-left", 270: "down", 315: "down-right", 359: "right", 22: "right", 23: "up-right"}
        for angle, expected in cases.items():
            self.assertEqual(expected, direction_from_angle(angle), angle)


class MotionEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.estimator = MotionEstimator(MotionSettings(window_seconds=1.0))

    def test_walking_left(self):
        # 50 px/0.2s = 250 px/s sang trai
        motion = run(self.estimator, [(500 - 50 * i, 300) for i in range(8)])
        self.assertEqual("left", motion["direction"])
        self.assertAlmostEqual(250.0, motion["speed_px_s"], delta=1)
        self.assertAlmostEqual(180.0, motion["angle_deg"], delta=0.5)

    def test_walking_up_means_y_decreasing(self):
        motion = run(self.estimator, [(320, 340 - 20 * i) for i in range(8)])
        self.assertEqual("up", motion["direction"])

    def test_walking_down_right(self):
        motion = run(self.estimator, [(100 + 20 * i, 100 + 20 * i) for i in range(8)])
        self.assertEqual("down-right", motion["direction"])

    def test_small_jitter_is_stationary(self):
        motion = run(self.estimator, [(320 + (i % 2) * 2, 300) for i in range(10)])
        self.assertEqual("stationary", motion["direction"])

    def test_unknown_until_enough_history(self):
        det = person(1, 300, 300)
        self.estimator.update(frame(0, [det]))
        self.assertEqual("unknown", det["motion"]["direction"])
        det = person(1, 250, 300)
        self.estimator.update(frame(0.2, [det]))
        self.assertEqual("unknown", det["motion"]["direction"])  # moi 0.2s < 0.5s

    def test_uses_only_last_window(self):
        # 2 giay dau di sang phai, sau do 1.2 giay di sang trai -> chi tinh huong moi
        right = [(100 + 30 * i, 300) for i in range(10)]
        left = [(right[-1][0] - 30 * i, 300) for i in range(1, 7)]
        motion = run(self.estimator, right + left)
        self.assertEqual("left", motion["direction"])

    def test_tracks_and_cameras_are_independent(self):
        run(self.estimator, [(100 + 30 * i, 300) for i in range(6)], track_id=1, camera="cam-1")
        motion = run(self.estimator, [(500 - 30 * i, 300) for i in range(6)], track_id=1, camera="cam-2")
        self.assertEqual("left", motion["direction"])

    def test_detection_without_track_id_is_unknown(self):
        det = {"class_name": "person", "bbox_xyxy": [0, 0, 10, 10]}
        self.estimator.update(frame(0, [det]))
        self.assertEqual("unknown", det["motion"]["direction"])

    def test_video_loop_resets_history(self):
        run(self.estimator, [(100 + 30 * i, 300) for i in range(6)])
        det = person(1, 600, 300)
        self.estimator.update(frame(0, [det]))  # thoi gian quay ve 0
        self.assertEqual("unknown", det["motion"]["direction"])


class MotionInRuleEventTests(unittest.TestCase):
    def test_event_and_violation_carry_direction(self):
        zone = ZoneConfig(
            id="z", camera_id="cam-1", name="Cong", zone_type="restricted_area",
            points=((0, 0), (640, 0), (640, 360), (0, 360)), frame_width=640, frame_height=360,
            rules=(RuleConfig(id="r", zone_id="z", rule_type="person_intrusion", object_type="person", duration_threshold=1),),
        )
        publisher = InMemoryPublisher()
        engine = RuleEngine(StaticConfigProvider({"cam-1": [zone]}), publisher)
        estimator = MotionEstimator()
        out = None
        for i in range(8):
            result = frame(i * 0.2, [person(5, 500 - 40 * i, 300)])
            estimator.update(result)
            out = engine.process(result)
        self.assertEqual("left", out["violations"][0]["direction"])
        contract_obj = publisher.events[-1]["payload"]["contract"]["objects"][0]
        self.assertEqual("left", contract_obj["direction"])
        self.assertGreater(contract_obj["speed_px_s"], 100)


if __name__ == "__main__":
    unittest.main()
