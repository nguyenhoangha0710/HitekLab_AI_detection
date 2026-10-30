import unittest
from datetime import datetime, timedelta, timezone

from rule_engine import InMemoryPublisher, RuleEngine, RuleEngineSettings, StaticConfigProvider, ZoneConfig
from rule_engine.config_provider import ZoneServiceConfigProvider
from rule_engine.engine import is_in_active_window
from rule_engine.geometry import point_in_polygon, scale_point
from rule_engine.models import RuleConfig
from rule_engine.publisher import AiEventPublisher

CAMERA = "cam-1"
BASE_TIME = datetime(2026, 10, 30, 3, 0, 0, tzinfo=timezone.utc)  # 10:00 gio VN
SQUARE = ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0))


def rule(rule_type, **kwargs):
    defaults = dict(id="rule-" + rule_type, zone_id="zone-1", rule_type=rule_type, object_type="person", duration_threshold=5)
    defaults.update(kwargs)
    return RuleConfig(**defaults)


def zone(*rules, points=SQUARE, frame=(640, 360), zone_id="zone-1"):
    return ZoneConfig(
        id=zone_id,
        camera_id=CAMERA,
        name="Kho hang",
        zone_type="restricted_area",
        points=points,
        frame_width=frame[0],
        frame_height=frame[1],
        rules=tuple(rules),
    )


def det(track_id, x1, y1, x2, y2, class_name="person", confidence=0.9):
    return {"class_name": class_name, "confidence": confidence, "bbox_xyxy": [x1, y1, x2, y2], "track_id": track_id}


def frame(seq, seconds, detections, size=(640, 360)):
    return {
        "camera_id": CAMERA,
        "location_id": "loc-1",
        "frame_id": "{}-{:06d}".format(CAMERA, seq),
        "sequence_number": seq,
        "captured_at": (BASE_TIME + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
        "frame_width": size[0],
        "frame_height": size[1],
        "detections": detections,
    }


class RuleEngineTestCase(unittest.TestCase):
    def make_engine(self, *zones, **settings):
        self.publisher = InMemoryPublisher()
        provider = StaticConfigProvider({CAMERA: list(zones)})
        return RuleEngine(provider, self.publisher, RuleEngineSettings(**settings))


class GeometryTests(unittest.TestCase):
    def test_point_in_polygon(self):
        self.assertTrue(point_in_polygon((200, 200), SQUARE))
        self.assertFalse(point_in_polygon((50, 200), SQUARE))
        self.assertFalse(point_in_polygon((1, 1), SQUARE[:2]))

    def test_scale_point_between_frame_sizes(self):
        self.assertEqual((320.0, 180.0), scale_point((640, 360), (1280, 720), (640, 360)))
        self.assertEqual((5.0, 6.0), scale_point((5, 6), (640, 360), (640, 360)))

    def test_active_window_crosses_midnight(self):
        self.assertTrue(is_in_active_window("23:00", "06:00", 23 * 60 + 30))
        self.assertTrue(is_in_active_window("23:00", "06:00", 2 * 60))
        self.assertFalse(is_in_active_window("23:00", "06:00", 10 * 60))
        self.assertTrue(is_in_active_window("08:00", "08:00", 0))
        self.assertFalse(is_in_active_window(None, "06:00", 0))


class DwellRuleTests(RuleEngineTestCase):
    def test_intrusion_fires_after_duration_threshold_using_captured_at(self):
        engine = self.make_engine(zone(rule("person_intrusion", duration_threshold=5)))
        # chan o (200, 250) nam trong zone
        for second in range(0, 5):
            out = engine.process(frame(second, second, [det(1, 180, 150, 220, 250)]))
            self.assertEqual([], out["violations"], "chua du 5s")
        out = engine.process(frame(5, 5, [det(1, 180, 150, 220, 250)]))
        self.assertEqual(1, len(out["violations"]))
        self.assertEqual(1, len(self.publisher.events))
        event = self.publisher.events[0]
        self.assertEqual("person_intrusion", event["event_type"])
        self.assertEqual("person-1", event["track_id"])
        self.assertEqual("FORBIDDEN_ZONE_INTRUSION", event["payload"]["contract"]["event_type"])
        self.assertEqual(5, event["payload"]["elapsed_seconds"])
        self.assertEqual({"x": 200.0, "y": 250.0}, event["payload"]["contract"]["objects"][0]["foot_point"])
        self.assertTrue(event["started_at"].startswith("2026-10-30T03:00:00"))

    def test_detection_is_annotated_with_zone_ids_and_foot_point(self):
        engine = self.make_engine(zone(rule("loitering")))
        inside, outside = det(1, 180, 150, 220, 250), det(2, 10, 10, 30, 50)
        engine.process(frame(1, 0, [inside, outside]))
        self.assertEqual(["zone-1"], inside["zone_ids"])
        self.assertEqual([], outside["zone_ids"])
        self.assertEqual({"x": 200.0, "y": 250.0}, inside["foot_point"])

    def test_bbox_overlapping_zone_but_foot_outside_does_not_count(self):
        engine = self.make_engine(zone(rule("person_intrusion", duration_threshold=0)))
        out = engine.process(frame(1, 0, [det(1, 180, 200, 220, 340)]))  # chan y=340 > 300
        self.assertEqual([], out["violations"])

    def test_heartbeat_republishes_same_source_event(self):
        engine = self.make_engine(zone(rule("loitering", duration_threshold=2)), heartbeat_seconds=10)
        for second in range(0, 25):
            engine.process(frame(second, second, [det(7, 180, 150, 220, 250)]))
        # vi pham tu giay 2 -> publish o 2, 12, 22
        self.assertEqual(3, len(self.publisher.events))
        self.assertEqual(1, len({e["source_event_id"] for e in self.publisher.events}))
        self.assertEqual([1, 2, 3], [e["payload"]["heartbeat_index"] for e in self.publisher.events])

    def test_track_id_switch_is_reattached_and_keeps_dwell_time(self):
        engine = self.make_engine(zone(rule("loitering", duration_threshold=6)))
        for second in range(0, 4):
            engine.process(frame(second, second, [det(1, 180, 150, 220, 250)]))
        # ByteTrack doi ID 1 -> 9 o vi tri gan nhu cu
        for second in range(4, 6):
            out = engine.process(frame(second, second, [det(9, 185, 152, 225, 252)]))
            self.assertEqual([], out["violations"])
        out = engine.process(frame(6, 6, [det(9, 185, 152, 225, 252)]))
        self.assertEqual(1, len(out["violations"]))
        self.assertEqual("person-1", self.publisher.events[0]["payload"]["reattached_from"])

    def test_far_away_new_track_is_not_reattached(self):
        engine = self.make_engine(zone(rule("loitering", duration_threshold=4)))
        for second in range(0, 3):
            engine.process(frame(second, second, [det(1, 110, 150, 130, 250)]))
        out = engine.process(frame(4, 4, [det(9, 270, 150, 290, 250)]))  # cach ~160px
        self.assertEqual([], out["violations"])

    def test_state_expires_when_object_leaves(self):
        engine = self.make_engine(zone(rule("loitering", duration_threshold=5)), state_expire_seconds=2)
        for second in range(0, 4):
            engine.process(frame(second, second, [det(1, 180, 150, 220, 250)]))
        engine.process(frame(10, 10, []))  # roi khoi zone > 2s
        out = engine.process(frame(11, 11, [det(1, 180, 150, 220, 250)]))
        self.assertEqual([], out["violations"])
        self.assertEqual([], self.publisher.events)

    def test_confidence_and_object_filters(self):
        engine = self.make_engine(zone(rule("person_intrusion", duration_threshold=0, confidence_threshold=0.6)))
        out = engine.process(frame(1, 0, [det(1, 180, 150, 220, 250, confidence=0.4)]))
        self.assertEqual([], out["violations"])
        out = engine.process(frame(2, 1, [det(2, 180, 150, 220, 250, class_name="car")]))
        self.assertEqual([], out["violations"])
        out = engine.process(frame(3, 2, [det(3, 180, 150, 220, 250, confidence=0.7)]))
        self.assertEqual(1, len(out["violations"]))

    def test_vehicle_group_matches_car_and_motorcycle(self):
        engine = self.make_engine(zone(rule("vehicle_intrusion", object_type="vehicle", duration_threshold=0)))
        out = engine.process(
            frame(1, 0, [det(1, 120, 150, 160, 250, class_name="motorcycle"), det(2, 220, 150, 260, 250, class_name="car")])
        )
        self.assertEqual({"motorcycle", "car"}, {v["object_type"] for v in out["violations"]})

    def test_active_time_uses_vietnam_local_time(self):
        night_rule = rule("person_intrusion", duration_threshold=0, use_active_time=True, active_start_time="23:00", active_end_time="06:00")
        engine = self.make_engine(zone(night_rule))
        # BASE_TIME = 10:00 gio VN -> ngoai khung
        self.assertEqual([], engine.process(frame(1, 0, [det(1, 180, 150, 220, 250)]))["violations"])
        # 17:30 UTC = 00:30 gio VN -> trong khung
        late = 14.5 * 3600
        self.assertEqual(1, len(engine.process(frame(2, late, [det(1, 180, 150, 220, 250)]))["violations"]))

    def test_zone_drawn_on_smaller_reference_frame_is_scaled(self):
        engine = self.make_engine(zone(rule("person_intrusion", duration_threshold=0), frame=(320, 180)))
        # detection tren khung 640x360: chan (400, 300) -> (200, 150) tren khung zone
        out = engine.process(frame(1, 0, [det(1, 380, 200, 420, 300)]))
        self.assertEqual(1, len(out["violations"]))

    def test_disabled_rule_is_ignored(self):
        engine = self.make_engine(zone(rule("person_intrusion", duration_threshold=0, enabled=False)))
        self.assertEqual([], engine.process(frame(1, 0, [det(1, 180, 150, 220, 250)]))["violations"])


class CrowdRuleTests(RuleEngineTestCase):
    def crowd(self, count, offset=0):
        return [det(i + offset, 110 + i * 30, 150, 130 + i * 30, 250) for i in range(count)]

    def test_crowd_limit_fires_when_count_held_for_duration(self):
        engine = self.make_engine(zone(rule("crowd_limit", people_threshold=3, duration_threshold=4)))
        for second in range(0, 4):
            self.assertEqual([], engine.process(frame(second, second, self.crowd(3)))["violations"])
        out = engine.process(frame(4, 4, self.crowd(3)))
        self.assertEqual(1, len(out["violations"]))
        event = self.publisher.events[0]
        self.assertEqual("RESTRICTED_ZONE_CROWDING", event["payload"]["contract"]["event_type"])
        self.assertEqual(3, event["payload"]["object_count"])
        self.assertEqual(3, len(event["payload"]["contract"]["objects"]))
        self.assertIn("|crowd|", event["source_event_id"])

    def test_crowd_resets_when_count_drops(self):
        engine = self.make_engine(zone(rule("crowd_limit", people_threshold=3, duration_threshold=4)))
        for second in range(0, 3):
            engine.process(frame(second, second, self.crowd(3)))
        engine.process(frame(3, 3, self.crowd(2)))
        out = engine.process(frame(5, 5, self.crowd(3)))
        self.assertEqual([], out["violations"])


class ProviderAndPublisherTests(unittest.TestCase):
    def test_zone_service_provider_parses_api_payload(self):
        responses = {
            "http://zone/api/cameras/cam-1/zones": [
                {
                    "id": "z1",
                    "camera_id": "cam-1",
                    "name": "Gate",
                    "zone_type": "restricted_area",
                    "polygon": {"points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}]},
                    "frame_width": 640,
                    "frame_height": 360,
                    "enabled": True,
                },
                {"id": "z2", "camera_id": "cam-1", "name": "Off", "zone_type": "x", "polygon": {"points": []},
                 "frame_width": 1, "frame_height": 1, "enabled": False},
            ],
            "http://zone/api/zones/z1/rules": [
                {"id": "r1", "zone_id": "z1", "rule_type": "person_intrusion", "enabled": True, "object_type": "person",
                 "duration_threshold": 15, "people_threshold": None, "confidence_threshold": 0.6,
                 "use_active_time": True, "active_start_time": "23:00:00", "active_end_time": "06:00:00"}
            ],
        }
        provider = ZoneServiceConfigProvider("http://zone/", fetch_json=responses.__getitem__, background=False)
        zones = provider.get("cam-1")
        self.assertEqual(1, len(zones))
        self.assertEqual(3, len(zones[0].points))
        self.assertEqual(15.0, zones[0].rules[0].duration_threshold)
        self.assertEqual("23:00:00", zones[0].rules[0].active_start_time)

    def test_provider_keeps_old_config_when_refresh_fails(self):
        calls = {"n": 0}

        def fetch(url):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("zone service down")
            return []

        provider = ZoneServiceConfigProvider("http://zone", ttl_seconds=0, retry_backoff_seconds=0, fetch_json=fetch, background=False)
        self.assertEqual([], provider.get("cam-1"))
        self.assertEqual([], provider.get("cam-1"))
        self.assertIn("zone service down", provider.stats()["last_error"])

    def test_http_publisher_retries_then_counts_failure(self):
        attempts = []

        def failing_post(url, payload):
            attempts.append(url)
            raise OSError("refused")

        publisher = AiEventPublisher("http://zone/api/ai-events", max_retries=2, retry_delay_seconds=0,
                                     post_json=failing_post, start_thread=False)
        publisher.publish({"source_event_id": "x"})
        self.assertTrue(publisher.flush_once())
        self.assertEqual(3, len(attempts))
        self.assertEqual(1, publisher.stats()["failed"])

    def test_http_publisher_success(self):
        sent = []
        publisher = AiEventPublisher("http://zone/api/ai-events", post_json=lambda u, p: sent.append(p), start_thread=False)
        publisher.publish({"source_event_id": "y"})
        publisher.flush_once()
        self.assertEqual([{"source_event_id": "y"}], sent)
        self.assertEqual(1, publisher.stats()["published"])


if __name__ == "__main__":
    unittest.main()
