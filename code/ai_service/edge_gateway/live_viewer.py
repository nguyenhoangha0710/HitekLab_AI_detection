import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from common.frame_job import FrameJob
from common.models import CameraQueueSummary
from common.time_utils import to_iso_utc

from .config import CameraIngestConfig
from .evidence_recorder import EvidenceFrame, EvidenceRecordingRequest, VideoEvidenceRecorder


LOGGER = logging.getLogger(__name__)


@dataclass
class LiveFrame:
    camera_id: str
    location_id: str
    camera_name: str
    frame_id: str
    sequence_number: int
    captured_at: str
    received_at: str
    image_bytes: bytes
    image_width: int
    image_height: int
    frame_count: int


class LiveFrameHub:
    """In-memory latest-frame hub cho viewer local tai Edge Gateway.

    Hub nay khong giu backlog. Moi camera chi co 1 latest frame; frame moi
    ghi de frame cu de viewer luon bam sat live va khong bi delay tang dan.
    """

    def __init__(self, cameras: List[CameraIngestConfig], history_size_per_camera: int = 300) -> None:
        self._camera_names = {camera.camera_id: camera.name for camera in cameras}
        self._frames: Dict[str, LiveFrame] = {}
        self._history: Dict[str, Deque[LiveFrame]] = {}
        self._history_by_frame_id: Dict[str, Dict[str, LiveFrame]] = {}
        self._received_counts: Dict[str, int] = {}
        self._history_size_per_camera = max(1, history_size_per_camera)
        self._condition = threading.Condition()

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        metadata = job.metadata
        camera_id = metadata.camera_id
        with self._condition:
            frame_count = self._received_counts.get(camera_id, 0) + 1
            self._received_counts[camera_id] = frame_count
            live_frame = LiveFrame(
                camera_id=camera_id,
                location_id=metadata.location_id,
                camera_name=self._camera_names.get(camera_id, camera_id),
                frame_id=metadata.frame_id,
                sequence_number=metadata.sequence_number,
                captured_at=to_iso_utc(metadata.captured_at or metadata.timestamp),
                received_at=to_iso_utc(metadata.received_at or job.received_at),
                image_bytes=job.image_bytes,
                image_width=metadata.frame_width,
                image_height=metadata.frame_height,
                frame_count=frame_count,
            )
            self._frames[camera_id] = live_frame
            history = self._history.setdefault(camera_id, deque())
            history_by_id = self._history_by_frame_id.setdefault(camera_id, {})
            history.append(live_frame)
            history_by_id[live_frame.frame_id] = live_frame
            while len(history) > self._history_size_per_camera:
                old_frame = history.popleft()
                history_by_id.pop(old_frame.frame_id, None)
            self._condition.notify_all()

            return CameraQueueSummary(
                camera_id=camera_id,
                location_id=metadata.location_id,
                queue_size=1,
                max_queue_size=1,
                buffered_frame_count=1,
                frame_buffer_size=1,
                claim_batch_size=1,
                pending_camera_count=0,
                received_frames=frame_count,
                enqueued_frames=frame_count,
                dropped_frames=max(0, frame_count - 1),
                consumed_frames=frame_count,
                latest_frame_id=metadata.frame_id,
                last_enqueued_frame_id=metadata.frame_id,
                last_consumed_frame_id=metadata.frame_id,
                last_received_at=live_frame.received_at,
                last_consumed_at=live_frame.received_at,
                sequence_number=metadata.sequence_number,
                last_consumed_sequence_number=metadata.sequence_number,
                image_width=metadata.frame_width,
                image_height=metadata.frame_height,
            )

    def close(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def latest(self, camera_id: str) -> Optional[LiveFrame]:
        with self._condition:
            return self._frames.get(camera_id)

    def frame_by_id(self, camera_id: str, frame_id: str) -> Optional[LiveFrame]:
        with self._condition:
            return self._history_by_frame_id.get(camera_id, {}).get(frame_id)

    def frames_between(self, camera_id: str, start_at: datetime, end_at: datetime) -> List[EvidenceFrame]:
        with self._condition:
            history = list(self._history.get(camera_id, []))
        frames: List[EvidenceFrame] = []
        for frame in history:
            captured_at = _parse_time(frame.captured_at)
            if captured_at is None or captured_at < start_at or captured_at > end_at:
                continue
            frames.append(
                EvidenceFrame(
                    frame_id=frame.frame_id,
                    sequence_number=frame.sequence_number,
                    captured_at=frame.captured_at,
                    image_bytes=frame.image_bytes,
                    image_width=frame.image_width,
                    image_height=frame.image_height,
                )
            )
        return frames

    def cameras(self) -> List[dict]:
        with self._condition:
            return [
                {
                    "camera_id": camera_id,
                    "location_id": frame.location_id,
                    "name": frame.camera_name,
                    "frame_id": frame.frame_id,
                    "sequence_number": frame.sequence_number,
                    "captured_at": frame.captured_at,
                    "frame_count": frame.frame_count,
                    "image_width": frame.image_width,
                    "image_height": frame.image_height,
                }
                for camera_id, frame in sorted(self._frames.items())
            ]

    def wait_for_new_frame(self, camera_id: str, last_frame_id: Optional[str], timeout: float = 1.0) -> Optional[LiveFrame]:
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    camera_id in self._frames
                    and self._frames[camera_id].frame_id != last_frame_id
                ),
                timeout=timeout,
            )
            return self._frames.get(camera_id)


class DetectionHub:
    """In-memory latest-detection hub cho bbox metadata tu AI Service."""

    def __init__(self) -> None:
        self._detections: Dict[str, dict] = {}
        self._condition = threading.Condition()

    def update(self, result: dict) -> None:
        camera_id = result.get("camera_id")
        if not camera_id:
            return
        with self._condition:
            self._detections[str(camera_id)] = result
            self._condition.notify_all()

    def latest(self, camera_id: str) -> Optional[dict]:
        with self._condition:
            return self._detections.get(camera_id)

    def wait_for_new_detection(self, camera_id: str, last_frame_id: Optional[str], timeout: float = 1.0) -> Optional[dict]:
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    camera_id in self._detections
                    and self._detections[camera_id].get("frame_id") != last_frame_id
                ),
                timeout=timeout,
            )
            return self._detections.get(camera_id)

    def close(self) -> None:
        with self._condition:
            self._condition.notify_all()


def create_live_viewer_app(
    hub: LiveFrameHub,
    cameras: List[CameraIngestConfig],
    detection_hub: Optional[DetectionHub] = None,
    viewer_mode: str = "live",
    evidence_recorder: Optional[VideoEvidenceRecorder] = None,
) -> FastAPI:
    app = FastAPI(title="Hitek Edge Gateway Live Viewer")
    camera_map = {camera.camera_id: camera for camera in cameras}
    detection_hub = detection_hub or DetectionHub()

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "edge-gateway-live-viewer",
            "mode": "gateway-direct-viewer",
            "camera_count": len(camera_map),
        }

    @app.get("/api/cameras")
    def list_cameras():
        latest_by_id = {item["camera_id"]: item for item in hub.cameras()}
        return {
            "cameras": [
                {
                    "camera_id": camera.camera_id,
                    "location_id": camera.location_id,
                    "name": camera.name,
                    "source_url": camera.source_url,
                    "target_fps": camera.target_fps,
                    "frame_width": camera.frame_width,
                    "frame_height": camera.frame_height,
                    "latest": latest_by_id.get(camera.camera_id),
                }
                for camera in cameras
            ],
            "count": len(cameras),
        }

    @app.get("/api/cameras/{camera_id}/latest.jpg")
    def latest_jpeg(camera_id: str):
        if camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(camera_id))
        frame = hub.latest(camera_id)
        if frame is None:
            raise HTTPException(status_code=404, detail="No frame yet for camera {}".format(camera_id))
        return StreamingResponse(iter([frame.image_bytes]), media_type="image/jpeg")

    @app.get("/api/cameras/{camera_id}/frames/{frame_id}.jpg")
    def frame_jpeg(camera_id: str, frame_id: str):
        if camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(camera_id))
        frame = hub.frame_by_id(camera_id, frame_id)
        if frame is None:
            raise HTTPException(status_code=404, detail="Frame {} is no longer in Gateway history.".format(frame_id))
        return StreamingResponse(iter([frame.image_bytes]), media_type="image/jpeg")

    @app.get("/api/cameras/{camera_id}/mjpeg")
    def mjpeg(camera_id: str):
        if camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(camera_id))

        def stream() -> Iterable[bytes]:
            last_frame_id = None
            while True:
                frame = hub.wait_for_new_frame(camera_id, last_frame_id, timeout=1.0)
                if frame is None or frame.frame_id == last_frame_id:
                    continue
                last_frame_id = frame.frame_id
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + "X-Camera-ID: {}\r\n".format(frame.camera_id).encode("ascii")
                    + "X-Frame-ID: {}\r\n".format(frame.frame_id).encode("ascii")
                    + "X-Sequence-Number: {}\r\n".format(frame.sequence_number).encode("ascii")
                    + "X-Captured-At: {}\r\n\r\n".format(frame.captured_at).encode("ascii")
                    + frame.image_bytes
                    + b"\r\n"
                )

        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/cameras/{camera_id}/detections")
    def latest_detections(camera_id: str):
        if camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(camera_id))
        result = detection_hub.latest(camera_id)
        if result is None:
            return {
                "camera_id": camera_id,
                "detections": [],
                "detection_count": 0,
                "message": "No AI detections yet.",
            }
        return result

    @app.get("/api/cameras/{camera_id}/detections/stream")
    def detection_stream(camera_id: str):
        if camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(camera_id))

        def stream() -> Iterable[str]:
            import json

            last_frame_id = None
            while True:
                result = detection_hub.wait_for_new_detection(camera_id, last_frame_id, timeout=1.0)
                if result is None or result.get("frame_id") == last_frame_id:
                    yield ": keep-alive\n\n"
                    continue
                last_frame_id = result.get("frame_id")
                yield "data: {}\n\n".format(json.dumps(result, separators=(",", ":")))

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/evidence-recordings")
    def create_evidence_recording(request: EvidenceRecordingRequest):
        if request.camera_id not in camera_map:
            raise HTTPException(status_code=404, detail="Unknown camera {}".format(request.camera_id))
        if evidence_recorder is None:
            raise HTTPException(status_code=503, detail="Evidence recorder is disabled")
        job_id = evidence_recorder.start(request)
        return {
            "status": "accepted",
            "job_id": job_id,
            "camera_id": request.camera_id,
            "ai_event_id": request.ai_event_id,
        }

    @app.get("/viewer")
    def viewer():
        return HTMLResponse(_viewer_html(cameras, mode=viewer_mode))

    @app.get("/viewer/live")
    def viewer_live():
        return HTMLResponse(_viewer_html(cameras, mode="live"))

    @app.get("/viewer/sync")
    def viewer_sync():
        return HTMLResponse(_viewer_html(cameras, mode="sync"))

    return app


def start_live_viewer_server(
    hub: LiveFrameHub,
    cameras: List[CameraIngestConfig],
    host: str,
    port: int,
    detection_hub: Optional[DetectionHub] = None,
    viewer_mode: str = "live",
    evidence_recorder: Optional[VideoEvidenceRecorder] = None,
) -> threading.Thread:
    import uvicorn

    app = create_live_viewer_app(
        hub,
        cameras,
        detection_hub=detection_hub,
        viewer_mode=viewer_mode,
        evidence_recorder=evidence_recorder,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="edge-live-viewer-server", daemon=True)
    thread.start()
    LOGGER.info("Edge live viewer started at http://%s:%s/viewer", host, port)
    return thread


def _parse_time(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _viewer_html(cameras: List[CameraIngestConfig], mode: str = "live") -> str:
    sync_mode = mode == "sync"
    cards = "\n".join(
        """
        <section class="camera">
          <header>
            <h2>{name}</h2>
            <p id="meta-{camera_id}">{camera_id}</p>
          </header>
          <div class="stage">
            <img id="img-{camera_id}" {src} alt="{name}">
            <canvas id="canvas-{camera_id}"></canvas>
          </div>
        </section>
        """.format(
            name=camera.name,
            camera_id=camera.camera_id,
            src="" if sync_mode else 'src="/api/cameras/{}/mjpeg"'.format(camera.camera_id),
        )
        for camera in cameras
    )
    return """
<!doctype html>
<html>
  <head>
    <title>Edge Gateway Live Viewer</title>
    <style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: Arial, sans-serif; background: #101010; color: #eee; }}
      .top {{ padding: 14px 16px 8px; border-bottom: 1px solid #252525; }}
      h1 {{ margin: 0 0 6px; font-size: 20px; }}
      .top p {{ margin: 0; color: #7dd3fc; font-size: 13px; }}
      main {{ padding: 14px 16px 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 14px; }}
      .camera {{ min-width: 0; background: #050505; border: 1px solid #333; border-radius: 6px; overflow: hidden; }}
      .camera header {{ padding: 8px 10px; background: #111; border-bottom: 1px solid #2a2a2a; }}
      h2 {{ margin: 0 0 4px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .camera p {{ margin: 0; color: #b8b8b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .stage {{ position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; }}
      img, canvas {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
      img {{ object-fit: contain; display: block; }}
      canvas {{ pointer-events: none; }}
    </style>
  </head>
  <body>
    <header class="top">
      <h1>Edge Gateway Live Viewer</h1>
      <p>{subtitle}</p>
    </header>
    <main>
      {cards}
    </main>
    <script>
      const cameras = {camera_ids};
      const latestDetections = {{}};

      function resizeCanvas(cameraId) {{
        const image = document.getElementById(`img-${{cameraId}}`);
        const canvas = document.getElementById(`canvas-${{cameraId}}`);
        const rect = image.getBoundingClientRect();
        const width = Math.max(1, Math.round(rect.width));
        const height = Math.max(1, Math.round(rect.height));
        if (canvas.width !== width || canvas.height !== height) {{
          canvas.width = width;
          canvas.height = height;
        }}
      }}

      function draw(cameraId) {{
        const result = latestDetections[cameraId];
        const canvas = document.getElementById(`canvas-${{cameraId}}`);
        const meta = document.getElementById(`meta-${{cameraId}}`);
        resizeCanvas(cameraId);
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!result || !result.detections) return;

        const sx = canvas.width / Math.max(1, result.frame_width || canvas.width);
        const sy = canvas.height / Math.max(1, result.frame_height || canvas.height);
        ctx.lineWidth = 2;
        ctx.font = "12px Arial";
        result.detections.forEach((det) => {{
          const box = det.bbox_xyxy || [0, 0, 0, 0];
          const x1 = box[0] * sx;
          const y1 = box[1] * sy;
          const x2 = box[2] * sx;
          const y2 = box[3] * sy;
          const label = `${{det.class_name}} ${{Number(det.confidence || 0).toFixed(2)}}`;
          ctx.strokeStyle = det.class_name === "car" ? "#38bdf8" : "#39ff14";
          ctx.fillStyle = ctx.strokeStyle;
          ctx.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));
          const textWidth = ctx.measureText(label).width + 8;
          ctx.fillRect(x1, Math.max(0, y1 - 18), textWidth, 18);
          ctx.fillStyle = "#071207";
          ctx.fillText(label, x1 + 4, Math.max(12, y1 - 5));
        }});
        meta.textContent = `${{cameraId}} | bbox seq ${{result.sequence_number}} | detections ${{result.detection_count}} | ai ${{result.inference_ms}}ms`;
      }}

      function connectDetections(cameraId) {{
        const events = new EventSource(`/api/cameras/${{encodeURIComponent(cameraId)}}/detections/stream`);
        events.onmessage = (event) => {{
          latestDetections[cameraId] = JSON.parse(event.data);
          if ({sync_mode}) {{
            renderSyncedFrame(cameraId, latestDetections[cameraId]);
          }} else {{
            draw(cameraId);
          }}
        }};
      }}

      function renderSyncedFrame(cameraId, result) {{
        if (!result || !result.frame_id) return;
        const image = document.getElementById(`img-${{cameraId}}`);
        image.onload = () => draw(cameraId);
        image.onerror = () => {{
          const meta = document.getElementById(`meta-${{cameraId}}`);
          meta.textContent = `${{cameraId}} | bbox seq ${{result.sequence_number}} | matched frame expired`;
        }};
        image.src = `/api/cameras/${{encodeURIComponent(cameraId)}}/frames/${{encodeURIComponent(result.frame_id)}}.jpg?t=${{Date.now()}}`;
      }}

      cameras.forEach((cameraId) => {{
        connectDetections(cameraId);
        if (!{sync_mode}) {{
          setInterval(() => draw(cameraId), 250);
        }}
      }});
      window.addEventListener("resize", () => cameras.forEach(draw));
    </script>
  </body>
</html>
""".format(
    cards=cards,
    camera_ids=[camera.camera_id for camera in cameras],
    sync_mode="true" if sync_mode else "false",
    subtitle=(
        "SYNC mode: AI bbox controls displayed frame. Video is slower but bbox/frame match."
        if sync_mode
        else "LIVE mode: raw MJPEG is realtime; AI bbox may lag behind video."
    ),
)
