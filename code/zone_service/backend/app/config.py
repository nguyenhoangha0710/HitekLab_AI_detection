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
    # backend: gui AI Event sang Backend API, Backend/Risk Engine tao canh bao (mac dinh).
    # local  : Zone Service tu gom alert nhu truoc (dung khi chay thu khong co Backend).
    alert_mode: str = "backend"
    backend_base_url: str = "http://localhost:5250"
    backend_client_id: str = "ai-service"
    backend_client_secret: str = "ai-service-dev-secret"
    backend_timeout_seconds: float = 2.0
    # Phan quyen: off (khong xac thuc, dev) | jwt (xac thuc bang JWT do Backend cap).
    auth_mode: str = "off"
    jwt_algorithm: str = "HS256"
    jwt_secret: Optional[str] = None
    jwt_public_key: Optional[str] = None
    jwt_issuer: Optional[str] = None
    jwt_audience: Optional[str] = None
    jwt_user_claim: str = "sub"
    jwt_tenant_claim: str = "tenant_id"
    # Khoa cho service noi bo (AI Service, Edge Gateway) goi API qua header X-Service-Key.
    service_api_key: Optional[str] = None
    # Cho phep /api/auth/dev-login cap token cho user demo (chi dung khi chua noi dang nhap Backend).
    auth_dev_login: bool = False
    access_cache_seconds: float = 30.0


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
        alert_mode=os.getenv("ALERT_MODE", "backend").strip().lower(),
        backend_base_url=os.getenv("BACKEND_BASE_URL", "http://localhost:5250").rstrip("/"),
        backend_client_id=os.getenv("BACKEND_CLIENT_ID", "ai-service"),
        backend_client_secret=os.getenv("BACKEND_CLIENT_SECRET", "ai-service-dev-secret"),
        backend_timeout_seconds=float(os.getenv("BACKEND_TIMEOUT_SECONDS", "2")),
        auth_mode=os.getenv("AUTH_MODE", "off").strip().lower(),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_secret=os.getenv("JWT_SECRET") or None,
        jwt_public_key=_read_optional_file(os.getenv("JWT_PUBLIC_KEY_FILE")) or os.getenv("JWT_PUBLIC_KEY") or None,
        jwt_issuer=os.getenv("JWT_ISSUER") or None,
        jwt_audience=os.getenv("JWT_AUDIENCE") or None,
        jwt_user_claim=os.getenv("JWT_USER_CLAIM", "sub"),
        jwt_tenant_claim=os.getenv("JWT_TENANT_CLAIM", "tenant_id"),
        service_api_key=os.getenv("SERVICE_API_KEY") or None,
        auth_dev_login=os.getenv("AUTH_DEV_LOGIN", "false").lower() in {"1", "true", "yes"},
        access_cache_seconds=float(os.getenv("ACCESS_CACHE_SECONDS", "30")),
    )


def _read_optional_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
