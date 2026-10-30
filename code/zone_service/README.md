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

## Giao diện (http://localhost:8010)

Console cho nhóm AI và camera, viết bằng JavaScript thuần (không cần build). FastAPI phục vụ thẳng thư mục `frontend/`.

| Màn hình | Dùng để |
| --- | --- |
| **Giám sát** (`#/monitor`) | Tường camera có lớp phủ AI: vùng, khung đối tượng, `#track_id`, mũi tên hướng đi, điểm chân. Có 2 cách hiển thị: **Khớp khung AI** (khung và hình luôn khớp, trễ theo AI) và **Video trực tiếp** (video mượt, khung vẽ theo kết quả mới nhất). Cột phải liệt kê vi phạm đang diễn ra; bấm vào để phóng to camera đó. Chân mỗi camera hiện số đối tượng, thời gian AI xử lý, độ trễ, AI chạy CPU hay GPU ở máy nào |
| **Vùng và luật** (`#/zones`) | Chụp ảnh nền, vẽ đa giác vùng (vùng cấm / vùng hạn chế), bật/tắt hoặc xoá vùng, sửa luật bằng tiếng Việt (đối tượng, số giây, số người, độ tin cậy, khung giờ). Chỉ người có quyền Quản trị khu vực mới sửa được |
| **Sự kiện và bằng chứng** (`#/events`) | Bảng sự kiện AI, lọc theo camera, loại sự kiện, thời gian, đã thành cảnh báo Backend hay chưa. Bấm một dòng để xem ảnh, clip và chi tiết (hướng đi, độ tin cậy, mã cảnh báo) |
| **Hệ thống** (`#/system`) | AI đang chạy ở đâu, hiệu năng từng camera (khung/giây, thời gian AI xử lý, trễ đầu-cuối), trạng thái gửi sang Backend, quyền của tài khoản đang đăng nhập |

Cấu trúc code:

```text
frontend/
  index.html            khung trang: sidebar, topbar, vùng nội dung
  src/app.js            khởi động: đăng nhập, tải camera, nối luồng kết quả AI, điều hướng theo #hash
  src/styles.css        toàn bộ giao diện (biến màu ở :root)
  src/core/api.js       gọi API, gắn token
  src/core/auth.js      đăng nhập, user hiện tại
  src/core/store.js     trạng thái chung + luồng SSE kết quả AI, danh sách vi phạm
  src/core/overlay.js   vẽ vùng, khung đối tượng, hướng đi lên canvas
  src/core/format.js    nhãn tiếng Việt, định dạng thời gian
  src/views/            monitor.js, zones.js, events.js, system.js
```

Dashboard tổng quan, quản lý cảnh báo chính thức (từ Backend), quản lý cảm biến và người dùng thuộc frontend của nhóm Backend & IoT.

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
