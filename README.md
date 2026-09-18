# hls-dl — tải video streaming, đặt tên theo tên tập

Xử lý đúng 2 vấn đề:

1. **Một video bị chia thành nhiều mảnh** → tải hết đúng thứ tự, giải mã AES-128 nếu có, ghép thành 1 `.mp4` (copy stream — nhanh, không giảm chất lượng). Nhận **HLS** (`.m3u8`), **DASH** (`.mpd`) và file tải thẳng; đoán không ra thì hỏi `Content-Type` của server.
2. **Tên file lộn xộn** → tên mảnh trên server (`50d6c3f0..._seg_00001.ts`) *không bao giờ* dùng làm tên file. Tên lấy từ **tên tập trong DOM** (`E1. Just an Old Book`), thư mục lấy từ **tên tác phẩm** (`My Vampire System`).

Link video không nằm trong HTML — nó chỉ sinh ra khi player chạy và gọi request. Nên cả hai công cụ bắt link đều hook vào tầng network lúc runtime, chứ không đọc HTML tĩnh.

## Cài đặt

Python 3.8 trở lên (đã chạy thực tế trên 3.12):

```bash
pip install -r requirements.txt
```

Cần thêm **ffmpeg** trên PATH — dùng để ghép các mảnh, không cài bằng pip được:

```bash
winget install Gyan.FFmpeg      # Windows
brew install ffmpeg             # macOS
sudo apt install ffmpeg         # Debian/Ubuntu
```

Chỉ khi dùng [auto_grab.js](auto_grab.js) mới cần thêm Playwright:

```bash
npm i playwright && npx playwright install chromium
```

`grab.js` không cần cài gì — nó chạy thẳng trong Console trình duyệt.

## Cấu hình: [.env](.env)

**Toàn bộ cấu hình ở [`.env`](.env) — không phải sửa code.** Mỗi mục có giải thích kèm theo; [.env.example](.env.example) là bản gốc để đối chiếu.

Tối thiểu cần điền một dòng:

```ini
SHOW_URL=https://site.com/show/<ma-show>
OUTPUT_DIR=D:/Videos
```

| Nhóm | Khoá | Việc |
|---|---|---|
| Tác phẩm | `SHOW_URL` | trang liệt kê các tập — **bắt buộc**; nhiều tác phẩm thì ngăn bằng dấu phẩy |
| | `SITE_URL` | gốc site; để trống → suy từ `SHOW_URL` |
| Nhận tên | `EPISODE_TITLE_RE` | mẫu nhận tên tập; để trống → mặc định (xem dưới) |
| | `EPISODE_SELECTOR` | chỉ định thẳng selector nếu tự nhận dạng sai |
| | `SERIES_TITLE_SELECTOR` | nơi chứa tên tác phẩm; để trống → thử `aria-label` rồi `<h1>` |
| | `SERIES_NAME` | ép cứng tên tác phẩm |
| | `PLAY_SELECTOR` | nút Play; để trống → tự gọi `.play()` trên `<video>` |
| Đặt tên | `NAME_TEMPLATE` | mẫu tên file (xem dưới) |
| | `GROUP_BY_SERIES` | `true` → mỗi tác phẩm một thư mục riêng |
| Đăng nhập | `COOKIE` `AUTH_HEADER` `REFERER` | chỉ cần khi chạy `hls_dl.py` trực tiếp |
| Tải | `OUTPUT_DIR` `MANIFEST` `WORKERS` `RETRIES` | thư mục lưu, file manifest, số luồng, số lần thử lại |
| Playwright | `BROWSER_PROFILE` `HEADLESS` `WAIT_MS` `SETTLE_MS` | phiên đăng nhập, chạy ẩn, thời gian chờ |

Thứ tự ưu tiên: **dòng lệnh > biến môi trường > `.env` > mặc định**.

`.env` chứa cookie = phiên đăng nhập của bạn, nên [.gitignore](.gitignore) đã loại sẵn.

### Nhận diện tên tập

Tên tập thường nằm trong `<span>` **không có class nào để bám**, nên công cụ bám theo *mẫu chữ* thay vì theo class. Mặc định nhận:

```
E1. Just an Old Book     TAP      My Vampire System    bỏ qua
E10. Blood Moon          TAP      1.5B plays           bỏ qua
Ep 2 - The Awakening     TAP      Fantasy              bỏ qua
Episode 3: Trial         TAP      Every day            bỏ qua
Tập 4. Khởi đầu          TAP      E1  (thiếu dấu .)    bỏ qua
```

Muốn biết trang của bạn cho ra gì thì dán [grab.js](grab.js) vào Console rồi gõ `HLS.probe()`.

### Đặt tên file

`NAME_TEMPLATE` dùng được `{index}`, `{title}`, `{series}`:

| Mẫu | Kết quả |
|---|---|
| `{index:03d} - {title}` *(mặc định)* | `001 - E1. Just an Old Book.mp4` |
| `{title}` | `E1. Just an Old Book.mp4` |
| `{series} - {title}` | `My Vampire System - E1. Just an Old Book.mp4` |

Nên giữ `{index:03d}` ở đầu: tên tập tuy đã có số, nhưng File Explorer sắp theo chữ cái nên ra `E1, E10, E11, E2`. Số zero-pad mới cho đúng thứ tự.

Với `GROUP_BY_SERIES=true`:

```
D:/Videos/My Vampire System/001 - E1. Just an Old Book.mp4
D:/Videos/My Vampire System/002 - E2. The Awakening.mp4
```

## Cách 1 — tự động (khuyến nghị nếu nhiều tập)

```bash
npm init -y && npm i playwright && npx playwright install chromium
node auto_grab.js
python hls_dl.py
```

`auto_grab.js` mở Chromium thật, cuộn hết danh sách tập (lazy load), rồi lần lượt mở/bấm từng tập, đợi link xuất hiện, ghi `manifest.json`. Xử lý được cả trang SPA khi bấm tập không chuyển trang.

Lần đầu trình duyệt dừng lại cho bạn **đăng nhập bằng tay**, bấm Enter trong terminal là chạy tiếp. Phiên lưu ở `BROWSER_PROFILE` nên lần sau khỏi làm lại — cũng vì thế mà cách này không cần `COOKIE`.

## Cách 2 — thủ công (nhanh hơn nếu chỉ vài tập)

1. Mở trang tác phẩm → F12 → **Console** → dán toàn bộ [grab.js](grab.js) → Enter. **Làm trước khi bấm Play.**
2. `await HLS.auto({ tu: 1, den: 38 })` — cuộn tới tập 38 rồi bấm phát lần lượt tập 1→38 và bắt link.
3. `HLS.save()` → tải `manifest.json` về, để cạnh `hls_dl.py`.
4. `python hls_dl.py`

Cách này không cần cài gì thêm và chạy trong chính trình duyệt bạn đang đăng nhập.

**Luôn nói rõ khoảng `tu`/`den`.** Danh sách tập lazy-load, cuộn tới đâu trang nạp thêm tới đó — một bộ dài có thể hơn 1000 tập. Không giới hạn thì `auto()` sẽ bấm hết và tải về hàng trăm GB, nên nó từ chối chạy khi quá 100 tập và bảo bạn nêu khoảng.

Ngắt giữa chừng cứ gọi lại `await HLS.auto()` — tập nào đã bắt được sẽ bỏ qua.

**Tập miễn phí / trả phí.** Tập trả phí không phát được nên không sinh ra link. `auto()` đợi tối đa `waitMs` rồi bỏ qua, và sau **3 tập liên tiếp** không phát được thì dừng hẳn — coi như đã hết phần miễn phí. Không cần biết trước có bao nhiêu tập free:

```js
await HLS.auto({ tu: 1, den: 100 })   // nó tự dừng ở ranh giới
```

Cuối cùng nó in ra khoảng thật sự lấy được, ví dụ `Xong: 38 tap da co link (E1 -> E38)`.

Muốn bấm tay từng tập cũng được: tên tập gắn theo **cú click của bạn**, chính xác hơn mọi cách đoán "tập nào đang active".

| Lệnh | Việc |
|---|---|
| `await HLS.auto({tu, den})` | tự bấm các tập trong khoảng (nên dùng) |
| `await HLS.loadAll({den})` | chỉ cuộn tới tập `den`, đếm số tập |
| `HLS.probe()` | xem script đọc ra tên tác phẩm / tên tập nào |
| `HLS.list()` | bảng những gì đã bắt được |
| `HLS.rename(3, 'E3. The Cave')` | sửa tên bắt sai |
| `HLS.setSeries('My Vampire System')` | đặt lại tên tác phẩm cho tất cả |
| `HLS.drop(5)` | bỏ mục bắt nhầm (quảng cáo, trailer) |
| `HLS.cookie()` | lấy cookie cho `.env` |
| `HLS.save()` | xuất `manifest.json` |

### manifest.json

```json
[
  { "index": 1, "series": "My Vampire System", "title": "E1. Just an Old Book",
    "url": "https://cdn.site/abc/index.m3u8" }
]
```

Sửa tay thoải mái trước khi tải.

## Tham số `hls_dl.py`

Tất cả đều tuỳ chọn — chỉ dùng khi muốn ghi đè `.env` cho một lần chạy.

| Cờ | Ghi đè | Ý nghĩa |
|---|---|---|
| `-o` | — | tên file cho một video lẻ |
| `-d` | `OUTPUT_DIR` | thư mục lưu |
| `-m` | `MANIFEST` | file manifest |
| `-r` | `REFERER` | **nhiều CDN chặn nếu thiếu** (tự set luôn `Origin`) |
| `-c` | `COOKIE` | cookie đầy đủ |
| `-H` | `AUTH_HEADER` | header bất kỳ |
| `-j` | `WORKERS` | số mảnh song song (hạ xuống 3–4 nếu bị chặn) |
| `--retries` | `RETRIES` | số lần thử lại mỗi mảnh |
| `--keep` | — | giữ lại các mảnh sau khi ghép |

Một video lẻ:

```bash
python hls_dl.py "https://cdn.site/abc/index.m3u8" -o "E1. Just an Old Book"
```

## Ghép các mảnh `.ts` đã tải sẵn

```bash
python merge_local.py "D:/tai-ve/tap-01" -o "E1. Just an Old Book" --dry-run
python merge_local.py "D:/tai-ve/tap-01" -o "E1. Just an Old Book"
```

Sắp xếp theo **số cuối cùng** trong tên file, nên phần hash ở đầu không ảnh hưởng:

```
50d6c3f0..._generated_vid_mid_seg_00001.ts   ->  1
50d6c3f0..._generated_vid_mid_seg_00005.ts   ->  5
```

Tự cảnh báo và dừng nếu số thứ tự đứt quãng (thiếu mảnh 2, 3, 4 như trên), vì ghép thiếu mảnh sẽ ra video nhảy cóc. Thêm `--force` nếu vẫn muốn ghép.

**Nếu tên mảnh là hash thuần không có số tăng dần** thì thứ tự không đoán được — phải lưu `.m3u8` gốc rồi dùng `--order playlist.m3u8`.

## Chạy test

```bash
python -m unittest discover -s tests    # 64 test
node tests/test_grab_js.js              # 27 assertion
```

Không cần cài thêm gì — dùng `unittest` của stdlib và `assert` của Node.

Dữ liệu test lấy từ các lần chạy thật, không bịa ra, nên nó canh đúng những chỗ đã từng sai:

| Test | Canh điều gì |
|---|---|
| `test_grab_js.js` | 22 mục thật trên trang phải lọc còn 20 tập; `EP-36` có gạch nối phải cắt đúng; mỗi tập chỉ giữ 1 master playlist |
| `test_dash.py` | các cách MPD mô tả danh sách mảnh, chọn luồng bitrate cao nhất cho cả hình và tiếng |
| `test_verify.py` | ngưỡng cảnh báo và ngưỡng báo lỗi khi file ghép ra không khớp thời lượng |
| `test_playlist.py` | chọn variant bitrate cao nhất, AES-128, fMP4, byte-range, `METHOD=NONE` giữa chừng |
| `test_naming.py` | ký tự cấm trên Windows, tên dành riêng (`CON`, `NUL`), phát hiện thiếu mảnh |
| `test_no_secrets.py` | không để giá trị riêng tư lọt vào file được commit |

Cái cuối có lý do cụ thể: trong lúc phát triển, một lệnh `cp .env .env.example` đã chép cả ID thư mục Google Drive thật vào file nằm trong repo. Lần đó phát hiện kịp bằng mắt. Test này để lần sau không phải trông vào may mắn.

## Đã có

- **HLS**: master playlist → tự chọn variant bitrate cao nhất; AES-128 kể cả khi playlist đổi key giữa chừng; fMP4 (`#EXT-X-MAP`); `#EXT-X-BYTERANGE`
- **DASH**: `SegmentTemplate` đếm theo số hoặc theo `SegmentTimeline` (kể cả `r=` lặp), `$Number%05d$`, `$Time$`, `SegmentList`, Representation là file đơn, chuỗi `BaseURL`. Hình và tiếng tách riêng thì tải cả hai rồi ghép lại
- **File tải thẳng**: `.mp4`, `.mkv`, `.webm`, `.mov`
- Resume: chạy lại chỉ tải mảnh còn thiếu, bỏ qua video đã xong
- Retry có backoff, báo rõ mảnh nào hỏng
- Tên file an toàn cho Windows, và console ép UTF-8 (không thì tên tiếng Việt có dấu làm crash cả tiến trình)

## Giới hạn

- **DRM Widevine/PlayReady** (`SAMPLE-AES`, `SAMPLE-AES-CTR`) không xử lý được — báo lỗi rõ ràng thay vì cho ra file hỏng. (Các mảnh mẫu của bạn không mã hoá, nên không dính.)
- Link `.m3u8` thường có token hết hạn sau vài chục phút. Batch dài bị lỗi giữa chừng thì chạy lại `auto_grab.js` lấy manifest mới rồi chạy lại — video đã xong sẽ được bỏ qua.
- Công cụ này để tải nội dung bạn có quyền xem, dùng offline cá nhân.
