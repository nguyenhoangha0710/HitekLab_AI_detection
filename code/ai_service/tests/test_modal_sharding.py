import unittest

from modal_ai.sharding import frame_queue_name, shard_id_for_camera


class ModalShardingTests(unittest.TestCase):
    def test_camera_maps_to_stable_shard(self):
        camera_id = "550e8400-e29b-41d4-a716-446655440001"

        first = shard_id_for_camera(camera_id, 2)
        second = shard_id_for_camera(camera_id, 2)

        self.assertEqual(first, second)
        self.assertIn(first, [0, 1])

    def test_frame_queue_name_contains_shard_id(self):
        self.assertEqual(frame_queue_name("frames", 1), "frames-1")

    def test_demo_camera_ids_split_across_two_shards(self):
        camera_1 = "550e8400-e29b-41d4-a716-446655440001"
        camera_2 = "550e8400-e29b-41d4-a716-446655440002"

        self.assertNotEqual(shard_id_for_camera(camera_1, 2), shard_id_for_camera(camera_2, 2))

    def test_num_shards_must_be_positive(self):
        with self.assertRaises(ValueError):
            shard_id_for_camera("camera-1", 0)


if __name__ == "__main__":
    unittest.main()
