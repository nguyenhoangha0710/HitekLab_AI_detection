import asyncio
import json
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from .frame_queue import FrameJob, FrameQueueManager
from .image_codec import decode_image, draw_debug_overlay, encode_jpeg, frame_size
from .models import FrameAcceptedResponse, FrameMetadata
from .time_utils import to_iso_utc, utc_now


app = FastAPI(title="HITEK AI Service", version="0.1.0")
frame_queue = FrameQueueManager(max_size_per_camera=2)


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
    return {"status": "READY", "service": "ai-service", "timestamp": to_iso_utc(utc_now())}


@app.post("/api/v1/ai/frames", status_code=202)
async def receive_frame(request: Request, metadata: str = Form(...), image: UploadFile = File(...)):
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
    cameras = frame_queue.list_cameras()
    sections = []
    for camera in cameras:
        sections.append(
            """
            <section>
              <h2>{camera_id}</h2>
              <p>{location_id} - queue {queue_size}/{max_queue_size} - received {received_frames} - dropped {dropped_frames} - consumed {consumed_frames}</p>
              <img src="/api/v1/ai/cameras/{camera_id}/stream" />
            </section>
            """.format(
                camera_id=camera.camera_id,
                location_id=camera.location_id,
                queue_size=camera.queue_size,
                max_queue_size=camera.max_queue_size,
                received_frames=camera.received_frames,
                dropped_frames=camera.dropped_frames,
                consumed_frames=camera.consumed_frames,
            )
        )

    if not sections:
        sections.append("<p>No frames received yet. Start Video Service with <code>--sink http</code>.</p>")

    refresh_tag = '<meta http-equiv="refresh" content="5">' if not frame_queue.list_cameras() else ""
    return """
    <!doctype html>
    <html>
      <head>
        <title>AI Service Frame Viewer</title>
        <style>
          body {{ margin: 0; font-family: Arial, sans-serif; background: #111; color: #eee; }}
          main {{ padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
          h1 {{ margin: 16px; font-size: 20px; font-weight: 600; }}
          h2 {{ margin: 0 0 6px; font-size: 14px; font-weight: 600; }}
          p {{ margin: 0 0 8px; font-size: 12px; color: #bbb; }}
          img {{ width: 100%; background: #000; border: 1px solid #333; }}
          section {{ min-width: 0; }}
          code {{ color: #b7e3ff; }}
        </style>
        {refresh_tag}
      </head>
      <body>
        <h1>AI Service Frame Viewer</h1>
        <main>{sections}</main>
      </body>
    </html>
    """.format(sections="\n".join(sections), refresh_tag=refresh_tag)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
