# Báo cáo thiết kế Video Service

Tài liệu này mô tả ý tưởng, kỹ thuật, công nghệ sử dụng và cách truyền dữ liệu của Video Service trong hệ thống AI-IoT cảnh báo bất thường. Phạm vi hiện tại tập trung vào việc mô phỏng camera thật bằng video file, phát thành RTSP stream, sau đó để Video Service đọc stream, tách frame, gắn metadata thời gian thực và chuẩn bị gửi sang AI Service.

## 1. Vai trò của Video Service

Video Service là thành phần trung gian giữa nguồn camera và AI Service.

Trong hệ thống thực tế, camera IP thường cung cấp luồng video qua giao thức RTSP. AI Service không nên trực tiếp quản lý camera, vì AI Service nên tập trung vào xử lý ảnh, YOLO, tracking và rule bất thường. Do đó Video Service được tách riêng để đảm nhiệm các tác vụ liên quan đến nguồn video.

Trách nhiệm chính của Video Service:

- Kết nối đến nguồn camera qua RTSP.
- Đọc frame liên tục từ camera stream.
- Quản lý nhiều camera cùng lúc.
- Theo dõi trạng thái camera: `ONLINE`, `RECONNECTING`, `OFFLINE`.
- Resize frame về kích thước cấu hình.
- Encode frame thành JPEG bytes.
- Gắn metadata cho từng frame.
- Gắn thời gian thực tại thời điểm đọc frame.
- Gửi frame và metadata sang AI Service.

Video Service không chịu trách nhiệm:

- Không chạy YOLO.
- Không tracking object.
- Không kiểm tra zone.
- Không sinh `AI_EVENT`.
- Không tạo `ALERT`.
- Không ghi trực tiếp PostgreSQL.

## 2. Ý tưởng thiết kế

Do giai đoạn hiện tại chưa có camera thật, hệ thống sử dụng video file để mô phỏng camera. Tuy nhiên Video Service không đọc trực tiếp file `.mp4`. Thay vào đó, video file được phát thành RTSP stream để mô phỏng hành vi của camera IP thật.

Pipeline hiện tại:

```text
dummy_video_1.mp4
    -> Camera Simulator
    -> rtsp://localhost:8554/camera1
    -> Video Service
    -> Frame + Metadata

dummy_video_2.mp4
    -> Camera Simulator
    -> rtsp://localhost:8554/camera2
    -> Video Service
    -> Frame + Metadata
```

Khi có camera thật, pipeline sẽ đổi thành:

```text
Camera IP thật
    -> rtsp://user:password@camera-ip:554/stream
    -> Video Service
    -> Frame + Metadata
```

Điểm quan trọng là Video Service chỉ phụ thuộc vào RTSP URL. Vì vậy khi thay camera giả lập bằng camera thật, code Video Service không cần thay đổi, chỉ cần cập nhật `source_url` trong cấu hình.

## 3. Kiến trúc tổng quan

```mermaid
flowchart LR
    subgraph Simulator["Camera Simulator"]
        V1["dummy_video_1.mp4"]
        V2["dummy_video_2.mp4"]
        F1["FFmpeg camera1"]
        F2["FFmpeg camera2"]
        M["MediaMTX RTSP Server"]
    end

    subgraph VideoService["Video Service"]
        CFG["config.yaml"]
        MAIN["video_service_main.py"]
        W1["CameraWorker camera1"]
        W2["CameraWorker camera2"]
        SRC["RtspVideoSource"]
        ENC["resize + JPEG encode"]
        META["FrameMetadata"]
        SINK["Console Sink / HTTP Sink"]
    end

    AI["AI Service"]

    V1 --> F1
    V2 --> F2
    F1 --> M
    F2 --> M
    M -->|"rtsp://localhost:8554/camera1"| SRC
    M -->|"rtsp://localhost:8554/camera2"| SRC
    CFG --> MAIN
    MAIN --> W1
    MAIN --> W2
    W1 --> SRC
    W2 --> SRC
    SRC --> ENC
    ENC --> META
    META --> SINK
    SINK --> AI
```

## 4. Công nghệ sử dụng

| Công nghệ | Vai trò |
| --- | --- |
| Python | Ngôn ngữ chính của Video Service |
| OpenCV | Kết nối RTSP, đọc frame, resize frame, encode JPEG |
| Docker Compose | Chạy RTSP simulator gồm MediaMTX và FFmpeg |
| MediaMTX | RTSP server nhận stream từ FFmpeg và expose ra port `8554` |
| FFmpeg | Đọc video file, phát realtime, encode H.264 và publish RTSP |
| RTSP | Giao thức truyền video giống camera IP thật |
| H.264 | Codec video phổ biến cho camera và stream realtime |
| PyYAML | Đọc file cấu hình `config.yaml` |
| Requests | Gửi frame sang AI Service qua HTTP multipart |
| unittest | Kiểm thử metadata, config và encode frame |

## 5. Camera Simulator

Camera Simulator dùng để biến video file thành RTSP stream. Thành phần này chỉ phục vụ giai đoạn chưa có camera thật.

Camera Simulator hiện được triển khai bằng Docker Compose tại:

```text
code/video_service/docker-compose.rtsp.yml
```

Docker Compose tạo ba container:

| Service | Container | Vai trò |
| --- | --- | --- |
| `mediamtx` | `hitek-mediamtx` | RTSP server |
| `camera1` | `hitek-camera1-simulator` | Phát `dummy_video_1.mp4` thành stream `camera1` |
| `camera2` | `hitek-camera2-simulator` | Phát `dummy_video_2.mp4` thành stream `camera2` |

Luồng camera giả lập:

```text
FFmpeg container
    -> đọc file mp4
    -> phát theo tốc độ realtime
    -> loop vô hạn
    -> encode H.264
    -> publish vào MediaMTX
```

Lệnh FFmpeg được khai báo trực tiếp trong `docker-compose.rtsp.yml`, không cần Python hỗ trợ khi chạy bằng Docker.

Các tham số FFmpeg quan trọng:

| Tham số | Ý nghĩa |
| --- | --- |
| `-re` | Đọc video theo tốc độ realtime |
| `-stream_loop -1` | Lặp video vô hạn để mô phỏng camera chạy liên tục |
| `-i /videos/dummy_video_1.mp4` | Chỉ định file video đầu vào |
| `-an` | Bỏ audio vì hệ thống chỉ xử lý hình ảnh |
| `-c:v libx264` | Encode video bằng H.264 |
| `-preset ultrafast` | Ưu tiên tốc độ encode |
| `-tune zerolatency` | Giảm độ trễ khi streaming |
| `-f rtsp` | Output là RTSP |
| `-rtsp_transport tcp` | Truyền RTSP qua TCP để ổn định khi test local |

MediaMTX expose port:

```yaml
ports:
  - "8554:8554"
```

Nhờ đó máy host và Video Service có thể truy cập:

```text
rtsp://localhost:8554/camera1
rtsp://localhost:8554/camera2
```

## 6. Cách truyền tín hiệu

Tín hiệu video được truyền qua RTSP.

RTSP URL hiện tại:

```text
rtsp://localhost:8554/camera1
rtsp://localhost:8554/camera2
```

Trong nội bộ Docker:

```text
FFmpeg camera1 -> rtsp://mediamtx:8554/camera1
FFmpeg camera2 -> rtsp://mediamtx:8554/camera2
```

Từ máy host:

```text
Video Service -> rtsp://localhost:8554/camera1
Video Service -> rtsp://localhost:8554/camera2
```

Giải thích:

- `mediamtx` là hostname nội bộ trong Docker network.
- `localhost:8554` là địa chỉ mà máy host dùng để truy cập RTSP server.
- Video Service hiện chạy trên máy host nên dùng `localhost`.
- Nếu Video Service chạy trong Docker cùng network, URL có thể đổi thành `rtsp://mediamtx:8554/camera1`.

## 7. Config của Video Service

File cấu hình:

```text
code/video_service/config.yaml
```

Config hiện tại:

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

Các field liên quan database:

| Config field | Database field | Ý nghĩa |
| --- | --- | --- |
| `camera_id` | `CAMERA.id` | ID camera |
| `location_id` | `CAMERA.location_id` | Khu vực camera giám sát |
| `name` | `CAMERA.name` | Tên camera |
| `source_type` | `CAMERA.source_type` | Loại nguồn video |
| `source_url` | `CAMERA.source_url` | RTSP URL để Video Service đọc |

Field `simulator_video_path` chỉ phục vụ Camera Simulator. Nó không phải field chính trong database.

## 8. Mapping với database hiện tại

Theo thiết kế database, bảng `CAMERA` có cấu trúc:

```text
CAMERA
-----------------------------
id              UUID PK
location_id     UUID FK
name            VARCHAR
source_type     VARCHAR
source_url      VARCHAR
status          VARCHAR
last_seen_at    TIMESTAMPTZ
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ
```

Video Service hiện sử dụng các thông tin tương ứng:

```text
CAMERA.id          -> camera_id
CAMERA.location_id -> location_id
CAMERA.name        -> name
CAMERA.source_type -> source_type
CAMERA.source_url  -> source_url
```

Các trạng thái runtime:

```text
status = ONLINE / RECONNECTING / OFFLINE
last_seen_at = thời điểm đọc được frame gần nhất
```

Hiện tại `status` và `last_seen_at` mới được quản lý trong runtime của Video Service. Khi Backend API sẵn sàng, Video Service có thể gọi API để cập nhật hai trường này về database.

## 9. Workflow xử lý trong code

### 9.1. Entry point

File:

```text
code/video_service/app/video_service_main.py
```

Hàm chính:

```python
main()
```

Workflow:

```text
1. Đọc command line arguments.
2. Load config.yaml.
3. Tạo sink output: console hoặc http.
4. Tạo stop_event để dừng service an toàn.
5. Tạo một CameraWorker cho từng camera trong config.
6. Mỗi CameraWorker chạy trong một thread riêng.
7. Main thread join các worker thread để giữ service chạy liên tục.
```

Mục đích của việc dùng thread:

- Camera 1 và camera 2 được đọc song song.
- Một camera lỗi không làm camera còn lại dừng ngay.
- Dễ mở rộng thêm camera bằng cách thêm record config.

### 9.2. Load config

File:

```text
code/video_service/app/config.py
```

Các class chính:

```python
CameraConfig
VideoServiceConfig
CameraSimulatorConfig
```

Hàm chính:

```python
load_config(path)
```

Hàm này đọc `config.yaml`, parse cấu hình service, AI endpoint và danh sách camera thành object Python.

### 9.3. Đọc RTSP

File:

```text
code/video_service/app/video_source.py
```

Class:

```python
RtspVideoSource
```

Hàm mở stream:

```python
open()
```

Trong hàm này, OpenCV tạo kết nối RTSP:

```python
cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
```

Hàm đọc frame:

```python
read()
```

Workflow:

```text
1. Kiểm tra capture đã tồn tại chưa.
2. Gọi capture.read().
3. Nếu đọc thành công, trả về frame dạng numpy.ndarray.
4. Nếu lỗi, trả về False để CameraWorker reconnect.
```

### 9.4. Camera worker

File:

```text
code/video_service/app/camera_worker.py
```

Class:

```python
CameraWorker
```

Hàm chính:

```python
run()
```

Workflow:

```text
1. Mở RTSP source.
2. Tính frame interval theo target_fps.
3. Loop liên tục:
   - đọc frame từ RTSP;
   - lấy thời điểm đọc frame;
   - tạo FramePacket;
   - gửi FramePacket sang sink;
   - sleep theo target_fps.
4. Nếu đọc stream lỗi:
   - chuyển trạng thái RECONNECTING;
   - release source;
   - sleep;
   - mở lại RTSP.
```

### 9.5. Tạo frame packet

File:

```text
code/video_service/app/camera_worker.py
```

Hàm:

```python
_build_packet(frame, frame_time)
```

Workflow:

```text
1. Lấy kích thước frame gốc.
2. Resize frame về kích thước cấu hình.
3. Encode frame thành JPEG bytes.
4. Tăng sequence_number.
5. Cập nhật last_seen_at.
6. Gắn status = ONLINE.
7. Tạo FrameMetadata.
8. Trả về FramePacket gồm metadata và image bytes.
```

### 9.6. Resize và encode JPEG

File:

```text
code/video_service/app/frame_encoder.py
```

Các hàm:

```python
resize_frame()
encode_jpeg()
frame_size()
```

Mục đích:

- Chuẩn hóa kích thước frame trước khi gửi AI.
- Giảm kích thước dữ liệu bằng JPEG.
- Đảm bảo output của Video Service không phụ thuộc kích thước gốc của từng camera.

### 9.7. Sink output

File:

```text
code/video_service/app/frame_sink.py
```

Sink nghĩa là nơi nhận output cuối của Video Service.

Các sink hiện có:

| Sink | Mục đích |
| --- | --- |
| `ConsoleFrameSink` | In metadata ra terminal để debug |
| `MemoryFrameSink` | Lưu packet trong RAM để unit test |
| `AiServiceHttpFrameSink` | Gửi frame sang AI Service bằng HTTP multipart |

Khi dùng HTTP sink, request gửi sang AI Service có dạng:

```http
POST /api/v1/ai/frames
Content-Type: multipart/form-data
X-Correlation-ID: <uuid>
```

Body:

```text
metadata: JSON
image: JPEG binary
```

## 10. Metadata của frame

Mỗi frame được đóng gói thành:

```text
FramePacket
    = FrameMetadata
    + JPEG image bytes
```

Metadata mẫu:

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

Ý nghĩa:

| Field | Ý nghĩa |
| --- | --- |
| `frame_id` | ID duy nhất của frame, ghép từ `camera_id` và `sequence_number` |
| `camera_id` | ID camera, đồng bộ với bảng `CAMERA` |
| `location_id` | Khu vực camera giám sát |
| `source_type` | Loại nguồn, hiện là `RTSP` |
| `source_url` | RTSP URL mà Video Service đọc |
| `timestamp` | Thời điểm chính của frame |
| `captured_at` | Thời điểm camera capture frame nếu lấy được |
| `received_at` | Thời điểm Video Service đọc được frame |
| `sequence_number` | Số thứ tự frame tăng dần theo từng camera |
| `source_width`, `source_height` | Kích thước frame gốc từ RTSP |
| `frame_width`, `frame_height` | Kích thước sau resize |
| `target_fps` | FPS mục tiêu gửi sang AI Service |
| `encoding` | Định dạng ảnh sau encode |

Hiện tại, vì OpenCV không lấy được timestamp gốc từ RTSP một cách ổn định, hệ thống tạm dùng:

```text
timestamp = captured_at = received_at = thời điểm Video Service đọc được frame
```

Khi dùng camera thật có timestamp chuẩn, có thể đổi thành:

```text
captured_at = timestamp từ camera
received_at = thời điểm Video Service nhận frame
timestamp = captured_at
```

## 11. Vấn đề realtime và FPS

Trong Camera Simulator, FFmpeg dùng `-re` để phát video theo tốc độ realtime. Vì vậy stream RTSP không bị đẩy nhanh hết file.

Trong Video Service, `target_fps` được dùng để kiểm soát tốc độ emit frame sang AI Service.

Ví dụ:

```yaml
target_fps: 10
```

Nghĩa là mỗi camera dự kiến gửi khoảng 10 frame mỗi giây.

Luồng hiện tại:

```text
read 1 frame
    -> build metadata
    -> send sink
    -> sleep theo target_fps
    -> read frame tiếp theo
```

Thiết kế này đủ đơn giản cho prototype. Tuy nhiên với camera thật và yêu cầu realtime cao hơn, có thể nâng cấp sang mô hình latest-frame buffer:

```text
Capture thread:
    đọc RTSP liên tục
    luôn giữ latest_frame

Publisher thread:
    mỗi 1 / target_fps giây
    lấy latest_frame mới nhất
    gửi sang AI Service
```

Ưu điểm của latest-frame buffer:

- Giảm nguy cơ xử lý frame cũ tồn trong buffer.
- Ưu tiên frame mới nhất.
- Phù hợp hệ thống cảnh báo realtime.
- Có thể drop frame cũ khi AI Service xử lý chậm.

## 12. Cách kiểm tra RTSP và Video Service

### 12.1. Chạy RTSP simulator

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
docker compose -f docker-compose.rtsp.yml up
```

Chạy nền:

```powershell
docker compose -f docker-compose.rtsp.yml up -d
```

Dừng:

```powershell
docker compose -f docker-compose.rtsp.yml down
```

### 12.2. Xem stream bằng UI OpenCV

Camera 1:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera1
```

Camera 2:

```powershell
python tools\view_rtsp.py rtsp://localhost:8554/camera2
```

Viewer hiển thị:

```text
Camera name | frame time | frame number | RTSP source
```

Thời gian hiển thị là thời điểm viewer đọc được frame từ RTSP.

### 12.3. Kiểm tra Video Service đọc RTSP và tạo frame

```powershell
python -m app.video_service_main --config config.yaml --sink console --max-frames-per-camera 31
```

Nếu thành công, terminal sẽ in metadata JSON cho từng camera.

### 12.4. Gửi frame sang AI Service

Khi AI Service đã chạy endpoint nhận frame:

```powershell
python -m app.video_service_main --config config.yaml --sink http
```

Video Service sẽ gửi multipart request gồm:

```text
metadata: JSON
image: JPEG bytes
```

## 13. Kiểm thử

Chạy test:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\video_service
python -m unittest discover -s tests
```

Các test hiện có:

- Load được hai camera từ `config.yaml`.
- Metadata mapping đúng với database.
- Metadata không có `session_id`.
- Metadata không có `loop_index`.
- `sequence_number` tăng dần.
- Timestamp format UTC kết thúc bằng `Z`.
- Frame encode thành JPEG bytes hợp lệ.

## 14. Lý do thiết kế không có session và loop trong metadata

Ban đầu có thể nghĩ đến `session_id` và `loop_index`, nhưng hai field này đã được loại bỏ khỏi metadata.

Lý do:

- Video loop chỉ là chi tiết mô phỏng của Camera Simulator.
- Camera thật không có khái niệm `loop_index`.
- Database hiện tại không có field `session_id` trong bảng `CAMERA` hoặc `AI_EVENT`.
- Metadata nên giống camera thật nhất có thể.
- Khi thay camera thật, contract không cần đổi.

Vì vậy, Video Service chỉ giữ các field có giá trị lâu dài:

```text
camera_id
location_id
source_type
source_url
frame_id
sequence_number
timestamp
captured_at
received_at
source_width
source_height
frame_width
frame_height
target_fps
encoding
```

## 15. Ưu điểm của thiết kế hiện tại

- Mô phỏng camera thật bằng RTSP thay vì đọc file trực tiếp.
- Dễ chuyển sang camera IP thật bằng cách đổi `source_url`.
- Mỗi camera chạy độc lập trên một worker thread.
- Metadata đồng bộ với bảng `CAMERA`.
- Có timestamp realtime khi đọc frame.
- Có console sink để debug trước khi nối AI Service.
- Có HTTP sink để gửi frame sang AI Service.
- Có OpenCV viewer để kiểm tra stream bằng UI.
- Docker Compose giúp khởi động simulator nhanh và nhất quán.

## 16. Hạn chế hiện tại

- `captured_at` chưa phải timestamp gốc từ camera thật, hiện fallback bằng thời điểm Video Service đọc frame.
- Chưa cập nhật `CAMERA.status` và `CAMERA.last_seen_at` về Backend API.
- Chưa có latest-frame buffer, nên nếu xử lý chậm có thể đọc frame cũ trong RTSP buffer.
- Chưa có retry/backoff nâng cao khi HTTP sink gửi AI Service thất bại.
- Chưa có metric như FPS thực tế, số frame drop, latency.
- Chưa chạy Video Service trong Docker chung với các service khác.

## 17. Hướng phát triển tiếp theo

Các bước nên làm tiếp:

1. Tạo Fake AI Service để nhận multipart frame.
2. Viết contract test cho frame metadata gửi sang AI Service.
3. Refactor Video Service sang latest-frame buffer để realtime hơn.
4. Thêm API cập nhật camera `status` và `last_seen_at` về Backend.
5. Thêm metrics: FPS đọc được, FPS gửi đi, reconnect count, latency.
6. Thêm HTTP retry có kiểm soát khi gửi frame sang AI Service.
7. Docker hóa Video Service để chạy chung với RTSP simulator và Backend.
8. Khi có camera thật, thay `source_url` bằng RTSP URL thật và kiểm tra reconnect.

## 18. Kết luận

Video Service hiện tại đã hoàn thành bước nền tảng: đọc được live RTSP stream từ hai camera giả lập, chuyển stream thành frame, encode thành JPEG và gắn metadata đồng bộ với database. Thiết kế dùng RTSP giúp pipeline gần với môi trường camera IP thật, trong khi Docker Compose giúp mô phỏng camera dễ dàng khi chưa có thiết bị vật lý.

Điểm quan trọng của thiết kế là Video Service chỉ xử lý lớp video input. Các bước AI như YOLO, tracking, zone rule và AI Event sẽ nằm ở AI Service. Nhờ tách trách nhiệm như vậy, hệ thống dễ kiểm thử, dễ thay camera giả bằng camera thật và dễ tích hợp với Backend/Risk Engine trong các giai đoạn sau.
