# Backend API (.NET 8)

Thư mục dành cho Backend API của nhóm Backend & IoT: quản lý thiết bị, IoT Service (MQTT/HTTP), Event & Risk Engine, người dùng và cảnh báo. Service này chạy trong `docker-compose.yml` chung với tên `backend`, ở cổng **5250**.

## 1. Đưa code vào đây (làm một lần)

**Cách A: giữ lịch sử commit của repo Backend cũ (khuyên dùng)**

```powershell
cd <thu-muc-HitekLab>
git checkout -b feature/add-backend
git subtree add --prefix=code/backend <url-repo-backend> main
```

Lệnh trên chép toàn bộ repo Backend vào `code/backend/` và giữ nguyên lịch sử commit. Nếu repo Backend đã có `Dockerfile` riêng thì so sánh với file `Dockerfile` mẫu ở đây và giữ một bản.

**Cách B: chỉ copy code**

Chép thư mục solution (file `.sln` cùng các project) vào `code/backend/`, rồi commit.

Sau đó tạo Pull Request vào `main`.

## 2. Khai báo project trong `.env`

```dotenv
COMPOSE_PROFILES=ai,backend
BACKEND_BASE_URL=http://backend:5250
BACKEND_PROJECT=Hitek.Backend.Api/Hitek.Backend.Api.csproj   # đường dẫn .csproj, tính từ code/backend/
BACKEND_DLL=Hitek.Backend.Api.dll                             # tên dll sau khi publish
```

Thay tên project cho đúng với code thật, rồi chạy `docker compose up -d --build`.

## 3. Backend cần đọc cấu hình từ biến môi trường

Compose truyền các biến sau. ASP.NET Core tự map `A__B` thành khóa cấu hình `A:B`.

| Biến môi trường | Khóa trong appsettings | Giá trị trong Docker |
| --- | --- | --- |
| `ConnectionStrings__Default` / `ConnectionStrings__DefaultConnection` | `ConnectionStrings:Default` | `Host=postgres;Port=5432;Database=hitek_ai_iot;...` |
| `ASPNETCORE_URLS` | | `http://+:5250` |
| `ASPNETCORE_ENVIRONMENT` | | `Development` |

Các cấu hình khác như MQTT broker, danh sách client (`ai-service` / `ai-service-dev-secret`), JWT key... thì Backend tự khai báo tên khóa. Gửi danh sách khóa cho nhóm AI, hoặc tự thêm vào mục `backend.environment` trong `docker-compose.yml`, theo dạng `Ten__Khoa: giá trị`. Nếu chuỗi kết nối database dùng tên khóa khác (ví dụ `ConnectionStrings:Postgres`) thì cũng thêm như vậy. Không ghi cứng `localhost` trong code: trong Docker, database có địa chỉ `postgres`, không phải `localhost`.

## 4. Quy ước database dùng chung

Backend và Zone Service dùng chung Postgres `hitek_ai_iot`. Mỗi bảng chỉ có **một bên** tạo và sửa cấu trúc:

| Bảng | Bên quản lý cấu trúc | Bên còn lại |
| --- | --- | --- |
| `tenant`, `location`, `camera`, `camera_reference_frame`, `zone`, `rule_config`, `ai_event`, `evidence` | Zone Service (`code/database/postgres/init/*.sql`) | Backend chỉ đọc (đọc `ai_event` để kiểm tra `aiEventId`) |
| `app_user`, `tenant_member` | SQL init (đã có sẵn) | Backend ghi dữ liệu, không đổi cấu trúc |
| `alert` và các bảng cảnh báo, sensor, sensor_reading, risk_rule... | **Backend** (EF Core migration hoặc SQL riêng) | Zone Service chỉ ghi dòng ánh xạ `alert` khi cần giữ khóa ngoại |

Muốn đổi bảng của bên kia: mở issue hoặc PR và tag người quản lý bảng đó.

## 5. Chạy Backend ngoài Docker khi đang code

```powershell
docker compose stop backend
# trong .env của bạn: BACKEND_BASE_URL=http://host.docker.internal:5250
docker compose up -d zone-service      # nạp lại BACKEND_BASE_URL
cd code\backend
dotnet run --project <Project>.csproj --urls http://0.0.0.0:5250
```

Khi chạy ngoài Docker, Backend kết nối database qua `Host=localhost;Port=5432`, vì compose đã mở cổng 5432 ra máy.

Code xong, trả lại `.env` về `BACKEND_BASE_URL=http://backend:5250` và chạy `docker compose up -d --build backend`.
