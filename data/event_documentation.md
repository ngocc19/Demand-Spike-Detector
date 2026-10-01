# Events Data Documentation

> **Document generated:** 2025  
> **Version:** 1.0

---

## Mục lục

1. [Cấu trúc dữ liệu](#1-cấu-trúc-dữ-liệu)
2. [Loại sự kiện (Event Types)](#2-loại-sự-kiện-event-types)
3. [Nguồn dữ liệu (Data Sources)](#3-nguồn-dữ-liệu-data-sources)
4. [Thống kê dữ liệu](#4-thống-kê-dữ-liệu)
5. [H3 Spatial Indexing](#5-h3-spatial-indexing)
6. [Time Slot cho Spike Detection](#6-time-slot-cho-spike-detection)

---

## 1. Cấu trúc dữ liệu

File Excel/CSV chứa thông tin chi tiết về các sự kiện tại Hà Nội. Dữ liệu bao gồm thông tin thời gian, địa điểm, loại sự kiện và nguồn gốc.

### 1.1 Danh sách các trường

| # | Field Name | Type | Description |
|---|------------|------|-------------|
| 1 | `event_name` | String | Tên đầy đủ của sự kiện |
| 2 | `venue` | String | Địa điểm tổ chức sự kiện |
| 3 | `start_date` | Date | Ngày bắt đầu (DD/MM/YY) |
| 4 | `start_time` | Time | Giờ bắt đầu (HH:MM) |
| 5 | `end_time` | Time | Giờ kết thúc (HH:MM) |
| 6 | `type` | String | Loại sự kiện (xem mục 2) |
| 7 | `estimate_attendence` | Number | Số lượng người tham dự ước tính |
| 8 | `source_url` | URL | URL nguồn gốc sự kiện |
| 9 | `attendance_source_url` | URL | URL nguồn dữ liệu về số lượng khán giả |
| 10 | `latitude` | Float | Vĩ độ của địa điểm (geocoded) |
| 11 | `longitude` | Float | Kinh độ của địa điểm (geocoded) |
| 12 | `h3_index` | String | Mã H3 cell (resolution 8) cho spatial indexing |
| 13 | `time_slot` | Time | Mốc thời gian 30 phút (dùng cho spike detection) |

### 1.2 Chi tiết các trường quan trọng

#### latitude, longitude
- **Mô tả:** Tọa độ địa lý của địa điểm
- **Nguồn:** Geocoding service (Nominatim/OpenStreetMap)
- **Ghi chú:** Các tọa độ được hard-coded cho các địa điểm phổ biến để đảm bảo độ chính xác cao nhất

#### h3_index
- **Mô tả:** Mã định danh H3 cell theo công nghệ hexagonal spatial indexing của Uber
- **Resolution:** 8 (mỗi hex có diện tích khoảng 33.9 km²)
- **Ứng dụng:** Dùng để group các sự kiện theo khu vực và join với dữ liệu weather
- **Ví dụ:** Văn Miếu - Quốc Tử Giám có tọa độ (21.0369, 105.8351), H3 index: `88415cb4adfffff`

#### time_slot
- **Mô tả:** Mốc thời gian 30 phút
- **Ứng dụng:** Mỗi sự kiện được chia thành nhiều rows để phục vụ cho việc phát hiện spike demand
- **Ví dụ:** Sự kiện 09:00-11:00 sẽ có 4 slots: 09:00, 09:30, 10:00, 10:30

---

## 2. Loại sự kiện (Event Types)

Cột `type` xác định loại/hạng mục của sự kiện. Việc phân loại này giúp phân tích demand theo từng loại hình sự kiện.

### 2.1 Bảng phân loại

| Type | Mô tả | Số rows | Tỷ lệ |
|------|--------|---------|--------|
| exhibition | Triển lãm - các sự kiện trưng bày, giới thiệu sản phẩm hoặc tác phẩm | 2,688 | 38.6% |
| cultural_event | Sự kiện văn hóa - hoạt động văn hóa, nghệ thuật, lễ kỷ niệm | 2,423 | 34.8% |
| festival | Lễ hội - các festival, ngày hội, sự kiện quy mô lớn | 1,500 | 21.5% |
| concert | Buổi hòa nhạc/hòa nhạc - các sự kiện âm nhạc, liveshow | 111 | 1.6% |
| workshop | Hội thảo/Workshop - các buổi chia sẻ, đào tạo, workshop | 96 | 1.4% |
| football | Bóng đá - các trận đấu bóng đá chuyên nghiệp | 76 | 1.1% |
| official_or_diplomatic | Sự kiện nhà nước/ngoại giao - các sự kiện cấp nhà nước | 45 | 0.6% |
| conference_seminar | Hội nghị/Hội thảo - các sự kiện học thuật, chuyên đề | 24 | 0.3% |

### 2.2 Biểu đồ phân bố

```
exhibition             ████████████████████████████████████████ 2688 (38.6%)
cultural_event          ███████████████████████████████████ 2423 (34.8%)
festival               ████████████████████ 1500 (21.5%)
concert               █ 111 (1.6%)
workshop              █ 96 (1.4%)
football              █ 76 (1.1%)
official_or_diplomatic ▌ 45 (0.6%)
conference_seminar     ▌ 24 (0.3%)
```

### 2.3 Nhận xét

- **Exhibition** và **cultural_event** chiếm tỷ lệ lớn nhất (~73%)
- Các sự kiện **football** và **concert** có số lượng thấp hơn, có thể cần bổ sung thêm nguồn

---

## 3. Nguồn dữ liệu (Data Sources)

Cột `source_url` chứa URL của trang web nơi sự kiện được crawl.

### 3.1 Bảng nguồn dữ liệu

| Nguồn | Mô tả | Số rows | Tỷ lệ |
|--------|--------|---------|--------|
| lehoivietnam.com.vn | Website tổng hợp sự kiện, lễ hội, triển lãm tại Việt Nam | 4,128 | 59.3% |
| vanmieu.gov.vn | Website chính thức của Văn Miếu - Quốc Tử Giám | 2,588 | 37.2% |
| ticketbox.vn | Nền tảng bán vé trực tuyến, nguồn cho concerts và sự kiện đặc biệt | 171 | 2.5% |
| vpf.vn (football) | Liên đoàn Bóng đá Việt Nam (V-League) | 60 | 0.9% |
| vff.org.vn (football) | Liên đoàn Bóng đá Việt Nam (Đội tuyển quốc gia) | 16 | 0.2% |

### 3.2 Biểu đồ phân bố

```
lehoivietnam.com.vn  █████████████████████████████████████████████████████████ 4128 (59.3%)
vanmieu.gov.vn       █████████████████████████████████████████████ 2588 (37.2%)
ticketbox.vn          ████ 171 (2.5%)
vpf.vn               ██ 60 (0.9%)
vff.org.vn           ▌ 16 (0.2%)
```

### 3.3 Đánh giá nguồn dữ liệu

**Ưu điểm:**
- Hai nguồn chính (lehoivietnam và vanmieu) cung cấp dữ liệu đa dạng về sự kiện văn hóa
- Website chính thức của Văn Miếu đảm bảo độ tin cậy cao

**Hạn chế:**
- Thiếu dữ liệu về một số loại hình sự kiện như concert, workshop từ các nguồn khác
- Số lượng events football còn ít (76 rows)

**Khuyến nghị:**
- Cần bổ sung thêm nguồn cho sports, concerts từ các nền tảng khác như Ticketbox, Idols
- Có thể thêm nguồn cho các sự kiện từ các trung tâm thương mại, mall

---

## 4. Thống kê dữ liệu

### 4.1 Tổng quan

| Chỉ số | Giá trị |
|---------|---------|
| Tổng số records | 6,963 rows |
| Số events gốc | 422 events |
| Events trong Hà Nội | 100% |
| Venue có tọa độ | 100% (geocoded) |

### 4.2 Phân bố theo khung giờ

| Giờ | Số events |
|------|-----------|
| 00:00 - 07:00 | ~174 events (toàn sự kiện cả ngày) |
| 09:00 | ~560 events (peak - nhiều sự kiện bắt đầu) |
| 17:00 | ~252 events (peak - sự kiện kết thúc) |
| 20:00 | ~228 events (sự kiện buổi tối) |

---

## 5. H3 Spatial Indexing

### 5.1 Giới thiệu về H3

H3 là thư viện hexagonal hierarchical spatial indexing của Uber, cho phép biểu diễn bề mặt Trái Đất dưới dạng lưới lục giác (hexagons).

**Đặc điểm:**
- Bề mặt Trái Đất được chia thành các lục giác đều
- Các cấp độ phân giải từ 0-15
- Cho phép zoom in/out với cấu trúc phân cấp

### 5.2 Bảng Resolution

| Resolution | Diện tích/hex | Ứng dụng |
|-------------|----------------|------------|
| 7 | ~254 km² | Cấp vùng/quốc gia |
| **8** | **~34 km²** | **Cấp thành phố (hiện tại)** |
| 9 | ~5 km² | Cấp quận/huyện |
| 10 | ~0.7 km² | Cấp phường/xã |
| 11 | ~0.1 km² | Cấp khu vực nhỏ |
| 12 | ~0.007 km² | Cấp block/tòa nhà |

### 5.3 Tại sao dùng Resolution 8?

- **Phù hợp với phạm vi Hà Nội:** Diện tích Hà Nội khoảng 3,300 km², tương đương ~97 cells ở resolution 8
- **Join với Weather data:** Các plugins weather (OWM, VCW, NCHMF) cũng sử dụng resolution 8
- **Đủ chi tiết:** Không quá thô (resolution 7) cũng không quá mịn (resolution 10)

### 5.4 Ví dụ H3 Index

| Địa điểm | Tọa độ | H3 Index (Res 8) |
|-----------|---------|-------------------|
| Văn Miếu - Quốc Tử Giám | (21.0369, 105.8351) | `88415cb4adfffff` |
| Hồ Gươm | (21.0285, 105.8527) | `88415cb4e5fffff` |
| Mỹ Đình | (21.0636, 105.7639) | `88415ca61bfffff` |
| AEON Mall Hà Đông | (20.9828, 105.7854) | `8841436b2bfffff` |

---

## 6. Time Slot cho Spike Detection

### 6.1 Nguyên tắc chia slot

Cột `time_slot` chia sự kiện thành các mốc thời gian 30 phút để phục vụ cho việc phát hiện spike trong demand forecasting.

**Quy tắc:**
- Event 09:00 - 11:00 → 4 slots: 09:00, 09:30, 10:00, 10:30
- Event 00:00 - 23:59 → 48 slots (all-day event)
- Event bắt đầu = kết thúc → 1 slot duy nhất

### 6.2 Peak Hours Multipliers (Đề xuất)

Để phản ánh đặc điểm demand thực tế, có thể áp dụng trọng số nhân (multiplier) cho các khung giờ cao điểm (peak hours):

| Khung giờ | Multiplier | Ghi chú |
|-----------|------------|----------|
| 06:00 - 08:00 | 1.5x | Rush hour sáng |
| **08:00 - 10:00** | **2.0x** | Peak sáng - event bắt đầu |
| 10:00 - 17:00 | 1.0x | Giờ bình thường |
| **17:00 - 19:00** | **2.5x** | Peak chiều - event kết thúc |
| 19:00 - 22:00 | 1.5x | Giờ tối |
| 22:00 - 06:00 | 0.5x | Đêm - demand thấp |

### 6.3 Ví dụ áp dụng

```
Event: "Lễ hội văn hóa"
Thời gian: 00:00 - 23:59 (cả ngày)
Base Weight: 1.0

Áp dụng Peak Multipliers:
├── 08:00-09:00: 1.0 × 2.0 = 2.0 (peak morning)
├── 12:00-13:00: 1.0 × 1.0 = 1.0 (normal)
├── 17:00-18:00: 1.0 × 2.5 = 2.5 (peak evening)
└── 23:00-00:00: 1.0 × 0.5 = 0.5 (night)
```

### 6.4 Lợi ích của việc chia slot

1. **Phát hiện spike chính xác hơn:** Các sự kiện được chia thành nhiều mốc, giúp xác định thời điểm demand cao nhất
2. **Join với weather data:** Dữ liệu thời tiết cũng được gán theo H3 cell và thời gian, dễ dàng join
3. **Phân tích theo khung giờ:** Có thể phân tích demand theo từng khung giờ trong ngày

---

## Phụ lục: Venue có tọa độ đã hard-coded

Để đảm bảo độ chính xác, một số venue phổ biến đã được hard-coded tọa độ:

| Venue | Latitude | Longitude | H3 Index |
|-------|---------|----------|----------|
| Văn Miếu - Quốc Tử Giám | 21.0369 | 105.8351 | 88415cb4adfffff |
| Cung Thể Thao Mỹ Đình | 21.0636 | 105.7639 | 88415ca61bfffff |
| SVĐ Hàng Đẫy | 21.0451 | 105.7841 | 88415ca65bfffff |
| Hồ Gươm | 21.0285 | 105.8527 | 88415cb4e5fffff |
| Trung Tâm Hội Nghị Quốc Gia | 21.0402 | 105.7871 | 8841436965fffff |
| AEON Mall Hà Đông | 20.9828 | 105.7854 | 8841436b2bfffff |
| GO! Thăng Long | 21.0136 | 105.7989 | 88415cb491fffff |

---

> **Document generated by:** Demand Spike Detector v0  
> **Generated:** 2025
