# AI Service

AI Service hien tai so huu truc tiep Video Ingest Layer de doc RTSP realtime, tao `FrameJob` va day vao Frame Broker. Duong HTTP multipart van duoc giu lai de test contract/debug, nhung khong con la pipeline realtime chinh.

## Pipeline Moi

```text
Camera Simulator / Camera thật
    -> RTSP
    -> AI Service Video Ingest Layer
    -> Frame Broker Redis
    -> AI Worker
    -> Result Store + Redis Pub/Sub
    -> AI API WebSocket
    -> /viewer
```

Trong pipeline moi:

- Video Ingest Layer ket noi RTSP, decode frame, sampling FPS, resize va tao metadata.
- Frame Broker giu frame buffer rieng theo tung `camera_id`, shard theo `camera_id`.
- AI Worker chi tap trung xu ly inference/tracking/rule.
- Viewer nhan frame da xu ly qua WebSocket, khong polling `/next.jpg`.

## Chay Full Pipeline Moi Bang Docker

Toan bo Redis, RTSP simulator, AI API, AI Worker va Video Ingest da duoc gom vao
`docker-compose.yml` o root project.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
docker compose up --build
```

Mo viewer:

```text
http://localhost:8001/viewer
```

Dung he thong:

```powershell
docker compose down
```

## Chay Thu Cong Khi Can Debug

Neu muon debug tung process khong qua Docker, chay Redis/RTSP rieng roi chay AI API,
AI Worker va AI Video Ingest tu `code/ai_service`.

AI API:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:AI_QUEUE_BACKEND="redis"
$env:AI_REDIS_URL="redis://localhost:6379/0"
$env:AI_REDIS_NUM_SHARDS="1"
$env:AI_REDIS_FRAME_BUFFER_SIZE="100"
$env:AI_REDIS_CLAIM_BATCH_SIZE="1"
$env:AI_PROCESSED_STREAM_BUFFER_SIZE="300"
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

AI Worker:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:AI_QUEUE_BACKEND="redis"
$env:AI_REDIS_URL="redis://localhost:6379/0"
$env:AI_REDIS_NUM_SHARDS="1"
$env:AI_REDIS_FRAME_BUFFER_SIZE="100"
$env:AI_REDIS_CLAIM_BATCH_SIZE="1"
$env:AI_PROCESSED_STREAM_BUFFER_SIZE="300"
python -m app.ai_worker_main --shard-id 0 --worker-id ai-worker-0
```

AI Video Ingest Layer:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:AI_QUEUE_BACKEND="redis"
$env:AI_REDIS_URL="redis://localhost:6379/0"
$env:AI_REDIS_NUM_SHARDS="1"
$env:AI_REDIS_FRAME_BUFFER_SIZE="100"
$env:AI_REDIS_CLAIM_BATCH_SIZE="1"
python -m app.video_ingest_main --config config.yaml
```

Chay worker voi YOLOv11 person + car detection tren Modal:

Terminal Modal:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
modal serve code\ai_service\modal_yolo11_service.py
```

Copy URL endpoint `detect` cua Modal, roi chay worker local:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:AI_QUEUE_BACKEND="redis"
$env:AI_REDIS_URL="redis://localhost:6379/0"
$env:AI_REDIS_NUM_SHARDS="1"
$env:AI_REDIS_FRAME_BUFFER_SIZE="100"
$env:AI_REDIS_CLAIM_BATCH_SIZE="1"
$env:AI_PROCESSED_STREAM_BUFFER_SIZE="300"
$env:MODAL_YOLO_ENDPOINT_URL="https://...modal.run"
python -m app.ai_worker_main --shard-id 0 --worker-id ai-worker-0 --detector modal --yolo-classes person,car --confidence 0.35
```

## Config Video Ingest

File:

```text
code/ai_service/config.yaml
```

Thong so quan trong:

```yaml
video_ingest:
  defaults:
    target_fps: 15
    frame_width: 640
    frame_height: 360
    jpeg_quality: 80
```

Muon live muot hon thi tang `target_fps`, nhung neu AI Worker khong xu ly kip thi Redis se drop frame cu trong buffer cua chinh camera do. Muon giam tai thi ha `frame_width/frame_height` va `jpeg_quality`.

## API Kiem Tra

```text
GET http://localhost:8001/health
GET http://localhost:8001/ready
GET http://localhost:8001/api/v1/ai/queues
GET http://localhost:8001/api/v1/ai/results
GET http://localhost:8001/api/v1/ai/debug/flow
WS  ws://localhost:8001/ws/ai/results
```

## Duong HTTP Multipart Debug

Endpoint nay van ton tai de unit test hoac test contract voi service khac:

```text
POST /api/v1/ai/frames
```

Pipeline realtime hien tai dung Video Ingest Layer noi bo cua AI Service de doc RTSP
va day frame vao Redis Broker.

## Test

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
python -m unittest discover -s tests
```

Redis integration:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
$env:RUN_REDIS_TESTS="1"
$env:AI_REDIS_URL="redis://localhost:6379/0"
python -m unittest tests.test_redis_frame_queue
```
