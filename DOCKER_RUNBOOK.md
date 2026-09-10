# Docker Runbook

File `docker-compose.yml` o root gom toan bo pipeline demo vao mot project Docker:

```text
Camera video files
  -> FFmpeg camera simulators
  -> MediaMTX RTSP server
  -> AI Video Ingest
  -> Redis Frame Broker
  -> AI Worker
  -> AI API + WebSocket Viewer
```

## Services

| Service | Vai tro |
| --- | --- |
| `redis` | Luu frame buffer, pending camera queue, result store va pub/sub. |
| `mediamtx` | RTSP server noi bo, expose port `8554`. |
| `camera1` | FFmpeg loop `dummy_video_1.mp4` va publish len `rtsp://mediamtx:8554/camera1`. |
| `camera2` | FFmpeg loop `dummy_video_2.mp4` va publish len `rtsp://mediamtx:8554/camera2`. |
| `ai-video-ingest` | Doc RTSP tu MediaMTX, tao `FrameJob`, enqueue vao Redis. |
| `ai-worker` | Claim frame tu Redis, chay detector/debug overlay, ghi result va publish. |
| `ai-api` | FastAPI server, debug API, `/ready`, `/viewer`, WebSocket result stream. |

## Run

Chay toan bo he thong tu root project:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
docker compose up --build
```

Mo viewer:

```text
http://localhost:8001/viewer
```

Kiem tra API:

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/ready" | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/ai/debug/flow" | ConvertTo-Json -Depth 8
```

Dung he thong:

```powershell
docker compose down
```

## Important Config

Docker network khong dung `localhost` de cac container goi nhau. Vi vay:

```text
AI_REDIS_URL=redis://redis:6379/0
RTSP camera1=rtsp://mediamtx:8554/camera1
RTSP camera2=rtsp://mediamtx:8554/camera2
```

Config RTSP cho container nam o:

```text
code/ai_service/config.docker.yaml
```

Config local van giu o:

```text
code/ai_service/config.yaml
```

## Realtime Defaults

Trong `docker-compose.yml` hien tai:

```text
AI_REDIS_NUM_SHARDS=1
AI_REDIS_FRAME_BUFFER_SIZE=100
AI_REDIS_CLAIM_BATCH_SIZE=1
AI_PROCESSED_STREAM_BUFFER_SIZE=300
```

Nghia la:

```text
1 shard
1 worker
Moi camera giu toi da 100 frame trong Redis buffer
Worker lay 1 frame moi luot de giu cong bang giua camera
Viewer nhan frame da xu ly bang WebSocket
```

## YOLO Mode

Mac dinh worker dang chay detector debug cho nhe:

```yaml
command: ["python", "-m", "app.ai_worker_main", "--shard-id", "0", "--worker-id", "ai-worker-0", "--detector", "debug"]
```

Image Docker mac dinh khong cai YOLO/Torch de build nhanh. Neu muon chay YOLO
person detection trong Docker, bat build arg `INSTALL_YOLO=true` cho service worker
va doi command cua `ai-worker` thanh:

```yaml
command: ["python", "-m", "app.ai_worker_main", "--shard-id", "0", "--worker-id", "ai-worker-0", "--detector", "yolo", "--yolo-model", "yolov8n.pt", "--confidence", "0.35", "--device", "cpu"]
```
