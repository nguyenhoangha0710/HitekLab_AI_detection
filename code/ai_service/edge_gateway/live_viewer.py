import logging
import threading
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from common.frame_job import FrameJob
from common.models import CameraQueueSummary
from common.time_utils import to_iso_utc

from .config import CameraIngestConfig


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

    def __init__(self, cameras: List[CameraIngestConfig]) -> None:
        self._camera_names = {camera.camera_id: camera.name for camera in cameras}
        self._frames: Dict[str, LiveFrame] = {}
        self._received_counts: Dict[str, int] = {}
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


def create_live_viewer_app(hub: LiveFrameHub, cameras: List[CameraIngestConfig]) -> FastAPI:
    app = FastAPI(title="Hitek Edge Gateway Live Viewer")
    camera_map = {camera.camera_id: camera for camera in cameras}

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

    @app.get("/viewer")
    def viewer():
        return HTMLResponse(_viewer_html(cameras))

    return app


def start_live_viewer_server(hub: LiveFrameHub, cameras: List[CameraIngestConfig], host: str, port: int) -> threading.Thread:
    import uvicorn

    app = create_live_viewer_app(hub, cameras)
    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="edge-live-viewer-server", daemon=True)
    thread.start()
    LOGGER.info("Edge live viewer started at http://%s:%s/viewer", host, port)
    return thread


def _viewer_html(cameras: List[CameraIngestConfig]) -> str:
    cards = "\n".join(
        """
        <section class="camera">
          <header>
            <h2>{name}</h2>
            <p>{camera_id}</p>
          </header>
          <img src="/api/cameras/{camera_id}/mjpeg" alt="{name}">
        </section>
        """.format(
            name=camera.name,
            camera_id=camera.camera_id,
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
      img {{ width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; display: block; }}
    </style>
  </head>
  <body>
    <header class="top">
      <h1>Edge Gateway Live Viewer</h1>
      <p>RTSP -> Edge Gateway -> Viewer. No Modal, no YOLO.</p>
    </header>
    <main>
      {cards}
    </main>
  </body>
</html>
""".format(cards=cards)
