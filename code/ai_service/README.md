# AI Service + Edge Gateway

Pipeline chạy hoàn toàn local, không dùng Modal/cloud:

```text
Camera / video giả lập (FFmpeg) ──RTSP──► MediaMTX
  └─► Edge Gateway (Docker, :8002)
        ├─ live viewer / MJPEG / frame theo frame_id  ──► Zone Service :8010 ──► Dashboard
        └─ lấy mẫu AI_FPS ──WebSocket /ws/detect──► AI Service (host, :8003)
                                                    YOLOv11 → ByteTrack → hướng di chuyển → Rule Engine
                                                    ├─ trả detection + rule_engine.violations về Gateway
                                                    └─ POST /api/ai-events ──► Zone Service
                                                         ghi ai_event, chụp snapshot, xin clip ±5s
                                                         └─ POST /api/v1/events ──► Backend API (Risk Engine tạo alert)
```

AI Service (`local_bbox_service.py`) chạy trên máy host để dùng GPU. Rule Engine
chạy ngay trong AI Service, nên cảnh báo vẫn được tạo khi không ai mở dashboard.

## Thành phần

| Thư mục / file | Vai trò |
| --- | --- |
| `common/` | `FrameJob`, model metadata, image codec, time helpers. |
| `edge_gateway/video_ingest.py` | Đọc RTSP, lấy mẫu FPS, resize, encode JPEG, tạo `FrameJob`. |
| `edge_gateway/live_viewer.py` | API viewer: MJPEG, `latest.jpg`, frame theo `frame_id`, SSE detection. |
| `edge_gateway/evidence_recorder.py` | Ghi clip bằng chứng ±N giây từ buffer frame. |
| `edge_gateway/transport/ai_bbox_sender.py` | Gửi frame sang AI Service (WebSocket hoặc HTTP), drop frame cũ khi nghẽn. |
| `local_bbox_service.py` | **AI Service**: FastAPI, YOLOv11 + ByteTrack + Rule Engine. |
| `local_ai/byte_tracker.py` | ByteTrack theo từng camera (fallback IoU nếu thiếu `lap`). |
| `local_ai/detector.py` | Bảng class COCO (`person`, `car`, `motorcycle`, `bus`, `truck`...). |
| `rule_engine/` | Kiểm tra zone/rule, sinh AI Event (xem bên dưới). |
| `local_ai/api.py`, `worker*.py` | API debug cũ với memory queue (không nằm trong luồng chính). |

## Rule Engine (`rule_engine/`)

| File | Nội dung |
| --- | --- |
| `geometry.py` | Foot point (điểm giữa cạnh dưới bbox), point-in-polygon, scale tọa độ. |
| `models.py` | `ZoneConfig`, `RuleConfig`, map `rule_type` → `event_type` theo contract. |
| `config_provider.py` | Lấy zone + rule từ Zone Service (`/api/cameras/{id}/zones`, `/api/zones/{id}/rules`), cache TTL, refresh nền. |
| `engine.py` | Tính thời gian ở trong zone theo `track_id`, đếm người, khung giờ active, gắn lại track khi ByteTrack đổi ID. |
| `publisher.py` | Gửi AI Event sang Zone Service bằng thread nền, có retry. |

Các rule (cấu hình trong bảng `rule_config`, sửa trên tab Zone Editor):

| rule_type | Điều kiện | event_type theo contract |
| --- | --- | --- |
| `person_intrusion` | người ở trong vùng cấm ≥ `duration_threshold` giây (0 = báo ngay) | `FORBIDDEN_ZONE_INTRUSION` |
| `vehicle_intrusion` | xe (`object_type=vehicle` = car/motorcycle/bus/truck) trong vùng cấm | `FORBIDDEN_ZONE_INTRUSION` |
| `loitering` | người lảng vảng ≥ `duration_threshold` giây | `RESTRICTED_ZONE_LOITERING` |
| `crowd_limit` | số track ≥ `people_threshold` liên tục ≥ `duration_threshold` giây | `RESTRICTED_ZONE_CROWDING` |
| `vehicle_stopping` | xe dừng trong vùng ≥ `duration_threshold` giây | `RESTRICTED_ZONE_VEHICLE_STOPPING` |

Mọi rule đều lọc thêm theo `confidence_threshold` và `use_active_time` +
`active_start_time`/`active_end_time` (dùng cho tình huống "người xuất hiện
ngoài giờ quy định", ví dụ 23:00–06:00, hỗ trợ khung giờ qua nửa đêm).

Quy tắc thời gian và chống trùng:

- Thời gian tính theo `captured_at` của frame, không theo đồng hồ trình duyệt.
- Mỗi vi phạm có `source_event_id = camera|zone|rule|track|first_seq` (crowd dùng `crowd`).
- Khi vi phạm còn kéo dài, AI Service gửi lại cùng `source_event_id` mỗi
  `RULE_EVENT_HEARTBEAT_SECONDS` giây (mặc định 1s). Zone Service cập nhật cùng dòng
  `ai_event` và chuyển tiếp sang Backend với cùng `aiEventId`, `occurredAt` mới, để
  Risk Engine (giữ nguồn AI 3 giây) kết hợp được với cảm biến.
- Track mới xuất hiện trong vòng 3 giây, cách track cũ ≤ 80px, diện tích bbox
  tương đương sẽ kế thừa thời gian đứng của track cũ (`reattached_from`).

Payload gửi `POST /api/ai-events` vẫn tương thích với Zone Service hiện tại. Phần
theo chuẩn `API_CONTRACT_AND_CONVENTIONS.md` mục 6 (`event_source`, `event_type`,
`objects[]` có `bbox`, `foot_point`, `dwell_time_seconds`, `metadata`) nằm trong
`payload.contract`.

Kết quả mỗi frame AI Service trả về có thêm:

```json
{
  "detections": [{"track_id": 3, "class_name": "person", "foot_point": {"x": 200, "y": 250}, "zone_ids": ["..."]}],
  "rule_engine": {
    "enabled": true,
    "zones_loaded": 2,
    "violations": [{"rule_type": "loitering", "zone_name": "Kho", "track_id": "person-3", "elapsed_seconds": 16.2}]
  }
}
```

## Hướng di chuyển (`local_ai/motion.py`)

Sau ByteTrack, AI Service lưu vị trí chân của mỗi `track_id` trong `MOTION_WINDOW_SECONDS`
gần nhất, theo thời gian `captured_at`. Vector dịch chuyển bằng vị trí hiện tại trừ vị trí cũ
nhất trong cửa sổ. Mỗi detection có thêm:

```json
"motion": {"direction": "left", "angle_deg": 180.0, "speed_px_s": 200.0, "dx": -200.0, "dy": 0.0, "window_seconds": 1.0}
```

- `direction`: `right`, `up-right`, `up`, `up-left`, `left`, `down-left`, `down`, `down-right`,
  hoặc `stationary` (tốc độ < `MOTION_STATIONARY_SPEED_RATIO` × chiều rộng khung hình mỗi giây),
  hoặc `unknown` (track mới, lịch sử chưa đủ nửa cửa sổ).
- Trục y của ảnh hướng xuống, nên `up` là đi lên trên khung hình (với camera đặt cao thường là đi ra xa
  camera), `down` là lại gần camera. `angle_deg`: 0° là sang phải, 90° là đi lên, tăng ngược chiều kim đồng hồ.
- `speed_px_s` tính theo pixel trên khung hình, chưa quy ra mét.
- Hướng được đưa vào AI Event (`payload.detection.motion`, `payload.contract.objects[].direction`),
  vào `rule_engine.violations[].direction`, và hiện thành mũi tên trên nhãn ở tab YOLO Detection.

## Biến môi trường của AI Service

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `LOCAL_YOLO_MODEL` | `yolo11n.pt` | File model. |
| `LOCAL_YOLO_CLASSES` | `person,car,motorcycle` | Class COCO cần detect. |
| `LOCAL_YOLO_CONFIDENCE` | `0.35` | Ngưỡng confidence của YOLO. |
| `LOCAL_YOLO_DEVICE` | auto | `cpu`, `0`, `cuda:0`... |
| `RULE_ENGINE_ENABLED` | `true` | Tắt/bật Rule Engine. |
| `ZONE_SERVICE_URL` | `http://localhost:8010` | Nơi lấy zone/rule và gửi AI Event. |
| `RULE_CONFIG_TTL_SECONDS` | `10` | Chu kỳ tải lại zone/rule. |
| `RULE_EVENT_HEARTBEAT_SECONDS` | `1` | Chu kỳ gửi lại event đang active (Risk Engine của Backend chỉ giữ nguồn AI 3 giây). |
| `RULE_STATE_EXPIRE_SECONDS` | `5` | Xóa state khi mất đối tượng quá N giây. |
| `RULE_TIMEZONE_OFFSET_HOURS` | `7` | Múi giờ để so khung giờ active. |
| `MOTION_WINDOW_SECONDS` | `1.0` | Cửa sổ thời gian để tính hướng di chuyển. |
| `MOTION_STATIONARY_SPEED_RATIO` | `0.02` | Ngưỡng coi là đứng yên (tỷ lệ chiều rộng khung hình mỗi giây; 640px thì khoảng 13 px/s). |

## Chạy

Xem [HUONG_DAN_CHAY.md](../../HUONG_DAN_CHAY.md) ở thư mục gốc. Tóm tắt:

- Toàn bộ trong Docker (AI chạy CPU): `docker compose up -d --build` với `COMPOSE_PROFILES=ai` trong `.env`.
- AI chạy GPU trong Docker: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`.
- AI chạy trên host để dev (`--reload`): đặt `COMPOSE_PROFILES=` và
  `AI_SERVICE_WS_URL=ws://host.docker.internal:8003/ws/detect` trong `.env`, rồi:

```powershell
cd code\ai_service
..\..\.venv12\Scripts\Activate.ps1
pip install -r requirements-yolo.txt
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003 --reload
```

`Dockerfile` có 2 target: `edge-gateway` (nhẹ, không có torch) và `ai-service`
(torch CPU mặc định; bản GPU dùng build arg `TORCH_INDEX_URL`). Model đặt trong
`models/` (được mount vào container, tự tải `yolo11n.pt` nếu chưa có).

## API của AI Service

```text
GET  /health          trạng thái model, tracker, rule engine
POST /detect          1 frame (JSON, image_b64) -> detection + rule_engine
WS   /ws/detect       như /detect nhưng qua WebSocket (Edge Gateway dùng mặc định)
GET  /rules/status    zone/rule đang cache, số state, thống kê publisher
POST /rules/reload    xóa cache zone/rule (?camera_id=... để chỉ xóa 1 camera)
```

## Test

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
python -m unittest discover -s tests
```

`tests/test_rule_engine.py` chỉ dùng thư viện chuẩn, chạy được cả khi máy chưa cài YOLO.
