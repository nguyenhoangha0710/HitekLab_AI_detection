# AI Service / Edge Gateway Prototype

Flow hien tai da rollback ve ban WebSocket Modal don gian:

```text
Camera LAN / Camera Simulator
  -> RTSP
  -> Edge Gateway / Video Ingest
  -> Modal /ws/ingest
  -> Modal Queue
  -> Modal YOLOv11 GPU Worker
  -> Modal Dict latest result + Modal Result Queue
  -> Modal /ws/results
  -> /viewer
```

Local khong chay YOLO trong duong realtime chinh. Local chi doc RTSP, sampling
FPS, tao metadata va gui frame len Modal. Modal la AI Server cloud: nhan frame,
dua vao Modal Queue, chay YOLOv11 GPU va push result ve viewer qua WebSocket.

## Thanh Phan Chinh

| File | Vai tro |
| --- | --- |
| `common/` | Models, `FrameJob`, image codec va time helpers dung chung. |
| `edge_gateway/video_ingest.py` | Doc RTSP, sampling, resize, encode JPEG, tao `FrameJob`. |
| `edge_gateway/main.py` | Entry point Edge Gateway local. |
| `edge_gateway/transport/modal_websocket_sender.py` | Gui `FrameJob` len Modal `/ws/ingest` bang WebSocket. |
| `edge_gateway/transport/modal_http_sender.py` | Gui `FrameJob` len Modal `/ingest` bang HTTP fallback. |
| `local_ai/` | Local FastAPI debug API, memory queue, worker, detector va result store. |
| `modal_yolo11_service.py` | Entry point Modal AI Server: khai bao worker va API routes. |
| `modal_ai/settings.py` | Hang so cau hinh cho Modal app, YOLO va queue. |
| `modal_ai/runtime.py` | Khoi tao Modal `app`, image, queue va state store. |
| `modal_ai/yolo.py` | Decode frame, chay YOLOv11 person/car, ve bbox va tao result payload. |
| `modal_ai/results.py` | Luu latest result va publish frame da xu ly sang viewer. |
| `modal_ai/viewer.py` | HTML/JavaScript viewer WebSocket. |
| `config.yaml` | Config chay local. |
| `config.docker.yaml` | Config chay trong Docker network. |

## Module Layout

```text
code/ai_service
  common/
    config.py                   # local queue config
    frame_job.py                # FrameJob shared contract
    image_codec.py              # resize/decode/encode/draw helpers
    models.py                   # FrameMetadata, response/summary schemas
    time_utils.py               # UTC helpers
  edge_gateway/
    main.py                     # CLI local edge gateway
    config.py                   # camera ingest YAML config
    video_source.py             # RTSP/OpenCV source
    video_ingest.py             # RTSP reader + sampler + FrameJob builder
    transport/
      modal_websocket_sender.py
      modal_http_sender.py
  local_ai/
    api.py                      # local FastAPI debug API
    worker.py                   # local AI worker
    worker_main.py              # local worker CLI
    detector.py                 # local/debug detector adapters
    frame_queue.py              # local frame broker abstraction
    result_store.py             # local result store abstraction
  modal_ai/
    settings.py                 # Modal constants
    runtime.py                  # Modal app/image/Queue/Dict resources
    yolo.py                     # Modal YOLO inference
    results.py                  # Modal result publish/store
    viewer.py                   # Modal browser viewer
  modal_yolo11_service.py       # Modal entrypoint, giu lenh chay cu
```

Quy tac tach module:

```text
Edge code chi biet doc RTSP va gui FramePacket.
Modal entrypoint chi noi route/worker voi cac module ben duoi.
YOLO logic khong nam trong route.
Viewer HTML khong nam lan voi inference.
Queue/state resource nam trong runtime.py de doi backend de hon sau nay.
```

## Chay Full Pipeline

Terminal 1: chay Modal AI Server.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
.\.venv12\Scripts\Activate.ps1
modal serve code\ai_service\modal_yolo11_service.py
```

Copy URL base cua Modal, vi du:

```text
https://xxx--api-dev.modal.run
```

Terminal 2: chay camera simulator va Edge Gateway.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
$env:MODAL_INGEST_URL="https://xxx--api-dev.modal.run/ingest"
docker compose up --build
```

Docker mac dinh dung WebSocket. URL `/ingest` se duoc Edge Gateway tu chuyen
thanh:

```text
wss://xxx--api-dev.modal.run/ingest
```

Mo viewer:

```text
https://xxx--api-dev.modal.run/viewer
```

## Chay Edge Gateway Thu Cong

Can co RTSP stream dang chay truoc, sau do:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:MODAL_INGEST_URL="https://xxx--api-dev.modal.run/ingest"
python -m edge_gateway.main --config config.yaml
```

## Modal API

```text
GET  /health
POST /ingest
WS   /ws/ingest
WS   /ws/results
GET  /queues
GET  /results
GET  /results/{camera_id}
GET  /viewer
```

`WS /ws/ingest` va `POST /ingest` nhan payload gom metadata va JPEG base64:

```json
{
  "tenant_id": "demo-tenant",
  "camera_id": "camera-id",
  "location_id": "location-id",
  "frame_id": "camera-id-000000000001",
  "sequence_number": 1,
  "captured_at": "2026-09-10T10:00:00.000Z",
  "edge_sent_at": "2026-09-10T10:00:00.100Z",
  "classes": ["person", "car"],
  "confidence": 0.35,
  "image_b64": "..."
}
```

YOLO xu ly async trong Modal worker. Viewer nhan frame da xu ly qua
`/ws/results`; `/results` chi la endpoint debug latest result. `/queues` chi bao
ten Modal Queue vi Modal Queue khong expose thong ke per-camera.

## Test

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
python -m unittest discover -s tests
```
