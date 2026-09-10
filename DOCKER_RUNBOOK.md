# Docker Runbook: Edge Gateway To Modal AI Server

Flow hien tai:

```text
Camera video files
  -> FFmpeg camera simulators
  -> MediaMTX RTSP server
  -> Edge Gateway / Video Ingest
  -> Modal /ws/ingest
  -> Modal Queue
  -> Modal YOLOv11 GPU Worker
  -> Modal Result Queue + Modal Dict latest result
  -> Modal /ws/results va /viewer
```

Flow nay chi dung cac primitive cua Modal cho queue/result.

## Local Docker Services

| Service | Vai tro |
| --- | --- |
| `mediamtx` | RTSP server noi bo, expose port `8554`. |
| `camera1` | FFmpeg loop `dummy_video_1.mp4` va publish len `rtsp://mediamtx:8554/camera1`. |
| `camera2` | FFmpeg loop `dummy_video_2.mp4` va publish len `rtsp://mediamtx:8554/camera2`. |
| `edge-gateway` | Doc RTSP, tao `FrameJob`, gui frame len Modal `/ws/ingest` bang WebSocket. |

## Run

Terminal 1: chay Modal AI Server async.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
.\.venv12\Scripts\Activate.ps1
modal serve code\ai_service\modal_yolo11_service.py
```

Copy URL base cua Modal, vi du:

```text
https://xxx--api-dev.modal.run
```

Terminal 2: chay Edge Gateway local.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
$env:MODAL_INGEST_URL="https://xxx--api-dev.modal.run/ingest"
docker compose up --build
```

Docker mac dinh dung `MODAL_TRANSPORT=websocket`. Neu ban set URL dang
`https://xxx--api-dev.modal.run/ingest`, Edge Gateway se tu chuyen thanh:

```text
wss://xxx--api-dev.modal.run/ingest
```

Mo viewer tren Modal:

```text
https://xxx--api-dev.modal.run/viewer
```

Kiem tra API:

```powershell
Invoke-RestMethod -Uri "https://xxx--api-dev.modal.run/health" | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "https://xxx--api-dev.modal.run/results" | ConvertTo-Json -Depth 8
```

Dung Edge local:

```powershell
docker compose down
```

## Important Config

Docker network khong dung `localhost` de cac container goi nhau. Vi vay:

```text
RTSP camera1=rtsp://mediamtx:8554/camera1
RTSP camera2=rtsp://mediamtx:8554/camera2
MODAL_INGEST_URL=https://xxx--api-dev.modal.run/ingest
MODAL_WS_URL=wss://xxx--api-dev.modal.run/ingest
```

Config RTSP cho container nam o:

```text
code/ai_service/config.docker.yaml
```

## Modal Queue Flow

```text
WebSocket /ws/ingest
  -> validate FramePacket
  -> put payload vao Modal Queue FIFO chung
  -> spawn ModalYoloQueueWorker theo chu ky frame

ModalYoloQueueWorker
  -> load YOLOv11 mot lan bang @modal.enter
  -> get frame tu Modal Queue
  -> detect person/car tren GPU T4
  -> ve bbox len frame
  -> luu latest result vao Modal Dict
  -> put result vao Modal Result Queue

WebSocket /ws/results
  -> gui latest snapshot tu Modal Dict khi viewer vua ket noi
  -> doc Modal Result Queue
  -> push frame da ve bbox xuong browser
```

## Realtime Defaults

Vi Edge gui frame qua internet len Modal, khong nen day FPS cao nhu local GPU.
Nen bat dau voi:

```yaml
target_fps: 2-5
frame_width: 640
frame_height: 360
jpeg_quality: 70-80
confidence: 0.25-0.35
```

Neu `target_fps` cao hon toc do Modal worker xu ly, Modal Queue se backlog va
viewer se lag.
