# HITEK AI-IoT: Phát hiện và cảnh báo bất thường

Prototype đề án thực tập HITEK SOLUTION: camera/cảm biến → AI phân tích → hợp nhất sự kiện → cảnh báo → lưu trữ và tra cứu.

> **Chạy lần đầu?** Đọc [HUONG_DAN_CHAY.md](HUONG_DAN_CHAY.md). Tóm tắt:
>
> ```powershell
> Copy-Item .env.example .env
> docker compose up -d --build
> # mở http://localhost:8010
> ```

## Kiến trúc đang chạy

```text
video (code/data/videos) ─► camera1/camera2 (FFmpeg) ─RTSP─► mediamtx
   ─► edge-gateway :8002 ── frame (AI_FPS) ──► ai-service :8003  YOLOv11 → ByteTrack → Rule Engine
         │                                         │
         │ live video / frame theo frame_id        │ POST /api/ai-events
         ▼                                         ▼
   zone-service :8010  ◄─────────────────────────────  (alert, snapshot, clip ±5s)
   Dashboard + API  ──► postgres :5432 (metadata)  +  minio :9000 (ảnh / clip)
```

| Service | Thư mục | Nhóm phụ trách |
| --- | --- | --- |
| `edge-gateway` | `code/ai_service/edge_gateway` | AI / Camera |
| `ai-service` | `code/ai_service` (`local_bbox_service.py`, `rule_engine/`) | AI / Camera |
| `zone-service` (backend + dashboard) | `code/zone_service` | Backend, Frontend |
| Database | `code/database/postgres/init` | Backend |
| IoT Service, Event & Risk Engine | *chưa có* | Backend & IoT |

## Cấu trúc repo

```text
.
├── docker-compose.yml        # toàn bộ hệ thống
├── docker-compose.gpu.yml    # override khi máy có GPU NVIDIA
├── .env.example              # mẫu cấu hình, copy thành .env
├── HUONG_DAN_CHAY.md         # hướng dẫn cài đặt và chạy cho cả nhóm
├── code/
│   ├── ai_service/           # Edge Gateway + AI Service (Dockerfile multi-stage)
│   ├── zone_service/         # Backend FastAPI + frontend dashboard
│   ├── database/postgres/    # SQL khởi tạo schema + seed
│   └── data/                 # video/ảnh test (không commit video lớn)
└── docs/                     # API contract, contract Camera → AI
```

## Tài liệu

- [HUONG_DAN_CHAY.md](HUONG_DAN_CHAY.md): cài đặt, các chế độ chạy, xử lý sự cố.
- [code/ai_service/README.md](code/ai_service/README.md): AI Service, Rule Engine, API `:8003`.
- [code/zone_service/README.md](code/zone_service/README.md): Zone Service và dashboard.
- [code/database/postgres/README.md](code/database/postgres/README.md): schema database.
- [docs/API_CONTRACT_AND_CONVENTIONS.md](docs/API_CONTRACT_AND_CONVENTIONS.md): contract chung giữa các nhóm.
