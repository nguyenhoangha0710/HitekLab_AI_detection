from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    location_id: str
    name: str
    source_type: str
    source_url: str
    target_fps: float
    frame_width: int
    frame_height: int
    encoding: str
    simulator_video_path: Optional[str] = None


@dataclass(frozen=True)
class VideoServiceConfig:
    reconnect_interval_seconds: float
    read_retry_count: int
    log_every_n_frames: int
    outbound_queue_size_per_camera: int
    http_sender_worker_count: int
    ai_service_base_url: Optional[str]
    ai_frame_endpoint: str
    ai_timeout_seconds: float
    cameras: List[CameraConfig]


@dataclass(frozen=True)
class CameraSimulatorConfig:
    ffmpeg_path: str
    cameras: List[CameraConfig]


def _resolve_path(config_path: Path, value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((config_path.parent / path).resolve())


def load_config(path: str) -> VideoServiceConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    service = raw.get("video_service", {})
    ai = raw.get("ai_service", {})
    cameras = []

    for item in raw.get("cameras", []):
        cameras.append(
            CameraConfig(
                camera_id=item["camera_id"],
                location_id=item["location_id"],
                name=item["name"],
                source_type=item.get("source_type", "RTSP"),
                source_url=item["source_url"],
                target_fps=float(item.get("target_fps", service.get("target_fps", 10))),
                frame_width=int(item.get("frame_width", service.get("frame_width", 1280))),
                frame_height=int(item.get("frame_height", service.get("frame_height", 720))),
                encoding=item.get("encoding", service.get("encoding", "JPEG")),
                simulator_video_path=_resolve_path(config_path, item.get("simulator_video_path")),
            )
        )

    return VideoServiceConfig(
        reconnect_interval_seconds=float(service.get("reconnect_interval_seconds", 3)),
        read_retry_count=int(service.get("read_retry_count", 3)),
        log_every_n_frames=int(service.get("log_every_n_frames", 30)),
        outbound_queue_size_per_camera=int(service.get("outbound_queue_size_per_camera", 2)),
        http_sender_worker_count=int(service.get("http_sender_worker_count", 1)),
        ai_service_base_url=ai.get("base_url"),
        ai_frame_endpoint=ai.get("frame_endpoint", "/api/v1/ai/frames"),
        ai_timeout_seconds=float(ai.get("timeout_seconds", 5)),
        cameras=cameras,
    )


def load_simulator_config(path: str) -> CameraSimulatorConfig:
    raw = yaml.safe_load(Path(path).resolve().read_text(encoding="utf-8"))
    simulator = raw.get("camera_simulator", {})
    return CameraSimulatorConfig(
        ffmpeg_path=simulator.get("ffmpeg_path", "ffmpeg"),
        cameras=load_config(path).cameras,
    )
