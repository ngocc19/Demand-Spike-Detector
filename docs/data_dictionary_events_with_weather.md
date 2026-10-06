# Data Dictionary: `events_with_weather.xlsx`

**Source:** `scripts/merge_event_weather.py`  
**Output shape:** 8,872 rows × 50 columns  
**Purpose:** Expanded event records merged with weather and calendar features for demand/traffic modeling

---

## 1. Event Fields (Nguồn: Event Pipeline)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `event_name` | string | Tên sự kiện | `"Những chiếc cổng" - Cuộc đối thoại giữa quá khứ và hiện tại` |
| `venue` | string | Địa điểm tổ chức | `Văn Miếu - Quốc Tử Giám` |
| `start_date` | string | Ngày bắt đầu (DD/MM/YY) | `05/07/26` |
| `end_date` | string | Ngày kết thúc (DD/MM/YY) | `05/08/26` |
| `start_time` | string | Giờ bắt đầu (HH:MM) | `09:00` |
| `end_time` | string | Giờ kết thúc (HH:MM) | `22:00` |
| `type` | string | Loại sự kiện đã phân loại | `cultural_event`, `concert`, `football` |
| `estimate_attendence` | float | Số người tham dự ước tính | `4000.0` |
| `source_url` | string | URL nguồn gốc của sự kiện | `https://vanmieu.gov.vn/...` |
| `attendance_source_url` | string | URL chứng minh attendance thực tế | `https://dantri.com.vn/...` |
| `latitude` | float | Vĩ độ địa điểm | `21.0369` |
| `longitude` | float | Kinh độ địa điểm | `105.8351` |
| `h3_index` | string | H3 hex ID (resolution 8) của venue | `88415cb4adfffff` |

---

## 2. Temporal Slot Fields (Temporal Expansion)

Mỗi sự kiện được expand thành các slot 30 phút.

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `slot_time` | string | Thời điểm slot (HH:MM) | `09:00`, `09:30`, `10:00` |
| `slot_datetime` | string | Datetime đầy đủ của slot | `2026-07-05 09:00:00` |
| `nearest_anchor` | string | Anchor thời tiết gần nhất | `HoanKiem` |
| `anchor_distance_km` | float | Khoảng cách đến anchor (km) | `2.19` |

**Weather Anchors hiện tại:**

| Anchor | Latitude | Longitude |
|--------|----------|-----------|
| HoanKiem | 21.0285 | 105.8542 |
| CauGiay | 21.0306 | 105.7925 |
| HoangMai | 20.9723 | 105.8454 |
| LongBien | 21.0470 | 105.8920 |
| TayHo | 21.0664 | 105.8176 |
| NoiBai | 21.2187 | 105.8042 |

---

## 3. Weather Fields (Nguồn: OpenWeatherMap / Visual Crossing)

| Field | Type | Description | Range | Example |
|-------|------|-------------|-------|---------|
| `datetime` | datetime | Thời điểm của weather data | - | `2026-07-05 09:00:00` |
| `temp_c` | float | Nhiệt độ (°C) | -10 → 50 | `30.0` |
| `feels_like` | float | Nhiệt độ cảm nhận (°C) | -15 → 55 | `38.7` |
| `humidity_pct` | float | Độ ẩm (%) | 0 → 100 | `84.0` |
| `precip` | float | Lượng mưa (mm) | 0 → ~100 | `0.9` |
| `precip_prob` | int | Xác suất mưa (%) | 0 → 100 | `100` |
| `wind_speed` | float | Tốc độ gió (km/h) | 0 → 200 | `13.0` |
| `cloud_cover` | float | Độ phủ mây (%) | 0 → 100 | `100.0` |
| `visibility` | float | Tầm nhìn (km) | 0 → 50 | `10.0` |
| `pressure` | float | Áp suất khí quyển (hPa) | 950 → 1050 | `1002.0` |
| `weather_conditions` | string | Mô tả thời tiết | - | `Rain, Overcast` |
| `weather_icon` | string | Icon thời tiết | - | `rain` |

---

## 4. Weather Impact Fields (Computed)

| Field | Type | Description | Range |
|-------|------|-------------|-------|
| `weather_impact` | float | Tác động thời tiết (0=trời trong, 1=mưa to) | 0.0 → 1.0 |
| `precip_impact` | float | Tác động từ lượng mưa (log scale) | 0.0 → 1.0 |
| `value` | float | Combined weather impact score | 0.0 → 1.0 |
| `severity` | string | Mức độ nghiêm trọng | `LOW`, `MEDIUM`, `HIGH`, `SEVERE` |

**Weather Impact Mapping:**

| Weather Code Range | Description | Impact |
|--------------------|-------------|--------|
| 0-3 | Trời trong / Ít mây | 0.0 |
| 45-48 | Sương mù | 0.2 |
| 51-55 | Mưa phùn | 0.4 |
| 61-67 | Mưa vừa | 0.6 |
| 80-82 | Mưa rào | 0.8 |
| 95-99 | Dông / Sấm sét | 1.0 |

---

## 5. Blended Weather Fields (Nguồn: Weather Ensemble)

Dữ liệu tổng hợp từ 4 nguồn: OWM, VCW, HSDC, NCHMF

| Field | Type | Description |
|-------|------|-------------|
| `blended_temp_c` | float | Nhiệt độ trung bình ensemble |
| `blended_precip` | float | Lượng mưa ensemble |
| `blended_humidity_pct` | float | Độ ẩm ensemble |
| `blended_weather_impact` | float | Weather impact ensemble |
| `blended_value` | float | Combined impact score ensemble |

---

## 6. Time Features (Computed)

| Field | Type | Description | Values |
|-------|------|-------------|--------|
| `is_weekend` | int | Có phải cuối tuần không | `0` / `1` |
| `is_rush_hour` | int | Có phải giờ cao điểm không | `0` / `1` |
| `part_of_day` | string | Buổi trong ngày | `morning`, `afternoon`, `evening`, `night` |
| `month` | int | Tháng (1-12) | `1` → `12` |
| `is_monsoon` | int | Có phải mùa mưa (May-Oct) không | `0` / `1` |

**Rush Hour Definition:**
- Buổi sáng: 07:00 - 09:00
- Buổi chiều: 17:00 - 19:00

---

## 7. Holiday & Calendar Fields (Nguồn: Holiday Plugin)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `is_holiday` | int | Có phải ngày lễ không | `0` / `1` |
| `holiday_name` | string | Tên ngày lễ | `normal`, `Ngày Quốc khánh` |
| `holiday_impact` | float | Tác động của ngày lễ | 0.0 → 1.0 |
| `tet_phase` | string | Giai đoạn Tết Nguyên Đán | `normal`, `pre_tet`, `during_tet`, `post_tet` |
| `is_working_day` | int | Có phải ngày làm việc không | `0` / `1` |
| `holiday_type` | string | Loại ngày lễ | `normal`, `official`, `cultural` |
| `category` | string | Category (từ source) | `none`, `holiday` |

**Tết Impact Phases:**

| Phase | Days | Impact | Description |
|-------|------|--------|-------------|
| `pre_tet` | 7 days before | 0.5-0.7 | Peak travel season |
| `during_tet` | 7 days | 0.8-1.0 | New Year holiday |
| `post_tet` | 7 days after | 0.5-0.7 | Return to normal |

---

## 8. Event Type Categories

| Type | Description | Demand Impact |
|------|-------------|---------------|
| `concert` | Live concert, music show | 1.0 |
| `football` | Football match (V-League, VFF) | 0.8 |
| `festival` | Festival, carnival | 0.9 |
| `cultural_event` | Cultural exhibition, workshop | 0.5 |
| `conference_seminar` | Conference, seminar | 0.4 |
| `official_or_diplomatic` | Official event | 0.3 |
| `other` | Uncategorized events | 0.5 |

---

## 9. Data Quality Notes

- **888 events** được expand thành **8,872 rows** (mỗi event ~10 slots 30 phút trung bình)
- Events nằm ngoài ranh giới Hà Nội đã được filter out
- Weather data được match theo: `nearest_anchor + date + 30-min slot`
- ~100% events có weather data (left join với weather parquet)

---

## 10. Usage for Modeling

**Target variable candidates:**

| Candidate | Description | Available |
|-----------|-------------|-----------|
| `estimate_attendence` | Số người tham dự | ✅ Có |
| `type` | Event category | ✅ Có |

**Features cho model:**

```
Weather:      temp_c, weather_impact, precip, humidity_pct, wind_speed
Time:         is_weekend, is_rush_hour, part_of_day, month, is_monsoon
Calendar:     is_holiday, holiday_impact, tet_phase
Spatial:      h3_index, nearest_anchor, anchor_distance_km
Event:        type, estimate_attendence
```

---

*Generated: 2026-01-15*
