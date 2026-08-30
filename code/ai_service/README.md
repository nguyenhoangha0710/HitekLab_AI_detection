# AI Service

AI Service phase 1 nhận frame từ Video Service qua HTTP multipart, decode ảnh, đưa frame vào queue theo từng `camera_id` và cung cấp viewer để consume frame từ queue. Queue đầy thì frame cũ nhất bị drop để giữ dữ liệu mới hơn cho realtime.

Pipeline:

```text
RTSP Simulator
    -> Video Service
    -> POST /api/v1/ai/frames
    -> AI Service
    -> per-camera frame queue
    -> /viewer consume frame from queue
```

## Chạy service

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Chạy full pipeline

Terminal 1: RTSP simulator.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
docker compose -f docker-compose.rtsp.yml up
```

Terminal 2: AI Service.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Terminal 3: Video Service gửi frame sang AI.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
python -m app.video_service_main --config config.yaml --sink http
```

Mở viewer:

```text
http://localhost:8001/viewer
```

API kiểm tra:

```text
GET http://localhost:8001/health
GET http://localhost:8001/ready
GET http://localhost:8001/api/v1/ai/cameras
GET http://localhost:8001/api/v1/ai/queues
GET http://localhost:8001/api/v1/ai/cameras/{camera_id}/latest.jpg
GET http://localhost:8001/api/v1/ai/cameras/{camera_id}/stream
```

## Contract nhận frame

```http
POST /api/v1/ai/frames
Content-Type: multipart/form-data
X-Correlation-ID: <uuid>
```

Multipart fields:

| Field | Type | Required |
| --- | --- | --- |
| `metadata` | JSON string | yes |
| `image` | JPEG/PNG file | yes |

Metadata hiện tại đồng bộ với Video Service:

```json
{
  "frame_id": "550e8400-e29b-41d4-a716-446655440001-000000000030",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440101",
  "source_type": "RTSP",
  "source_url": "rtsp://localhost:8554/camera1",
  "timestamp": "2026-08-30T09:15:22.120Z",
  "captured_at": "2026-08-30T09:15:22.120Z",
  "received_at": "2026-08-30T09:15:22.120Z",
  "sequence_number": 30,
  "source_width": 640,
  "source_height": 360,
  "frame_width": 1280,
  "frame_height": 720,
  "target_fps": 10.0,
  "encoding": "JPEG"
}
```

Không dùng `session_id` và `loop_index`.

## Queue behavior

Hiện tại AI Service dùng queue trong RAM:

```text
camera_id -> queue frame riêng
max_queue_size = 2
queue đầy -> drop frame cũ nhất -> append frame mới
```

Endpoint nhận frame:

```text
POST /api/v1/ai/frames
    -> validate metadata
    -> decode image
    -> enqueue frame
    -> trả 202 Accepted
```

Viewer/stream consume frame:

```text
GET /api/v1/ai/cameras/{camera_id}/stream
    -> pop frame khỏi queue
    -> vẽ overlay debug
    -> trả MJPEG frame cho browser
```

Vì viewer đang đóng vai trò debug consumer giống AI worker, frame đã hiển thị xong sẽ bị xóa khỏi queue. Sau này YOLO worker sẽ thay viewer làm consumer chính:

```text
queue -> YOLO inference -> AI_EVENT
```

Chỉ số queue:

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "queue_size": 2,
  "max_queue_size": 2,
  "received_frames": 120,
  "enqueued_frames": 120,
  "dropped_frames": 30,
  "consumed_frames": 88,
  "last_enqueued_frame_id": "...",
  "last_consumed_frame_id": "...",
  "last_received_at": "2026-08-30T09:15:22.120Z",
  "last_consumed_at": "2026-08-30T09:15:22.220Z"
}
```

## Test

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
python -m unittest discover -s tests
```
