# Phân quyền theo tenant và location

Câu hỏi của mentor: *một tenant có nhiều location, mỗi user trong tenant chỉ phụ trách một số location. Làm sao tách dữ liệu để phân quyền?*

## 1. Mô hình

```text
tenant ── location ── camera ── zone ── rule_config
   │                     └──── ai_event ── evidence ── alert
   └── tenant_member (role: owner | admin | operator | viewer)
          └── user_location_access (location_id, permission_level: admin | operator | viewer)
```

| Lớp | Bảng | Ý nghĩa |
| --- | --- | --- |
| Vai trò trong tenant | `tenant_member.role` | `owner`, `admin`: quản lý toàn tenant, là **admin ở mọi location**. `operator`, `viewer`: chỉ thấy location được gán |
| Quyền theo location | `user_location_access` | Mỗi dòng gán một user vào một location với một mức quyền |

| `permission_level` | Được làm |
| --- | --- |
| `viewer` | Xem camera, zone, sự kiện, bằng chứng, cảnh báo |
| `operator` | Như viewer, cộng xử lý cảnh báo (ghi sự kiện, xác nhận) |
| `admin` | Như operator, cộng chụp ảnh nền, vẽ, sửa, xóa zone, sửa rule |

Mọi dữ liệu đều quy về `camera.location_id`, nên chỉ cần một câu hỏi: **user này được những location nào, ở mức nào?**

## 2. Cách Zone Service áp dụng

Code: `code/zone_service/backend/app/access_control.py`.

1. **Xác thực**: lấy token từ header `Authorization: Bearer <JWT>`. Với `<img>`, `<video>`, `EventSource` thì lấy từ tham số `?access_token=`. Kiểm tra chữ ký, hạn dùng, issuer, audience.
2. **Lấy danh sách location**: dùng `sub` (id hoặc email user) và `tenant_id` (id hoặc code tenant) trong token để tra `tenant_member` và `user_location_access`. **Danh sách location không nằm trong token** mà được tra lại, cache 30 giây. Nhờ vậy admin giao hoặc rút quyền thì có hiệu lực sau tối đa 30 giây, không phải cấp lại token.
3. **Lọc dữ liệu**: các API danh sách (`/api/cameras`, `/api/ai-events`, `/api/alerts`, `/api/evidence`) chỉ trả dữ liệu của camera thuộc location được phép.
4. **Kiểm tra từng bản ghi**: các API theo id (camera, zone, rule, evidence, ảnh nền, video live, luồng detection) đều lần ngược về camera để kiểm tra location.
   - Không có quyền: **404**, không để lộ là bản ghi có tồn tại.
   - Có quyền xem nhưng thiếu mức quyền (ví dụ viewer sửa zone): **403**.
5. **Không bao giờ lấy tenant từ tham số client gửi lên.** Tenant luôn lấy từ token.
6. **Service nội bộ** (AI Service, Edge Gateway) dùng header `X-Service-Key: <SERVICE_API_KEY>` và có toàn quyền. Quyền chỉ áp lên user, ở đầu ra dữ liệu.

| API | Mức tối thiểu |
| --- | --- |
| `GET` camera, video live, ảnh, luồng detection, zone, rule, sự kiện, bằng chứng | `viewer` tại location của camera |
| `POST /api/ai-events`, `POST /api/evidence/video` | `operator` (AI Service, Edge Gateway dùng service key) |
| Chụp ảnh nền, tạo, sửa, xóa zone, sửa rule | `admin` tại location đó |
| `GET /api/integration/backend` | owner/admin của tenant |
| `GET /api/me` | Mọi user đã đăng nhập: thông tin user và danh sách location kèm mức quyền |

## 3. Thống nhất với Backend (.NET)

Backend là nơi **đăng nhập và cấp JWT**, đồng thời quản lý user (bảng `app_user`, `tenant_member`, `user_location_access`). Zone Service chỉ **kiểm tra** token. Hai bên cần thống nhất:

| Mục | Zone Service đang chờ | Biến cấu hình |
| --- | --- | --- |
| Thuật toán ký | `HS256` (khóa bí mật dùng chung) hoặc `RS256` (khóa công khai) | `JWT_ALGORITHM`, `JWT_SECRET` / `JWT_PUBLIC_KEY_FILE` |
| Claim id user | `sub` = `app_user.id` (hoặc email) | `JWT_USER_CLAIM` |
| Claim tenant | `tenant_id` = `tenant.id` (hoặc `tenant.code`) | `JWT_TENANT_CLAIM` |
| Issuer / audience | Không bắt buộc | `JWT_ISSUER`, `JWT_AUDIENCE` |

Backend cũng nên áp **cùng quy tắc** cho API cảnh báo, cảm biến và real-time:
- lọc theo location;
- SignalR cho user vào nhóm `location:{id}` theo quyền, và chỉ đẩy cảnh báo vào nhóm của location đó.

## 4. Dữ liệu demo

File `code/database/postgres/init/006_demo_location_access.sql`:

| User | Vai trò | Thấy |
| --- | --- | --- |
| `owner@demo.local` | owner | Warehouse + Main Gate (admin) |
| `admin@demo.local` | admin | Warehouse + Main Gate (admin) |
| `kho.operator@demo.local` | operator | **Chỉ Warehouse** (operator: xem, không sửa zone) |
| `cong.viewer@demo.local` | viewer | **Chỉ Main Gate** (chỉ xem) |

Demo cho mentor:
1. Trong `.env` đặt `AUTH_MODE=jwt` và `AUTH_DEV_LOGIN=true`, rồi chạy `docker compose up -d --build`.
2. Mở http://localhost:8010, chọn user trong ô **Đăng nhập demo**.
3. `kho.operator` chỉ thấy Camera 01; vào Zone Editor sửa zone sẽ bị báo 403. `cong.viewer` chỉ thấy Camera 02. `owner` thấy cả hai.
4. Thử gọi trực tiếp: `GET /api/cameras/<id camera của location khác>` thì nhận 404.

Khi Backend đã có màn hình đăng nhập: đặt `AUTH_DEV_LOGIN=false`, dùng token Backend cấp (frontend có ô dán token, hoặc frontend của Backend gửi kèm).

## 5. Giới hạn hiện tại

- Edge Gateway (cổng 8002) và MinIO (9000/9001) đang **mở ra máy host để dev**, nên vẫn xem trực tiếp được mà không qua kiểm tra quyền. Khi triển khai thật, chỉ mở cổng 8010 (và cổng Backend); bỏ phần `ports` của `edge-gateway` và `minio` trong compose.
- Token trên URL (`?access_token=`) có thể bị ghi vào log truy cập. Bản thật nên dùng token ngắn hạn riêng cho media, hoặc cookie.
- Chưa có cấp location cha/con (khu → tòa → tầng). Khi cần: thêm `location.parent_id`, quyền ở cấp cha tự áp xuống cấp con.
- Chưa có Row-Level Security ở Postgres làm lớp bảo vệ thứ hai.
