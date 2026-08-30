# Kế hoạch triển khai Camera Service và AI Service

Tài liệu này mô tả kế hoạch chi tiết để triển khai module Camera Service và AI Service trong hệ thống AI-IoT cảnh báo bất thường. Module này được thiết kế chạy độc lập, có unit test và contract test trước khi tích hợp với Backend API, Event & Risk Engine.

## 1. Phạm vi phụ trách

Module Camera/AI chịu trách nhiệm xử lý toàn bộ pipeline hình ảnh:

```text
Camera / Video File / Webcam
    -> Camera Service
    -> Frame + Metadata
    -> AI Service
    -> YOLO Detection
    -> ByteTrack Tracking
    -> Zone Rule Evaluation
    -> AI Event + Evidence
    -> Backend API / Event & Risk Engine
```

Nguyên tắc quan trọng:

- Camera Service không chạy YOLO.
- AI Service không trực tiếp tạo Alert.
- AI Service chỉ tạo AI Event.
- Event & Risk Engine là nơi tạo Alert chính thức.
- Output của AI Service phải đúng contract đã thống nhất với Backend/Risk Engine.

## 2. Mục tiêu hoàn thành

Module được xem là hoàn thành khi đạt được các mục tiêu sau:

- Đọc được video file, webcam hoặc RTSP camera.
- Sinh frame metadata đúng contract.
- Chạy YOLO để detect tối thiểu đối tượng `PERSON`.
- Dùng ByteTrack để gán `track_id` cho object qua nhiều frame.
- Tính được `foot_point` từ bounding box.
- Kiểm tra được `foot_point` có nằm trong zone polygon hay không.
- Hỗ trợ các rule bất thường chính: xâm nhập vùng cấm, đứng lâu trong vùng hạn chế, tụ tập đông người.
- Có cơ chế chống gửi trùng AI Event.
- Tạo được evidence image khi rule được kích hoạt.
- Gửi AI Event đúng contract sang Backend API.
- Có unit test cho các logic cốt lõi.
- Có contract test cho output gửi sang Risk Engine.
- Có integration test với video/image mẫu và fake Backend.

## 3. Phân chia trách nhiệm

### 3.1. Camera Service

Camera Service chịu trách nhiệm với nguồn hình ảnh đầu vào.


| Nhóm việc           | Mô tả                                                                                    |
| ------------------- | ---------------------------------------------------------------------------------------- |
| Quản lý nguồn video | Hỗ trợ RTSP, webcam và video file                                                        |
| Đọc frame           | Dùng OpenCV hoặc thư viện tương đương để lấy frame                                       |
| Sampling FPS        | Giảm số frame gửi sang AI, ví dụ nguồn 30 FPS nhưng AI chỉ xử lý 10 FPS                  |
| Sinh metadata       | Gắn `camera_id`, `location_id`, `session_id`, `frame_id`, `timestamp`, `sequence_number` |
| Theo dõi trạng thái | Quản lý `ONLINE`, `OFFLINE`, `RECONNECTING`                                              |
| Reconnect           | Thử kết nối lại khi RTSP lỗi hoặc timeout                                                |
| Session lifecycle   | Tạo `session_id` mới sau reconnect để AI reset tracking state                            |
| Gửi frame           | Gửi frame + metadata sang AI Service qua API hoặc gọi pipeline nội bộ trong prototype    |


Camera Service không làm:

- Không chạy YOLO.
- Không chạy tracking.
- Không kiểm tra zone rule.
- Không tạo AI Event.
- Không tạo Alert.

### 3.2. AI Service

AI Service chịu trách nhiệm phân tích frame và sinh AI Event.


| Nhóm việc          | Mô tả                                               |
| ------------------ | --------------------------------------------------- |
| Validate input     | Kiểm tra frame và metadata                          |
| Preprocess         | Resize, normalize, convert format nếu cần           |
| YOLO detection     | Detect `PERSON`, có thể mở rộng `CAR`, `MOTORBIKE`  |
| Filter detection   | Lọc class và confidence threshold                   |
| ByteTrack tracking | Gán `track_id` theo từng `camera_id` + `session_id` |
| Foot point         | Tính điểm chân từ bbox                              |
| Zone matching      | Kiểm tra object nằm trong polygon zone              |
| Rule evaluation    | Xử lý intrusion, loitering, crowding                |
| Dedup              | Chống gửi lặp event theo cửa sổ thời gian           |
| Evidence           | Lưu ảnh bằng chứng khi có event                     |
| Backend client     | Gửi AI Event sang Backend API                       |


AI Service không làm:

- Không quản lý user.
- Không quản lý thiết bị IoT.
- Không tính risk đa nguồn.
- Không tạo hoặc đóng Alert.
- Không lưu toàn bộ camera frame vào database.

## 4. Contract cần thống nhất

Các contract nên được định nghĩa bằng Markdown, JSON example và schema code, ví dụ Pydantic model nếu dùng Python.

File contract đề xuất:

```text
docs/CAMERA_AI_EVENT_CONTRACT.md
```

Các contract tối thiểu:

- Frame metadata từ Camera Service sang AI Service.
- Zone configuration.
- Frame analysis result phục vụ debug.
- AI Event output gửi sang Backend/Risk Engine.
- Evidence metadata.
- Error response.
- Health check.

### 4.1. Frame metadata

Camera Service gửi frame kèm metadata sang AI Service.

Endpoint:

```http
POST /api/v1/ai/frames
Authorization: Bearer <service_token>
Content-Type: multipart/form-data
X-Correlation-ID: <uuid>
```

Metadata mẫu:

```json
{
  "frame_id": "cam01-0000018280",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "source_type": "RTSP",
  "timestamp": "2026-07-30T09:15:22Z",
  "sequence_number": 18280,
  "source_width": 1920,
  "source_height": 1080,
  "frame_width": 1280,
  "frame_height": 720,
  "target_fps": 10,
  "encoding": "JPEG"
}
```

Response:

```http
HTTP/1.1 202 Accepted
```

```json
{
  "frame_id": "cam01-0000018280",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "status": "ACCEPTED",
  "received_at": "2026-07-30T09:15:22.180Z",
  "correlation_id": "7908fa63-a43d-4d72-a75d-c87262bd2382"
}
```

### 4.2. Zone configuration

Zone là polygon được cấu hình theo từng camera. AI Service không tự phát hiện zone.

```json
{
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "frame_width": 1280,
  "frame_height": 720,
  "zones": [
    {
      "zone_id": "550e8400-e29b-41d4-a716-446655440010",
      "name": "Vung cam cua kho",
      "zone_type": "FORBIDDEN",
      "enabled": true,
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
      "name": "Vung han che sanh cho",
      "zone_type": "RESTRICTED",
      "enabled": true,
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

Lưu ý:

- `frame_width` và `frame_height` là kích thước frame tham chiếu khi vẽ polygon.
- Khi AI resize frame, cần scale polygon tương ứng hoặc đảm bảo dùng cùng hệ tọa độ.
- Chỉ kiểm tra zone có `enabled = true`.

### 4.3. AI Event output

AI Event là output chính gửi sang Backend/Risk Engine.

Endpoint cần chốt với Backend:

```http
POST /api/v1/events
```

Nếu nhóm Backend chọn endpoint rõ nguồn hơn, có thể dùng:

```http
POST /api/v1/ai/events
```

Khuyến nghị: chốt một endpoint chính, tránh để hai contract cùng tồn tại mà không rõ service nào dùng.

AI Event mẫu:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440101",
  "source": "AI",
  "event_type": "FORBIDDEN_ZONE_INTRUSION",
  "camera_id": "550e8400-e29b-41d4-a716-446655440001",
  "location_id": "550e8400-e29b-41d4-a716-446655440002",
  "session_id": "550e8400-e29b-41d4-a716-446655440099",
  "zone_id": "550e8400-e29b-41d4-a716-446655440010",
  "timestamp": "2026-07-30T09:15:22Z",
  "confidence": 0.92,
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
    "storage_key": "evidence/2026/08/event-101/image.jpg",
    "mime_type": "image/jpeg",
    "captured_at": "2026-07-30T09:15:22Z"
  },
  "metadata": {
    "model_name": "yolo11n",
    "model_version": "pretrained-coco",
    "tracker": "bytetrack",
    "rule_name": "forbidden_zone_intrusion_v1"
  }
}
```

Field bắt buộc tối thiểu:


| Field         | Bắt buộc              | Ghi chú                                     |
| ------------- | --------------------- | ------------------------------------------- |
| `event_id`    | Có                    | Dùng để idempotency khi retry               |
| `source`      | Có                    | Luôn là `AI`                                |
| `event_type`  | Có                    | Enum đã thống nhất                          |
| `camera_id`   | Có                    | Camera sinh event                           |
| `location_id` | Có                    | Khu vực vật lý dùng để Risk Engine hợp nhất |
| `session_id`  | Có                    | Phiên xử lý camera                          |
| `zone_id`     | Có với zone event     | Zone bị vi phạm                             |
| `timestamp`   | Có                    | ISO 8601 UTC                                |
| `confidence`  | Có                    | Confidence đại diện cho event               |
| `objects`     | Có                    | Danh sách object liên quan                  |
| `evidence`    | Có nếu tạo bằng chứng | Metadata ảnh/video                          |
| `metadata`    | Có                    | Model, tracker, rule                        |


### 4.4. Event type

Các event type cần hỗ trợ:


| Event type                   | Ý nghĩa                                            |
| ---------------------------- | -------------------------------------------------- |
| `FORBIDDEN_ZONE_INTRUSION`   | Người xâm nhập vùng cấm                            |
| `RESTRICTED_ZONE_LONG_DWELL` | Người đứng hoặc lưu lại quá lâu trong vùng hạn chế |
| `RESTRICTED_ZONE_CROWDING`   | Số người trong vùng hạn chế vượt ngưỡng đủ lâu     |


Nếu tài liệu cũ dùng `RESTRICTED_ZONE_LOITERING`, cần chốt lại với Backend. Khuyến nghị chọn một tên duy nhất:

```text
RESTRICTED_ZONE_LONG_DWELL
```

hoặc

```text
RESTRICTED_ZONE_LOITERING
```

Không nên dùng lẫn cả hai.

## 5. Cấu trúc thư mục đề xuất

Nếu module viết bằng Python, cấu trúc đề xuất:

```text
camera_ai_service/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── contracts/
│   │   ├── frame_metadata.py
│   │   ├── zone_config.py
│   │   └── ai_event.py
│   ├── camera/
│   │   ├── camera_source.py
│   │   ├── video_file_source.py
│   │   ├── webcam_source.py
│   │   ├── rtsp_source.py
│   │   └── frame_sampler.py
│   ├── ai/
│   │   ├── yolo_detector.py
│   │   ├── tracker.py
│   │   ├── foot_point.py
│   │   ├── zone_matcher.py
│   │   └── pipeline.py
│   ├── rules/
│   │   ├── intrusion_rule.py
│   │   ├── loitering_rule.py
│   │   ├── crowding_rule.py
│   │   └── dedup.py
│   ├── evidence/
│   │   ├── evidence_writer.py
│   │   └── image_annotator.py
│   └── clients/
│       └── backend_client.py
├── tests/
│   ├── unit/
│   ├── contract/
│   └── integration/
├── models/
│   └── yolo11n.pt
└── README.md
```

## 6. Kế hoạch thực hiện chi tiết

### Giai đoạn 1. Chốt contract và schema

Mục tiêu: đảm bảo output của module không lệch với Backend/Risk Engine.

Việc cần làm:

- Chốt endpoint nhận AI Event.
- Chốt JSON naming: khuyến nghị dùng `snake_case`.
- Chốt enum `event_type`.
- Chốt cách lấy `location_id`.
- Chốt evidence upload do AI tự lưu hay Backend cấp signed URL.
- Tạo schema cho `FrameMetadata`, `ZoneConfig`, `AIEvent`, `EvidenceMetadata`.
- Tạo JSON example hợp lệ cho từng event type.

Output:

- File contract Markdown.
- Schema code.
- Bộ JSON sample.
- Contract test đầu tiên.

Unit/contract test:


| Test                                | Kỳ vọng                      |
| ----------------------------------- | ---------------------------- |
| AI Event thiếu `event_id`           | Không hợp lệ                 |
| AI Event thiếu `location_id`        | Không hợp lệ                 |
| `event_type` ngoài enum             | Không hợp lệ                 |
| `timestamp` không phải UTC ISO 8601 | Không hợp lệ                 |
| Evidence thiếu `storage_key`        | Không hợp lệ nếu có evidence |


### Giai đoạn 2. Xây dựng Camera Service skeleton

Mục tiêu: đọc được nguồn video và tạo frame metadata ổn định.

Việc cần làm:

- Tạo abstract interface cho camera source.
- Implement `VideoFileSource`.
- Implement `WebcamSource`.
- Implement `RtspSource` sau khi video file ổn định.
- Sinh `session_id` khi bắt đầu đọc source.
- Sinh `frame_id` theo `camera_id` và `sequence_number`.
- Gắn timestamp UTC cho từng frame.
- Implement FPS sampling.
- Theo dõi trạng thái source.

Unit test:


| Test                         | Kỳ vọng                               |
| ---------------------------- | ------------------------------------- |
| Tạo metadata frame           | Có đủ field bắt buộc                  |
| `sequence_number`            | Tăng đúng thứ tự                      |
| Sampling 30 FPS xuống 10 FPS | Chỉ chọn đúng frame cần xử lý         |
| Video hết frame              | Trả trạng thái kết thúc hợp lệ        |
| Source lỗi                   | Chuyển status sang lỗi hoặc reconnect |
| Reconnect thành công         | Tạo `session_id` mới                  |


### Giai đoạn 3. Xây dựng YOLO detection

Mục tiêu: chuẩn hóa output detection để các bước sau không phụ thuộc trực tiếp vào thư viện YOLO.

Việc cần làm:

- Load model `yolo11n.pt`.
- Detect trên ảnh đơn.
- Lọc class cần quan tâm, tối thiểu `PERSON`.
- Lọc theo confidence threshold.
- Chuẩn hóa bbox về format `x1`, `y1`, `x2`, `y2`.
- Trả output detection nội bộ.

Detection output nội bộ:

```json
{
  "object_type": "PERSON",
  "confidence": 0.92,
  "bbox": {
    "x1": 120,
    "y1": 80,
    "x2": 260,
    "y2": 420
  }
}
```

Unit test:


| Test                               | Kỳ vọng                       |
| ---------------------------------- | ----------------------------- |
| Mock YOLO trả PERSON               | Detection được giữ lại        |
| Mock YOLO trả class không quan tâm | Detection bị loại             |
| Confidence thấp hơn threshold      | Detection bị loại             |
| Bbox sai format                    | Bị reject hoặc normalize đúng |
| Frame rỗng                         | Không làm crash pipeline      |


Lưu ý: unit test không nên phụ thuộc model thật. Model thật chỉ dùng trong integration test hoặc notebook kiểm tra.

### Giai đoạn 4. Tích hợp ByteTrack

Mục tiêu: duy trì `track_id` ổn định qua nhiều frame.

Việc cần làm:

- Tạo wrapper cho tracker.
- Duy trì tracking state theo `camera_id + session_id`.
- Reset tracking state khi `session_id` đổi.
- Không dùng chung state giữa hai camera.
- Kiểm tra thứ tự frame theo `sequence_number`.

Tracking output nội bộ:

```json
{
  "track_id": 12,
  "object_type": "PERSON",
  "confidence": 0.92,
  "bbox": {
    "x1": 120,
    "y1": 80,
    "x2": 260,
    "y2": 420
  }
}
```

Unit test:


| Test                               | Kỳ vọng                                        |
| ---------------------------------- | ---------------------------------------------- |
| Cùng object qua nhiều frame        | Giữ `track_id` ổn định                         |
| `session_id` mới                   | Reset tracking state                           |
| Hai camera khác nhau               | Không dùng chung state                         |
| Frame sai thứ tự                   | Reject hoặc log warning                        |
| Không có detection trong vài frame | Tracker xử lý được hoặc mất track có kiểm soát |


### Giai đoạn 5. Foot point và zone matcher

Mục tiêu: xác định vị trí đứng của người trong zone.

Foot point:

```text
foot_point.x = (x1 + x2) / 2
foot_point.y = y2
```

Việc cần làm:

- Implement hàm tính foot point.
- Implement point-in-polygon.
- Hỗ trợ nhiều zone trên một camera.
- Chỉ xét zone `enabled = true`.
- Xử lý scale polygon nếu frame xử lý khác kích thước frame config.

Unit test:


| Test                        | Kỳ vọng                    |
| --------------------------- | -------------------------- |
| Bbox `(100, 50, 200, 300)`  | Foot point `(150, 300)`    |
| Point nằm trong polygon     | Trả `true`                 |
| Point nằm ngoài polygon     | Trả `false`                |
| Point nằm trên cạnh polygon | Có quy tắc rõ ràng         |
| Zone disabled               | Không trigger              |
| Polygon ít hơn 3 điểm       | Reject config              |
| Frame resize                | Scale zone hoặc point đúng |


### Giai đoạn 6. Rule engine cho AI Service

Mục tiêu: sinh AI Event khi thỏa điều kiện bất thường.

#### 6.1. Rule xâm nhập vùng cấm

Điều kiện:

```text
zone_type = FORBIDDEN
foot_point nằm trong polygon
dwell_time_seconds >= forbidden_min_duration_seconds
```

Output:

```text
FORBIDDEN_ZONE_INTRUSION
```

Unit test:


| Test                                  | Kỳ vọng         |
| ------------------------------------- | --------------- |
| Người vào forbidden zone đủ thời gian | Tạo event       |
| Người lướt qua quá nhanh              | Không tạo event |
| Object không phải PERSON              | Không tạo event |
| Zone disabled                         | Không tạo event |


#### 6.2. Rule đứng lâu trong vùng hạn chế

Điều kiện:

```text
zone_type = RESTRICTED
foot_point nằm trong polygon
dwell_time_seconds >= loitering_duration_seconds
movement_distance_pixels <= loitering_movement_threshold_pixels
```

Output:

```text
RESTRICTED_ZONE_LONG_DWELL
```

Unit test:


| Test                               | Kỳ vọng                                             |
| ---------------------------------- | --------------------------------------------------- |
| Một track đứng lâu và ít di chuyển | Tạo event                                           |
| Một track đứng chưa đủ lâu         | Không tạo event                                     |
| Một track di chuyển nhiều          | Không tạo event                                     |
| Track rời zone rồi vào lại         | Reset hoặc tính lại dwell time theo quy tắc đã chốt |


#### 6.3. Rule tụ tập đông người

Điều kiện:

```text
zone_type = RESTRICTED
person_count >= crowding_min_people
duration_seconds >= crowding_duration_seconds
```

Output:

```text
RESTRICTED_ZONE_CROWDING
```

Unit test:


| Test                        | Kỳ vọng                                 |
| --------------------------- | --------------------------------------- |
| Đủ số người và đủ thời gian | Tạo event                               |
| Đủ số người nhưng quá ngắn  | Không tạo event                         |
| Thiếu số người              | Không tạo event                         |
| Người vào ra liên tục       | Tính duration ổn định, không spam event |


### Giai đoạn 7. Dedup AI Event

Mục tiêu: AI Service không gửi lặp cùng một event qua từng frame.

Dedup key đề xuất:

```text
event_type:camera_id:zone_id:track_id
```

Với crowding có thể dùng:

```text
event_type:camera_id:zone_id
```

Quy tắc:

- Event đầu tiên được gửi.
- Event giống nhau trong `dedup_window_seconds` bị chặn.
- Event giống nhau sau khi hết cửa sổ dedup có thể được gửi lại.
- Camera khác hoặc zone khác không bị dedup nhầm.

Unit test:


| Test                       | Kỳ vọng                                      |
| -------------------------- | -------------------------------------------- |
| Event đầu tiên             | Được gửi                                     |
| Event giống trong 60 giây  | Bị chặn                                      |
| Event giống sau 60 giây    | Được gửi lại                                 |
| Cùng zone nhưng track khác | Có thể gửi event mới với intrusion/loitering |
| Camera khác                | Không bị dedup nhầm                          |
| Crowding cùng zone         | Không spam theo từng frame                   |


### Giai đoạn 8. Evidence

Mục tiêu: lưu bằng chứng khi có AI Event.

Prototype có thể lưu local trước, sau đó đổi sang MinIO.

Việc cần làm:

- Khi rule trigger, tạo event_id.
- Annotate frame với bbox, track_id và zone.
- Lưu ảnh evidence.
- Sinh `storage_key`.
- Gắn evidence metadata vào AI Event.

Evidence metadata:

```json
{
  "evidence_id": "550e8400-e29b-41d4-a716-446655440201",
  "storage_key": "evidence/2026/08/event-id/image.jpg",
  "mime_type": "image/jpeg",
  "captured_at": "2026-08-29T10:30:00Z"
}
```

Unit test:


| Test                         | Kỳ vọng               |
| ---------------------------- | --------------------- |
| Có event                     | Tạo evidence metadata |
| Không có event               | Không tạo evidence    |
| `storage_key`                | Đúng format           |
| Annotator không có detection | Không crash           |
| Evidence metadata            | Khớp `event_id`       |


### Giai đoạn 9. Backend client

Mục tiêu: gửi AI Event sang Backend an toàn và có thể retry.

Việc cần làm:

- Implement HTTP client gửi event.
- Timeout rõ ràng.
- Retry cho lỗi tạm thời.
- Không retry lỗi validation 400/422.
- Không tạo `event_id` mới khi retry.
- Log `correlation_id`.

Unit test:


| Test            | Kỳ vọng                  |
| --------------- | ------------------------ |
| Backend trả 202 | Đánh dấu gửi thành công  |
| Backend timeout | Retry có kiểm soát       |
| Backend trả 400 | Không retry              |
| Backend trả 500 | Retry                    |
| Retry           | Dùng lại cùng `event_id` |


### Giai đoạn 10. Integration test end-to-end nội bộ

Mục tiêu: kiểm tra toàn bộ module trước khi nối Risk Engine thật.

Pipeline test:

```text
Video/Image sample
    -> Fake Camera Source
    -> Detector hoặc Mock Detector
    -> Tracker
    -> Foot Point
    -> Zone Matcher
    -> Rule Engine
    -> Dedup
    -> Evidence Writer
    -> Fake Backend
```

Kỳ vọng:

- Có AI Event đúng loại khi tình huống bất thường xảy ra.
- Không tạo AI Event khi không vi phạm rule.
- Không spam duplicate event.
- Payload gửi sang fake Backend đúng contract.
- Evidence được tạo khi event được tạo.

## 7. Test strategy

### 7.1. Unit test

Unit test tập trung vào logic nhỏ, deterministic, không phụ thuộc camera thật, model thật hoặc Backend thật.

Ưu tiên test:

- Frame metadata generation.
- FPS sampling.
- Foot point calculation.
- Point in polygon.
- Zone matching.
- Rule evaluation.
- Dedup.
- Event schema validation.
- Backend retry logic.

### 7.2. Contract test

Contract test đảm bảo output gửi sang Backend/Risk Engine đúng format.

Các kiểm tra chính:

- AI Event có đủ field bắt buộc.
- `event_type` nằm trong enum.
- `timestamp` là ISO 8601 UTC.
- `location_id` không null.
- Event liên quan zone có `zone_id`.
- Event có object thì object có `track_id`, `bbox`, `foot_point`.
- Evidence nếu có thì có `evidence_id`, `storage_key`, `mime_type`.

### 7.3. Integration test

Integration test dùng video/image mẫu và fake Backend.

Không nên yêu cầu Backend/Risk Engine thật trong test của module Camera/AI. Module này phải chứng minh được output độc lập trước.

## 8. Cấu hình đề xuất

Các tham số nên nằm trong file config:

```yaml
camera:
  source_type: VIDEO_FILE
  source_url: ./data/videos/sample.mp4
  target_fps: 10
  frame_width: 1280
  frame_height: 720
  reconnect_retry_count: 3
  reconnect_interval_seconds: 5

ai:
  model_name: yolo11n
  model_path: ./models/yolo11n.pt
  confidence_threshold: 0.5
  object_classes:
    - PERSON

tracker:
  name: bytetrack

rules:
  forbidden_min_duration_seconds: 1
  loitering_duration_seconds: 10
  loitering_movement_threshold_pixels: 30
  crowding_min_people: 3
  crowding_duration_seconds: 5
  dedup_window_seconds: 60

backend:
  base_url: http://localhost:5000
  ai_event_endpoint: /api/v1/events
  timeout_seconds: 5
  retry_count: 3

evidence:
  storage_type: LOCAL
  local_dir: ./evidence
  image_format: jpg
```

## 9. Thứ tự triển khai khuyến nghị

Nên làm theo thứ tự sau:

```text
1. Contract schema
2. Video file source
3. Frame metadata
4. Foot point
5. Zone matcher
6. Rule engine bằng mocked detection
7. AI Event output
8. Dedup
9. Evidence
10. YOLO thật
11. ByteTrack thật
12. Backend client
13. Integration test end-to-end
14. RTSP reconnect và camera lifecycle
```

Lý do nên làm rule bằng mocked detection trước: phần khó nhất khi tích hợp hệ thống không phải là chạy YOLO, mà là tạo event đúng, sạch, không trùng và Risk Engine hiểu được. Khi rule và contract đã chắc, YOLO và ByteTrack chỉ là nguồn dữ liệu thật thay cho dữ liệu giả.

## 10. Kế hoạch theo tuần


| Tuần   | Mục tiêu                                                          | Đầu ra                                        |
| ------ | ----------------------------------------------------------------- | --------------------------------------------- |
| Tuần 1 | Chốt contract, tạo skeleton module, đọc video file, sinh metadata | Contract file, schema, video source chạy được |
| Tuần 2 | Làm foot point, zone matcher, rule engine bằng mocked detection   | Unit test cho zone và rule                    |
| Tuần 3 | Tích hợp YOLO, ByteTrack, evidence, dedup                         | AI Event sinh từ video mẫu                    |
| Tuần 4 | Gửi event sang fake Backend, contract test, integration test      | Module sẵn sàng nối Backend/Risk Engine       |


## 11. Checklist đồng bộ với Backend/Risk Engine

Trước khi tích hợp thật, cần chốt các câu hỏi sau với nhóm Backend:


| Câu hỏi                            | Cần chốt                                                           |
| ---------------------------------- | ------------------------------------------------------------------ |
| Endpoint nhận AI Event là gì?      | `/api/v1/events` hay `/api/v1/ai/events`                           |
| JSON naming dùng chuẩn nào?        | `snake_case` hay `camelCase`                                       |
| `location_id` lấy từ đâu?          | Khuyến nghị `GET /api/v1/areas` hoặc endpoint location tương đương |
| AI Event có cần idempotency không? | Nên có, dùng `event_id`                                            |
| Backend có lưu `payload` không?    | Nên lưu JSONB để debug                                             |
| Evidence upload do ai quản lý?     | AI upload MinIO/local hay Backend cấp signed URL                   |
| Confidence lọc ở đâu?              | AI lọc trước, Backend/Risk có thể lọc thêm                         |
| Retry event xử lý thế nào?         | Backend nhận lại cùng `event_id` không tạo duplicate               |
| Event type chốt tên nào?           | `RESTRICTED_ZONE_LONG_DWELL` hoặc `RESTRICTED_ZONE_LOITERING`      |
| Zone config lấy từ đâu?            | Backend API hoặc file config trong prototype                       |


## 12. Definition of Done

Module Camera/AI đạt chuẩn bàn giao khi:

- Có README hướng dẫn chạy độc lập.
- Có file config mẫu.
- Có contract Markdown và JSON sample.
- Có unit test cho các logic cốt lõi.
- Có contract test cho AI Event.
- Có fake Backend để kiểm tra payload gửi đi.
- Có video/image sample để chạy demo.
- Có evidence image khi trigger event.
- Có log rõ theo `correlation_id`, `camera_id`, `session_id`, `frame_id`.
- Không gửi duplicate event liên tục theo từng frame.
- Có endpoint health check nếu chạy dưới dạng service.

## 13. Rủi ro cần chú ý


| Rủi ro                                    | Hậu quả                      | Cách giảm                                         |
| ----------------------------------------- | ---------------------------- | ------------------------------------------------- |
| Contract lệch với Backend                 | Risk Engine không hiểu event | Chốt schema và contract test sớm                  |
| Không dedup AI Event                      | Backend/Risk bị spam alert   | Dedup theo event type, camera, zone, track        |
| Tracking state không reset khi reconnect  | Dwell time và track_id sai   | Tạo session mới sau reconnect                     |
| Frame xử lý sai thứ tự                    | ByteTrack mất ổn định        | Kiểm tra `sequence_number`                        |
| Resize frame nhưng không scale zone       | Check polygon sai            | Lưu `frame_width`, `frame_height` và scale đúng   |
| Unit test phụ thuộc model thật            | Test chậm và không ổn định   | Mock detector trong unit test                     |
| Evidence upload trước nhưng event gửi lỗi | File orphan                  | Có cleanup job hoặc để Backend quản lý signed URL |
| RTSP lỗi mạng                             | Pipeline dừng                | Reconnect và camera lifecycle event               |


## 14. Kết luận

Hướng triển khai tốt nhất là xây dựng Camera/AI như một module độc lập, có contract rõ và test được trước khi nối Risk Engine. Nên ưu tiên làm chắc phần schema, zone matcher, rule engine, dedup và event output bằng dữ liệu giả trước. Sau đó mới gắn YOLO và ByteTrack thật vào pipeline.

Khi module này gửi được AI Event đúng chuẩn, có evidence và không spam duplicate, nhóm Backend/Risk Engine có thể hợp nhất dữ liệu AI với IoT một cách ổn định để tạo cảnh báo chính thức.