# Camera/Video Service Sang AI Service Và Output Của AI Service

Tài liệu này mô tả chi tiết cách Camera/Video Service truyền dữ liệu sang AI Service, AI Service xử lý YOLO detection + ByteTrack tracking + rule vùng, và output mà AI Service cần trả ra cho các module phía sau.

Phạm vi chính:

- Camera/Video Service kết nối RTSP, webcam hoặc video file.
- Camera/Video Service đọc frame, chuẩn hóa metadata, kiểm soát FPS.
- AI Service nhận frame hoặc tự đọc video source.
- AI Service chạy YOLO detection.
- AI Service chạy ByteTrack tracking.
- AI Service kiểm tra vùng cấm và vùng hạn chế.
- AI Service xuất kết quả detection/tracking và AI Event.

## 1. Vai Trò Của Hai Service

### 1.1. Camera/Video Service

Camera/Video Service chịu trách nhiệm với nguồn hình ảnh đầu vào.

Trách nhiệm chính:

- Kết nối camera IP qua RTSP.
- Đọc video file để mô phỏng khi chưa có camera thật.
- Đọc webcam nếu cần demo nhanh.
- Quản lý nhiều luồng camera.
- Theo dõi trạng thái camera: `ONLINE`, `OFFLINE`, `RECONNECTING`.
- Giới hạn FPS gửi sang AI để tránh quá tải.
- Gắn metadata cho mỗi frame.
- Gửi frame hoặc thông tin camera source sang AI Service.

Camera/Video Service không nên làm:

- Không chạy YOLO.
- Không chạy tracking.
- Không quyết định cảnh báo nghiệp vụ.
- Không tự tạo Official Alert.

Lý do:

- Camera/Video Service nên nhẹ và ổn định, tập trung vào video stream.
- AI logic thay đổi thường xuyên, nên để riêng trong AI Service.
- Khi AI bị chậm, camera service vẫn có thể kiểm soát sampling, reconnect và trạng thái camera.

### 1.2. AI Service

AI Service chịu trách nhiệm phân tích hình ảnh.

Trách nhiệm chính:

- Nhận frame hoặc nhận camera source URL.
- Chạy YOLO để detect đối tượng.
- Lọc class cần quan tâm, tối thiểu là `PERSON`.
- Chạy ByteTrack để gán `track_id`.
- Tính `bbox`, `foot_point`, `confidence`.
- Kiểm tra đối tượng có nằm trong zone không.
- Tính thời gian đứng trong vùng.
- Đếm số người trong vùng hạn chế.
- Sinh AI Event khi phát hiện bất thường.
- Lưu ảnh bằng chứng khi có event.

AI Service không nên làm:

- Không quản lý user.
- Không xử lý trạng thái alert của người vận hành.
- Không quyết định toàn bộ risk khi cần kết hợp IoT.
- Không lưu toàn bộ video vào database.

Lý do:

- AI Service chỉ nên xuất sự kiện đã phân tích từ camera.
- Event & Risk Engine mới là nơi kết hợp camera + IoT để tạo cảnh báo chính thức.

## 2. Hai Phương Án Truyền Dữ Liệu

Có hai phương án tích hợp giữa Camera/Video Service và AI Service.

## 2.1. Phương Án A: AI Service Tự Đọc Camera Source

Pipeline:

```text
Backend/API hoặc Camera Config
    |
    | camera_id + source_url + zones + rules
    v
AI Service
    |
    | tự đọc RTSP/video file
    v
YOLO Detection
    |
    v
ByteTrack Tracking
    |
    v
Zone Rule
    |
    v
AI Event
```

Request đăng ký camera session:

```http
POST /api/v1/ai/camera-sessions
Authorization: Bearer <service_token>
Content-Type: application/json
```

Body:

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "source_type": "RTSP",
  "source_url": "rtsp://user:password@192.168.1.10:554/stream1",
  "target_fps": 10,
  "frame_width": 1280,
  "frame_height": 720,
  "zones": [
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "zone_type": "FORBIDDEN",
      "name": "Vùng cấm cửa kho",
      "points": [
        { "x": 100, "y": 200 },
        { "x": 500, "y": 200 },
        { "x": 520, "y": 600 },
        { "x": 80, "y": 600 }
      ]
    },
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440011",
      "zone_type": "RESTRICTED",
      "name": "Vùng hạn chế sảnh chờ",
      "points": [
        { "x": 650, "y": 240 },
        { "x": 1150, "y": 240 },
        { "x": 1180, "y": 680 },
        { "x": 620, "y": 680 }
      ]
    }
  ],
  "rules": {
    "forbidden_min_duration_seconds": 1,
    "loitering_duration_seconds": 10,
    "loitering_movement_threshold_pixels": 30,
    "crowding_min_people": 3,
    "crowding_duration_seconds": 5,
    "dedup_window_seconds": 60
  }
}
```

Response:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "RUNNING",
  "created_at": "2026-07-30T09:15:22Z"
}
```

Khi nên dùng:

- Prototype giai đoạn đầu.
- Team ít người.
- Muốn demo nhanh YOLO + ByteTrack + zone.
- Chưa cần tách tối ưu video streaming riêng.

Ưu điểm:

- Ít API truyền frame liên tục.
- Ít overhead network.
- Code nhanh hơn.
- AI Service kiểm soát được FPS, resize và batch inference.

Nhược điểm:

- AI Service phải kiêm luôn việc đọc RTSP.
- Nếu nhiều camera, AI Service sẽ phức tạp hơn.
- Khó chia độc lập tuyệt đối giữa nhóm Camera và nhóm AI.

Khuyến nghị cho thực tập:

```text
Ưu tiên phương án A để làm prototype chạy được trước.
Sau khi pipeline ổn, nếu cần mới tách sang phương án B.
```

## 2.2. Phương Án B: Camera/Video Service Gửi Frame Sang AI Service

Pipeline:

```text
Camera / Video File
    |
    v
Camera/Video Service
    |
    | HTTP/gRPC/Message Queue
    | frame + metadata
    v
AI Service
    |
    v
YOLO Detection + ByteTrack + Zone Rule
    |
    v
AI Output
```

Khi nên dùng:

- Cần tách module rõ ràng.
- Camera/Video Service quản lý nhiều camera.
- AI Service chỉ tập trung inference.
- Muốn sau này scale nhiều AI worker.

Ưu điểm:

- Ranh giới service rõ.
- Camera Service xử lý reconnect, sampling, buffering riêng.
- Có thể đổi AI Service mà không đổi camera logic.
- Có thể gửi frame vào message queue để nhiều AI worker xử lý.

Nhược điểm:

- Gửi ảnh liên tục qua network khá nặng.
- Cần xử lý backpressure khi AI chậm.
- Cần định nghĩa frame encoding, timeout, retry.

Khuyến nghị:

```text
Nếu làm prototype: chưa bắt buộc.
Nếu làm kiến trúc bài bản để chia nhóm: nên định nghĩa contract này từ đầu.
```

## 3. Contract Frame Từ Camera/Video Service Sang AI Service

Nếu dùng phương án B, mỗi frame gửi sang AI Service phải có đủ metadata.

### 3.1. Endpoint Gửi Frame

```http
POST /api/v1/ai/frames
Authorization: Bearer <service_token>
Content-Type: multipart/form-data
X-Correlation-ID: <uuid>
```

Lý do chọn `multipart/form-data`:

- Gửi được file ảnh nhị phân và metadata cùng lúc.
- Dễ test bằng Postman/curl.
- Tránh encode ảnh base64 làm payload JSON phình lớn hơn khoảng 30%.

### 3.2. Multipart Fields

| Field | Kiểu | Bắt buộc | Mô tả |
| --- | --- | --- | --- |
| `metadata` | JSON string | Có | Metadata của frame |
| `image` | File JPEG/PNG | Có | Ảnh frame |

### 3.3. Metadata Của Frame

```json
{
  "frame_id": "cam01-0000018280",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "source_type": "RTSP",
  "timestamp": "2026-07-30T09:15:22Z",
  "sequence_number": 18280,
  "frame_width": 1280,
  "frame_height": 720,
  "fps": 10,
  "encoding": "JPEG",
  "zones_version": "2026-07-30T09:00:00Z"
}
```

Ý nghĩa field:

| Field | Ý nghĩa |
| --- | --- |
| `frame_id` | ID duy nhất của frame trong camera session |
| `camera_id` | Camera sinh ra frame |
| `location_id` | Khu vực vật lý của camera |
| `session_id` | Phiên xử lý camera hiện tại |
| `source_type` | `RTSP`, `VIDEO_FILE`, `WEBCAM` |
| `timestamp` | Thời điểm frame được lấy, dùng UTC ISO 8601 |
| `sequence_number` | Số thứ tự frame trong session |
| `frame_width` | Chiều rộng frame gốc |
| `frame_height` | Chiều cao frame gốc |
| `fps` | FPS mục tiêu gửi sang AI |
| `encoding` | Kiểu ảnh gửi sang AI, khuyến nghị `JPEG` |
| `zones_version` | Version cấu hình zone đang áp dụng |

Lý do cần metadata:

- AI Service cần `camera_id` để lấy zone config.
- `timestamp` dùng để tính dwell time và so khớp event.
- `sequence_number` giúp phát hiện mất frame hoặc frame đến sai thứ tự.
- `frame_width`, `frame_height` cần để scale bbox và polygon.
- `zones_version` giúp biết AI đang chạy với cấu hình vùng nào.

### 3.4. Response Khi AI Nhận Frame

```json
{
  "frame_id": "cam01-0000018280",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "ACCEPTED",
  "received_at": "2026-07-30T09:15:22Z"
}
```

Response này chỉ xác nhận AI Service đã nhận frame, chưa chắc đã có event.

Lý do:

- Không phải frame nào cũng có bất thường.
- Nếu chờ AI xử lý xong mới trả response, Camera/Video Service dễ bị nghẽn.
- Tốt hơn là AI xử lý async rồi xuất AI Output riêng.

## 4. Frame Sampling Và FPS

Không nên gửi toàn bộ frame gốc nếu camera 25 hoặc 30 FPS.

Khuyến nghị prototype:

```text
Input camera: 25 FPS
AI target FPS: 5-10 FPS
Evidence image: lưu khi có event
```

Quy tắc:

- Detection/tracking người: 5-10 FPS là đủ cho demo.
- Vùng cấm: có thể cần 10 FPS nếu người đi nhanh.
- Đứng lâu: 3-5 FPS vẫn đủ vì rule tính theo giây.
- Tụ tập: 3-5 FPS vẫn đủ.

Lý do:

- YOLO chạy trên từng frame, FPS càng cao càng tốn GPU/CPU.
- Prototype cần ổn định hơn là xử lý mọi frame.
- ByteTrack vẫn có thể tracking ổn nếu FPS không quá thấp.

## 5. Cấu Hình Zone Gửi Cho AI Service

AI Service cần biết vùng nào là vùng cấm, vùng nào là vùng hạn chế.

Zone config nên lấy từ Backend API hoặc nhận lúc tạo camera session.

### 5.1. Zone Config

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "frame_width": 1280,
  "frame_height": 720,
  "zones": [
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "name": "Vùng cấm cửa kho",
      "zone_type": "FORBIDDEN",
      "points": [
        { "x": 100, "y": 200 },
        { "x": 500, "y": 200 },
        { "x": 520, "y": 600 },
        { "x": 80, "y": 600 }
      ],
      "rules": {
        "forbidden_min_duration_seconds": 1
      }
    },
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440011",
      "name": "Vùng hạn chế sảnh chờ",
      "zone_type": "RESTRICTED",
      "points": [
        { "x": 650, "y": 240 },
        { "x": 1150, "y": 240 },
        { "x": 1180, "y": 680 },
        { "x": 620, "y": 680 }
      ],
      "rules": {
        "loitering_duration_seconds": 10,
        "loitering_movement_threshold_pixels": 30,
        "crowding_min_people": 3,
        "crowding_duration_seconds": 5
      }
    }
  ],
  "updated_at": "2026-07-30T09:00:00Z"
}
```

### 5.2. Cách AI Kiểm Tra Đối Tượng Trong Zone

AI Service không nên dùng tâm bbox để kiểm tra người trong vùng. Nên dùng `foot_point`.

Công thức:

```text
foot_point.x = (bbox.x1 + bbox.x2) / 2
foot_point.y = bbox.y2
```

Sau đó kiểm tra:

```text
foot_point nằm trong polygon zone hay không
```

Lý do:

- Camera thường nhìn xiên, bbox người cao có tâm nằm lệch khỏi vị trí thật trên mặt đất.
- Điểm chân thể hiện vị trí đứng tốt hơn.
- Rule vùng cấm/vùng hạn chế thường dựa trên vị trí trên mặt sàn.

## 6. AI Processing Pipeline Nội Bộ

Pipeline xử lý trong AI Service:

```text
Frame
  |
  v
Preprocess
  |
  v
YOLO Detection
  |
  v
Filter class + confidence
  |
  v
ByteTrack Tracking
  |
  v
Compute foot_point
  |
  v
Zone matching
  |
  v
Rule evaluation
  |
  v
AI Output
```

Chi tiết:

1. Nhận frame từ Camera/Video Service hoặc tự đọc từ RTSP/video.
2. Resize nếu cần, nhưng phải giữ thông tin scale để quy về tọa độ frame gốc.
3. Chạy YOLO.
4. Lọc object theo class quan tâm.
5. Lọc object theo confidence threshold.
6. Gửi detection sang ByteTrack.
7. Nhận `track_id`.
8. Tính `foot_point`.
9. Kiểm tra `foot_point` nằm trong zone nào.
10. Cập nhật trạng thái theo `track_id`.
11. Đánh giá rule vùng cấm, đứng lâu, tụ tập.
12. Sinh AI Event nếu có bất thường.
13. Lưu ảnh bằng chứng nếu có event.
14. Gửi AI Event sang Event & Risk Engine hoặc Backend API.

## 7. Detection Và Tracking Output Theo Frame

Không phải lúc nào AI Service cũng cần gửi output từng frame sang backend. Tuy nhiên trong quá trình debug và hiển thị live overlay, nên có format output theo frame.

### 7.1. Frame Analysis Result

```json
{
  "result_id": "550e8400-e29b-41d4-a716-446655440901",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "frame_id": "cam01-0000018280",
  "timestamp": "2026-07-30T09:15:22Z",
  "frame_width": 1280,
  "frame_height": 720,
  "detections": [
    {
      "track_id": 12,
      "object_type": "PERSON",
      "confidence": 0.92,
      "bbox": {
        "x1": 120,
        "y1": 80,
        "x2": 260,
        "y2": 420
      },
      "foot_point": {
        "x": 190,
        "y": 420
      },
      "zones": [
        {
          "zone_id": "550e8400-e29b-41d4-a716-446655440010",
          "zone_type": "FORBIDDEN",
          "is_inside": true,
          "dwell_time_seconds": 2.4
        }
      ],
      "movement": {
        "speed_pixels_per_second": 12.5,
        "movement_distance_pixels": 18.2
      }
    }
  ],
  "summary": {
    "person_count": 1,
    "vehicle_count": 0,
    "objects_in_forbidden_zone": 1,
    "objects_in_restricted_zone": 0
  },
  "processing": {
    "model_name": "yolo11n",
    "tracker": "bytetrack",
    "inference_time_ms": 38,
    "total_processing_time_ms": 52
  }
}
```

Ý nghĩa:

- `detections`: danh sách object sau detection + tracking.
- `track_id`: ID tạm thời do ByteTrack tạo trong một camera session.
- `zones`: object đang thuộc zone nào.
- `dwell_time_seconds`: object đã ở trong zone bao lâu.
- `movement`: dùng để xác định đứng lâu.
- `summary`: tiện cho dashboard hiển thị tổng quan.
- `processing`: dùng để debug hiệu năng AI.

Khi dùng:

- Debug AI.
- Vẽ bounding box realtime trên dashboard.
- Ghi log ngắn hạn.

Không khuyến nghị:

- Không nên lưu toàn bộ `Frame Analysis Result` của mọi frame vào database lâu dài.
- Chỉ nên lưu khi có event hoặc lưu cache ngắn hạn.

Lý do:

- Dữ liệu frame rất lớn.
- Nếu 4 camera x 10 FPS, mỗi giây đã có 40 kết quả.
- Database sẽ phình nhanh nếu lưu tất cả.

## 8. AI Event Output

AI Event là output quan trọng nhất của AI Service. Event chỉ sinh khi có tình huống đáng chú ý.

AI Service cần tạo các loại event tối thiểu:

- `FORBIDDEN_ZONE_INTRUSION`: người vào vùng cấm.
- `RESTRICTED_ZONE_LOITERING`: người đứng lâu trong vùng hạn chế.
- `RESTRICTED_ZONE_CROWDING`: nhiều người tụ tập trong vùng hạn chế.
- `CAMERA_DISCONNECTED`: camera mất kết nối.
- `CAMERA_RECONNECTED`: camera kết nối lại.

## 8.1. Event Người Vào Vùng Cấm

Điều kiện:

```text
object_type = PERSON
foot_point nằm trong zone_type = FORBIDDEN
dwell_time_seconds >= forbidden_min_duration_seconds
chưa gửi alert trùng trong dedup_window_seconds
```

Output:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440101",
  "event_source": "AI",
  "event_type": "FORBIDDEN_ZONE_INTRUSION",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-07-30T09:15:22Z",
  "objects": [
    {
      "track_id": 12,
      "object_type": "PERSON",
      "confidence": 0.92,
      "bbox": {
        "x1": 120,
        "y1": 80,
        "x2": 260,
        "y2": 420
      },
      "foot_point": {
        "x": 190,
        "y": 420
      },
      "dwell_time_seconds": 2.4
    }
  ],
  "evidence": {
    "evidence_id": "550e8400-e29b-41d4-a716-446655440201",
    "image_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440201/image",
    "thumbnail_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440201/thumbnail"
  },
  "metadata": {
    "model_name": "yolo11n",
    "model_version": "pretrained-coco",
    "tracker": "bytetrack",
    "rule_name": "forbidden_zone_intrusion_v1",
    "dedup_key": "FORBIDDEN_ZONE_INTRUSION:550e8400-e29b-41d4-a716-446655440001:550e8400-e29b-41d4-a716-446655440010:track_12"
  }
}
```

## 8.2. Event Đứng Lâu Trong Vùng Hạn Chế

Điều kiện:

```text
object_type = PERSON
foot_point nằm trong zone_type = RESTRICTED
dwell_time_seconds >= loitering_duration_seconds
movement_distance_pixels <= loitering_movement_threshold_pixels
chưa gửi event trùng trong dedup_window_seconds
```

Output:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440102",
  "event_source": "AI",
  "event_type": "RESTRICTED_ZONE_LOITERING",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440011",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-07-30T09:16:10Z",
  "objects": [
    {
      "track_id": 18,
      "object_type": "PERSON",
      "confidence": 0.89,
      "bbox": {
        "x1": 720,
        "y1": 170,
        "x2": 860,
        "y2": 610
      },
      "foot_point": {
        "x": 790,
        "y": 610
      },
      "dwell_time_seconds": 12.6,
      "movement_distance_pixels": 16.8
    }
  ],
  "evidence": {
    "evidence_id": "550e8400-e29b-41d4-a716-446655440202",
    "image_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440202/image",
    "thumbnail_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440202/thumbnail"
  },
  "metadata": {
    "model_name": "yolo11n",
    "model_version": "pretrained-coco",
    "tracker": "bytetrack",
    "rule_name": "restricted_zone_loitering_v1",
    "loitering_duration_threshold_seconds": 10,
    "movement_threshold_pixels": 30
  }
}
```

## 8.3. Event Tụ Tập Trong Vùng Hạn Chế

Điều kiện:

```text
zone_type = RESTRICTED
số PERSON trong zone >= crowding_min_people
duy trì >= crowding_duration_seconds
chưa gửi event trùng trong dedup_window_seconds
```

Output:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440103",
  "event_source": "AI",
  "event_type": "RESTRICTED_ZONE_CROWDING",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440011",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-07-30T09:17:05Z",
  "objects": [
    {
      "track_id": 21,
      "object_type": "PERSON",
      "confidence": 0.94,
      "bbox": {
        "x1": 680,
        "y1": 150,
        "x2": 800,
        "y2": 600
      },
      "foot_point": {
        "x": 740,
        "y": 600
      }
    },
    {
      "track_id": 22,
      "object_type": "PERSON",
      "confidence": 0.91,
      "bbox": {
        "x1": 820,
        "y1": 160,
        "x2": 950,
        "y2": 620
      },
      "foot_point": {
        "x": 885,
        "y": 620
      }
    },
    {
      "track_id": 23,
      "object_type": "PERSON",
      "confidence": 0.88,
      "bbox": {
        "x1": 960,
        "y1": 180,
        "x2": 1080,
        "y2": 630
      },
      "foot_point": {
        "x": 1020,
        "y": 630
      }
    }
  ],
  "zone_summary": {
    "person_count": 3,
    "duration_seconds": 6.2,
    "crowding_min_people": 3,
    "crowding_duration_seconds": 5
  },
  "evidence": {
    "evidence_id": "550e8400-e29b-41d4-a716-446655440203",
    "image_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440203/image",
    "thumbnail_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440203/thumbnail"
  },
  "metadata": {
    "model_name": "yolo11n",
    "model_version": "pretrained-coco",
    "tracker": "bytetrack",
    "rule_name": "restricted_zone_crowding_v1"
  }
}
```

## 9. Camera Status Event

AI Service hoặc Camera/Video Service cần báo trạng thái camera khi mất kết nối hoặc kết nối lại.

### 9.1. Camera Disconnected

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440104",
  "event_source": "AI",
  "event_type": "CAMERA_DISCONNECTED",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-07-30T09:20:00Z",
  "metadata": {
    "last_frame_at": "2026-07-30T09:19:45Z",
    "reason": "RTSP_READ_TIMEOUT",
    "retry_count": 3
  }
}
```

### 9.2. Camera Reconnected

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440105",
  "event_source": "AI",
  "event_type": "CAMERA_RECONNECTED",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "timestamp": "2026-07-30T09:20:15Z",
  "metadata": {
    "downtime_seconds": 30,
    "current_fps": 9.7
  }
}
```

Lý do:

- Dashboard cần biết camera nào đang mất hình.
- Event & Risk Engine có thể tạo alert `DEVICE_OFFLINE`.
- Khi demo, trạng thái camera là tiêu chí nghiệm thu quan trọng.

## 10. Gửi AI Event Sang Module Phía Sau

AI Service không tạo Official Alert trực tiếp. AI Service gửi AI Event sang Backend API hoặc Event & Risk Engine.

### 10.1. REST API

```http
POST /api/v1/ai/events
Authorization: Bearer <service_token>
Content-Type: application/json
X-Correlation-ID: <uuid>
```

Response:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440101",
  "status": "ACCEPTED",
  "received_at": "2026-07-30T09:15:23Z"
}
```

Khi nên dùng:

- Prototype.
- Dễ debug.
- Dễ test bằng Postman.
- Chưa cần message queue.

### 10.2. Message Queue

Topic đề xuất:

```text
ai.events
```

Envelope:

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440801",
  "message_type": "AI_EVENT_CREATED",
  "schema_version": "1.0",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440777",
  "timestamp": "2026-07-30T09:15:22Z",
  "producer": "ai-service",
  "data": {
    "event_id": "550e8400-e29b-41d4-a716-446655440101",
    "event_source": "AI",
    "event_type": "FORBIDDEN_ZONE_INTRUSION"
  }
}
```

Khi nên dùng:

- Có nhiều camera.
- AI Event nhiều.
- Backend/Event Engine cần xử lý async.
- Muốn tránh mất event khi backend tạm thời chậm.

Khuyến nghị:

```text
Giai đoạn đầu dùng REST.
Khi REST ổn và cần scale, chuyển body AI Event sang message queue.
```

## 11. Quy Tắc Dedup Trong AI Service

AI Service nên có dedup cơ bản để không gửi quá nhiều event giống nhau.

### 11.1. Vùng Cấm

Không gửi lại `FORBIDDEN_ZONE_INTRUSION` nếu cùng:

```text
camera_id
zone_id
track_id
```

trong vòng:

```text
dedup_window_seconds = 60
```

### 11.2. Đứng Lâu

Không gửi lại `RESTRICTED_ZONE_LOITERING` nếu cùng:

```text
camera_id
zone_id
track_id
```

trong vòng 60 giây.

### 11.3. Tụ Tập

Không gửi lại `RESTRICTED_ZONE_CROWDING` nếu cùng:

```text
camera_id
zone_id
```

trong vòng 60 giây, trừ khi số người tăng mạnh.

Lý do:

- AI xử lý nhiều frame mỗi giây.
- Một người đứng trong vùng cấm 10 giây có thể tạo hàng chục event nếu không dedup.
- Dedup ở AI giúp giảm tải cho Backend/Event Engine.

Lưu ý:

```text
AI dedup chỉ là lớp giảm nhiễu ban đầu.
Event & Risk Engine vẫn cần dedup chính thức trước khi tạo alert.
```

## 12. Trạng Thái Theo Dõi Trong AI Service

AI Service cần lưu state tạm theo `camera_id + track_id`.

Ví dụ:

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "track_id": 12,
  "object_type": "PERSON",
  "first_seen_at": "2026-07-30T09:15:20Z",
  "last_seen_at": "2026-07-30T09:15:25Z",
  "current_zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "zone_entered_at": "2026-07-30T09:15:21Z",
  "dwell_time_seconds": 4.0,
  "center_history": [
    { "x": 185, "y": 390, "timestamp": "2026-07-30T09:15:21Z" },
    { "x": 190, "y": 395, "timestamp": "2026-07-30T09:15:22Z" }
  ],
  "last_alerted_events": {
    "FORBIDDEN_ZONE_INTRUSION": "2026-07-30T09:15:22Z"
  }
}
```

Lý do:

- Muốn biết đứng lâu thì phải nhớ thời điểm vào vùng.
- Muốn biết lảng vảng thì phải nhớ lịch sử di chuyển.
- Muốn dedup thì phải nhớ lần cuối gửi event.
- `track_id` chỉ có ý nghĩa khi đi kèm `camera_id` hoặc `session_id`.

## 13. Error Contract

### 13.1. Frame Sai Format

Status:

```text
400 Bad Request
```

Response:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "metadata.frame_id is required",
    "details": [
      {
        "field": "metadata.frame_id",
        "issue": "required"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440888",
    "timestamp": "2026-07-30T09:15:22Z"
  }
}
```

### 13.2. AI Service Quá Tải

Status:

```text
503 Service Unavailable
```

Response:

```json
{
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "AI inference queue is full",
    "details": [
      {
        "field": "queue",
        "issue": "backpressure"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440889",
    "timestamp": "2026-07-30T09:15:22Z"
  }
}
```

Camera/Video Service nên làm gì khi gặp `503`:

- Giảm FPS gửi sang AI.
- Bỏ qua frame cũ, ưu tiên frame mới.
- Không retry quá nhiều frame cũ vì sẽ làm AI càng trễ.
- Ghi log cảnh báo.

Lý do:

- Với video realtime, frame cũ quá nhiều thường không còn giá trị.
- Ưu tiên độ trễ thấp hơn là xử lý đủ mọi frame.

## 14. Health Check Và Metrics

### 14.1. AI Service Health

```http
GET /health
```

Response:

```json
{
  "service": "ai-service",
  "status": "OK",
  "version": "1.0.0",
  "timestamp": "2026-07-30T09:15:22Z"
}
```

### 14.2. AI Service Ready

```http
GET /ready
```

Response:

```json
{
  "service": "ai-service",
  "status": "READY",
  "dependencies": {
    "model_loaded": true,
    "tracker_ready": true,
    "event_sink_ready": true
  },
  "timestamp": "2026-07-30T09:15:22Z"
}
```

### 14.3. Metrics Tối Thiểu

AI Service nên log hoặc expose:

- FPS đọc được.
- FPS xử lý được.
- Số frame bị bỏ qua.
- Thời gian inference YOLO.
- Thời gian tracking.
- Tổng thời gian xử lý mỗi frame.
- Số detection mỗi frame.
- Số event đã sinh.
- Số lần camera mất kết nối.

Lý do:

- Dễ biết bottleneck nằm ở camera, CPU/GPU hay network.
- Dễ chứng minh prototype chạy ổn khi nghiệm thu.

## 15. Checklist Implementation Cho Task Của Bạn

### 15.1. Camera/Video Service

- Đọc được video file.
- Đọc được RTSP hoặc webcam nếu có.
- Lấy được `frame_width`, `frame_height`, FPS.
- Gán `camera_id`, `location_id`, `frame_id`, `timestamp`.
- Sampling về 5-10 FPS.
- Báo trạng thái camera online/offline.
- Nếu dùng phương án B, gửi frame sang `/api/v1/ai/frames`.

### 15.2. AI Service

- Load YOLO pretrained.
- Detect được `PERSON`.
- Lọc confidence, ví dụ `confidence >= 0.5`.
- Chạy ByteTrack để có `track_id`.
- Tính `foot_point`.
- Load zone polygon.
- Kiểm tra điểm trong polygon.
- Tính dwell time theo `track_id`.
- Đếm số người trong vùng hạn chế.
- Sinh event vùng cấm.
- Sinh event đứng lâu.
- Sinh event tụ tập.
- Lưu ảnh bằng chứng khi có event.
- Gửi AI Event sang `/api/v1/ai/events`.

### 15.3. Output Bắt Buộc Của AI Service

Tối thiểu mỗi AI Event phải có:

- `event_id`
- `event_source`
- `event_type`
- `camera_id`
- `location_id`
- `zone_id`
- `timestamp`
- `objects`
- `metadata`

Nếu có bằng chứng, thêm:

- `evidence.evidence_id`
- `evidence.image_url`
- `evidence.thumbnail_url`

## 16. Luồng Demo Tối Thiểu

Luồng demo vùng cấm:

```text
1. Chạy video có người đi vào vùng cấm.
2. Camera/Video Service hoặc AI Service đọc frame.
3. YOLO detect PERSON.
4. ByteTrack gán track_id.
5. AI Service tính foot_point.
6. foot_point nằm trong FORBIDDEN zone.
7. dwell_time_seconds >= 1.
8. AI Service lưu ảnh bằng chứng.
9. AI Service tạo FORBIDDEN_ZONE_INTRUSION event.
10. Event được in ra console hoặc gửi API.
```

Luồng demo đứng lâu:

```text
1. Người đứng trong RESTRICTED zone.
2. ByteTrack giữ cùng track_id.
3. AI Service tính dwell_time_seconds >= 10.
4. Movement nhỏ hơn threshold.
5. AI Service tạo RESTRICTED_ZONE_LOITERING event.
```

Luồng demo tụ tập:

```text
1. Có ít nhất 3 người trong RESTRICTED zone.
2. Số người duy trì >= 5 giây.
3. AI Service tạo RESTRICTED_ZONE_CROWDING event.
```

## 17. Quyết Định Kỹ Thuật Khuyến Nghị

Cho giai đoạn thực tập, nên chọn:

| Hạng mục | Khuyến nghị |
| --- | --- |
| Cách tích hợp ban đầu | AI Service tự đọc video source |
| Model | YOLO pretrained COCO |
| Tracker | ByteTrack |
| Object chính | `PERSON` |
| FPS xử lý | 5-10 FPS |
| Vùng giám sát | Polygon theo pixel |
| Điểm kiểm tra zone | `foot_point` |
| Output chính | AI Event |
| Evidence | Lưu ảnh khi có event |
| Gửi event | REST trước, message queue sau |

Lý do:

- Đủ để chứng minh pipeline end-to-end.
- Không cần train model riêng ngay.
- Giảm độ khó tích hợp ban đầu.
- Dễ chia việc: một bạn làm đọc camera, một bạn làm YOLO/ByteTrack, một bạn làm rule zone/output event.

