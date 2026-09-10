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
| `app/video_ingest.py` | Doc RTSP, sampling, resize, encode JPEG, tao `FrameJob`. |
| `app/edge_gateway_main.py` | Entry point Edge Gateway local. |
| `app/modal_websocket_frame_sender.py` | Gui `FrameJob` len Modal `/ws/ingest` bang WebSocket. |
| `app/modal_frame_sender.py` | Gui `FrameJob` len Modal `/ingest` bang HTTP fallback. |
| `modal_yolo11_service.py` | Modal AI Server: `/ws/ingest`, Modal Queue, YOLO Worker, `/ws/results`, `/viewer`. |
| `config.yaml` | Config chay local. |
| `config.docker.yaml` | Config chay trong Docker network. |

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
python -m app.edge_gateway_main --config config.yaml
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
