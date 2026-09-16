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
    evidence_interval_seconds: int = 120
    alert_resolve_grace_seconds: int = 30
    evidence_storage_backend: str = "local"
    minio_endpoint: Optional[str] = None
    minio_access_key: Optional[str] = None
    minio_secret_key: Optional[str] = None
    minio_bucket: str = "hitek-evidence"
    minio_secure: bool = False
    evidence_video_enabled: bool = True
    evidence_video_pre_seconds: float = 5.0
    evidence_video_post_seconds: float = 5.0
    evidence_video_fps: float = 10.0
    evidence_video_upload_url: str = "http://localhost:8010/api/evidence/video"


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
        evidence_interval_seconds=int(os.getenv("EVIDENCE_INTERVAL_SECONDS", "120")),
        alert_resolve_grace_seconds=int(os.getenv("ALERT_RESOLVE_GRACE_SECONDS", "30")),
        evidence_storage_backend=os.getenv("EVIDENCE_STORAGE_BACKEND", "local").lower(),
        minio_endpoint=os.getenv("MINIO_ENDPOINT"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY"),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY"),
        minio_bucket=os.getenv("MINIO_BUCKET", "hitek-evidence"),
        minio_secure=os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
        evidence_video_enabled=os.getenv("EVIDENCE_VIDEO_ENABLED", "true").lower() in {"1", "true", "yes"},
        evidence_video_pre_seconds=float(os.getenv("EVIDENCE_VIDEO_PRE_SECONDS", "5")),
        evidence_video_post_seconds=float(os.getenv("EVIDENCE_VIDEO_POST_SECONDS", "5")),
        evidence_video_fps=float(os.getenv("EVIDENCE_VIDEO_FPS", "10")),
        evidence_video_upload_url=os.getenv("EVIDENCE_VIDEO_UPLOAD_URL", "http://localhost:8010/api/evidence/video"),
    )
