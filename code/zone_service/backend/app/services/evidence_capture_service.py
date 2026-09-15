import urllib.request
from pathlib import Path
from typing import Optional, Tuple


class EvidenceCaptureService:
    def __init__(self, edge_gateway_base_url: str, evidence_dir: Path) -> None:
        self.edge_gateway_base_url = edge_gateway_base_url.rstrip("/")
        self.evidence_dir = Path(evidence_dir)

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
        absolute_path = self.evidence_dir / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(image_bytes)
        return relative_path.as_posix(), len(image_bytes)
