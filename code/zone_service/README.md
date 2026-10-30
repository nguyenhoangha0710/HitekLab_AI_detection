# Hitek Zone Management Service

Service này dùng để cấu hình camera zone độc lập với pipeline Video Ingest/AI.

## Chức năng

- Xem tất cả camera trong tab `Live Cameras`.
- Chọn từng camera ở sidebar.
- Capture một reference frame từ Edge Gateway.
- Vẽ polygon zone trên ảnh tĩnh bằng canvas.
- Lưu nhiều zone cho một camera vào database.

## Database dev

Mặc định dùng SQLite:

```text
code/zone_service/data/zone_service.db
```

Schema được thiết kế gần với database chính:

- `tenant`
- `location`
- `camera`
- `camera_reference_frame`
- `zone`
- `rule_config`

Khi chuyển sang PostgreSQL, lớp cần thay chủ yếu là repository/database layer.

## Chạy service

Cách chạy toàn hệ thống và chạy riêng Zone Service để dev: xem
[HUONG_DAN_CHAY.md](../../HUONG_DAN_CHAY.md) (mục 5 và mục 9).

**Cảnh báo do Backend API tạo (`ALERT_MODE=backend`, mặc định).** `POST /api/ai-events`
ghi `ai_event`, commit, rồi gọi Backend `POST /api/v1/events` (kèm token lấy từ
`/api/v1/auth/token`) và gán `alertId` trả về vào `ai_event.alert_id` / `evidence.alert_id`.
Nếu Backend lưu alert ở bảng khác, Zone Service tạo dòng `alert` "mirror"
(`dedup_key = backend:<id>`) chỉ để giữ khoá ngoại và hiển thị tab Evidence.
`ALERT_MODE=local` giữ cách tự gom alert cũ. Trạng thái: `GET /api/integration/backend`.

**Rule Engine không còn chạy trên trình duyệt.** AI Service lấy zone/rule qua
`GET /api/cameras/{id}/zones` và `GET /api/zones/{id}/rules`, rồi gửi vi phạm về
`POST /api/ai-events`. Frontend chỉ hiển thị `result.rule_engine.violations` mà AI
Service trả kèm trong luồng detection.

Mở:

```text
http://localhost:8010
```

Mở thẳng màn hình YOLO Detection:

```text
http://localhost:8010/detect
```

UI chính tại `http://localhost:8010` có 3 tab:

- `Live Cameras`: live video qua Zone Service proxy, browser chỉ gọi `localhost:8010`.
- `YOLO Detection`: hiển thị frame đồng bộ theo bbox YOLO + zone polygon đã lưu trong SQLite, tất cả trong `localhost:8010/detect`.
- `Zone Editor`: capture reference frame, vẽ polygon zone và lưu xuống database.

Edge Gateway `localhost:8002` vẫn chạy như nguồn dữ liệu nội bộ cho frame/detection, nhưng người dùng không cần mở `http://localhost:8002/viewer`.
