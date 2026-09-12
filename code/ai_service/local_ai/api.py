import asyncio
import json
import logging
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from common.config import load_queue_config
from common.frame_job import FrameJob
from common.image_codec import decode_image, draw_debug_overlay, encode_jpeg, frame_size
from common.models import FrameAcceptedResponse, FrameMetadata
from common.time_utils import to_iso_utc, utc_now

from .queue_factory import build_frame_queue
from .result_publisher import processed_frame_to_message
from .result_store_factory import build_result_store


app = FastAPI(title="HITEK AI Service", version="0.1.0")
queue_config = load_queue_config()
frame_queue = build_frame_queue(queue_config)
result_store = build_result_store(queue_config)
LOGGER = logging.getLogger(__name__)


class WebSocketResultManager:
    """Quản lý các browser đang subscribe kết quả xử lý qua WebSocket."""

    def __init__(self) -> None:
        self._clients = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast_text(self, payload: str) -> int:
        async with self._lock:
            clients = list(self._clients)

        stale_clients = []
        for websocket in clients:
            try:
                await websocket.send_text(payload)
            except RuntimeError:
                stale_clients.append(websocket)

        if stale_clients:
            async with self._lock:
                for websocket in stale_clients:
                    self._clients.discard(websocket)
        return max(0, len(clients) - len(stale_clients))

    async def connected_count(self) -> int:
        async with self._lock:
            return len(self._clients)


websocket_results = WebSocketResultManager()


def error_response(code: str, message: str, request_id: Optional[str], status_code: int = 400, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "request_id": request_id,
                "timestamp": to_iso_utc(utc_now()),
            }
        },
    )


@app.get("/health")
def health():
    return {"status": "OK", "service": "ai-service", "timestamp": to_iso_utc(utc_now())}


@app.get("/ready")
def ready():
    return {
        "status": "READY",
        "service": "ai-service",
        "queue_backend": queue_config.backend,
        "processed_stream_buffer_size": queue_config.processed_stream_buffer_size,
        "timestamp": to_iso_utc(utc_now()),
    }


@app.post("/api/v1/ai/frames", status_code=202)
async def receive_frame(request: Request, metadata: str = Form(...), image: UploadFile = File(...)):
    # Endpoint này là đường debug/test contract cũ.
    # Pipeline realtime chính hiện tại đi qua Video Ingest nội bộ, không qua HTTP multipart.
    correlation_id = request.headers.get("X-Correlation-ID")
    received_at = utc_now()

    try:
        raw_metadata = json.loads(metadata)
    except json.JSONDecodeError as exc:
        return error_response(
            "VALIDATION_ERROR",
            "metadata must be valid JSON",
            correlation_id,
            details=[{"field": "metadata", "issue": str(exc)}],
        )

    try:
        frame_metadata = FrameMetadata(**raw_metadata)
    except ValidationError as exc:
        return error_response(
            "VALIDATION_ERROR",
            "metadata is invalid",
            correlation_id,
            details=json.loads(exc.json()),
        )

    image_bytes = await image.read()
    if not image_bytes:
        return error_response(
            "VALIDATION_ERROR",
            "image is required",
            correlation_id,
            details=[{"field": "image", "issue": "empty_file"}],
        )

    try:
        frame = decode_image(image_bytes)
    except ValueError as exc:
        return error_response(
            "VALIDATION_ERROR",
            str(exc),
            correlation_id,
            details=[{"field": "image", "issue": "decode_failed"}],
        )

    queue_summary = frame_queue.enqueue(
        FrameJob(
            metadata=frame_metadata,
            frame=frame,
            image_bytes=image_bytes,
            received_at=received_at,
        )
    )
    image_width, image_height = frame_size(frame)

    response = FrameAcceptedResponse(
        frame_id=frame_metadata.frame_id,
        camera_id=frame_metadata.camera_id,
        status="ACCEPTED",
        received_at=to_iso_utc(received_at),
        image_width=image_width,
        image_height=image_height,
        queue_size=queue_summary.queue_size,
        dropped_frames=queue_summary.dropped_frames,
        correlation_id=correlation_id,
    )
    return response.model_dump()


@app.get("/api/v1/ai/cameras")
def list_cameras():
    return [summary.model_dump() for summary in frame_queue.list_cameras()]


@app.get("/api/v1/ai/queues")
def list_queues():
    return [summary.model_dump() for summary in frame_queue.list_cameras()]


@app.get("/api/v1/ai/results")
def list_results():
    return [summary.model_dump() for summary in result_store.list_cameras()]


@app.get("/api/v1/ai/debug/flow")
def debug_flow():
    # Gom queue state và latest result theo camera để kiểm tra drop/backlog/end-to-end.
    queue_by_camera = {summary.camera_id: summary.model_dump() for summary in frame_queue.list_cameras()}
    result_by_camera = {summary.camera_id: summary.model_dump() for summary in result_store.list_cameras()}
    camera_ids = sorted(set(queue_by_camera) | set(result_by_camera))
    return [
        {
            "camera_id": camera_id,
            "queue": queue_by_camera.get(camera_id),
            "latest_result": result_by_camera.get(camera_id),
        }
        for camera_id in camera_ids
    ]


@app.get("/api/v1/ai/results/{camera_id}/latest.jpg")
def latest_result_frame(camera_id: str):
    result = result_store.get_latest(camera_id)
    if result is None:
        return error_response("NOT_FOUND", "camera has no processed frame", None, status_code=404)
    return Response(content=result.image_bytes, media_type="image/jpeg")


@app.websocket("/ws/ai/results")
async def websocket_result_stream(websocket: WebSocket):
    # Browser chỉ mở một kết nối WebSocket. Frame mới được worker publish sẽ được
    # AI API push xuống đây, không polling /next.jpg theo từng frame.
    await websocket_results.connect(websocket)
    LOGGER.info("WebSocket viewer connected clients=%s", await websocket_results.connected_count())
    try:
        for summary in result_store.list_cameras():
            result = result_store.get_latest(summary.camera_id)
            if result is not None:
                await websocket.send_text(json.dumps(processed_frame_to_message(result), ensure_ascii=False))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await websocket_results.disconnect(websocket)
        LOGGER.info("WebSocket viewer disconnected clients=%s", await websocket_results.connected_count())


@app.get("/api/v1/ai/results/{camera_id}/next.jpg")
def next_result_frame(
    camera_id: str,
    fallback_latest: bool = False,
    after_sequence_number: Optional[str] = None,
):
    sequence_cursor = int(after_sequence_number) if after_sequence_number not in (None, "") else None
    result = result_store.get_after(camera_id, sequence_cursor)
    if result is None and fallback_latest:
        result = result_store.get_latest(camera_id)
    if result is None:
        return Response(status_code=204)

    return Response(
        content=result.image_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-ID": result.metadata.frame_id,
            "X-Sequence-Number": str(result.metadata.sequence_number),
            "X-Processed-At": to_iso_utc(result.processed_at),
            "X-Worker-ID": result.worker_id,
            "X-Shard-ID": str(result.shard_id),
            "X-Location-ID": result.metadata.location_id,
        },
    )


async def stream_result_camera(camera_id: str):
    last_frame_id = None
    while True:
        try:
            result = result_store.pop_next(camera_id, timeout_seconds=1.0)
        except TypeError:
            result = result_store.pop_next(camera_id)
        if result is None and last_frame_id is None:
            result = result_store.get_latest(camera_id)
        if result is not None and result.metadata.frame_id != last_frame_id:
            last_frame_id = result.metadata.frame_id
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + result.image_bytes + b"\r\n"
            await asyncio.sleep(0)
        else:
            await asyncio.sleep(0.03)


@app.get("/api/v1/ai/results/{camera_id}/stream")
def result_camera_stream(camera_id: str):
    return StreamingResponse(stream_result_camera(camera_id), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/v1/ai/cameras/{camera_id}/latest.jpg")
def latest_frame(camera_id: str):
    job = frame_queue.consume(camera_id)
    if job is None:
        return error_response("NOT_FOUND", "camera queue has no frame", None, status_code=404)

    label = "{} | consumed | seq {}".format(
        job.metadata.camera_id,
        job.metadata.sequence_number,
    )
    image = draw_debug_overlay(job.frame, label)
    return Response(content=encode_jpeg(image), media_type="image/jpeg")


async def stream_camera(camera_id: str):
    while True:
        job = frame_queue.consume(camera_id)
        if job is not None:
            label = "{} | consumed | seq {} | received {}".format(
                job.metadata.camera_id,
                job.metadata.sequence_number,
                to_iso_utc(job.received_at),
            )
            image = draw_debug_overlay(job.frame, label)
            jpeg = encode_jpeg(image)
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        await asyncio.sleep(0.1)


@app.get("/api/v1/ai/cameras/{camera_id}/stream")
def camera_stream(camera_id: str):
    return StreamingResponse(stream_camera(camera_id), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/viewer", response_class=HTMLResponse)
def viewer():
    return """
    <!doctype html>
    <html>
      <head>
        <title>AI Service Frame Viewer</title>
        <style>
          body { margin: 0; font-family: Arial, sans-serif; background: #111; color: #eee; }
          main { padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
          h1 { margin: 16px; font-size: 20px; font-weight: 600; }
          h2 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
          p { margin: 0 0 8px; font-size: 12px; color: #bbb; }
          img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; display: block; background: #000; border: 1px solid #333; }
          section { min-width: 0; }
          code { color: #b7e3ff; }
          .empty { margin: 0 16px; color: #bbb; font-size: 13px; }
          .status { margin: 0 16px 8px; color: #8fd3ff; font-size: 12px; }
        </style>
      </head>
      <body>
        <h1>AI Service Worker Result Viewer</h1>
        <p class="status" id="status">Connecting WebSocket...</p>
        <p class="empty" id="empty">No processed frames yet. Start AI Worker and Video Ingest.</p>
        <main id="camera-grid"></main>
        <script>
          const grid = document.getElementById("camera-grid");
          const empty = document.getElementById("empty");
          const status = document.getElementById("status");
          const sections = new Map();
          let renderedFrames = 0;

          function text(stats) {
            return `${stats.location_id} - shard ${stats.shard_id} - worker ${stats.worker_id} - processed seq ${stats.sequence_number} - ${stats.processed_at}`;
          }

          function ensureSection(frame) {
            let state = sections.get(frame.camera_id);
            if (state) {
              state.meta.textContent = text(frame);
              return state;
            }

            const section = document.createElement("section");
            const title = document.createElement("h2");
            const meta = document.createElement("p");
            const image = document.createElement("img");

            title.textContent = frame.camera_id;
            meta.textContent = text(frame);
            image.alt = frame.camera_id;

            section.appendChild(title);
            section.appendChild(meta);
            section.appendChild(image);
            grid.appendChild(section);
            state = { section, meta, image };
            sections.set(frame.camera_id, state);
            return state;
          }

          function renderFrame(frame) {
            const state = ensureSection(frame);
            state.meta.textContent = text(frame);
            state.image.src = `data:image/jpeg;base64,${frame.image_jpeg_base64}`;
            renderedFrames += 1;
            status.textContent = `WebSocket receiving frames - rendered ${renderedFrames}`;
            empty.style.display = "none";
          }

          function connect() {
            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const socket = new WebSocket(`${protocol}//${window.location.host}/ws/ai/results`);
            socket.onmessage = event => {
              try {
                renderFrame(JSON.parse(event.data));
              } catch (error) {
                status.textContent = `Viewer render error: ${error}`;
              }
            };
            socket.onopen = () => {
              status.textContent = "WebSocket connected.";
              empty.textContent = "Waiting for processed frames from AI Worker.";
            };
            socket.onclose = () => {
              status.textContent = "WebSocket disconnected. Reconnecting...";
              empty.textContent = "Waiting for viewer reconnect.";
              empty.style.display = sections.size ? "none" : "block";
              setTimeout(connect, 1000);
            };
            socket.onerror = () => socket.close();
          }

          connect();
        </script>
      </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("local_ai.api:app", host="0.0.0.0", port=8001, reload=True)
