# AI Service / Edge Gateway Prototype

He thong hien tai da chuyen sang flow B:

```text
Camera LAN / Camera Simulator
  -> RTSP
  -> Edge Gateway / Video Ingest
  -> Modal /ingest
  -> Modal Queue
  -> Modal YOLOv11 GPU Worker
  -> Modal Dict Result Store
  -> Modal /results va /viewer
```

Local khong con chay AI Worker YOLO trong duong realtime chinh. Local chi doc RTSP,
sampling FPS, tao metadata va gui frame len Modal. Modal la AI Server cloud chinh:
nhan frame, queue/buffer, chay YOLOv11 GPU va luu result.

## Thanh Phan Chinh

| File | Vai tro |
| --- | --- |
| `app/video_ingest.py` | Doc RTSP, sampling, resize, encode JPEG, tao `FrameJob`. |
| `app/edge_gateway_main.py` | Entry point Edge Gateway local. |
| `app/modal_frame_sender.py` | Gui `FrameJob` len Modal `/ingest`. |
| `modal_yolo11_service.py` | Modal AI Server: `/ingest`, Queue, YOLO Worker, `/results`, `/viewer`. |
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
GET  /results
GET  /results/{camera_id}
GET  /viewer
```

`POST /ingest` nhan payload gom metadata va JPEG base64:

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

Endpoint tra nhanh:

```json
{
  "status": "accepted",
  "camera_id": "camera-id",
  "frame_id": "camera-id-000000000001",
  "sequence_number": 1
}
```

YOLO xu ly async trong Modal worker, result doc qua `/results`.

## Test

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
python -m unittest discover -s tests
```

Redis tests cu van ton tai cho prototype broker local, nhung flow B realtime khong
can Redis local.
