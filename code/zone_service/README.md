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

Chạy Edge Gateway trước để có live camera. Nếu chỉ cần video và zone overlay:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
$env:MODAL_TRANSPORT="viewer"
docker compose up --build
```

Nếu muốn tab `Live Cameras` hiển thị thêm bbox YOLO, chạy AI bbox service trước rồi bật Gateway ở mode `viewer-ai`.

Local YOLO:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
..\..\.venv12\Scripts\Activate.ps1
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003
```

Gateway gửi frame sang local YOLO và vẫn stream video cho viewer:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
$env:MODAL_TRANSPORT="viewer-ai"
$env:MODAL_BBOX_TRANSPORT="websocket"
$env:MODAL_BBOX_WS_URL="ws://host.docker.internal:8003/ws/detect"
$env:VIEWER_FPS="15"
$env:AI_FPS="5"
docker compose up --build
```

Chạy Zone Service:

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
