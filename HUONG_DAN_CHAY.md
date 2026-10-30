# Hướng dẫn chạy hệ thống HITEK AI-IoT

Tài liệu cho cả nhóm (AI, Backend & IoT, Frontend, Kiểm thử). Làm theo mục 1 → 5 là chạy được; các mục sau dùng khi phát triển và khi gặp lỗi.

## Mục lục

1. [Chuẩn bị máy](#1-chuẩn-bị-máy)
2. [Lấy code](#2-lấy-code)
3. [Chuẩn bị video và model](#3-chuẩn-bị-video-và-model)
4. [Tạo file .env](#4-tạo-file-env)
5. [Chạy hệ thống](#5-chạy-hệ-thống)
6. [Kiểm tra sau khi chạy](#6-kiểm-tra-sau-khi-chạy)
7. [Demo nhanh: vẽ zone và nhận cảnh báo](#7-demo-nhanh-vẽ-zone-và-nhận-cảnh-báo)
8. [Lệnh dùng hằng ngày](#8-lệnh-dùng-hằng-ngày)
9. [Phát triển theo từng nhóm](#9-phát-triển-theo-từng-nhóm)
10. [Quy ước làm việc chung](#10-quy-ước-làm-việc-chung)
11. [Xử lý sự cố](#11-xử-lý-sự-cố)

---

## 1. Chuẩn bị máy

| Phần mềm | Bắt buộc | Ghi chú |
| --- | --- | --- |
| Git | Có | |
| Docker Desktop (Windows/macOS) hoặc Docker Engine + Compose v2 (Linux) | Có | Windows: bật WSL2 backend. Kiểm tra: `docker compose version` |
| RAM trống ≥ 6 GB, ổ đĩa trống ≥ 10 GB | Có | Image AI Service (torch) khoảng 2–3 GB |
| Python 3.11 hoặc 3.12 | Không | Chỉ cần khi chạy service ngoài Docker để dev (mục 9) |
| Card NVIDIA + driver mới | Không | Chạy AI bằng GPU (chế độ B). Không có GPU vẫn chạy được bằng CPU |

## 2. Lấy code

```powershell
git clone <url-repo> HitekLab
cd HitekLab
git checkout main          # hoặc branch nhóm đang tích hợp, ví dụ feature/ai-rule-engine
```

## 3. Chuẩn bị video và model

**Video camera giả lập.** Hệ thống giả lập 2 camera IP bằng cách phát lặp file video trong `code/data/videos/`.

- Repo chỉ có sẵn `dummy_video_2.mp4`; cấu hình mặc định dùng file này cho cả 2 camera nên clone về là chạy được.
- Video demo đầy đủ (`neighbors_yard.ts`, `video_4_police.mp4`, `stole.mp4`, `camera_test.mp4`...) không commit vì quá nặng. Lấy từ thư mục chung của nhóm, chép vào `code/data/videos/`, rồi khai báo tên file trong `.env` (`CAMERA1_VIDEO`, `CAMERA2_VIDEO`).
- Thêm video mới: nên dùng `.mp4` (H.264) hoặc `.ts`, độ phân giải ≤ 1280×720.

**Model YOLO.** Không cần chuẩn bị. Lần đầu AI Service nhận frame sẽ tự tải `yolo11n.pt` (khoảng 5 MB, cần Internet) vào `code/ai_service/models/`. Muốn dùng model khác: chép file `.pt` vào thư mục đó và sửa `YOLO_MODEL` trong `.env`.

## 4. Tạo file .env

```powershell
Copy-Item .env.example .env      # PowerShell
# cp .env.example .env           # Git Bash / Linux / macOS
```

`.env` là cấu hình riêng của từng máy, **không commit**. Các biến hay sửa:

| Biến | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `COMPOSE_PROFILES` | `ai` / để trống | `ai` = chạy AI Service trong Docker |
| `EDGE_MODE` | `viewer-ai` / `viewer` | `viewer` = chỉ xem video, không gửi frame cho AI |
| `AI_SERVICE_WS_URL` | `ws://ai-service:8003/ws/detect` | Đổi thành `ws://host.docker.internal:8003/ws/detect` nếu AI chạy trên máy host |
| `CAMERA1_VIDEO`, `CAMERA2_VIDEO` | tên file | File trong `code/data/videos/` |
| `YOLO_DEVICE` | `cpu` / `0` | Thiết bị chạy YOLO |
| `AI_FPS` | `5` | Số frame/giây gửi AI cho mỗi camera; máy yếu giảm xuống 2–3 |
| `ALERT_MODE` | `backend` / `local` | `backend` = gửi sự kiện sang Backend API, Backend tạo cảnh báo. `local` = chạy thử không cần Backend |
| `BACKEND_BASE_URL` | `http://host.docker.internal:5250` | Địa chỉ Backend API nhìn từ container zone-service |
| `*_PORT` | | Đổi nếu bị trùng cổng trên máy |

## 5. Chạy hệ thống

Chọn **một** trong bốn chế độ.

### A. Toàn bộ trong Docker, AI chạy CPU (mặc định, khuyên dùng cho Backend/Frontend/Kiểm thử)

```powershell
docker compose up -d --build
```

Lần đầu build mất 5–15 phút (tải torch). Các lần sau chỉ vài giây.

### B. Toàn bộ trong Docker, AI chạy GPU NVIDIA

Kiểm tra Docker thấy GPU:

```powershell
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

Nếu in ra bảng GPU thì chạy:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

### C. AI Service chạy trên máy host, phần còn lại trong Docker (cho nhóm AI)

Tiện để sửa code AI và reload nhanh, dùng GPU trực tiếp. Trong `.env`:

```dotenv
COMPOSE_PROFILES=
AI_SERVICE_WS_URL=ws://host.docker.internal:8003/ws/detect
```

```powershell
# Terminal 1: AI Service
cd code\ai_service
python -m venv ..\..\.venv12            # lần đầu
..\..\.venv12\Scripts\Activate.ps1
pip install -r requirements-yolo.txt    # lần đầu
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003 --reload

# Terminal 2: các service còn lại
cd <thu-muc-repo>
docker compose up -d --build
```

AI Service trên host tự gọi Zone Service ở `http://localhost:8010` (đổi bằng biến `ZONE_SERVICE_URL`).

### Kết nối Backend API (cảnh báo chính thức)

Cảnh báo do **Backend API** (.NET, cổng 5250) và Risk Engine tạo ra, gộp cả sự kiện camera lẫn cảm biến. Zone Service chỉ ghi `ai_event`, chụp bằng chứng rồi chuyển tiếp sang Backend:

```text
AI Service ─► Zone Service POST /api/ai-events
                ├─ ghi ai_event (commit)
                ├─ POST {BACKEND_BASE_URL}/api/v1/auth/token   (lấy token, giữ 12h, gặp 401 thì lấy lại)
                ├─ POST {BACKEND_BASE_URL}/api/v1/events        {cameraId, areaId, objectType, confidence, occurredAt, aiEventId}
                └─ nhận {alertId} ─► gán vào ai_event.alert_id và evidence.alert_id
```

- Chạy Backend trước theo hướng dẫn của nhóm Backend; mặc định Zone Service gọi `http://host.docker.internal:5250`.
- Vi phạm còn kéo dài thì AI gửi lại mỗi giây (`RULE_EVENT_HEARTBEAT_SECONDS=1`), vì Risk Engine chỉ giữ nguồn AI trong 3 giây.
- Backend tắt hoặc báo lỗi thì `ai_event` vẫn được lưu (`alert_id` để trống), AI vẫn chạy bình thường.
- Chưa có Backend để test: đặt `ALERT_MODE=local` trong `.env`, Zone Service tự gom alert như trước.
- Xem tình trạng kết nối: http://localhost:8010/api/integration/backend (số event đã gửi, số alertId nhận về, mã lỗi gần nhất).

### D. Chỉ xem video, không chạy AI

```dotenv
COMPOSE_PROFILES=
EDGE_MODE=viewer
```

```powershell
docker compose up -d --build
```

## 6. Kiểm tra sau khi chạy

```powershell
docker compose ps
```

Các service phải ở trạng thái `running`; những service có healthcheck hiện `(healthy)` sau khoảng 30 giây.

| Địa chỉ | Dùng để |
| --- | --- |
| http://localhost:8010 | **Dashboard**: Live Cameras, YOLO Detection, Zone Editor, Evidence |
| http://localhost:8010/docs | Swagger API của Zone Service |
| http://localhost:8010/api/integration/backend | Tình trạng gửi sự kiện sang Backend API |
| http://localhost:8003/health | Trạng thái AI Service (model, tracker, rule engine) |
| http://localhost:8003/rules/status | Zone/rule AI đang dùng, số event đã gửi |
| http://localhost:8003/docs | Swagger API của AI Service |
| http://localhost:8002/viewer | Viewer nội bộ của Edge Gateway (debug) |
| http://localhost:9001 | MinIO console (`hitek_minio` / `hitek_minio_password`) |
| `rtsp://localhost:8554/camera1` | Luồng camera giả lập, mở bằng VLC |
| `localhost:5432` | PostgreSQL (`hitek_app` / `hitek_app_password`, DB `hitek_ai_iot`) |

Kiểm tra nhanh bằng PowerShell:

```powershell
Invoke-RestMethod http://localhost:8010/health
Invoke-RestMethod http://localhost:8003/health | ConvertTo-Json -Depth 6
```

## 7. Demo nhanh: vẽ zone và nhận cảnh báo

1. Mở http://localhost:8010, tab **Live Cameras**: thấy 2 camera chạy.
2. Tab **YOLO Detection**: thấy bounding box, nhãn `person-3`, `car-5`... (số sau là `track_id`).
3. Tab **Zone Editor**: chọn camera, bấm *Capture* để lấy ảnh nền, click để vẽ đa giác, chọn loại zone:
   - `restricted_area` (vùng cấm): rule mặc định `person_intrusion`, `vehicle_intrusion`, chỉ bật từ 23:00 đến 06:00.
   - `controlled_area` (vùng hạn chế): rule mặc định `loitering`, `crowd_limit`, `vehicle_stopping`.
4. Chỉnh rule cho dễ thấy khi demo: ví dụ bỏ tick *Use active time*, `Duration = 3`, bấm *Save Rule*.
5. AI Service tải lại zone/rule sau tối đa 10 giây. Muốn áp dụng ngay:
   `Invoke-RestMethod -Method Post http://localhost:8003/rules/reload`
6. Khi có vi phạm: banner đỏ hiện trên dashboard, tab **Evidence** có ảnh và clip ±5 giây.

Cảnh báo vẫn được tạo khi không ai mở dashboard, vì Rule Engine chạy trong AI Service.

## 8. Lệnh dùng hằng ngày

```powershell
docker compose logs -f ai-service edge-gateway       # xem log (Ctrl+C để thoát)
docker compose restart edge-gateway                  # khởi động lại 1 service
docker compose up -d --build zone-service            # build lại 1 service sau khi sửa code
docker compose stop                                  # tạm dừng, giữ nguyên dữ liệu
docker compose down                                  # xóa container, giữ dữ liệu (volume)
docker compose down -v                               # xóa luôn database + ảnh/clip, về trạng thái sạch
```

Sau khi `git pull` code mới, luôn chạy lại `docker compose up -d --build`.

## 9. Phát triển theo từng nhóm

Code của `zone-service`, `edge-gateway`, `ai-service` được đóng vào image, nên sửa code xong phải build lại service đó (`docker compose up -d --build <service>`). Nếu cần sửa nhiều và xem kết quả ngay, chạy service đó ngoài Docker như dưới đây.

### Nhóm AI

- Dùng chế độ C (mục 5) để có `--reload`.
- Test: `cd code\ai_service; python -m unittest discover -s tests`. `tests/test_rule_engine.py` chỉ cần Python, không cần YOLO.
- Code chính: `local_bbox_service.py` (API), `rule_engine/` (zone, rule, event), `local_ai/byte_tracker.py`, `edge_gateway/`.

### Nhóm Backend & Frontend (Zone Service)

Chạy zone-service ngoài Docker, các service khác vẫn trong Docker:

```powershell
docker compose stop zone-service

.\.venv12\Scripts\Activate.ps1
pip install -r code\zone_service\requirements.txt
$env:DATABASE_URL="postgresql://hitek_app:hitek_app_password@localhost:5432/hitek_ai_iot"
$env:EDGE_GATEWAY_BASE_URL="http://localhost:8002"
$env:ZONE_CAMERA_CONFIG_PATH="code/ai_service/config.docker.yaml"
$env:EVIDENCE_STORAGE_BACKEND="minio"; $env:MINIO_ENDPOINT="localhost:9000"
$env:MINIO_ACCESS_KEY="hitek_minio"; $env:MINIO_SECRET_KEY="hitek_minio_password"
$env:EVIDENCE_VIDEO_UPLOAD_URL="http://host.docker.internal:8010/api/evidence/video"
uvicorn backend.app.main:app --app-dir code\zone_service --host 0.0.0.0 --port 8010 --reload
```

- Nếu AI Service chạy trong Docker, nó gọi `http://zone-service:8010`, tên này không còn khi bạn dừng container. Khi đó chạy AI theo chế độ C, hoặc đặt `ZONE_SERVICE_URL=http://host.docker.internal:8010` cho ai-service.
- Frontend là file tĩnh (`code/zone_service/frontend`), sửa xong tải lại trình duyệt là thấy (với `--reload`).
- Test: `cd code\zone_service; python -m unittest discover -s tests`.
- Schema: `code/database/postgres/init/*.sql`. Zone Service chạy lại **tất cả** file này mỗi lần khởi động, nên script phải chạy lại được nhiều lần (`IF NOT EXISTS`, không `UPDATE` vô điều kiện). File mới đặt số tiếp theo (`006_...sql`), sau đó `docker compose up -d --build zone-service`.

### Nhóm IoT (chưa có service)

Khi thêm IoT Service hoặc Mosquitto: thêm service vào `docker-compose.yml`, biến cấu hình vào `.env.example`, cập nhật bảng cổng ở mục 6 của tài liệu này.

### Nhóm Kiểm thử

- Dùng chế độ A hoặc B; reset dữ liệu giữa các lượt test bằng `docker compose down -v`.
- Đổi video kịch bản bằng `CAMERA1_VIDEO`/`CAMERA2_VIDEO` trong `.env` rồi `docker compose up -d`.
- Lấy số liệu: `GET http://localhost:8010/api/alerts`, `GET /api/ai-events`, `GET /api/evidence`, `GET http://localhost:8003/rules/status`.

## 10. Quy ước làm việc chung

- Không commit: `.env`, video trong `code/data/videos/`, model `*.pt`, thư mục `.venv*`, dữ liệu trong `code/zone_service/data/`.
- Mỗi việc một branch (`feature/<nhom>-<viec>`), merge vào `main` qua Pull Request, có ít nhất một người review.
- Thêm biến môi trường mới: cập nhật đồng thời `docker-compose.yml`, `.env.example` và bảng ở mục 4.
- Đổi API giữa các service: cập nhật `docs/API_CONTRACT_AND_CONVENTIONS.md` và báo nhóm liên quan.
- Trước khi tạo PR: chạy test của service mình sửa và `docker compose up -d --build` để chắc toàn hệ thống vẫn lên.

## 11. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| `port is already allocated` | Cổng 8010/5432/9000/8554... đang bị chiếm | Đổi `*_PORT` trong `.env`, hoặc tắt chương trình đang dùng cổng |
| Camera đen, log `camera1` báo `No such file` | Tên video trong `.env` sai hoặc chưa chép file | Kiểm tra `code/data/videos/` và `CAMERA1_VIDEO`, rồi `docker compose up -d camera1 camera2` |
| Có video nhưng không có bbox | AI Service chưa chạy hoặc sai địa chỉ | `docker compose ps ai-service`; xem log `docker compose logs edge-gateway` có `EDGE_AI_BBOX_WS_FAILED`; kiểm tra `COMPOSE_PROFILES` và `AI_SERVICE_WS_URL` |
| Lần đầu bbox xuất hiện chậm | AI đang tải `yolo11n.pt` | Đợi khoảng 1 phút; máy không có Internet thì chép sẵn file vào `code/ai_service/models/` |
| AI rất chậm, video detection giật | Chạy CPU với FPS cao | Giảm `AI_FPS=2`, hoặc dùng GPU (chế độ B/C) |
| `could not select device driver "nvidia"` | Docker chưa thấy GPU | Cập nhật driver NVIDIA, bật WSL2 trong Docker Desktop; tạm thời dùng chế độ A |
| Vẽ zone xong không có cảnh báo | Rule chỉ bật theo giờ (23:00–06:00), duration lớn, hoặc AI chưa tải lại | Sửa rule (mục 7, bước 4), gọi `/rules/reload`, xem `http://localhost:8003/rules/status` |
| Sửa SQL trong `init/` mà database không đổi | SQL được đóng vào image zone-service | `docker compose up -d --build zone-service`; nếu đổi cấu trúc bảng đã có dữ liệu thì `docker compose down -v` (mất dữ liệu cũ) |
| `zone-service` khởi động lại liên tục | Postgres chưa sẵn sàng hoặc lỗi SQL | `docker compose logs zone-service postgres` |
| Build báo lỗi mạng khi `pip install` | Mạng chặn PyPI hoặc download.pytorch.org | Thử lại mạng khác, hoặc dùng chế độ C với venv đã cài |
| `/api/integration/backend` báo `BACKEND_UNREACHABLE` hoặc `AUTH_FAILED` | Backend chưa chạy, sai địa chỉ, sai clientId/secret | Kiểm tra Backend ở cổng 5250, `BACKEND_BASE_URL`, `BACKEND_CLIENT_ID`/`BACKEND_CLIENT_SECRET`; chạy thử không Backend thì `ALERT_MODE=local` |
| Báo `CAMERA_NOT_FOUND` / `AREA_NOT_FOUND` | Backend chưa có camera/khu vực trùng id với `config.docker.yaml` | Hai bên dùng chung `camera_id` và `location_id` (bảng `camera`, `location` trong Postgres) |
| Báo `AI_EVENT_NOT_FOUND` | Backend đọc database khác với Zone Service | Backend và Zone Service phải dùng chung Postgres `hitek_ai_iot` |
| Muốn làm lại từ đầu | | `docker compose down -v`, sau đó `docker compose up -d --build` |
