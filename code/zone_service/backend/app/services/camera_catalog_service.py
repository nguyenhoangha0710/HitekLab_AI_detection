from pathlib import Path
from typing import Dict, List

import yaml


class CameraCatalogService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)

    def load_cameras(self) -> List[Dict[str, str]]:
        if not self.config_path.exists():
            return []

        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        defaults = (raw.get("video_ingest") or {}).get("defaults") or {}
        cameras = []
        for item in raw.get("cameras", []):
            if not bool(item.get("enabled", True)):
                continue
            cameras.append(
                {
                    "id": str(item["camera_id"]),
                    "location_id": str(item["location_id"]),
                    "name": str(item["name"]),
                    "source_type": str(item.get("source_type", defaults.get("source_type", "RTSP"))).upper(),
                    "source_url": str(item["source_url"]),
                    "status": "ACTIVE",
                }
            )
        return cameras
