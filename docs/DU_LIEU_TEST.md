# Dữ liệu test cho AI Service

Tài liệu này tổng hợp các nguồn video để kiểm thử và đo kết quả (precision/recall/F1, độ trễ) cho các tình huống của đề án. Video **không commit vào git**: tải về rồi đặt vào `code/data/videos/` (hoặc thư mục chung của nhóm), sau đó khai báo tên file trong `.env` (`CAMERA1_VIDEO`, `CAMERA2_VIDEO`).

> Đề án mục 10 yêu cầu: *"Dữ liệu thử nghiệm phải được quản lý tách biệt với mã nguồn và có mô tả nguồn gốc."* Mỗi video đưa vào thư mục chung phải ghi rõ nguồn và giấy phép, theo bảng ở mục 4.

## 1. Chọn bộ nào cho tình huống nào

| Tình huống của đề án | Nguồn nên dùng | Ghi chú |
| --- | --- | --- |
| Kiểm tra luồng hệ thống, demo | 2 video đang có + **tự quay** | Tự vẽ zone cho phù hợp với video |
| Xâm nhập vùng cấm, ngoài giờ quy định | **Tự quay**, CAVIAR (INRIA) | Vẽ vùng cấm ở lối đi; ngoài giờ = bật khung giờ |
| Lảng vảng / đứng lâu | **CAVIAR**: nhóm *Browsing*, *Resting* | Có nhãn XML theo frame, cho phép dùng lại (CC BY-SA) |
| Số người vượt ngưỡng | **Mall dataset**, CAVIAR *Meeting* | Mall có số người đếm sẵn ở từng frame |
| Tracking giữ ID ổn định | **MOT17** (tập train) | Có nhãn bbox + ID từng frame; dùng các chuỗi quay bằng camera đứng yên |
| Xe máy, ô tô | **Tự quay** đường/cổng ở Việt Nam; VIRAT Ground (ô tô) | Bộ dữ liệu nước ngoài gần như không có xe máy |
| Vật thể bị bỏ lại (tùy chọn) | **ABODA**, CAVIAR *Leaving bags* | |

## 2. Chi tiết từng bộ

### CAVIAR: phù hợp nhất (lảng vảng, gặp nhau, bỏ túi)

- Link: <https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/>
- **Tập INRIA** (sảnh tòa nhà, camera trên cao): khoảng 26 clip, gồm *Walking*, *Browsing*, *Resting/Slumping/Fainting*, *Leaving bags*, *Meeting/Walking together/Splitting*, *Fighting*.
- **Tập Lisbon** (hành lang trung tâm thương mại): 26 tình huống, mỗi tình huống quay từ 2 góc.
- Định dạng: MPEG2 384×288, 25 fps, mỗi clip 6–21 MB. Nhãn XML (CVML) theo từng frame: bbox, ID, hoạt động, tình huống.
- Giấy phép: **Creative Commons BY-SA**. Khi dùng phải ghi nguồn *"EC Funded CAVIAR project/IST 2001 37540"* kèm link trang trên.
- Lưu ý: độ phân giải thấp nên người ở xa nhỏ. Có thể phải hạ `YOLO_CONFIDENCE` xuống 0.25, hoặc dùng model `yolo11s.pt`.

### Mall dataset: đếm người / đông người

- Link trang: <https://personal.ie.cuhk.edu.hk/~ccloy/downloads_mall_dataset.html>, file: `mall_dataset.zip`.
- 2.000 frame JPEG 640×480 từ webcam trong trung tâm thương mại, **dưới 2 fps**. Hơn 60.000 người được gán nhãn vị trí đầu ở mọi frame.
- Dùng để so sánh số người AI đếm được với số thật ở từng frame, tức kiểm tra rule `crowd_limit`.
- Muốn chạy qua hệ thống thì ghép ảnh thành video:
  `ffmpeg -framerate 2 -i frames/seq_%06d.jpg -c:v libx264 -pix_fmt yuv420p mall.mp4`
  (tên file ảnh trong gói có thể khác, xem lại trước khi chạy).
- Tracking kém chính xác ở 2 fps, nên chỉ dùng để đo **đếm người**, không đo tracking.
- Giấy phép: **chỉ dùng cho nghiên cứu, không thương mại**. Báo cáo phải trích dẫn bài ICCV 2013 *"From Semi-Supervised to Transfer Counting of Crowds"*.

### MOT17: đánh giá tracking

- Link: <https://motchallenge.net/data/MOT17/>. Bản đầy đủ khoảng 5.5 GB; chỉ cần tải tập train.
- 7 chuỗi train có nhãn bbox + ID theo frame. Nên chọn các chuỗi quay bằng camera đứng yên giống camera giám sát (kiểm tra trong `seqinfo.ini` và mô tả trên trang).
- Dùng để đo độ ổn định ID: số lần đổi ID (ID switch), MOTA/IDF1. Có thể dùng công cụ `TrackEval` của chính MOTChallenge.
- Giấy phép: xem điều khoản trên trang MOTChallenge trước khi đưa vào báo cáo.

### ABODA: vật thể bị bỏ lại

- Link: <https://github.com/kevinlin311tw/ABODA> (`video1.avi` … `video11.avi`).
- 11 video: trong nhà, ngoài trời, đông người, ánh sáng thay đổi, ban đêm.
- Repo không ghi giấy phép rõ ràng. Chỉ dùng nội bộ để test, hỏi tác giả trước khi đưa hình vào báo cáo.

### VIRAT Video Dataset (Ground): người và xe ngoài trời

- Mô tả: [bài báo CVPR 2011](https://people.csail.mit.edu/jenny/papers/cvpr2011_virat.pdf). Tải qua trang VIRAT của Kitware, cần đăng ký ([thông tin tải](https://public.kitware.com/pipermail/viratdata/2018-July/000025.html)).
- Camera giám sát cố định ngoài trời, có nhãn sự kiện người và xe (ra vào xe, chất hàng...). Dung lượng rất lớn.
- Chỉ nên tải vài clip nếu cần thử ô tô trong bãi đỗ.

### Bộ dữ liệu cần xin phép (không khuyên dùng trong thời gian thực tập)

- **PETS 2006 / AVSS 2007 (i-LIDS)**: hành lý bị bỏ lại ở nhà ga, đỗ xe trái phép. Phải gửi yêu cầu, thời gian chờ không chắc chắn.

## 3. Tự quay: cách nhanh nhất cho xe máy và kịch bản sát đề tài

Chuẩn bị: điện thoại cố định trên cao khoảng 2–3 m, nhìn chéo xuống. Quay ngang 1280×720, 25–30 fps. Mỗi clip 30–60 giây, **một tình huống mỗi clip**.

| Clip | Kịch bản | Kết quả mong đợi |
| --- | --- | --- |
| `S01_di_ngang` | 1 người đi ngang qua vùng, không dừng | Không có cảnh báo lảng vảng |
| `S02_xam_nhap` | 1 người đi vào vùng cấm | `person_intrusion` (với `Duration = 0–3`) |
| `S03_lang_vang` | 1 người vào vùng, đi tới đi lui 20 giây | `loitering` sau `duration_threshold` |
| `S04_vao_ra_nhanh` | Vào vùng 3 giây rồi ra | Không có `loitering` (ngưỡng 10 giây) |
| `S05_tu_tap` | 4 người lần lượt vào vùng và đứng 20 giây | `crowd_limit` khi số người ≥ ngưỡng |
| `S06_che_khuat` | 2 người đi cắt ngang nhau trong vùng | ID không đổi, hoặc được gắn lại; không báo trùng |
| `S07_xe_may_dung` | Xe máy chạy vào và dừng trong vùng 20 giây | `vehicle_stopping` (`object_type = vehicle`) |
| `S08_huong_di` | 1 người đi trái → phải, rồi phải → trái | Mũi tên `→` rồi `←` |
| `S09_toi` | Lặp lại S02 trong điều kiện thiếu sáng | Ghi nhận hạn chế, nếu có |
| `S10_bo_tui` (tùy chọn) | Đặt ba lô xuống rồi đi khỏi | Vật thể bị bỏ lại (khi có tính năng) |

Lưu ý: chỉ quay thành viên nhóm, hoặc người đã đồng ý. Không quay người qua đường rồi đưa hình vào báo cáo.

## 4. Ghi nhãn và quản lý dữ liệu

**Nhãn theo sự kiện** (đủ để tính precision/recall/F1 và độ trễ cảnh báo, không cần vẽ bbox): mỗi video một dòng cho mỗi sự kiện, thời gian tính bằng giây từ đầu video.

```csv
video,zone,event_type,start_s,end_s,note
S03_lang_vang.mp4,Kho,loitering,4,26,1 nguoi di toi di lui
S05_tu_tap.mp4,Sanh,crowd_limit,10,32,4 nguoi
S01_di_ngang.mp4,Kho,none,0,0,khong duoc bao
```

**Bảng nguồn gốc**: ghi vào `code/data/SOURCES.md`. File này được commit; thư mục `code/data/videos/` thì không.

| File | Nguồn | Giấy phép | Người thêm | Ghi chú |
| --- | --- | --- | --- | --- |
| `caviar_browse1.mpg` | CAVIAR INRIA, Browse1 | CC BY-SA | Hà | |
| `S03_lang_vang.mp4` | Nhóm tự quay 30/10/2026 | Nội bộ | Hà | Có đồng ý của người trong video |

**Nơi lưu:** thư mục chung của nhóm (Drive, OneDrive...). Mỗi người tải về `code/data/videos/`. Không đưa lên git; `.gitignore` đã bỏ qua toàn bộ `code/data/videos/`.
