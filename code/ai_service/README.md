# AI Service + Edge Gateway

Pipeline chạy hoàn toàn local, không dùng Modal/cloud:

```text
Camera / video giả lập (FFmpeg) ──RTSP──► MediaMTX
  └─► Edge Gateway (Docker, :8002)
        ├─ live viewer / MJPEG / frame theo frame_id  ──► Zone Service :8010 ──► Dashboard
        └─ lấy mẫu AI_FPS ──WebSocket /ws/detect──► AI Service (host, :8003)
                                                    YOLOv11 → ByteTrack → Rule Engine
                                                    ├─ trả detection + rule_engine.violations về Gateway
                                                    └─ POST /api/ai-events ──► Zone Service
                                                         (gom Alert, chụp snapshot, xin clip ±5s)
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
  `RULE_EVENT_HEARTBEAT_SECONDS` giây để Alert không bị resolve. Zone Service chỉ
  cập nhật `last_seen_at`, không tăng `active_source_count`.
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
| `RULE_EVENT_HEARTBEAT_SECONDS` | `10` | Chu kỳ gửi lại event đang active. |
| `RULE_STATE_EXPIRE_SECONDS` | `5` | Xóa state khi mất đối tượng quá N giây. |
| `RULE_TIMEZONE_OFFSET_HOURS` | `7` | Múi giờ để so khung giờ active. |

## Chạy

Terminal 1, AI Service trên host (cần GPU để chạy nhanh):

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
..\..\.venv12\Scripts\Activate.ps1
pip install -r requirements-yolo.txt
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003
```

Terminal 2, toàn bộ phần còn lại bằng Docker:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
docker compose up --build
```

Mở dashboard: `http://localhost:8010`.

Chỉ xem video, không chạy AI: `$env:EDGE_MODE="viewer"; docker compose up --build`.

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
