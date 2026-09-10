import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass(frozen=True)
class QueueBackendConfig:
    backend: str
    redis_url: str
    redis_key_prefix: str
    redis_num_shards: int
    redis_latest_ttl_seconds: int
    redis_frame_buffer_size: int
    redis_claim_batch_size: int
    processed_stream_buffer_size: int


@dataclass(frozen=True)
class CameraIngestConfig:
    camera_id: str
    location_id: str
    name: str
    source_type: str
    source_url: str
    target_fps: float
    frame_width: int
    frame_height: int
    encoding: str
    enabled: bool = True


@dataclass(frozen=True)
class VideoIngestConfig:
    reconnect_interval_seconds: float
    read_retry_count: int
    log_every_n_frames: int
    jpeg_quality: int
    cameras: List[CameraIngestConfig]


def load_queue_config() -> QueueBackendConfig:
    return QueueBackendConfig(
        backend=os.getenv("AI_QUEUE_BACKEND", "memory").strip().lower(),
        redis_url=os.getenv("AI_REDIS_URL", "redis://localhost:6379/0"),
        redis_key_prefix=os.getenv("AI_REDIS_KEY_PREFIX", "ai"),
        redis_num_shards=max(1, int(os.getenv("AI_REDIS_NUM_SHARDS", "4"))),
        redis_latest_ttl_seconds=max(1, int(os.getenv("AI_REDIS_LATEST_TTL_SECONDS", "10"))),
        redis_frame_buffer_size=max(1, int(os.getenv("AI_REDIS_FRAME_BUFFER_SIZE", "5"))),
        redis_claim_batch_size=max(1, int(os.getenv("AI_REDIS_CLAIM_BATCH_SIZE", "1"))),
        processed_stream_buffer_size=max(1, int(os.getenv("AI_PROCESSED_STREAM_BUFFER_SIZE", "120"))),
    )


def load_video_ingest_config(path: str = "config.yaml") -> VideoIngestConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ingest = raw.get("video_ingest", {})
    defaults = ingest.get("defaults", {})
    cameras = []

    for item in raw.get("cameras", []):
        enabled = bool(item.get("enabled", True))
        cameras.append(
            CameraIngestConfig(
                camera_id=item["camera_id"],
                location_id=item["location_id"],
                name=item["name"],
                source_type=item.get("source_type", defaults.get("source_type", "RTSP")).upper(),
                source_url=item["source_url"],
                target_fps=float(item.get("target_fps", defaults.get("target_fps", 10))),
                frame_width=int(item.get("frame_width", defaults.get("frame_width", 1280))),
                frame_height=int(item.get("frame_height", defaults.get("frame_height", 720))),
                encoding=item.get("encoding", defaults.get("encoding", "JPEG")).upper(),
                enabled=enabled,
            )
        )

    return VideoIngestConfig(
        reconnect_interval_seconds=float(ingest.get("reconnect_interval_seconds", 3)),
        read_retry_count=int(ingest.get("read_retry_count", 3)),
        log_every_n_frames=int(ingest.get("log_every_n_frames", 30)),
        jpeg_quality=int(defaults.get("jpeg_quality", 85)),
        cameras=[camera for camera in cameras if camera.enabled],
    )
