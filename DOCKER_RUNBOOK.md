# Docker Runbook

Luồng hiện tại (không dùng Modal):

```text
Video files ─► FFmpeg camera1/camera2 ─► MediaMTX (RTSP :8554)
  ─► edge-gateway (:8002, nội bộ Docker)
       ├─► zone-service (:8010) ─► Dashboard
       └─► AI Service trên host (:8003): YOLOv11 + ByteTrack + Rule Engine
              └─► POST zone-service /api/ai-events ─► alert + evidence (Postgres + MinIO)
```

## Service

| Service | Vai trò |
| --- | --- |
| `postgres` | Database chính, init từ `code/database/postgres/init`. |
| `minio` | Lưu ảnh và clip bằng chứng (console :9001). |
| `mediamtx` | RTSP server nội bộ, port `8554`. |
| `camera1`, `camera2` | FFmpeg phát lặp video lên `rtsp://mediamtx:8554/cameraN`. |
| `edge-gateway` | Đọc RTSP, phục vụ viewer, gửi frame sang AI Service qua `AI_SERVICE_WS_URL`. |
| `zone-service` | Dashboard, cấu hình zone/rule, nhận AI Event, gom alert, lưu evidence. |

AI Service không nằm trong compose vì cần GPU của máy host.

## Chạy

```powershell
# Terminal 1: AI Service
cd D:\NguyenHoangHa_nam4\Internship\HitekLab\code\ai_service
..\..\.venv12\Scripts\Activate.ps1
uvicorn local_bbox_service:app --host 0.0.0.0 --port 8003

# Terminal 2: hệ thống
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
docker compose up --build
```

Dashboard: `http://localhost:8010`. Kiểm tra AI Service:

```powershell
Invoke-RestMethod http://localhost:8003/health | ConvertTo-Json -Depth 6
Invoke-RestMethod http://localhost:8003/rules/status | ConvertTo-Json -Depth 6
```

Sau khi vẽ hoặc sửa zone/rule, AI Service tự tải lại sau tối đa 10 giây. Muốn áp dụng ngay:

```powershell
Invoke-RestMethod -Method Post http://localhost:8003/rules/reload
```

Dừng: `docker compose down`.

## Biến môi trường hay dùng

| Biến | Mặc định | Ghi chú |
| --- | --- | --- |
| `EDGE_MODE` | `viewer-ai` | `viewer` = chỉ stream video. |
| `AI_SERVICE_WS_URL` | `ws://host.docker.internal:8003/ws/detect` | Địa chỉ AI Service nhìn từ container. |
| `AI_SERVICE_TRANSPORT` | `websocket` | Hoặc `http` (khi đó URL là `.../detect`). |
| `VIEWER_FPS` / `AI_FPS` | `15` / `5` | FPS cho viewer và FPS gửi AI. |

Trong Docker network không dùng `localhost` để các container gọi nhau: camera là
`rtsp://mediamtx:8554/cameraN` (xem `code/ai_service/config.docker.yaml`).
