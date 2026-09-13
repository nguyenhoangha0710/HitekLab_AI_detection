import urllib.request
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

from ..time_utils import utc_iso


class FrameCaptureService:
    def __init__(self, edge_gateway_base_url: str, reference_frame_dir: Path) -> None:
        self.edge_gateway_base_url = edge_gateway_base_url.rstrip("/")
        self.reference_frame_dir = Path(reference_frame_dir)

    def capture_latest(self, camera_id: str, reference_id: str) -> Tuple[str, int, int, str]:
        url = "{}/api/cameras/{}/latest.jpg".format(self.edge_gateway_base_url, camera_id)
        request = urllib.request.Request(url, headers={"Accept": "image/jpeg"})
        with urllib.request.urlopen(request, timeout=5) as response:
            image_bytes = response.read()

        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Gateway returned invalid JPEG bytes for camera {}".format(camera_id))

        height, width = frame.shape[:2]
        camera_dir = self.reference_frame_dir / camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        storage_key = "{}/{}.jpg".format(camera_id, reference_id)
        output_path = self.reference_frame_dir / storage_key
        output_path.write_bytes(image_bytes)
        return storage_key, width, height, utc_iso()
