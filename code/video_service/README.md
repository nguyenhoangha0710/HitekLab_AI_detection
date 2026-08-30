# Video Service

Video Service mô phỏng pipeline camera thật bằng cách đọc hai RTSP stream:

```text
code/data/videos/dummy_video_1.mp4 -> Camera Simulator -> rtsp://localhost:8554/camera1 -> Video Service
code/data/videos/dummy_video_2.mp4 -> Camera Simulator -> rtsp://localhost:8554/camera2 -> Video Service
```

Service này đọc stream, sampling frame, gắn metadata rồi đưa vào outbound queue để gửi sang AI Service. Service không chạy YOLO, không tạo `AI_EVENT`, không ghi database trực tiếp và không tạo `ALERT`.

Pipeline gửi frame hiện tại:

```text
RTSP Camera
    -> CameraWorker
    -> FramePacket
    -> Video outbound queue
    -> HTTP sender worker
    -> POST /api/v1/ai/frames
    -> AI Service frame queue
```

`CameraWorker` không POST trực tiếp sang AI Service nữa. Nó chỉ enqueue frame vào queue nội bộ rồi quay lại đọc camera. Nếu outbound queue đầy, frame cũ nhất bị drop để giữ realtime.

Config liên quan trong `config.yaml`:

```yaml
video_service:
  outbound_queue_size_per_camera: 2
  http_sender_worker_count: 2
```

| Config | Ý nghĩa |
| --- | --- |
| `outbound_queue_size_per_camera` | Số frame tối đa chờ gửi cho mỗi camera |
| `http_sender_worker_count` | Số worker thread chuyên gửi HTTP sang AI Service |

## Database Mapping

Mỗi RTSP stream tương ứng một record trong bảng `CAMERA`:

| Database field | Config field |
| --- | --- |
| `CAMERA.id` | `camera_id` |
| `CAMERA.location_id` | `location_id` |
| `CAMERA.name` | `name` |
| `CAMERA.source_type` | `source_type` = `RTSP` |
| `CAMERA.source_url` | `source_url` |
| `CAMERA.status` | runtime status trong Video Service |
| `CAMERA.last_seen_at` | `received_at` của frame gần nhất |

Video Service hiện đọc camera config từ `config.yaml`. Khi Backend API sẵn sàng, phần config này có thể thay bằng API lấy danh sách camera từ bảng `CAMERA`.

## Frame Metadata

Metadata gửi sang AI Service:

```json
{
  "frame_id": "550e8400-e29b-41d4-a716-446655440001-000000000001",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440101",
  "source_type": "RTSP",
  "source_url": "rtsp://localhost:8554/camera1",
  "timestamp": "2026-08-29T10:15:22.120Z",
  "captured_at": "2026-08-29T10:15:22.120Z",
  "received_at": "2026-08-29T10:15:22.120Z",
  "sequence_number": 1,
  "source_width": 1920,
  "source_height": 1080,
  "frame_width": 1280,
  "frame_height": 720,
  "target_fps": 10,
  "encoding": "JPEG"
}
```

Không có `session_id` và không có `loop_index`. Video loop là chi tiết nội bộ của Camera Simulator, không lộ ra contract của Video Service.

`captured_at` hiện fallback bằng thời điểm Video Service đọc frame vì RTSP qua OpenCV chưa có timestamp gốc đáng tin cậy. Khi dùng camera thật có timestamp chuẩn, có thể map timestamp camera vào `captured_at`, còn `received_at` vẫn là thời điểm Video Service nhận frame.

## Chạy RTSP Simulation

Bạn cần một RTSP server đang lắng nghe port `8554`, ví dụ MediaMTX, và FFmpeg trong PATH.

### Cách 1: Dùng Docker Compose

Nếu Docker dùng được, chạy RTSP server và hai camera simulator bằng container:

```powershell
cd code/video_service
docker compose -f docker-compose.rtsp.yml up
```

Sau đó chạy Video Service ở terminal khác:

```powershell
cd code/video_service
python -m app.video_service_main --config config.yaml --sink console
```

### Cách 2: Dùng FFmpeg local

Terminal 1: chạy RTSP server.

Terminal 2: publish hai video vào RTSP:

```powershell
cd code/video_service
python -m app.camera_simulator_main --config config.yaml
```

Terminal 3: đọc hai RTSP stream:

```powershell
cd code/video_service
python -m app.video_service_main --config config.yaml --sink console
```

Test nhanh mỗi camera 5 frame:

```powershell
python -m app.video_service_main --config config.yaml --sink console --max-frames-per-camera 5
```

Xem trực tiếp RTSP bằng OpenCV:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1
```

Viewer sẽ tự lấy tên camera từ `config.yaml` nếu `source_url` khớp. Có thể đặt tên thủ công:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera2 --camera-name "Camera 02 - Main Gate"
```

Giới hạn FPS đọc RTSP và FPS hiển thị của UI:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1 --read-fps 25 --display-fps 10
```

Trong đó:

| Tham số | Ý nghĩa |
| --- | --- |
| `--read-fps` | Giới hạn tốc độ đọc frame từ RTSP stream |
| `--display-fps` | Giới hạn tốc độ render frame lên UI |
| `0` | Không giới hạn FPS |

Ví dụ đọc stream tối đa, nhưng UI chỉ hiển thị 10 FPS:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1 --read-fps 0 --display-fps 10
```

Ví dụ đọc và hiển thị đều không giới hạn:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1 --read-fps 0 --display-fps 0
```

Thoát cửa sổ xem bằng phím `q` hoặc `ESC`.

Khi AI Service có endpoint `/api/v1/ai/frames`, đổi sink sang HTTP. Lúc này frame sẽ đi qua outbound queue rồi mới được HTTP sender worker gửi sang AI:

```powershell
python -m app.video_service_main --config config.yaml --sink http
```

## RTSP Server Gợi Ý

MediaMTX là RTSP server nhẹ, phù hợp cho prototype. Chạy MediaMTX trước, sau đó Camera Simulator dùng FFmpeg publish vào:

```text
rtsp://localhost:8554/camera1
rtsp://localhost:8554/camera2
```

## Test

Chạy unit test:

```powershell
cd code/video_service
python -m unittest discover -s tests
```
