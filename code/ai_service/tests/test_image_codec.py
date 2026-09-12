import unittest

import cv2
import numpy as np

from common.image_codec import decode_image, encode_jpeg, frame_size


class ImageCodecTests(unittest.TestCase):
    def test_encode_and_decode_jpeg(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        image_bytes = encode_jpeg(frame)

        decoded = decode_image(image_bytes)

        self.assertGreater(len(image_bytes), 0)
        self.assertEqual((160, 120), frame_size(decoded))

    def test_decode_invalid_bytes_raises(self):
        with self.assertRaises(ValueError):
            decode_image(b"not an image")


if __name__ == "__main__":
    unittest.main()
