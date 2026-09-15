import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class ZoneServiceSettings:
    database_path: Path
    reference_frame_dir: Path
    evidence_dir: Path
    camera_config_path: Path
    edge_gateway_base_url: str
    tenant_id: str
    database_url: Optional[str] = None


def load_settings() -> ZoneServiceSettings:
    root = project_root()
    database_path = Path(os.getenv("ZONE_DB_PATH", root / "code" / "zone_service" / "data" / "zone_service.db"))
    reference_frame_dir = Path(
        os.getenv("ZONE_REFERENCE_FRAME_DIR", root / "code" / "zone_service" / "data" / "reference_frames")
    )
    evidence_dir = Path(os.getenv("ZONE_EVIDENCE_DIR", root / "code" / "zone_service" / "data" / "evidence"))
    camera_config_path = Path(
        os.getenv("ZONE_CAMERA_CONFIG_PATH", root / "code" / "ai_service" / "config.docker.yaml")
    )
    return ZoneServiceSettings(
        database_path=database_path,
        reference_frame_dir=reference_frame_dir,
        evidence_dir=evidence_dir,
        camera_config_path=camera_config_path,
        edge_gateway_base_url=os.getenv("EDGE_GATEWAY_BASE_URL", "http://localhost:8002").rstrip("/"),
        tenant_id=os.getenv("TENANT_ID", "demo-tenant"),
        database_url=os.getenv("DATABASE_URL"),
    )
