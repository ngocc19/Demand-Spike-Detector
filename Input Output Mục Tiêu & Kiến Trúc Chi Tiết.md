# Input/Output Muc Tieu & Kien Truc Chi Tiet

---

## 1. INPUT - Du Lieu Dau Vao

### 1.1 Data Sources (≥2 external sources)

#### SOURCE 1: DEMAND DATA (INTERNAL - tu he thong cua ban)

**DAY LA DU LIEU COT LOI - ban phai co**

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Thoi diem (30-min intervals) |
| hex_id | string | H3 hex ID (resolution 8-9) |
| requests | int | So requests trong slot do |
| avg_eta_min | float | Thoi gian cho trung binh |

**Vi du:**

| timestamp | hex_id | requests | avg_eta_min |
|-----------|--------|----------|-------------|
| 2024-09-01 08:00 | 8a2a1008affffff | 45 | 12.3 |
| 2024-09-01 08:30 | 8a2a1008affffff | 52 | 15.1 |
| 2024-09-01 08:00 | 8a2a1009affffff | 28 | 8.7 |
| 2024-09-01 08:30 | 8a2a1009affffff | 31 | 9.2 |

---

#### SOURCE 2: WEATHER API (EXTERNAL - mien phi)

| Thong tin | Chi tiet |
|-----------|----------|
| API | Open-Meteo |
| URL | https://api.open-meteo.com/v1/forecast |
| Cost | FREE, no API key required |

**Parameters:**

```
latitude: 21.0285 (Hanoi)
longitude: 105.8542
hourly: temperature_2m,precipitation,weather_code
forecast_days: 7
timezone: Asia/Ho_Chi_Minh
```

**Response Example:**

| time | temp_2m | precipitation | weather_code |
|------|---------|---------------|--------------|
| 2024-09-01 08:00 | 28.5 | 0.0 | 1 |
| 2024-09-01 09:00 | 29.2 | 0.5 | 61 |
| 2024-09-01 10:00 | 30.1 | 2.3 | 63 |

**Weather Code -> Impact Mapping:**

| code | description | impact |
|------|-------------|--------|
| 0-3 | Clear/Cloudy | 0.0 |
| 45-48 | Fog | 0.2 |
| 51-55 | Drizzle | 0.4 |
| 61-67 | Rain | 0.6 |
| 80-82 | Rain showers | 0.8 |
| 95-99 | Thunderstorm | 1.0 |

---

#### SOURCE 3: EVENT DATA (EXTERNAL - manual/CSV)

**File: events.csv**

| event_name | venue | start_time | end_time | type |
|------------|-------|------------|----------|------|
| Concert Son Tung | SVD My Dinh | 2024-09-01 19:00:00 | 2024-09-01 22:00:00 | concert |
| Football Match | Thong Nhat Stadium | 2024-09-01 17:00:00 | 2024-09-01 19:00:00 | football |
| Tech Conference | ICE Ha Noi | 2024-09-05 08:00:00 | 2024-09-05 17:00:00 | conference |

**Event Type -> Demand Impact:**

| type | description | impact |
|------|-------------|--------|
| concert | Concert/Music | 1.0 |
| football | Sports match | 0.8 |
| festival | Festival/Carnival | 0.9 |
| conference | Business event | 0.5 |

---

#### SOURCE 4: FLOOD RSS (EXTERNAL - mien phi)

| Thong tin | Chi tiet |
|-----------|----------|
| Source | VNExpress RSS feed |
| URL | https://vnexpress.net/rss/thoi-su.rss |
| Format | Parse title/summary tim keywords "ngap", "lut" |

**Parsed Example:**

```
title: "Mua lon khien duong pho Ha Noi ngap nang"
published: 2024-09-01 14:30
location_keywords: ["Ha Noi", "duong pho"]
severity_keywords: ["ngap nang"] -> SEVERE
```

**Severity Keywords Mapping:**

| keyword | severity | impact |
|---------|----------|--------|
| ngap nang, ngap sau, ngap trang | SEVERE | 0.9 |
| ngap, ngap lut, u dong | HIGH | 0.7 |
| ngap nhe, xe kho di | MEDIUM | 0.5 |

---

### 1.2 Feature Store (Unified Input Format)

**Day la OUTPUT cua Data Pipeline, INPUT cua Model**

- **Primary Key:** (hex_id, datetime_30min)
- **Storage:** Parquet file (production) hoac CSV (MVP)

| hex_id | datetime_30min | weather | flood | event | holiday | demand |
|--------|---------------|---------|-------|-------|---------|--------|
| 8a2a1008... | 2024-09-01 08:00 | 0.0 | 0.0 | 0.0 | 0.0 | 45 |
| 8a2a1008... | 2024-09-01 08:30 | 0.0 | 0.0 | 0.0 | 0.0 | 52 |
| 8a2a1008... | 2024-09-01 09:00 | 0.3 | 0.0 | 0.0 | 0.0 | 58 |
| 8a2a1008... | 2024-09-01 09:30 | 0.6 | 0.0 | 0.8 | 0.0 | 78 |
| 8a2a1008... | 2024-09-01 10:00 | 0.8 | 0.0 | 1.0 | 0.0 | 85 |
| 8a2a1009... | 2024-09-01 08:00 | 0.0 | 0.0 | 0.0 | 0.0 | 28 |
| 8a2a100a... | 2024-09-01 08:00 | 0.0 | 0.85 | 0.0 | 0.0 | 15 |

**Ghi chu:**
- weather = 0.0 -> khong mua
- weather = 0.6 -> mua vua (code 61-67)
- flood = 0.85 -> ngap nang (SEVERE)
- event = 1.0 -> concert tai hex nay luc nay
- holiday = 0.0 -> ngay binh thuong
- MOI HANG = 1 time slot cho 1 hex = 1 observation

---

## 2. OUTPUT - Ket Qua Dau Ra

### 2.1 Spike Alert (TC4 Output)

**TC4 Requirement:** "Alert co hex, muc do, nguyen nhan goi y"

```json
{
  "alert_id": "SPK-20240901-0845-001",
  "timestamp": "2024-09-01T08:45:00",
  "detected_at": "2024-09-01T08:45:05",
  "hex_id": "8a2a1008affffff",
  "hex_location": "Quan Cau Giay, Ha Noi",
  "severity": "HIGH",
  "demand_metrics": {
    "actual_requests": 78,
    "baseline_requests": 45,
    "deviation_pct": 73.3,
    "threshold_pct": 30.0
  },
  "suggested_causes": [
    {
      "cause": "weather",
      "confidence": 0.85,
      "description": "Mua vua den lon (code 63)"
    },
    {
      "cause": "event",
      "confidence": 0.72,
      "description": "Football match tai Thong Nhat Stadium"
    }
  ],
  "primary_cause": "weather",
  "action_recommendations": [
    "Tang driver online o khu vuc Cau Giay",
    "Pre-position drivers near stadium truoc match 30 phut"
  ]
}
```

---

### 2.2 TC Metrics Summary

#### TC1: Detection Rate

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | Phat hien ≥80% dot bien ≥30% Requests |
| Formula | TP / (TP + FN) |

**Vi du:**

| Metric | Value |
|--------|-------|
| Ground Truth: spikes thuc su xay ra | 50 |
| Detected: spikes | 43 |
| Missed: spikes | 7 |
| **Detection Rate** | **43 / 50 = 86% ✅ (≥80%)** |

---

#### TC2: False Alert Rate

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | ≤2 false alerts/ngay toan thanh pho |
| Formula | FP / num_days |

**Vi du:**

| Metric | Value |
|--------|-------|
| Alerts tong cong | 156 |
| Actual spikes | 143 |
| False positives | 13 |
| Days in period | 30 |
| **False alerts/day** | **13 / 30 = 0.43 ✅ (≤2)** |

---

#### TC3: External Data Sources

> **BACKFILL DAM BAO DU DATA SOURCES**
>
> Nho backfill, ta co du 4 data sources cho ca training (Phase 0) va inference (Phase 1).

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | ≥2 nguon du lieu ngoai duoc tich hop |

**Vi du:**

| Source | Status | Backfill Method |
|--------|--------|-----------------|
| Open-Meteo Weather API | ✅ | `past_days=60` parameter |
| Event data (Ticketbox/manual CSV) | ✅ | Manual collection |
| Flood RSS feeds (VNExpress) | ✅ | Wayback Machine archive |
| Holiday calendar (file) | ✅ | Static calendar (biet truoc) |
| **Total** | **4 sources ✅ (≥2)** | |

> **Note:** Tat ca sources deu duoc backfill day du cho Phase 0 va hoat dong real-time cho Phase 1. Khong co data mismatch giua training va inference.

---

#### TC4: Alert Completeness

> **CAUSE ATTRIBUTION TU BACKFILLED MODEL**
>
> Nho train model voi day du features (weather, event, flood, holiday) tu backfill data, model co the tu dong goi y nguyen nhan cho moi alert dua tren feature importance va SHAP values.

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | Alert co hex, muc do, nguyen nhan goi y |

**Vi du:**

| Metric | Value |
|--------|-------|
| Total alerts | 143 |
| Alerts with hex_id | 143/143 = 100% ✅ |
| Alerts with severity | 143/143 = 100% ✅ |
| Alerts with suggested_causes | 143/143 = **100%** ✅ |
| (Model goi y duoc nguyen nhan) | |

**Cach hoat dong (tu Backfilled Model):**

```
Alert duoc tao voi suggested_causes tu model:
+---------------------------------------------------------------------+
|  "suggested_causes": [                                              |
|    {                                                               |
|      "cause": "weather",         <- Model du doan: "mua"          |
|      "confidence": 0.85,         <- SHAP value cho weather         |
|      "description": "Mua vua den lon (code 63)"                  |
|    },                                                              |
|    {                                                               |
|      "cause": "event",           <- Model: "su kien gan do"       |
|      "confidence": 0.72,         <- SHAP value cho event           |
|      "description": "Football match tai Thong Nhat Stadium"        |
|    }                                                               |
|  ]                                                                |
+---------------------------------------------------------------------+

Model hoc duoc pattern tu backfill data:
* Spike + weather=0.9 + event=0.8 -> primary_cause=weather
* Spike + flood=0.85 -> primary_cause=flood
* Spike + holiday=0.9 -> primary_cause=holiday
* Spike + multiple factors -> phan bo confidence theo SHAP
```

---

## 3. Chi Tiet Kien Truc - Tung Buoc

### Phase 0: OFFLINE (Training)

> **LUU Y QUAN TRONG: BACKFILL STRATEGY**
>
> De dam bao model hoc duoc pattern day du tu TAT CA cac yeu to anh huong, ta can **backfill du lieu lich su** cho flood va holiday:
>
> | Data Source | Cach Backfill | Ghi chu |
> |-------------|---------------|---------|
> | **Flood (VNExpress RSS)** | Archive RSS feeds, su dung Internet Archive (Wayback Machine) | Co the lay lai tin tuc ngap tu thang truoc |
> | **Holiday Calendar** | Biet truoc ngay le (Tet, Quoc khánh,...) | Khong can fetch - chi can tao danh sach |
> | **Weather** | Open-Meteo co luu tru forecast history | Su dung `past_days` parameter |
> | **Events** | Manual CSV, Ticketbox API (co the lay events qua khu) | Can thu thap thu cong |
>
> **U u tien:** U u tien backfill du 8 tuan data nhu design ban dau de model hoc pattern day du.

#### Step 1: Thu Thap Du Lieu (Backfill)

```
+-------------------------------------------------------------------------+
|                   PHASE 0: OFFLINE (BACKFILL)                          |
+-------------------------------------------------------------------------+
|                                                                          |
|  Step 1: BACKFILL - Thu thap du lieu LICH SU                           |
|  ===================================================================     |
|                                                                          |
|  +-----------------+    +-----------------+    +-----------------+      |
|  |  Demand Data    |    |  Weather API    |    |  Event CSV      |      |
|  |  (Internal)     |    |  (Open-Meteo)   |    |  (Manual)       |      |
|  |                 |    |                 |    |                 |      |
|  | hex,timestamp,  |    | timestamp,      |    | event, venue,   |      |
|  | requests,eta    |    | weather_code,   |    | start_time,     |      |
|  |                 |    | precipitation   |    | type            |      |
|  | <- INTERNAL    |    | <- Backfill    |    | <- Manual       |      |
|  +--------+--------+    +--------+--------+    +--------+--------+      |
|           |                      |                      |                 |
|           +----------------------+----------------------+                 |
|                                  |                                       |
|                                  v                                       |
|  +-----------------+    +-----------------+                             |
|  |  Flood RSS      |    |  Holiday        |                             |
|  |  (VNExpress/    |    |  Calendar       |                             |
|  |   Wayback)      |    |  (Static)       |                             |
|  |                 |    |                 |                             |
|  | news titles,    |    | holiday dates,  |                             |
|  | severity        |    | tet_phase       |                             |
|  |                 |    |                 |                             |
|  | <- BACKFILL    |    | <- Static      |                             |
|  +--------+--------+    +--------+--------+                             |
|           |                      |                                      |
|           +----------------------+                                      |
|                                  |                                       |
|                                  v                                       |
|                     +----------------------------+                       |
|                     |   FEATURE STORE            |                       |
|                     |   (8 tuan BACKFILL)       |                       |
|                     |                            |                       |
|                     | hex_id | datetime |        |                       |
|                     | weather | event |          |                       |
|                     | flood | holiday |          |                       |
|                     | demand <- INTERNAL         |                       |
|                     +-------------+--------------+                       |
|                                   |                                     |
|                                   v                                     |
|                     +----------------------------+                       |
|                     |  MANUAL LABELING           |                       |
|                     |  (is_spike, cause)        |                       |
|                     +-------------+--------------+                       |
|                                   |                                     |
|                                   v                                     |
|                     +----------------------------+                       |
|                     |  TRAIN LIGHTGBM            |                       |
|                     |  spike_predictor.pkl      |                       |
|                     +----------------------------+                       |
|                                                                          |
+-------------------------------------------------------------------------+
```

#### Backfill Chi Tiet Tung Data Source

| Data Source | Backfill Method | URL/Source | Notes |
|------------|----------------|------------|-------|
| **Weather** | Open-Meteo Archive API | `api.open-meteo.com/v1/forecast?past_days=60` | Mien phi, lay 60 ngay tro lai |
| **Flood (VNExpress)** | Wayback Machine RSS Archive | `web.archive.org/web/{date}/*/vnexpress.net/rss/thoi-su.rss` | Can parse multiple snapshots |
| **Holiday** | Static Calendar | Viet Nam holidays 2023-2024 | Khong can fetch - biet truoc |
| **Events** | Manual CSV | Ticketbox API (historical endpoint) | Can thu thap thu cong |
| **Demand** | Internal Database | He thong cua ban | Co san, export ra CSV |

#### Step 2: Gan Nhan Spike (Labeling)

> **LUU Y: LABELING VOI DAY DU FEATURES**
>
> Sau khi backfill xong, **TAT CA features** (weather, event, flood, holiday) deu co mat trong dataset. Khi labeling, ta xem **tat ca features dong thoi** de gan nguyen nhan chinh xac.

**Rule:** spike = demand > 1.3 * baseline (30%)

**Baseline Calculation (cho moi hex, moi gio, moi ngay trong tuan):**

Vi du: hex=8a2a1008, hour=8, dow=Monday
- Lay data 8 tuan truoc (da backfill day du)
- Cac ngay: Week1-Mon, Week2-Mon, ..., Week8-Mon
- Baseline = median([45, 42, 48, 41, 44, 46, 43, 47]) = 44.5
- Spike threshold = 44.5 * 1.3 = 57.85

**Neu demand_thuc_te > 57.85 -> SPIKE = 1**
**Neu demand_thuc_te ≤ 57.85 -> SPIKE = 0**

**Labeling Interface (cho Human Annotator):**

```
+-----------------------------------------------------------------------+
|  SPIKE LABELING TOOL                                                 |
+-----------------------------------------------------------------------+
|                                                                       |
|  Hex: 8a2a1008affffff | Time: 2024-09-01 17:30                   |
|  Demand: 78 | Baseline: 45 | Ratio: 1.73x -> SPIKE!                |
|                                                                       |
|  ----------------------------------------------------------------    |
|  CAC YEU TO DONG THOI (tu BACKFILL DATA):                           |
|                                                                       |
|  Weather: 0.9 (Mua to - code 65)           <- HIGH IMPACT          |
|  Event:   0.8 (Football match nearby)       <- HIGH IMPACT          |
|  Flood:   0.0 (Khong co tin ngap)          <- NO IMPACT            |
|  Holiday: 0.0 (Ngay binh thuong)           <- NO IMPACT            |
|                                                                       |
|  ----------------------------------------------------------------    |
|  NGUOI ANNOTATOR QUYET DINH:                                        |
|                                                                       |
|  is_spike: 1                                                         |
|  primary_cause: [weather]                                            |
|  secondary_cause: [event]                                            |
|  cause_confidence: [0.85]                                            |
|  notes: "Mua lon ket hop match bong da tai gan day"                  |
|                                                                       |
+-----------------------------------------------------------------------+
```

**Labeled Dataset (day du features tu backfill):**

| hex_id | datetime | demand | baseline | is_spike | weather | flood | event | holiday | primary_cause | confidence |
|--------|----------|--------|----------|----------|---------|-------|-------|---------|--------------|------------|
| 8a2a1008 | 2024-08-01 08 | 52 | 44.5 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | - | - |
| 8a2a1008 | 2024-08-01 09 | 78 | 45.0 | 1 | 0.9 | 0.0 | 0.8 | 0.0 | weather | 0.85 |
| 8a2a1008 | 2024-08-01 10 | 61 | 46.0 | 1 | 0.6 | 0.85 | 0.0 | 0.0 | flood | 0.90 |
| 8a2a1009 | 2024-08-01 08 | 28 | 25.0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | - | - |

#### Step 3: Train LightGBM

> **LUU Y: TRAIN VOI DAY DU FEATURES**
>
> Dataset sau backfill co **TAT CA** features, nen model se hoc duoc:
> - Mua -> spike (voi flood impact)
> - Su kien -> spike (voi event impact)
> - Ngap -> spike (voi flood impact)
> - Ngay le -> spike (voi holiday impact)
> - **Ket hop nhieu factors** -> spike manh hon

**Feature Engineering (tu Backfill Data):**

| Feature | Type | Description | Source |
|---------|------|-------------|--------|
| weather_impact | float | 0.0-1.0 tu weather API | Backfill ✓ |
| event_impact | float | 0.0-1.0 tu event data | Backfill ✓ |
| flood_severity | float | 0.0-1.0 tu flood RSS | **Backfill ✓** |
| is_holiday | bool | Co phai ngay le | **Backfill ✓** |
| hour | int | 0-23 | Derived |
| day_of_week | int | 0-6 | Derived |
| is_weekend | bool | Thu 7, CN | Derived |
| demand_lag_1h | float | Demand 1 gio truoc | Internal |
| demand_lag_24h | float | Demand cung gio hom qua | Internal |
| demand_lag_1w | float | Demand cung gio tuan truoc | Internal |
| hex_avg_demand | float | Average demand cua hex | Internal |
| hex_volatility | float | Std dev cua hex demand | Internal |

**Training Parameters:**

```python
Model: LightGBM Classifier
Parameters:
  - num_leaves: 31
  - learning_rate: 0.05
  - n_estimators: 100
  - max_depth: 6
  - class_weight: balanced  # handle imbalanced

Train/Validation Split:
  - Train: 2024-06-01 to 2024-07-31 (8 weeks) - BACKFILLED DATA
  - Validation: last 2 weeks
```

**Output:** `spike_predictor.pkl`
- Trained LightGBM model
- Feature names
- Label encoders
- SHAP explainer (for cause attribution)

**Model Benefit tu Backfill:**
- Model hoc duoc pattern: "Ngay mua + su kien -> spike manh"
- Model phan biet duoc: spike do mua vs spike do ngap vs spike do su kien
- Accuracy cao hon vi co du training data cho tat ca scenarios

---

### Phase 1: ONLINE (Real-time Inference)

> **LUU Y: FEATURES GIONG NHU PHASE 0**
>
> Nho backfill day du o Phase 0, Phase 1 su dung **CUNG MOT MODEL** voi features giong het:
> - weather (real-time fetch)
> - event (daily fetch)
> - flood (15-min fetch)
> - holiday (static lookup)
>
> **Khong co training/test mismatch** vi features hoan toan tuong thich.

#### Schedule

| Plugin | Schedule | Data Source |
|--------|----------|-------------|
| Weather | Every hour | Open-Meteo API |
| Event | Daily at 23:00 | Manual CSV / Ticketbox |
| Flood | Every 15 minutes | VNExpress RSS |
| Holiday | Monthly + on-demand | Static Calendar |

#### Step 1: Plugin Orchestrator

```
+-------------------------------------------------------------------------+
|                   PHASE 1: REAL-TIME INFERENCE                          |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-------------+    +-------------+    +-------------+    +---------+  |
|  | Weather     |    | Flood       |    | Event       |    | Holiday |  |
|  | Plugin      |    | Plugin      |    | Plugin      |    | Plugin  |  |
|  | (hourly)   |    | (15 min)   |    | (daily)    |    |(monthly)|  |
|  | <-Real-time|    | <-Real-time|    | <-Real-time|    |<-Static |  |
|  +------+------+    +------+------+    +------+------+    +----+----+  |
|         |                  |                  |                |        |
|         +------------------+------------------+----------------+        |
|                                 |                                   |
|                                 v                                   |
|                    +-----------------------+                       |
|                    |   FEATURE STORE       |                       |
|                    |   (Current State)     |                       |
|                    |   <- TUONG TU NHU     |                       |
|                    |     PHASE 0!          |                       |
|                    +-----------+-----------+                       |
```

#### Step 2: Feature Construction

**Current time:** 2024-09-01 08:45:00

**Input Features for Prediction:**

| Feature | Value | Source |
|---------|-------|--------|
| hex_id | 8a2a1008affffff | Input |
| datetime | 2024-09-01 08:30 | Input |
| weather_impact | 0.6 | Open-Meteo, mua vua |
| event_impact | 0.8 | Concert gan day |
| flood_severity | 0.0 | Khong co ngap |
| is_holiday | False | Calendar |
| hour | 8 | Derived |
| day_of_week | 1 (Monday) | Derived |
| is_weekend | False | Derived |
| demand_lag_1h | 52 | Demand luc 07:30 |
| demand_lag_24h | 48 | Demand 08:30 yesterday |
| demand_lag_1w | 44 | Demand 08:30 last Monday |
| hex_avg_demand | 45 | Baseline cua hex nay |
| hex_volatility | 0.15 | Low volatility |

#### Step 3: Inference

```python
Model: spike_predictor.predict(features)
Output:
{
  "spike_probability": 0.82,
  "will_spike": True,  # (threshold: 0.5)
  "feature_importance": {
    "weather_impact": 0.35,
    "event_impact": 0.28,
    "demand_lag_1h": 0.18,
    "hour": 0.12
  }
}
```

#### Step 4: CUSUM Filter (Reduce False Alerts)

**Problem:** LightGBM predict spike_prob=0.82, nhung day co the la noise -> 1 spike chi count khi CUSUM vuot threshold

**Per-Hex CUSUM State Machine:**

```
hex_id: 8a2a1008affffff
baseline: 45
adaptive_threshold: 5.2  (tinh tu historical volatility)

CUSUM Timeline:
+------------------------------------------------+
| t=08:00 | demand=52 | deviation=+7 | CUSUM=1.5    |
| t=08:30 | demand=78 | deviation=+33 | CUSUM=34.5   |
|                             ^                      |
|            CUSUM vuot threshold 5.2 -> ALERT!    |
|            (sustained spike, not noise)            |
+------------------------------------------------+
```

#### Step 5: Alert Generation

```json
{
  "alert_id": "SPK-20240901-0845-001",
  "hex_id": "8a2a1008affffff",
  "severity": "HIGH",
  "deviation_pct": 73.3,
  "suggested_causes": [
    { "cause": "weather", "confidence": 0.85 },
    { "cause": "event", "confidence": 0.72 }
  ],
  "timestamp": "2024-09-01 08:45:00"
}
```

---

## 4. Data Flow Tong Hop

```
                           EXTERNAL SOURCES
                           ==================
+------------+                                                   |
| Open-Meteo | ----(hourly)---->                                 |
| Weather API|                                                      |
+------------+                                                      |
                                      +-------------+              |
| Event CSV  | ----(daily)------>     |             |              |
| (manual)  |                        |  FEATURE    |              |
+------------+                       |  STORE      |  ---->  ALERTS
                                     |             |              |
+------------+                       | hex_id      |              hex_id
| Flood RSS  | ----(15 min)---->     | datetime   |              severity
| (VNExpress)|                      | weather    |              causes
+------------+                       | event      |              deviation
                                     | flood      |              |
+------------+                       | holiday    |              |
| Holiday    | ----(monthly)---->   | demand     |              |
| Calendar   |                       | ...        |              |
+------------+                       +------+------+              |
                                            |                     |
                                            v                     |
                                   +---------------+              |
                                   | LIGHTGBM      |              |
                                   | spike_predict |              |
                                   | .pkl          |              |
                                   +-------+-------+              |
                                           |                      |
                                           v                      |
                                   +---------------+              |
                                   | CUSUM         | ---------------
                                   | FILTER        |
                                   | (reduce FPs)  |
                                   +---------------+
```

---

## 5. Dieu Ban Can Xac Nhan Voi Mentor

### 5.1 DATA ACCESS

**Ban co access vao demand data (requests per hex per 30min)?**

Day la data cot loi - khong co thi khong lam duoc gi ca.

**Neu KHONG co access:**
- Phuong an thay the: Dung historical data tu reports/logs
- Hoac mock data de demo concept

### 5.2 TECHNICAL STACK

**Tech stack hien tai cua team la gi?**

- Python? R? SQL?
- Cloud platform? (AWS, GCP, Azure?)
- Existing data infrastructure?
- Monitoring/Alerting system hien tai?

-> Xac dinh de align architecture vao he thong hien co

### 5.3 SCOPE CLARIFICATION

**MVP co can real-time khong, hay batch (daily) la du?**

| Option | Complexity | Timeline |
|--------|------------|----------|
| Batch (daily) | Don gian hon | 4 tuan ✅ |
| Near real-time (15-30 min) | Phuc tap hon | Can them time |

**Dashboard can interactive khong, hay static report la du?**

### 5.4 INTEGRATION POINT

**Alert output can integrate vao dau?**

- Slack/Teams notification?
- Email?
- Existing MOC dashboard?
- Database table cho ops team query?

---

## 6. Simplified MVP Architecture (4 tuan) voi BACKFILL

> **BACKFILL STRATEGY CHO MVP**
>
> De dat TC3 (≥2 data sources) va train model hieu qua, MVP can backfill du data sources.

```
+-------------------------------------------------------------------------+
|                       SIMPLIFIED MVP (4 WEEKS)                          |
+-------------------------------------------------------------------------+
|                                                                          |
|  WEEK 1: BACKFILL + Data Pipeline                                     |
|  ------------------------------------------------------------------     |
|                                                                          |
|  BACKFILL (U u tien cao nhat):                                         |
|  +- Weather: Open-Meteo API voi past_days=60                          |
|  +- Flood: Wayback Machine archive VNExpress RSS                        |
|  +- Holiday: Static calendar 2023-2024                                  |
|  +- Events: Manual CSV (thu thap tu Ticketbox)                         |
|  +- Demand: Export tu internal database                                 |
|                                                                          |
|  weather.csv <-- Open-Meteo API (past_days=60)                         |
|  events.csv  <-- Manual entry (daily)                                  |
|  flood.csv   <-- Wayback Machine RSS Archive                            |
|  holiday.csv <-- Static Calendar (2023-2024)                           |
|                                                                          |
|  +-->                                                                   |
|                                                                          |
|  feature_store.csv                                                      |
|  (hex_id, datetime, weather, event, flood, holiday, demand)            |
|  <-- DAY DU features cho training                                     |
|                                                                          |
|  WEEK 2: Manual Labeling + Train                                       |
|  ------------------------------------------------------------------     |
|                                                                          |
|  1. Xem feature_store.csv trong Dataset Viewer                        |
|  2. Gan nhan: is_spike, primary_cause, confidence                     |
|  3. Train LightGBM voi day du features                                |
|                                                                          |
|  WEEK 3: Detection + Alerting                                         |
|  ------------------------------------------------------------------     |
|                                                                          |
|  CUSUM Detector (Real-time)                                           |
|  +- Per-hex baseline (moving average)                                  |
|  +- Per-hex threshold (volatility-based)                              |
|  +- Model inference (spike_predictor.pkl)                             |
|                                                                          |
|  Output:                                                                |
|  +- alerts.csv (hex, time, severity, cause, deviation)                 |
|  +- alerts.json (for API consumption)                                  |
|                                                                          |
|  WEEK 4: Dashboard + Documentation                                     |
|  ------------------------------------------------------------------     |
|                                                                          |
|  Streamlit Dashboard                                                   |
|  +- Time series chart (demand vs baseline)                            |
|  +- Alert table (filterable by severity)                              |
|  +- Metrics summary (TC1-TC4 compliance)                               |
|                                                                          |
|  Documentation                                                         |
|  +- README.md                                                          |
|  +- Architecture diagram                                               |
|  +- Setup & run instructions                                          |
|                                                                          |
+-------------------------------------------------------------------------+
```

### Backfill Checklist

```
+-------------------------------------------------------------------------+
|                     BACKFILL CHECKLIST                                  |
+-------------------------------------------------------------------------+
|                                                                          |
|  [ ] Weather: Open-Meteo API                                           |
|      curl "https://api.open-meteo.com/v1/forecast?past_days=60&..."   |
|                                                                          |
|  [ ] Flood: Wayback Machine                                             |
|      https://web.archive.org/web/{timestamp}/vnexpress.net/rss/         |
|                                                                          |
|  [ ] Holiday: Tao file holidays.csv                                    |
|      - Tet Nguyen Dan 2024 (10/02/2024)                                |
|      - Tet Duong Lich 2024 (01/01/2024)                                |
|      - Gio To Hung Vuong 2024 (18/04/2024)                            |
|      - Quoc Khanh 2024 (02/09/2024)                                    |
|                                                                          |
|  [ ] Events: Manual collection                                          |
|      - Thu thap tu Ticketbox API (historical events)                   |
|      - Hoac manual entry vao events.csv                                |
|                                                                          |
|  [ ] Demand: Export tu internal system                                 |
|      - Yeu cau team backend export CSV                                  |
|      - Format: timestamp, hex_id, requests, avg_eta_min               |
|                                                                          |
|  [ ] Validate: Dam bao du 8 tuan data cho moi source                   |
|                                                                          |
+-------------------------------------------------------------------------+
```

---

## Tom Tat

| Component | Input | Output |
|-----------|-------|--------|
| Data Pipeline | Weather API, Events CSV, Flood RSS | Feature Store (CSV) |
| CUSUM Detector | Feature Store + Demand | Alerts (JSON) |
| Dashboard | Alerts | Visualizations |

| TC | Metric | Target |
|----|--------|--------|
| TC1 | Detection Rate | ≥80% |
| TC2 | False Alerts | ≤2/day |
| TC3 | Data Sources | ≥2 |
| TC4 | Alert Completeness | hex, severity, causes |
