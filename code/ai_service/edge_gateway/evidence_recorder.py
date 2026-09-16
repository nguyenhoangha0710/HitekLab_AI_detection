import json
import logging
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import httpx
from pydantic import BaseModel, Field


LOGGER = logging.getLogger(__name__)


class EvidenceRecordingRequest(BaseModel):
    ai_event_id: str = Field(..., min_length=1)
    alert_id: Optional[str] = None
    camera_id: str = Field(..., min_length=1)
    frame_id: Optional[str] = None
    sequence_number: Optional[int] = None
    captured_at: str
    pre_seconds: float = Field(5.0, ge=0)
    post_seconds: float = Field(5.0, ge=0)
    fps: float = Field(10.0, gt=0)
    upload_url: str = Field(..., min_length=1)


@dataclass(frozen=True)
class EvidenceFrame:
    frame_id: str
    sequence_number: int
    captured_at: str
    image_bytes: bytes
    image_width: int
    image_height: int


class VideoEvidenceRecorder:
    def __init__(
        self,
        frame_lookup: Callable[[str, datetime, datetime], List[EvidenceFrame]],
        timeout_seconds: float = 30.0,
    ) -> None:
        self.frame_lookup = frame_lookup
        self.timeout_seconds = timeout_seconds
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

    def start(self, request: EvidenceRecordingRequest) -> str:
        job_id = str(uuid.uuid4())
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, request),
            name="evidence-recorder-{}".format(job_id[:8]),
            daemon=True,
        )
        with self._lock:
            self._threads.append(thread)
        thread.start()
        return job_id

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(timeout=1.0)

    def _run_job(self, job_id: str, request: EvidenceRecordingRequest) -> None:
        event_time = _parse_time(request.captured_at)
        started_at = event_time - timedelta(seconds=request.pre_seconds)
        ended_at = event_time + timedelta(seconds=request.post_seconds)
        self._wait_until(ended_at)

        frames = self.frame_lookup(request.camera_id, started_at, ended_at)
        if not frames:
            LOGGER.warning("EVIDENCE_VIDEO_NO_FRAMES job=%s camera=%s event=%s", job_id, request.camera_id, request.ai_event_id)
            return
        frames = _sample_frames(frames, request.fps)

        status = "completed"
        if _parse_time(frames[0].captured_at) > started_at or _parse_time(frames[-1].captured_at) < ended_at:
            status = "partial"

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_path = Path(temp_dir) / "{}.mp4".format(job_id)
                _encode_h264_mp4(frames, output_path, request.fps)
                self._upload_video(job_id, request, frames, output_path, started_at, ended_at, status)
        except Exception as exc:
            LOGGER.warning(
                "EVIDENCE_VIDEO_FAILED job=%s camera=%s event=%s error=%s",
                job_id,
                request.camera_id,
                request.ai_event_id,
                exc,
            )

    def _wait_until(self, target_time: datetime) -> None:
        while not self._stop_event.is_set():
            remaining = (target_time - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.2))

    def _upload_video(
        self,
        job_id: str,
        request: EvidenceRecordingRequest,
        frames: List[EvidenceFrame],
        output_path: Path,
        started_at: datetime,
        ended_at: datetime,
        status: str,
    ) -> None:
        metadata = {
            "ai_event_id": request.ai_event_id,
            "alert_id": request.alert_id,
            "camera_id": request.camera_id,
            "evidence_type": "video_clip",
            "frame_id": request.frame_id or frames[-1].frame_id,
            "sequence_number": request.sequence_number or frames[-1].sequence_number,
            "captured_at": _to_iso(event_time := _parse_time(request.captured_at)),
            "started_at": _to_iso(started_at),
            "ended_at": _to_iso(ended_at),
            "duration_seconds": max(0.0, (ended_at - started_at).total_seconds()),
            "codec": "h264",
            "fps": request.fps,
            "frame_width": frames[0].image_width,
            "frame_height": frames[0].image_height,
            "status": status,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            with output_path.open("rb") as handle:
                response = client.post(
                    request.upload_url,
                    data={"metadata": json.dumps(metadata, separators=(",", ":"))},
                    files={"file": ("clip.mp4", handle, "video/mp4")},
                )
                response.raise_for_status()

        LOGGER.info(
            "EVIDENCE_VIDEO_UPLOADED job=%s camera=%s event=%s frames=%s status=%s",
            job_id,
            request.camera_id,
            request.ai_event_id,
            len(frames),
            status,
        )


def _encode_h264_mp4(frames: Iterable[EvidenceFrame], output_path: Path, fps: float) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(frame.image_bytes)
        process.stdin.close()
        return_code = process.wait(timeout=30)
    except Exception:
        process.kill()
        raise
    if return_code != 0:
        raise RuntimeError("ffmpeg exited with code {}".format(return_code))


def _sample_frames(frames: List[EvidenceFrame], fps: float) -> List[EvidenceFrame]:
    if not frames:
        return []
    interval = 1.0 / max(0.001, fps)
    sampled = []
    last_kept_at = None
    for frame in frames:
        captured_at = _parse_time(frame.captured_at)
        if last_kept_at is None or (captured_at - last_kept_at).total_seconds() >= interval:
            sampled.append(frame)
            last_kept_at = captured_at
    if sampled[-1].frame_id != frames[-1].frame_id:
        sampled.append(frames[-1])
    return sampled


def _parse_time(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
