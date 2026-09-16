import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from ..config import ZoneServiceSettings
from .evidence_storage_service import EvidenceStorageService


class EvidenceCaptureService:
    def __init__(self, settings: ZoneServiceSettings) -> None:
        self.edge_gateway_base_url = settings.edge_gateway_base_url.rstrip("/")
        self.storage = EvidenceStorageService(settings)

    def capture_snapshot(self, camera_id: str, ai_event_id: str, frame_id: Optional[str]) -> Tuple[str, int]:
        if frame_id:
            url = "{}/api/cameras/{}/frames/{}.jpg".format(self.edge_gateway_base_url, camera_id, frame_id)
            filename = "{}.jpg".format(frame_id)
        else:
            url = "{}/api/cameras/{}/latest.jpg".format(self.edge_gateway_base_url, camera_id)
            filename = "latest.jpg"

        request = urllib.request.Request(url, headers={"Accept": "image/jpeg"})
        with urllib.request.urlopen(request, timeout=5) as response:
            image_bytes = response.read()

        safe_event_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in ai_event_id)
        safe_filename = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in filename)
        relative_path = Path(camera_id) / safe_event_id / safe_filename
        storage_key = relative_path.as_posix()
        file_size = self.storage.save_bytes(storage_key, image_bytes, "image/jpeg")
        return storage_key, file_size
