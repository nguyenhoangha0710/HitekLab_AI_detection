# Quy Ước Chung Và API Contract Cho Hệ Thống AI-IoT Cảnh Báo Bất Thường

Tài liệu này dùng để thống nhất cách các module trong dự án giao tiếp với nhau:

- Camera/Video Service
- AI Service
- IoT Service
- Event & Risk Engine
- Backend API
- Web Dashboard

Mục tiêu là giúp mỗi nhóm có thể code độc lập nhưng vẫn ghép được thành pipeline end-to-end.

## 1. Pipeline Tổng Thể

```text
Camera / Video
    |
    v
Camera/Video Service
    |
    | Frame + camera metadata
    v
AI Service
    |
    | AI Event
    v
Event & Risk Engine
    |
    | Official Alert
    v
Backend API
    |
    | REST API + WebSocket/SignalR
    v
Web Dashboard

IoT Device / Sensor
    |
    | MQTT / HTTP
    v
IoT Service
    |
    | Sensor Reading / Sensor Event
    v
Event & Risk Engine
```

Lý do chọn pipeline này:

- Tách Camera/Video Service khỏi AI Service để sau này có thể thay nguồn đầu vào mà không sửa AI.
- Tách AI Event và Sensor Event khỏi Official Alert để Event & Risk Engine có thể lọc nhiều tín hiệu trước khi tạo cảnh báo chính thức.
- Backend API chỉ nên quản lý dữ liệu, cấu hình, người dùng, realtime và truy vấn. Không nên nhận logic AI nặng.
- Web Dashboard chỉ nhận dữ liệu đã được backend chuẩn hóa, tránh việc frontend phải tự xử lý logic cảnh báo phức tạp.

## 2. Quy Ước Chung

### 2.1. Timestamp

Tất cả timestamp dùng chuẩn ISO 8601 và giờ UTC.

```text
2026-07-30T09:15:22Z
```

Quy ước field:

- `timestamp`: thời điểm sự kiện xảy ra.
- `created_at`: thời điểm bản ghi được tạo trong hệ thống.
- `updated_at`: thời điểm bản ghi được cập nhật lần cuối.
- `received_at`: thời điểm service nhận được dữ liệu.

Lý do chọn UTC ISO 8601:

- Tránh sai lệch múi giờ khi camera, server, dashboard hoặc thiết bị IoT đặt ở các múi giờ khác nhau.
- ISO 8601 dễ sort theo chuỗi, dễ đọc log, và được hỗ trợ tốt trong hầu hết ngôn ngữ lập trình.
- UTC giúp Event & Risk Engine so khớp sự kiện camera và sensor theo cửa sổ thời gian chính xác hơn.

### 2.2. ID

Tất cả ID chính dùng UUID dạng chuỗi.

```text
550e8400-e29b-41d4-a716-446655440000
```

Áp dụng cho:

- `camera_id`
- `sensor_id`
- `device_id`
- `location_id`
- `zone_id`
- `event_id`
- `alert_id`
- `user_id`
- `rule_id`
- `evidence_id`

Ngoại lệ:

- `track_id` do tracker sinh ra có thể là số nguyên trong từng camera stream.
- Khi gửi ra ngoài module AI, nên kèm `camera_id` và `session_id` để tránh trùng `track_id` giữa các camera.

Lý do chọn UUID:

- Nhiều module có thể tạo ID độc lập mà không phụ thuộc database trung tâm.
- Dễ merge dữ liệu từ nhiều service.
- Phù hợp với kiến trúc microservice hoặc distributed service sau này.

### 2.3. Kiểu Dữ Liệu JSON

Tất cả REST API trả về JSON.

Header bắt buộc:

```http
Content-Type: application/json
Accept: application/json
```

Quy ước tên field:

- Dùng `snake_case`.
- Enum dùng `UPPER_SNAKE_CASE`.
- Boolean bắt đầu bằng `is_`, `has_`, hoặc `can_` nếu phù hợp.

Ví dụ:

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "FORBIDDEN_ZONE_INTRUSION",
  "is_online": true
}
```

Lý do chọn JSON và `snake_case`:

- JSON dễ dùng cho REST, WebSocket, MQTT payload và log.
- `snake_case` đồng nhất với Python AI Service và vẫn dễ map sang C#/.NET, JavaScript/TypeScript.
- Enum `UPPER_SNAKE_CASE` giúp phân biệt giá trị cố định với chuỗi tự do.

### 2.4. REST API Version

Tất cả REST API dùng tiền tố:

```text
/api/v1
```

Ví dụ:

```text
GET /api/v1/cameras
POST /api/v1/ai/events
GET /api/v1/alerts
```

Lý do:

- Khi thay đổi contract lớn, có thể thêm `/api/v2` mà không phá frontend hoặc service cũ.
- Backend dễ quản lý tài liệu API và migration.

### 2.5. HTTP Status Code

| Code | Ý nghĩa | Khi dùng |
| --- | --- | --- |
| 200 | Thành công | GET, PUT, PATCH thành công |
| 201 | Đã tạo mới | POST tạo resource thành công |
| 204 | Thành công, không có body | DELETE thành công |
| 400 | Request sai | Payload thiếu field, sai enum, sai format |
| 401 | Chưa xác thực | Thiếu hoặc sai JWT |
| 403 | Không có quyền | Đã đăng nhập nhưng không đủ role |
| 404 | Không tìm thấy | Resource không tồn tại |
| 409 | Xung đột | Trùng `dedup_key`, trùng cấu hình, sai trạng thái cập nhật |
| 422 | Dữ liệu hợp lệ về format nhưng sai nghiệp vụ | Ví dụ zone polygon ít hơn 3 điểm |
| 500 | Lỗi hệ thống | Lỗi server không mong đợi |

Lý do:

- Dùng đúng chuẩn HTTP giúp frontend và service khác xử lý lỗi rõ ràng.
- Phân biệt `400` và `422` giúp debug nhanh: sai format hay sai logic nghiệp vụ.

### 2.6. Error Response

Tất cả lỗi trả về theo format:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "zone_id is required",
    "details": [
      {
        "field": "zone_id",
        "issue": "required"
      }
    ],
    "request_id": "9f1b7f7a-5b3d-4e8a-9b7e-96f5e3a9f111",
    "timestamp": "2026-07-30T09:15:22Z"
  }
}
```

Quy ước `error.code`:

- `VALIDATION_ERROR`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `NOT_FOUND`
- `CONFLICT`
- `INTERNAL_ERROR`
- `SERVICE_UNAVAILABLE`

Lý do:

- Frontend có thể hiển thị `message` cho người dùng.
- Developer có thể dùng `details`, `request_id`, `timestamp` để trace lỗi.

### 2.7. Xác Thực Và Phân Quyền

Tất cả API nội bộ có tác động đến dữ liệu cần dùng Bearer JWT:

```http
Authorization: Bearer <token>
```

Role đề xuất:

- `ADMIN`: quản lý user, camera, sensor, zone, rule.
- `OPERATOR`: xem dashboard, xử lý alert, thêm ghi chú.
- `VIEWER`: chỉ xem dashboard và lịch sử.
- `SERVICE`: service-to-service, dùng cho AI Service, IoT Service, Event & Risk Engine.

Lý do:

- JWT phù hợp với REST API và WebSocket authentication.
- Role rõ ràng giúp chia quyền giữa người vận hành và service nội bộ.
- `SERVICE` tách riêng để không dùng tài khoản người dùng cho các module backend.

### 2.8. Request ID Và Correlation ID

Mỗi request nên có:

```http
X-Request-ID: <uuid>
X-Correlation-ID: <uuid>
```

Quy ước:

- `request_id`: ID cho một request cụ thể.
- `correlation_id`: ID dùng để nối nhiều bước trong cùng một pipeline.

Ví dụ:

```text
Camera frame -> AI Event -> Risk Engine -> Alert -> Dashboard
```

Tất cả bước trên nên dùng chung `correlation_id`.

Lý do:

- Dễ truy vết một cảnh báo đi qua nhiều service.
- Rất hữu ích khi debug độ trễ, mất event, hoặc duplicate alert.

### 2.9. Pagination, Filter, Sorting

Danh sách resource dùng query chung:

```text
GET /api/v1/alerts?page=1&page_size=20&sort=-timestamp
```

Response:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 125,
    "total_pages": 7
  }
}
```

Quy ước:

- `page` bắt đầu từ 1.
- `page_size` mặc định 20, tối đa 100.
- `sort=timestamp` là tăng dần.
- `sort=-timestamp` là giảm dần.

Lý do:

- Frontend dashboard cần tải danh sách alert, event, camera theo trang.
- Giới hạn `page_size` tránh query quá nặng.

## 3. Quy Ước Dữ Liệu Hình Ảnh Và Vùng Giám Sát

### 3.1. Bounding Box

Bounding box dùng tọa độ pixel trên frame gốc, format `xyxy`:

```json
{
  "x1": 120,
  "y1": 80,
  "x2": 260,
  "y2": 420
}
```

Kèm kích thước frame:

```json
{
  "frame_width": 1280,
  "frame_height": 720
}
```

Lý do chọn `xyxy` pixel:

- YOLO và nhiều thư viện tracking trả về bbox dạng `xyxy`.
- Pixel dễ vẽ lên ảnh bằng chứng và dashboard.
- Kèm `frame_width`, `frame_height` giúp frontend scale lại khi hiển thị trên màn hình khác kích thước.

### 3.2. Điểm Đại Diện Của Đối Tượng

Điểm đại diện để kiểm tra đối tượng nằm trong zone là `foot_point`:

```json
{
  "x": 190,
  "y": 420
}
```

Công thức:

```text
foot_point.x = (bbox.x1 + bbox.x2) / 2
foot_point.y = bbox.y2
```

Lý do:

- Với người, điểm chân phản ánh vị trí trên mặt sàn tốt hơn tâm bbox.
- Giảm sai lệch khi người cao/thấp hoặc bbox bao gồm phần thân trên.

### 3.3. Zone Polygon

Zone được định nghĩa bằng polygon theo pixel trên frame tham chiếu:

```json
{
  "zone_id": "550e8400-e29b-41d4-a716-446655440000",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Kho hàng - Vùng cấm",
  "zone_type": "FORBIDDEN",
  "frame_width": 1280,
  "frame_height": 720,
  "points": [
    { "x": 100, "y": 200 },
    { "x": 500, "y": 200 },
    { "x": 520, "y": 600 },
    { "x": 80, "y": 600 }
  ]
}
```

`zone_type`:

- `FORBIDDEN`: không được vào.
- `RESTRICTED`: được đi qua nhưng không được đứng lâu hoặc tụ tập.

Lý do:

- Polygon linh hoạt hơn rectangle, phù hợp với góc camera nghiêng.
- Lưu theo pixel giúp AI Service kiểm tra nhanh bằng OpenCV.
- Kèm kích thước frame để phát hiện zone bị lệch nếu camera đổi resolution.

## 4. Enum Chuẩn

### 4.1. Object Type

```text
PERSON
CAR
MOTORCYCLE
BICYCLE
TRUCK
UNKNOWN
```

### 4.2. AI Event Type

```text
OBJECT_DETECTED
FORBIDDEN_ZONE_INTRUSION
RESTRICTED_ZONE_LOITERING
RESTRICTED_ZONE_CROWDING
CAMERA_DISCONNECTED
CAMERA_RECONNECTED
```

### 4.3. Sensor Type

```text
PIR_MOTION
DOOR
SMOKE
GAS
TEMPERATURE
HUMIDITY
LIGHT
CUSTOM
```

### 4.4. Sensor Event Type

```text
MOTION_DETECTED
DOOR_OPENED
DOOR_CLOSED
SMOKE_DETECTED
GAS_THRESHOLD_EXCEEDED
TEMPERATURE_THRESHOLD_EXCEEDED
SENSOR_OFFLINE
SENSOR_ONLINE
```

### 4.5. Alert Type

```text
UNAUTHORIZED_ENTRY
LOITERING
CROWDING
SENSOR_ABNORMAL
CAMERA_SENSOR_CORRELATED_RISK
DEVICE_OFFLINE
```

### 4.6. Risk Level

```text
LOW
MEDIUM
HIGH
CRITICAL
```

### 4.7. Alert Status

```text
NEW
ACKNOWLEDGED
IN_PROGRESS
RESOLVED
FALSE_POSITIVE
IGNORED
```

Lý do dùng enum cố định:

- Giảm lỗi do mỗi nhóm đặt tên sự kiện khác nhau.
- Event & Risk Engine có thể map rule theo enum.
- Frontend dễ filter, hiển thị màu sắc, icon và trạng thái.

## 5. Contract Giữa Camera/Video Service Và AI Service

Có 2 cách tích hợp:

1. AI Service tự đọc video source trực tiếp.
2. Camera/Video Service đọc frame rồi gửi frame sang AI Service.

Trong prototype, khuyến nghị cách 1 nếu team ít người:

```text
AI Service nhận camera source URL -> tự đọc frame -> detect -> track -> tạo AI Event
```

Khi cần tách service rõ ràng, dùng cách 2:

```text
Camera/Video Service đọc frame -> gửi frame metadata và image sang AI Service
```

Lý do khuyến nghị cách 1 cho prototype:

- Ít service hơn, dễ demo nhanh.
- Giảm overhead gửi ảnh qua HTTP liên tục.
- Phù hợp với task YOLO + ByteTrack + rule zone.

Lý do vẫn định nghĩa contract cách 2:

- Khi hệ thống lớn hơn, Camera/Video Service có thể quản lý nhiều luồng, reconnect, buffering và sampling riêng.
- AI Service tập trung vào inference và rule.

### 5.1. Đăng Ký Camera Source Cho AI Service

```http
POST /api/v1/ai/camera-sessions
Authorization: Bearer <service_token>
Content-Type: application/json
```

Request:

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "source_type": "RTSP",
  "source_url": "rtsp://user:password@192.168.1.10:554/stream1",
  "target_fps": 10,
  "zones": [
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "zone_type": "FORBIDDEN",
      "name": "Vùng cấm của kho",
      "points": [
        { "x": 100, "y": 200 },
        { "x": 500, "y": 200 },
        { "x": 520, "y": 600 },
        { "x": 80, "y": 600 }
      ],
      "frame_width": 1280,
      "frame_height": 720
    }
  ],
  "rules": {
    "forbidden_min_duration_seconds": 1,
    "loitering_duration_seconds": 10,
    "loitering_movement_threshold_pixels": 30,
    "crowding_min_people": 3,
    "crowding_duration_seconds": 5
  }
}
```

Response `201`:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "RUNNING",
  "created_at": "2026-07-30T09:15:22Z"
}
```

### 5.2. Trạng Thái Camera Session

```http
GET /api/v1/ai/camera-sessions/{session_id}
```

Response:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "RUNNING",
  "fps": 9.6,
  "last_frame_at": "2026-07-30T09:15:30Z",
  "last_error": null
}
```

## 6. AI Event Contract

AI Service tạo `AI Event` khi phát hiện sự kiện có ý nghĩa.

```http
POST /api/v1/ai/events
Authorization: Bearer <service_token>
Content-Type: application/json
X-Correlation-ID: 550e8400-e29b-41d4-a716-446655440777
```

Request:

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
  "frame": {
    "frame_id": "cam01-0000018280",
    "frame_width": 1280,
    "frame_height": 720,
    "fps": 10
  },
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
    "rule_name": "forbidden_zone_intrusion_v1"
  }
}
```

Response `201`:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440101",
  "status": "ACCEPTED",
  "received_at": "2026-07-30T09:15:23Z"
}
```

Lý do cấu trúc AI Event như trên:

- `event_id` do AI Service tạo để retry mà không tạo trùng.
- `event_type` giúp Event & Risk Engine map rule.
- `objects` là mảng vì một sự kiện có thể liên quan nhiều người, nhất là `CROWDING`.
- `track_id` giữ theo dạng số nguyên để phù hợp output ByteTrack.
- `evidence` đặt riêng để Backend và Dashboard hiển thị bằng chứng mà không phải lấy raw frame trong database.
- `metadata` giúp kiểm tra model, tracker và rule nào đã sinh event.

## 7. IoT Device Và IoT Service Contract

IoT có thể gửi dữ liệu theo MQTT hoặc HTTP. Khuyến nghị:

- MQTT cho thiết bị thật hoặc simulator gửi liên tục.
- HTTP cho test nhanh, tool nội bộ, hoặc service khác push dữ liệu.

Lý do:

- MQTT nhẹ, phù hợp IoT và kết nối kém ổn định.
- HTTP dễ debug bằng Postman/curl và dễ tích hợp với backend hơn.

### 7.1. MQTT Topic

Topic đề xuất:

```text
hitek/v1/devices/{device_id}/readings
hitek/v1/devices/{device_id}/status
```

Ví dụ:

```text
hitek/v1/devices/550e8400-e29b-41d4-a716-446655440301/readings
```

Payload reading:

```json
{
  "reading_id": "550e8400-e29b-41d4-a716-446655440401",
  "device_id": "550e8400-e29b-41d4-a716-446655440301",
  "sensor_id": "550e8400-e29b-41d4-a716-446655440302",
  "sensor_type": "DOOR",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "value": "OPEN",
  "unit": null,
  "status": "ACTIVE",
  "timestamp": "2026-07-30T09:15:21Z"
}
```

Payload status:

```json
{
  "device_id": "550e8400-e29b-41d4-a716-446655440301",
  "status": "ONLINE",
  "battery_percent": 87,
  "signal_strength": -52,
  "timestamp": "2026-07-30T09:15:20Z"
}
```

### 7.2. HTTP Reading API

```http
POST /api/v1/iot/readings
Authorization: Bearer <service_or_device_token>
Content-Type: application/json
```

Request:

```json
{
  "reading_id": "550e8400-e29b-41d4-a716-446655440401",
  "device_id": "550e8400-e29b-41d4-a716-446655440301",
  "sensor_id": "550e8400-e29b-41d4-a716-446655440302",
  "sensor_type": "PIR_MOTION",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "value": true,
  "unit": null,
  "status": "ACTIVE",
  "timestamp": "2026-07-30T09:15:21Z"
}
```

Response `201`:

```json
{
  "reading_id": "550e8400-e29b-41d4-a716-446655440401",
  "status": "ACCEPTED",
  "received_at": "2026-07-30T09:15:22Z"
}
```

### 7.3. Sensor Event Contract

IoT Service chuẩn hóa reading thành event khi reading có ý nghĩa cảnh báo.

```http
POST /api/v1/iot/events
Authorization: Bearer <service_token>
Content-Type: application/json
```

Request:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440501",
  "event_source": "IOT",
  "event_type": "DOOR_OPENED",
  "device_id": "550e8400-e29b-41d4-a716-446655440301",
  "sensor_id": "550e8400-e29b-41d4-a716-446655440302",
  "sensor_type": "DOOR",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "value": "OPEN",
  "timestamp": "2026-07-30T09:15:21Z",
  "metadata": {
    "reading_id": "550e8400-e29b-41d4-a716-446655440401"
  }
}
```

Lý do tách Sensor Reading và Sensor Event:

- `Sensor Reading` là dữ liệu raw/ban đầu, có thể rất nhiều.
- `Sensor Event` là dữ liệu đã có ý nghĩa, ví dụ cửa mở, PIR phát hiện chuyển động, gas vượt ngưỡng.
- Event & Risk Engine chỉ cần nhận event có ý nghĩa để giảm tải.

## 8. Event & Risk Engine Contract

Event & Risk Engine nhận AI Event và Sensor Event, sau đó tạo Official Alert.

### 8.1. Rule Xử Lý Mẫu

Rule 1: Vùng cấm

```text
Nếu AI Event = FORBIDDEN_ZONE_INTRUSION
Và zone_type = FORBIDDEN
Thì tạo alert UNAUTHORIZED_ENTRY với risk_level = HIGH
```

Rule 2: Vùng cấm + cửa mở

```text
Nếu AI Event = FORBIDDEN_ZONE_INTRUSION
Và Sensor Event = DOOR_OPENED
Và cùng location_id hoặc zone_id
Và chênh lệch timestamp <= 10 giây
Thì tạo alert CAMERA_SENSOR_CORRELATED_RISK với risk_level = CRITICAL
```

Rule 3: Đứng lâu vùng hạn chế

```text
Nếu AI Event = RESTRICTED_ZONE_LOITERING
Và dwell_time_seconds >= 10
Thì tạo alert LOITERING với risk_level = MEDIUM
```

Rule 4: Tụ tập vùng hạn chế

```text
Nếu AI Event = RESTRICTED_ZONE_CROWDING
Và số PERSON >= 3
Và duy trì >= 5 giây
Thì tạo alert CROWDING với risk_level = HIGH
```

### 8.2. Deduplication

Mỗi alert nên có `dedup_key`.

Format đề xuất:

```text
{alert_type}:{location_id}:{zone_id}:{primary_object_or_device}:{time_window}
```

Ví dụ:

```text
UNAUTHORIZED_ENTRY:warehouse_a:forbidden_01:track_12:202607300915
```

Quy ước:

- Vùng cấm: không tạo lại alert cho cùng `track_id` trong `dedup_window_seconds`, mặc định 60 giây.
- Tụ tập: không tạo lại alert cho cùng zone trong 60 giây nếu số người vẫn còn trên ngưỡng.
- Device offline: không tạo lại alert cho cùng device trong 5 phút.

Lý do:

- AI chạy theo frame nên cùng một người có thể sinh nhiều event.
- Nếu không dedup, dashboard sẽ bị spam alert.
- `dedup_key` giúp retry request an toàn hơn.

### 8.3. Official Alert Contract

```http
POST /api/v1/alerts
Authorization: Bearer <service_token>
Content-Type: application/json
```

Request:

```json
{
  "alert_id": "550e8400-e29b-41d4-a716-446655440601",
  "alert_type": "CAMERA_SENSOR_CORRELATED_RISK",
  "risk_level": "CRITICAL",
  "status": "NEW",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "title": "Phát hiện xâm nhập vùng cấm kèm tín hiệu cửa mở",
  "message": "Camera phát hiện người trong vùng cấm, đồng thời cảm biến cửa báo trạng thái OPEN.",
  "timestamp": "2026-07-30T09:15:22Z",
  "dedup_key": "CAMERA_SENSOR_CORRELATED_RISK:550e8400-e29b-41d4-a716-446655440002:550e8400-e29b-41d4-a716-446655440010:track_12:202607300915",
  "sources": [
    {
      "source_type": "AI_EVENT",
      "event_id": "550e8400-e29b-41d4-a716-446655440101"
    },
    {
      "source_type": "IOT_EVENT",
      "event_id": "550e8400-e29b-41d4-a716-446655440501"
    }
  ],
  "evidence_ids": [
    "550e8400-e29b-41d4-a716-446655440201"
  ],
  "metadata": {
    "camera_id": "550e8400-e29b-41d4-a716-446655440001",
    "device_id": "550e8400-e29b-41d4-a716-446655440301",
    "track_ids": [12],
    "risk_score": 95
  }
}
```

Response `201`:

```json
{
  "alert_id": "550e8400-e29b-41d4-a716-446655440601",
  "status": "NEW",
  "created_at": "2026-07-30T09:15:23Z"
}
```

Nếu trùng `dedup_key`, trả `409`:

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "Duplicated alert in deduplication window",
    "details": [
      {
        "field": "dedup_key",
        "issue": "already_exists"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440888",
    "timestamp": "2026-07-30T09:15:23Z"
  }
}
```

Lý do cấu trúc alert:

- `sources` lưu nguồn gốc alert để trace lại event camera và sensor.
- `evidence_ids` tách khỏi alert để một alert có thể có nhiều ảnh/clip.
- `metadata` cho phép lưu thông tin phụ mà không cần sửa schema liên tục trong prototype.
- `risk_level` để dashboard ưu tiên hiển thị.
- `risk_score` tùy chọn, phù hợp nếu sau này cần tính điểm rủi ro chi tiết.

## 9. Backend API Contract Cho Dashboard

### 9.1. Camera

Lấy danh sách camera:

```http
GET /api/v1/cameras?location_id={location_id}&status=ONLINE
Authorization: Bearer <token>
```

Response:

```json
{
  "data": [
    {
      "camera_id": "550e8400-e29b-41d4-a716-446655440001",
      "name": "Camera kho A",
      "location_id": "550e8400-e29b-41d4-a716-446655440002",
      "stream_url": "/api/v1/cameras/550e8400-e29b-41d4-a716-446655440001/stream",
      "status": "ONLINE",
      "last_seen_at": "2026-07-30T09:15:20Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

Tạo camera:

```http
POST /api/v1/cameras
Authorization: Bearer <admin_token>
Content-Type: application/json
```

Request:

```json
{
  "name": "Camera kho A",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "source_type": "RTSP",
  "source_url": "rtsp://user:password@192.168.1.10:554/stream1",
  "frame_width": 1280,
  "frame_height": 720,
  "is_enabled": true
}
```

### 9.2. Zone

```http
GET /api/v1/cameras/{camera_id}/zones
POST /api/v1/cameras/{camera_id}/zones
PUT /api/v1/zones/{zone_id}
DELETE /api/v1/zones/{zone_id}
```

Request tạo zone:

```json
{
  "name": "Vùng hạn chế trước cửa",
  "zone_type": "RESTRICTED",
  "frame_width": 1280,
  "frame_height": 720,
  "points": [
    { "x": 300, "y": 250 },
    { "x": 800, "y": 250 },
    { "x": 850, "y": 650 },
    { "x": 280, "y": 650 }
  ],
  "rules": {
    "loitering_duration_seconds": 10,
    "crowding_min_people": 3,
    "crowding_duration_seconds": 5
  }
}
```

Lý do zone nằm dưới camera:

- Mỗi camera có góc nhìn và tọa độ riêng.
- Cùng một khu vực vật lý có thể cần nhiều polygon khác nhau trên từng camera.

### 9.3. Sensor / Device

```http
GET /api/v1/devices
POST /api/v1/devices
GET /api/v1/devices/{device_id}
PATCH /api/v1/devices/{device_id}
```

Response:

```json
{
  "data": [
    {
      "device_id": "550e8400-e29b-41d4-a716-446655440301",
      "name": "Door Sensor kho A",
      "device_type": "SENSOR",
      "sensor_type": "DOOR",
      "location_id": "550e8400-e29b-41d4-a716-446655440002",
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "status": "ONLINE",
      "last_seen_at": "2026-07-30T09:15:20Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

### 9.4. Alert

Lấy danh sách alert:

```http
GET /api/v1/alerts?status=NEW&risk_level=HIGH&from=2026-07-30T00:00:00Z&to=2026-07-30T23:59:59Z&page=1&page_size=20&sort=-timestamp
Authorization: Bearer <token>
```

Response:

```json
{
  "data": [
    {
      "alert_id": "550e8400-e29b-41d4-a716-446655440601",
      "alert_type": "CAMERA_SENSOR_CORRELATED_RISK",
      "risk_level": "CRITICAL",
      "status": "NEW",
      "title": "Phát hiện xâm nhập vùng cấm kèm tín hiệu cửa mở",
      "message": "Camera phát hiện người trong vùng cấm, đồng thời cảm biến cửa báo trạng thái OPEN.",
      "location_id": "550e8400-e29b-41d4-a716-446655440002",
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "timestamp": "2026-07-30T09:15:22Z",
      "evidence_ids": [
        "550e8400-e29b-41d4-a716-446655440201"
      ],
      "created_at": "2026-07-30T09:15:23Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

Cập nhật trạng thái alert:

```http
PATCH /api/v1/alerts/{alert_id}
Authorization: Bearer <operator_token>
Content-Type: application/json
```

Request:

```json
{
  "status": "ACKNOWLEDGED",
  "note": "Nhân viên bảo vệ đã kiểm tra camera.",
  "updated_by": "550e8400-e29b-41d4-a716-446655440701"
}
```

Lý do dùng `PATCH`:

- Chỉ cập nhật một phần resource, vì alert có nhiều field không nên gửi lại toàn bộ.
- Phù hợp với thao tác của dashboard như đổi status, thêm note.

### 9.5. Evidence

```http
GET /api/v1/evidence/{evidence_id}
GET /api/v1/evidence/{evidence_id}/image
GET /api/v1/evidence/{evidence_id}/thumbnail
```

Metadata response:

```json
{
  "evidence_id": "550e8400-e29b-41d4-a716-446655440201",
  "evidence_type": "IMAGE",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "captured_at": "2026-07-30T09:15:22Z",
  "image_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440201/image",
  "thumbnail_url": "/api/v1/evidence/550e8400-e29b-41d4-a716-446655440201/thumbnail",
  "created_at": "2026-07-30T09:15:23Z"
}
```

Lý do tách evidence:

- Database chỉ lưu metadata, ảnh/clip lưu filesystem hoặc object storage.
- Dashboard có thể load thumbnail trước, ảnh đầy đủ sau.
- Một alert có thể có nhiều bằng chứng.

## 10. Realtime Contract Cho Dashboard

Dùng WebSocket hoặc SignalR. Nếu backend là .NET 8 thì khuyến nghị SignalR.

Endpoint:

```text
/realtime/alerts
```

Client subscribe theo:

```json
{
  "action": "SUBSCRIBE",
  "channels": [
    "alerts",
    "device_status",
    "camera_status"
  ],
  "filters": {
    "location_ids": [
      "550e8400-e29b-41d4-a716-446655440002"
    ]
  }
}
```

Message `ALERT_CREATED`:

```json
{
  "type": "ALERT_CREATED",
  "timestamp": "2026-07-30T09:15:23Z",
  "data": {
    "alert_id": "550e8400-e29b-41d4-a716-446655440601",
    "alert_type": "CAMERA_SENSOR_CORRELATED_RISK",
    "risk_level": "CRITICAL",
    "status": "NEW",
    "title": "Phát hiện xâm nhập vùng cấm kèm tín hiệu cửa mở",
    "location_id": "550e8400-e29b-41d4-a716-446655440002",
    "zone_id": "550e8400-e29b-41d4-a716-446655440010",
    "timestamp": "2026-07-30T09:15:22Z",
    "evidence_ids": [
      "550e8400-e29b-41d4-a716-446655440201"
    ]
  }
}
```

Message `DEVICE_STATUS_CHANGED`:

```json
{
  "type": "DEVICE_STATUS_CHANGED",
  "timestamp": "2026-07-30T09:15:30Z",
  "data": {
    "device_id": "550e8400-e29b-41d4-a716-446655440301",
    "status": "OFFLINE",
    "last_seen_at": "2026-07-30T09:10:30Z"
  }
}
```

Lý do dùng realtime riêng:

- Dashboard cần nhận cảnh báo gần thời gian thực, không nên polling liên tục.
- REST dùng cho truy vấn lịch sử, realtime dùng cho sự kiện mới.
- SignalR phù hợp nếu backend .NET vì có sẵn reconnect, group, auth và typed hub.

## 11. Message Queue Contract Nội Bộ

Nếu hệ thống dùng message queue, đề xuất topic:

```text
ai.events
iot.readings
iot.events
alerts.created
device.status.changed
camera.status.changed
```

Envelope chung:

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440801",
  "message_type": "AI_EVENT_CREATED",
  "schema_version": "1.0",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440777",
  "timestamp": "2026-07-30T09:15:22Z",
  "producer": "ai-service",
  "data": {}
}
```

Lý do dùng envelope:

- Mỗi message đều có metadata giống nhau.
- `schema_version` giúp nâng cấp format message an toàn.
- `producer` và `correlation_id` giúp trace.

Trong prototype chưa bắt buộc dùng message queue. Có thể dùng REST trước, sau đó thay body `data` thành message payload khi cần scale.

## 12. Health Check Contract

Mỗi service nên có endpoint:

```http
GET /health
GET /ready
```

Response:

```json
{
  "service": "ai-service",
  "status": "OK",
  "version": "1.0.0",
  "timestamp": "2026-07-30T09:15:22Z",
  "dependencies": {
    "model": "OK",
    "database": "OK",
    "mqtt": "OK"
  }
}
```

Quy ước:

- `/health`: service còn sống hay không.
- `/ready`: service sẵn sàng nhận traffic hay chưa.

Lý do:

- Docker Compose, Kubernetes hoặc script demo có thể kiểm tra service.
- Dễ debug nhanh khi demo end-to-end.

## 13. Data Ownership

| Dữ liệu | Module sở hữu chính | Module đọc |
| --- | --- | --- |
| Camera config | Backend API | Camera/Video Service, AI Service, Dashboard |
| Zone config | Backend API | AI Service, Dashboard |
| AI Event | AI Service tạo, Backend lưu | Event & Risk Engine, Dashboard |
| Sensor Reading | IoT Service tạo, Backend lưu | Event & Risk Engine, Dashboard |
| Sensor Event | IoT Service tạo, Backend lưu | Event & Risk Engine |
| Alert | Event & Risk Engine tạo, Backend lưu | Dashboard |
| Evidence | AI Service tạo file, Backend quản lý metadata/storage | Dashboard |
| User | Backend API | Dashboard |

Lý do:

- Mỗi loại dữ liệu có một module chịu trách nhiệm chính.
- Tránh tình trạng nhiều module cùng sửa một resource và gây xung đột.

## 14. Luồng End-To-End Mẫu

### 14.1. Xâm Nhập Vùng Cấm Kèm Cảm Biến Cửa

```text
1. Door sensor gửi MQTT reading: DOOR = OPEN.
2. IoT Service chuẩn hóa reading thành Sensor Event: DOOR_OPENED.
3. Camera đọc frame từ RTSP.
4. AI Service detect PERSON bằng YOLO.
5. ByteTrack gán track_id = 12.
6. AI Service tính foot_point nằm trong zone FORBIDDEN.
7. AI Service tạo AI Event: FORBIDDEN_ZONE_INTRUSION.
8. Event & Risk Engine thấy AI Event và Sensor Event cùng zone trong 10 giây.
9. Engine tạo Official Alert: CAMERA_SENSOR_CORRELATED_RISK, risk_level = CRITICAL.
10. Backend lưu alert và evidence.
11. Backend đẩy realtime ALERT_CREATED cho Dashboard.
12. Operator mở alert, xem ảnh bằng chứng và ACKNOWLEDGED.
```

### 14.2. Đứng Lâu Vùng Hạn Chế

```text
1. AI Service detect PERSON trong RESTRICTED zone.
2. ByteTrack giữ cùng track_id qua nhiều frame.
3. AI Service tính dwell_time_seconds.
4. Nếu dwell_time_seconds >= 10 và di chuyển nhỏ hơn ngưỡng, tạo AI Event: RESTRICTED_ZONE_LOITERING.
5. Event & Risk Engine tạo Alert: LOITERING, risk_level = MEDIUM.
6. Backend lưu alert, Dashboard nhận realtime.
```

### 14.3. Tụ Tập Vùng Hạn Chế

```text
1. AI Service đếm số PERSON có foot_point trong RESTRICTED zone.
2. Nếu count >= 3 liên tục trong 5 giây, tạo AI Event: RESTRICTED_ZONE_CROWDING.
3. Event & Risk Engine tạo Alert: CROWDING, risk_level = HIGH.
4. Backend lưu alert, Dashboard hiển thị cảnh báo.
```

## 15. Contract Tối Thiểu Để Các Nhóm Chia Việc

### Nhóm AI/Camera Cần Làm

- Đọc RTSP hoặc video file.
- Chạy YOLO pretrained để detect `PERSON`.
- Chạy ByteTrack để lấy `track_id`.
- Load zone config theo `camera_id`.
- Tạo AI Event theo contract `/api/v1/ai/events`.
- Lưu ảnh bằng chứng khi có event.

Output tối thiểu:

```json
{
  "event_id": "<uuid>",
  "event_source": "AI",
  "event_type": "FORBIDDEN_ZONE_INTRUSION",
  "camera_id": "<uuid>",
  "location_id": "<uuid>",
  "zone_id": "<uuid>",
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
      }
    }
  ]
}
```

### Nhóm IoT Cần Làm

- Nhận MQTT hoặc HTTP reading.
- Chuẩn hóa reading theo contract.
- Theo dõi `ONLINE`/`OFFLINE`.
- Tạo Sensor Event khi có bất thường.

Output tối thiểu:

```json
{
  "event_id": "<uuid>",
  "event_source": "IOT",
  "event_type": "DOOR_OPENED",
  "device_id": "<uuid>",
  "sensor_id": "<uuid>",
  "sensor_type": "DOOR",
  "location_id": "<uuid>",
  "zone_id": "<uuid>",
  "value": "OPEN",
  "timestamp": "2026-07-30T09:15:21Z"
}
```

### Nhóm Backend/Event Engine Cần Làm

- Nhận AI Event và Sensor Event.
- Lưu event vào database.
- Áp dụng rule và dedup.
- Tạo alert.
- Cung cấp REST API cho dashboard.
- Đẩy realtime alert.

Output tối thiểu:

```json
{
  "alert_id": "<uuid>",
  "alert_type": "UNAUTHORIZED_ENTRY",
  "risk_level": "HIGH",
  "status": "NEW",
  "location_id": "<uuid>",
  "zone_id": "<uuid>",
  "title": "Phát hiện người vào vùng cấm",
  "timestamp": "2026-07-30T09:15:22Z",
  "sources": [
    {
      "source_type": "AI_EVENT",
      "event_id": "<uuid>"
    }
  ]
}
```

### Nhóm Frontend Cần Làm

- Gọi REST API lấy camera, device, alert, evidence.
- Kết nối realtime `/realtime/alerts`.
- Hiển thị alert theo `risk_level`, `status`, `timestamp`.
- Cập nhật status alert bằng `PATCH /api/v1/alerts/{alert_id}`.

## 16. Checklist Thống Nhất Trước Khi Code

- Tất cả service dùng UTC ISO 8601.
- Tất cả resource ID chính dùng UUID.
- Tất cả JSON field dùng `snake_case`.
- Tất cả enum dùng `UPPER_SNAKE_CASE`.
- Tất cả API bắt đầu bằng `/api/v1`.
- AI Event và Sensor Event đều có `event_id`, `event_type`, `timestamp`, `location_id`.
- Event liên quan camera có `camera_id`.
- Event liên quan sensor có `device_id` và `sensor_id`.
- Alert có `alert_id`, `alert_type`, `risk_level`, `status`, `sources`.
- Ảnh/clip bằng chứng không lưu trực tiếp trong database.
- Realtime chỉ đẩy event mới hoặc status thay đổi, lịch sử lấy bằng REST API.
- Mỗi service có `/health` và `/ready`.
- Mỗi request quan trọng có `X-Correlation-ID`.

## 17. Nguyên Tắc Thực Hiện Prototype

- Ưu tiên REST trước message queue để demo nhanh.
- Ưu tiên YOLO pretrained, chưa cần train model riêng nếu chỉ detect người/xe.
- Ưu tiên rule rõ ràng, có ngưỡng cấu hình được.
- Ưu tiên lưu metadata và evidence ảnh khi có sự kiện, không lưu toàn bộ video vào database.
- Ưu tiên làm end-to-end sớm: camera -> AI event -> alert -> dashboard.
- Sau khi pipeline chạy được, mới tối ưu FPS, GPU, queue, cache và scale nhiều camera.

## 18. Cấu Trúc Thư Mục Đề Xuất

```text
project-root/
  docs/
    API_CONTRACT_AND_CONVENTIONS.md
    ARCHITECTURE.md
    TEST_CASES.md
  services/
    ai-service/
    camera-video-service/
    iot-service/
    backend-api/
  web-dashboard/
  docker-compose.yml
  README.md
```

Lý do:

- `docs` giữ tài liệu chung cho cả team.
- `services` tách từng module để mỗi nhóm làm độc lập.
- `docker-compose.yml` ở root giúp chạy demo toàn hệ thống bằng một lệnh.
- `README.md` ở root dùng cho hướng dẫn cài đặt và demo nhanh.
