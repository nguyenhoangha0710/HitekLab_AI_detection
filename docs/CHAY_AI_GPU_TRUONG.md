# Chạy AI trên GPU của trường (khoa-gpu): ghi chú nhanh

## 1. Cơ chế kết nối

### Ai chạy ở đâu

| Máy | Chạy gì | Cổng |
| --- | --- | --- |
| **Laptop** (Windows + Docker) | camera giả lập, Edge Gateway, Zone Service + dashboard, Postgres, MinIO | Zone Service `8010` |
| **Server khoa-gpu** (Tesla T4) | **chỉ AI Service** (YOLO + ByteTrack + hướng di chuyển + rule engine), chạy bằng Python | AI `18003`, chỉ nghe ở `127.0.0.1` |

Hai máy không gọi thẳng nhau được: server nằm trong mạng trường, phải đi qua máy trung gian `103.130.211.150`, nên mỗi lần SSH phải nhập mật khẩu 2 lần. Vì vậy dùng **một kết nối SSH làm "ống"** để chở dữ liệu qua lại.

### Hai chiều của đường hầm (một lệnh `ssh` mở cả hai)

```text
           LAPTOP                                              SERVER khoa-gpu
 ┌───────────────────────────────┐                 ┌────────────────────────────────┐
 │ edge-gateway (Docker)         │                 │                                │
 │   └► host.docker.internal:28003 ══ -L ════════════► 127.0.0.1:18003  AI Service  │
 │        (cổng 28003 của laptop)│   chiều ĐI       │                   (GPU T4)     │
 │                               │                 │                     │          │
 │ zone-service :8010  ◄══════════ -R ═══════════════ localhost:18010 ◄───┘          │
 │   (Docker, mở ra laptop)      │   chiều VỀ       │  (AI lấy zone/rule, gửi sự kiện)│
 └───────────────────────────────┘                 └────────────────────────────────┘
        ssh -N -L 28003:localhost:18003 -R 18010:localhost:8010 khoa-gpu
```

- **`-L 28003:localhost:18003`** (Local forward): chương trình trên laptop gửi vào cổng `28003` thì dữ liệu chui qua ống, ra ở `localhost:18003` **trên server**, tức là AI.
- **`-R 18010:localhost:8010`** (Remote forward, chiều ngược): chương trình trên server gửi vào cổng `18010` thì dữ liệu chui qua ống, ra ở `localhost:8010` **trên laptop**, tức là Zone Service.
- **`host.docker.internal`**: container Docker dùng tên này để gọi cổng của chính laptop. Edge Gateway gọi `ws://host.docker.internal:28003/ws/detect`, đi vào đầu ống `-L`.
- Dùng cổng **28003** chứ không dùng 8003 vì trên Windows cổng 8003 bị VS Code hoặc Windows giữ (lỗi `bind ... Permission denied`). Số cổng này nằm trong `.env` (`AI_SERVICE_PORT=28003`).

### Hành trình của một frame

1. Camera giả lập phát video lên MediaMTX. **Edge Gateway** cắt frame (laptop, Docker).
2. Edge Gateway gửi frame tới `host.docker.internal:28003`, qua **ống -L**, tới AI ở `127.0.0.1:18003` trên server.
3. AI chạy YOLO trên **GPU T4** (khoảng 10–30 ms) rồi trả khung, ID, hướng di chuyển về theo đúng đường đó. Tab YOLO Detection hiện kết quả kèm `GPU Tesla T4 @ khoa-gpu`.
4. Nếu có vi phạm, AI gọi `localhost:18010` trên server, qua **ống -R**, tới **Zone Service** `:8010` trên laptop. Zone Service lưu `ai_event`, chụp ảnh, xin clip, rồi gửi sang Backend.
5. Cứ khoảng 10 giây, AI hỏi Zone Service danh sách zone/rule mới, cũng qua **ống -R**.

### Tắt cửa sổ nào thì mất gì

| Tắt | Hậu quả |
| --- | --- |
| Terminal AI trên server | Không còn khung AI; video vẫn chạy |
| Cửa sổ `ssh -N ...` (cửa sổ B) | Mất cả hai ống: không có khung, không có cảnh báo |
| Docker | Không có video, không có dashboard |
| VS Code | Chỉ mất terminal AI (nếu AI chạy trong terminal VS Code mà không có tmux). Đường hầm ở cửa sổ B **không** phụ thuộc VS Code |

## 2. Lệnh chạy mỗi lần (copy theo thứ tự)

### Cửa sổ A: server (VS Code Remote-SSH `khoa-gpu`, hoặc `ssh khoa-gpu` trong PowerShell)

```bash
cd ~/HitekLab
git pull
CONDA_ENV=base bash scripts/run_ai_remote.sh
```

Đúng khi thấy `CUDA : True - Tesla T4` và `Uvicorn running on http://127.0.0.1:18003`. **Để nguyên cửa sổ này.** Dòng cảnh báo `chua goi duoc http://localhost:18010` lúc mới chạy là bình thường; sau bước B và C nó tự thông.

### Cửa sổ B: PowerShell trên laptop, mở đường hầm

```powershell
ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -L 28003:localhost:18003 -R 18010:localhost:8010 khoa-gpu
```

Nhập mật khẩu 2 lần. Lệnh **đứng im** là đúng. **Để nguyên cửa sổ này.**

### Cửa sổ C: PowerShell trên laptop, bật Docker

Mở Docker Desktop, đợi chữ *Engine running*, rồi:

```powershell
cd D:\NguyenHoangHa_nam4\Internship\HitekLab
git pull
.\scripts\use-ai.ps1 remote
```

Đúng khi dòng cuối in màu xanh: `AI dang chay : GPU Tesla T4 @ khoa-gpu`.

### Kiểm tra

- Trình duyệt: http://localhost:8010, tab YOLO Detection: thấy `GPU Tesla T4 @ khoa-gpu` (chữ xanh), `ai ...ms` nhỏ.
- Chiều về (gõ trên server, ở terminal khác): `curl -s -m 3 localhost:18010/health` phải ra JSON `zone-management-service`.
- Bất kỳ lúc nào trên laptop: `.\scripts\use-ai.ps1 status`.

### Tắt khi xong việc (để trả GPU)

```text
Cửa sổ C:  docker compose down
Cửa sổ B:  Ctrl+C
Cửa sổ A:  Ctrl+C
```

### Quay về chạy hết trên laptop (không cần server)

```powershell
.\scripts\use-ai.ps1 cpu
```

## 3. Lỗi hay gặp

| Lỗi | Ở đâu | Cách xử lý |
| --- | --- | --- |
| `bind [127.0.0.1]:28003: Permission denied` / `Address already in use` | Cửa sổ B | Đổi sang cổng khác, ví dụ 38003: sửa `AI_SERVICE_PORT=38003` trong `.env`, dùng `-L 38003:localhost:18003`, chạy lại `use-ai.ps1 remote` |
| `remote port forwarding failed for listen port 18010` | Cửa sổ B | Cổng 18010 trên server bị chiếm. Dùng `-R 18110:localhost:8010`, và chạy AI bằng `ZONE_SERVICE_URL=http://localhost:18110 CONDA_ENV=base bash scripts/run_ai_remote.sh` |
| `address already in use ... 18003` | Cửa sổ A | AI đã chạy ở terminal khác rồi, không cần chạy lại. Muốn chạy lại thì `Ctrl+C` ở terminal cũ trước |
| `use-ai.ps1 status` báo `AI chua tra loi` | Cửa sổ C | Kiểm tra cửa sổ B còn chạy không; AI ở cửa sổ A còn chạy không; lần đầu đợi khoảng 30 giây để AI tải model |
| Có khung nhưng không có cảnh báo | | Chiều về chưa thông: chạy `curl localhost:18010/health` trên server; kiểm tra Docker đang chạy và cửa sổ B có `-R 18010:localhost:8010` |
| Mở terminal VS Code báo `cwd ... does not exist` | VS Code | File → Open Folder → `/home/hoangha/HitekLab` |

## 4. Cải thiện (tùy chọn)

- **Không phải nhập mật khẩu 2 lần:** tạo SSH key (`ssh-keygen -t ed25519`), rồi chép khóa công khai lên cả máy trung gian lẫn máy GPU (`~/.ssh/authorized_keys`).
- **AI vẫn chạy khi đóng VS Code:** `conda install -c conda-forge tmux -y`, rồi chạy AI trong `tmux new -s hitek-ai` (thoát giữ AI chạy: `Ctrl+B` rồi `D`; vào lại: `tmux attach -t hitek-ai`).
- **Dùng chung GPU lịch sự:** xem `nvidia-smi` trước khi chạy; script tự chọn GPU đang rảnh nhất; tắt AI khi không dùng.
