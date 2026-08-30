# Hướng dẫn thiết lập và sử dụng Video Service

Tài liệu này mô tả cách thiết lập Docker, cấu hình camera, chạy RTSP simulator, kiểm tra stream và chạy Video Service trong prototype AI-IoT. Mục tiêu của phần này là mô phỏng camera thật bằng video file, sau đó để Video Service đọc dữ liệu qua giao thức RTSP giống cách đọc camera IP thực tế.

## 1. Mục tiêu

Trong giai đoạn chưa có camera thật, hệ thống dùng hai video trong thư mục `code/data/videos` để mô phỏng hai camera.

Pipeline hiện tại:

```text
dummy_video_1.mp4
    -> FFmpeg container
    -> MediaMTX RTSP server
    -> rtsp://localhost:8554/camera1
    -> Video Service

dummy_video_2.mp4
    -> FFmpeg container
    -> MediaMTX RTSP server
    -> rtsp://localhost:8554/camera2
    -> Video Service
```

Khi thay bằng camera thật:

```text
Camera IP thật
    -> rtsp://user:password@camera-ip:554/stream
    -> Video Service
```

Như vậy, Docker chỉ dùng để giả lập camera. Video Service vẫn đọc RTSP giống nhau trong cả hai trường hợp.

## 2. Thành phần sử dụng

| Thành phần | Vai trò |
| --- | --- |
| `dummy_video_1.mp4` | Video mẫu mô phỏng camera 1 |
| `dummy_video_2.mp4` | Video mẫu mô phỏng camera 2 |
| FFmpeg container | Đọc video file và phát ra RTSP realtime |
| MediaMTX container | RTSP server nhận stream từ FFmpeg và expose ra `localhost:8554` |
| Video Service | Kết nối RTSP, đọc frame, resize, encode JPEG và gắn metadata |
| RTSP viewer | Script OpenCV để xem trực tiếp stream khi debug |

## 3. Cấu trúc file liên quan

```text
code/
├── data/
│   └── videos/
│       ├── dummy_video_1.mp4
│       └── dummy_video_2.mp4
│
└── video_service/
    ├── config.yaml
    ├── docker-compose.rtsp.yml
    ├── README.md
    ├── app/
    │   ├── video_service_main.py
    │   ├── camera_worker.py
    │   ├── video_source.py
    │   ├── frame_encoder.py
    │   ├── frame_sink.py
    │   ├── models.py
    │   └── config.py
    └── tools/
        └── view_rtsp.py
```

## 4. Docker RTSP simulator

File cấu hình Docker:

```text
code/video_service/docker-compose.rtsp.yml
```

File này tạo ba container:

| Service | Container | Mục đích |
| --- | --- | --- |
| `mediamtx` | `hitek-mediamtx` | RTSP server, mở port `8554` ra host |
| `camera1` | `hitek-camera1-simulator` | Phát `dummy_video_1.mp4` vào `rtsp://mediamtx:8554/camera1` |
| `camera2` | `hitek-camera2-simulator` | Phát `dummy_video_2.mp4` vào `rtsp://mediamtx:8554/camera2` |

Phần RTSP server:

```yaml
mediamtx:
  image: bluenviron/mediamtx:latest
  container_name: hitek-mediamtx
  ports:
    - "8554:8554"
```

Ý nghĩa:

- Dùng image `bluenviron/mediamtx`.
- Container mở RTSP port `8554`.
- Máy host có thể truy cập stream bằng `rtsp://localhost:8554/...`.

Phần camera 1:

```yaml
camera1:
  image: jrottenberg/ffmpeg:4.4-alpine
  container_name: hitek-camera1-simulator
  depends_on:
    - mediamtx
  volumes:
    - ../data/videos:/videos:ro
  command:
    - -re
    - -stream_loop
    - "-1"
    - -i
    - /videos/dummy_video_1.mp4
    - -an
    - -c:v
    - libx264
    - -preset
    - ultrafast
    - -tune
    - zerolatency
    - -f
    - rtsp
    - -rtsp_transport
    - tcp
    - rtsp://mediamtx:8554/camera1
```

Các tham số quan trọng:

| Tham số | Ý nghĩa |
| --- | --- |
| `-re` | Đọc video theo tốc độ realtime, không phát nhanh hết file |
| `-stream_loop -1` | Lặp video vô hạn để mô phỏng camera chạy liên tục |
| `-i /videos/dummy_video_1.mp4` | File video đầu vào |
| `-an` | Bỏ audio |
| `-c:v libx264` | Encode video bằng H.264 |
| `-preset ultrafast` | Giảm độ trễ encode |
| `-tune zerolatency` | Tối ưu cho stream realtime |
| `-f rtsp` | Output format là RTSP |
| `-rtsp_transport tcp` | Dùng TCP để ổn định hơn khi test local |

Camera 2 tương tự, chỉ thay file đầu vào và RTSP path:

```text
/videos/dummy_video_2.mp4 -> rtsp://mediamtx:8554/camera2
```

## 5. Config của Video Service

File:

```text
code/video_service/config.yaml
```

Nội dung chính:

```yaml
video_service:
  target_fps: 10
  frame_width: 1280
  frame_height: 720
  encoding: JPEG
  reconnect_interval_seconds: 3
  read_retry_count: 3
  log_every_n_frames: 30

ai_service:
  base_url: http://localhost:8001
  frame_endpoint: /api/v1/ai/frames
  timeout_seconds: 5

cameras:
  - camera_id: "550e8400-e29b-41d4-a716-446655440001"
    location_id: "550e8400-e29b-41d4-a716-446655440101"
    name: "Camera 01 - Warehouse"
    source_type: "RTSP"
    source_url: "rtsp://localhost:8554/camera1"
    simulator_video_path: "../data/videos/dummy_video_1.mp4"

  - camera_id: "550e8400-e29b-41d4-a716-446655440002"
    location_id: "550e8400-e29b-41d4-a716-446655440102"
    name: "Camera 02 - Main Gate"
    source_type: "RTSP"
    source_url: "rtsp://localhost:8554/camera2"
    simulator_video_path: "../data/videos/dummy_video_2.mp4"
```

Ý nghĩa các nhóm cấu hình:

| Nhóm | Ý nghĩa |
| --- | --- |
| `video_service` | Cấu hình xử lý frame của Video Service |
| `ai_service` | Cấu hình endpoint để gửi frame sang AI Service |
| `cameras` | Danh sách camera mà Video Service cần đọc |

Ý nghĩa các field camera:

| Field | Mapping database | Ý nghĩa |
| --- | --- | --- |
| `camera_id` | `CAMERA.id` | ID camera |
| `location_id` | `CAMERA.location_id` | Khu vực vật lý camera giám sát |
| `name` | `CAMERA.name` | Tên hiển thị |
| `source_type` | `CAMERA.source_type` | Loại nguồn, hiện là `RTSP` |
| `source_url` | `CAMERA.source_url` | URL RTSP Video Service sẽ đọc |
| `simulator_video_path` | Không thuộc DB chính | Chỉ dùng cho Camera Simulator để biết file video nào cần phát |

Lưu ý: `simulator_video_path` là cấu hình phục vụ mô phỏng, không phải field chính của bảng `CAMERA`.

## 6. Metadata Video Service tạo ra

Mỗi frame đọc được từ RTSP sẽ được Video Service đóng gói thành:

```text
FramePacket = FrameMetadata + JPEG image bytes
```

Metadata mẫu:

```json
{
  "frame_id": "550e8400-e29b-41d4-a716-446655440001-000000000030",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440101",
  "source_type": "RTSP",
  "source_url": "rtsp://localhost:8554/camera1",
  "timestamp": "2026-08-29T14:32:37.629Z",
  "captured_at": "2026-08-29T14:32:37.629Z",
  "received_at": "2026-08-29T14:32:37.629Z",
  "sequence_number": 30,
  "source_width": 640,
  "source_height": 360,
  "frame_width": 1280,
  "frame_height": 720,
  "target_fps": 10.0,
  "encoding": "JPEG"
}
```

Giải thích:

| Field | Ý nghĩa |
| --- | --- |
| `frame_id` | ID duy nhất của frame, ghép từ `camera_id` và `sequence_number` |
| `camera_id` | Camera tạo ra frame, đồng bộ với `CAMERA.id` |
| `location_id` | Khu vực vật lý, dùng để AI Event và Risk Engine hợp nhất dữ liệu |
| `source_type` | Hiện là `RTSP`, sau này camera thật vẫn dùng `RTSP` |
| `source_url` | RTSP URL đang đọc |
| `timestamp` | Timestamp chính của frame |
| `captured_at` | Thời điểm camera capture frame nếu lấy được |
| `received_at` | Thời điểm Video Service nhận frame |
| `sequence_number` | Số thứ tự frame tăng dần theo từng camera |
| `source_width`, `source_height` | Kích thước frame gốc đọc từ RTSP |
| `frame_width`, `frame_height` | Kích thước frame sau resize để gửi AI |
| `target_fps` | FPS mục tiêu Video Service emit |
| `encoding` | Định dạng ảnh gửi sang AI, hiện là JPEG |

Hiện tại:

```text
captured_at = received_at = thời điểm Video Service đọc frame
```

Lý do là RTSP qua OpenCV chưa lấy được timestamp gốc đáng tin cậy từ camera. Sau này nếu camera thật cung cấp timestamp chuẩn, chỉ cần map timestamp đó vào `captured_at`, còn `received_at` vẫn là thời điểm Video Service nhận frame.

Không có các field sau:

```text
session_id
loop_index
```

Vì đây là chi tiết mô phỏng video, không nên đưa vào contract lâu dài.

## 7. Cách chạy hệ thống

### 7.1. Cài thư viện Python

Từ thư mục `code/video_service`:

```powershell
pip install -r requirements.txt
```

Các thư viện chính:

| Thư viện | Vai trò |
| --- | --- |
| `opencv-python` | Đọc RTSP, resize frame, encode JPEG |
| `PyYAML` | Đọc `config.yaml` |
| `requests` | Gửi frame sang AI Service qua HTTP |

### 7.2. Chạy RTSP simulator bằng Docker

Mở terminal 1:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
docker compose -f docker-compose.rtsp.yml up
```

Sau khi chạy, hệ thống có hai RTSP stream:

```text
rtsp://localhost:8554/camera1
rtsp://localhost:8554/camera2
```

Để chạy nền:

```powershell
docker compose -f docker-compose.rtsp.yml up -d
```

Để dừng:

```powershell
docker compose -f docker-compose.rtsp.yml down
```

### 7.3. Xem RTSP stream bằng OpenCV viewer

Mở terminal 2:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
python tools\view_rtsp.py rtsp://localhost:8554/camera1
```

Xem camera 2:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera2
```

Thoát cửa sổ bằng:

```text
q hoặc ESC
```

### 7.4. Chạy Video Service ở chế độ console

Chế độ console dùng để kiểm tra metadata trước khi nối AI Service.

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
python -m app.video_service_main --config config.yaml --sink console
```

Service sẽ đọc cả hai RTSP stream song song và in metadata sau mỗi `log_every_n_frames`.

Test nhanh giới hạn số frame mỗi camera:

```powershell
python -m app.video_service_main --config config.yaml --sink console --max-frames-per-camera 31
```

### 7.5. Chạy Video Service gửi sang AI Service

Khi AI Service đã có endpoint nhận frame:

```http
POST /api/v1/ai/frames
Content-Type: multipart/form-data
```

chạy:

```powershell
python -m app.video_service_main --config config.yaml --sink http
```

Video Service sẽ gửi:

```text
metadata: JSON
image: JPEG binary
```

đến endpoint được cấu hình trong `config.yaml`:

```yaml
ai_service:
  base_url: http://localhost:8001
  frame_endpoint: /api/v1/ai/frames
  timeout_seconds: 5
```

## 8. Cách thay bằng camera thật

Khi có camera IP thật, không cần Docker RTSP simulator nữa.

Không cần chạy:

```powershell
docker compose -f docker-compose.rtsp.yml up
```

Chỉ cần sửa `source_url` trong `config.yaml`.

Ví dụ:

```yaml
cameras:
  - camera_id: "550e8400-e29b-41d4-a716-446655440001"
    location_id: "550e8400-e29b-41d4-a716-446655440101"
    name: "Camera 01 - Warehouse"
    source_type: "RTSP"
    source_url: "rtsp://user:password@192.168.1.50:554/stream1"
```

Pipeline khi dùng camera thật:

```text
Camera IP thật
    -> RTSP stream của camera
    -> Video Service đọc bằng OpenCV
    -> FrameMetadata + JPEG image bytes
    -> AI Service
```

Code Video Service không cần đổi nếu camera thật cung cấp RTSP URL hợp lệ.

## 9. Workflow bên trong Video Service

### 9.1. Entry point

File:

```text
app/video_service_main.py
```

Workflow:

```text
1. Đọc tham số command line.
2. Load config.yaml.
3. Tạo sink output: console hoặc http.
4. Tạo một CameraWorker cho mỗi camera.
5. Mỗi CameraWorker chạy trên một thread riêng.
6. Main thread chờ các worker chạy.
```

### 9.2. Camera worker

File:

```text
app/camera_worker.py
```

Workflow:

```text
1. Nhận CameraConfig.
2. Tạo RtspVideoSource từ source_url.
3. Mở RTSP stream.
4. Loop liên tục:
   - đọc frame;
   - resize frame;
   - encode JPEG;
   - tạo metadata;
   - gửi FramePacket sang sink;
   - sleep theo target_fps.
5. Nếu đọc lỗi, chuyển trạng thái RECONNECTING và thử kết nối lại.
```

### 9.3. RTSP source

File:

```text
app/video_source.py
```

Workflow:

```text
1. Dùng cv2.VideoCapture(source_url, cv2.CAP_FFMPEG).
2. read() trả về frame nếu đọc thành công.
3. Nếu stream lỗi hoặc mất kết nối, trả False để CameraWorker reconnect.
```

### 9.4. Frame encoding

File:

```text
app/frame_encoder.py
```

Workflow:

```text
1. Lấy kích thước frame gốc.
2. Resize frame về frame_width/frame_height.
3. Encode frame thành JPEG bytes.
```

### 9.5. Sink output

File:

```text
app/frame_sink.py
```

Có hai output chính:

| Sink | Vai trò |
| --- | --- |
| `console` | In metadata để debug |
| `http` | Gửi multipart frame sang AI Service |

## 10. Kiểm thử

Chạy unit test:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
python -m unittest discover -s tests
```

Các test hiện có kiểm tra:

- Load được 2 camera config.
- Metadata đúng mapping với database.
- Không có `session_id`.
- Không có `loop_index`.
- `sequence_number` tăng dần.
- Timestamp là UTC ISO 8601.
- Frame được encode JPEG hợp lệ.

## 11. Lỗi thường gặp

### 11.1. Không xem được stream

Kiểm tra Docker đã chạy chưa:

```powershell
docker compose -f docker-compose.rtsp.yml ps
```

Nếu chưa chạy:

```powershell
docker compose -f docker-compose.rtsp.yml up
```

### 11.2. Port 8554 bị chiếm

Nếu có service khác dùng port `8554`, đổi port trong `docker-compose.rtsp.yml`:

```yaml
ports:
  - "8555:8554"
```

và sửa `config.yaml`:

```yaml
source_url: "rtsp://localhost:8555/camera1"
```

### 11.3. Video Service không đọc được RTSP

Kiểm tra:

- RTSP simulator đã chạy chưa.
- URL có đúng không.
- Port có bị firewall chặn không.
- OpenCV có hỗ trợ FFmpeg không.

Test bằng viewer:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1
```

### 11.4. Không mở được viewer

Viewer dùng OpenCV GUI. Nếu môi trường không hỗ trợ cửa sổ GUI, hãy dùng Video Service console mode để kiểm tra metadata:

```powershell
python -m app.video_service_main --config config.yaml --sink console --max-frames-per-camera 31
```

## 12. Kết luận

Thiết lập hiện tại giúp mô phỏng camera thật bằng video file nhưng vẫn giữ đúng cách tích hợp thực tế thông qua RTSP. Khi thay bằng camera thật, chỉ cần đổi `source_url` trong `config.yaml`; Video Service vẫn giữ nguyên logic đọc stream, tạo metadata và gửi frame sang AI Service.

Điểm quan trọng là Video Service không phụ thuộc vào chi tiết video loop. Nó chỉ nhìn thấy một RTSP stream liên tục, giống như khi làm việc với camera IP thật.
