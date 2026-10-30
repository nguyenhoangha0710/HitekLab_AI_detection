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

Chạy AI Service trên host trước (YOLO + ByteTrack + Rule Engine), sau đó bật hệ thống bằng Docker:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
..\..\.venv12\Scripts\Activate.ps1
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003

cd D:\NguyenHoangHa_nam4\Internship\HitekLab
docker compose up --build
```

Nếu chỉ cần video và zone overlay (không chạy AI): `$env:EDGE_MODE="viewer"` trước khi `docker compose up`.

**Rule Engine không còn chạy trên trình duyệt.** AI Service lấy zone/rule qua
`GET /api/cameras/{id}/zones` và `GET /api/zones/{id}/rules`, rồi gửi vi phạm về
`POST /api/ai-events`. Frontend chỉ hiển thị `result.rule_engine.violations` mà AI
Service trả kèm trong luồng detection.

Chạy Zone Service ngoài Docker (dev):


```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
.\.venv12\Scripts\Activate.ps1
pip install -r code\zone_service\requirements.txt
uvicorn backend.app.main:app --app-dir code\zone_service --host 0.0.0.0 --port 8010 --reload
```

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
