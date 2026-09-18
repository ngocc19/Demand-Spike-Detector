
## Workflow Tổng Quan

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                      │
└──────────────────────────────────────────────────────────────────────────────┘

    ╔═══════════════════════════════════════════════════════════════════════╗
    ║                        PHASE 1: OFFLINE                                 ║
    ║                   (Xây dựng Training Set)                              ║
    ║                   ────────────────────────                              ║
    ║                   Môi trường: STATIC                                    ║
    ╚═══════════════════════════════════════════════════════════════════════╝
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  1.1 THU THẬP DỮ LIỆU QUÁ KHỨ (Static Collection)                  │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │     ┌──────────────────────────────────────────────────────────┐   │
    │     │            PLUGIN REGISTRY (Config-Driven)                 │   │
    │     │            factors.yaml                                    │   │
    │     │            ─────────────                                   │   │
    │     │  config:                                                 │   │
    │     │    weather: schedule, source, radius_km                   │   │
    │     │    flood:   schedule, rss_sources                        │   │
    │     │    event:   schedule, ticketbox_api                      │   │
    │     │    holiday: schedule, holiday_file                        │   │
    │     └──────────────────────────────────────────────────────────┘   │
    │                              │                                       │
    │                              ▼                                       │
    │     ┌─────────────────────────────────────────────────────────┐     │
    │     │              PLUGIN LOADER (Dynamic Discovery)           │     │
    │     │                                                        │     │
    │     │  ┌────────────┐ ┌────────────┐ ┌────────────┐          │     │
    │     │  │  Weather  │ │   Flood    │ │   Event    │   ...   │     │
    │     │  │  Plugin   │ │   Plugin   │ │   Plugin   │          │     │
    │     │  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘          │     │
    │     │        │              │              │                  │     │
    │     │        └──────────────┴──────────────┘                  │     │
    │     │                     │                                    │     │
    │     │                     ▼                                    │     │
    │     │           ┌─────────────────────┐                      │     │
    │     │           │  FactorRecord[]     │                      │     │
    │     │           │  Standard Contract   │                      │     │
    │     │           │  (hex_id, datetime, │                      │     │
    │     │           │   factor_type, value)│                      │     │
    │     │           └─────────────────────┘                      │     │
    │     └─────────────────────────────────────────────────────────┘     │
    │                              │                                       │
    │                              ▼                                       │
    │     ┌──────────────────────────────────────────────────────────┐   │
    │     │              FEATURE STORE (Parquet)                     │   │
    │     │              Dynamic Schema (Pivot Table)                │   │
    │     │              ───────────────────────────                 │   │
    │     │  ┌────────────┬──────────────┬────────┬────────┬────┐   │   │
    │     │  │ hex_id     │datetime_30min│ weather│ flood  │event│   │   │
    │     │  ├────────────┼──────────────┼────────┼────────┼────┤   │   │
    │     │  │ 8a2a100...│2023-08-15 14│  0.3   │  0.0   │ 0.0 │   │   │
    │     │  │ 8a2a100...│2023-08-15 14│  0.0   │  0.85  │ 1.0 │   │   │
    │     │  └────────────┴──────────────┴────────┴────────┴────┘   │   │
    │     │  # Schema tự động mở rộng khi thêm factor mới!        │   │
    │     └──────────────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  1.2 GẮN NHÃN THỦ CÔNG (Manual Labeling)                           │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │  DATASET VIEWER (Streamlit/Dash App)                        │    │
    │  │                                                             │    │
    │  │   datetime        hex_id     demand   baseline   spike?   │    │
    │  │   ─────────────────────────────────────────────────────    │    │
    │  │   2023-08-15 14:00   H1       245      120       [✓ spike] │    │
    │  │   2023-08-15 14:00   H2       180      115       [ ]       │    │
    │  │   2023-08-15 14:00   H3        95       98       [ ]       │    │
    │  │   2023-08-15 15:00   H1       289      125       [✓ spike] │    │
    │  │                              ▲                              │    │
    │  │                         Heavy rain                         │    │
    │  │                         + concert                          │    │
    │  └─────────────────────────────────────────────────────────────┘    │
    │                              │                                         │
    │         ┌────────────────────┼────────────────────┐                   │
    │         │                    │                    │                   │
    │         ▼                    ▼                    ▼                   │
    │   is_spike=True       primary_cause          confidence              │
    │   (boolean)           (enum)                  (0.0-1.0)              │
    │                       - weather                                       │
    │                       - event                                         │
    │                       - flood                                         │
    │                       - holiday                                       │
    │                       - aoe_sale                                       │
    │                       - concert                                       │
    │                       - multi                                         │
    │                       - unknown                                       │
    │                                                                     │
    │  LABELING RULES:                                                    │
    │  • Spike = demand > 1.5x baseline for that hex, that hour           │
    │  • Primary cause = điều kiện ngoại cảnh rõ ràng nhất               │
    │  • Confidence = 1.0 nếu có 2+ nguồn xác nhận                        │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  1.3 TRAIN MODEL (Supervised Learning)                              │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │     ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      │
    │     │ Train Set   │      │ Validation  │      │  Test Set   │      │
    │     │ 2023-01     │      │ 2023-06     │      │ 2024-01     │      │
    │     │     ↓       │      │     ↓       │      │     ↓       │      │
    │     │ 2023-05     │      │ 2023-09     │      │ 2024-06     │      │
    │     │ (5 months) │      │ (4 months)  │      │ (6 months) │      │
    │     └─────────────┘      └─────────────┘      └─────────────┘      │
    │           │                    │                    │              │
    │           └────────────────────┼────────────────────┘              │
    │                                ▼                                   │
    │                    ┌─────────────────────┐                         │
    │                    │                     │                         │
    │                    │   FEATURE ENGINEERING                      │
    │                    │   ──────────────────                        │
    │                    │   • Weather: temp, rain, humidity           │
    │                    │   • Events: nearby events, capacity         │
    │                    │   • Flood: proximity, severity              │
    │                    │   • Holiday: tet_phase, is_holiday         │
    │                    │   • Temporal: hour, day_of_week, is_holiday │
    │                    │   • Historical: same hour last week         │
    │                    │                     │                        │
    │                    └─────────┬───────────┘                        │
    │                              ▼                                    │
    │                    ┌─────────────────────┐                         │
    │                    │                     │                         │
    │                    │   MODEL TRAINING    │                         │
    │                    │   ──────────────     │                         │
    │                    │   Algorithm options: │                        │
    │                    │   • LightGBM (base)  │                        │
    │                    │   • XGBoost          │                        │
    │                    │   • Neural Network   │                        │
    │                    │                     │                         │
    │                    │   Output:            │                         │
    │                    │   spike_predictor.pkl                      │
    │                    │                     │                         │
    │                    └─────────────────────┘                         │
    └─────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼

    ╔═══════════════════════════════════════════════════════════════════════╗
    ║                        PHASE 2: ONLINE                                  ║
    ║                   (Inference / Production)                             ║
    ║                   ────────────────────────                              ║
    ║                   Môi trường: DYNAMIC                                   ║
    ╚═══════════════════════════════════════════════════════════════════════╝
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  2.1 DEPLOY MODEL                                                   │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │  MODEL REGISTRY                                             │    │
    │  │  ──────────────                                             │    │
    │  │  spike_predictor_v2.pkl  ←── [Promoted from Phase 1]        │    │
    │  │  baseline_lookup.parquet ←── [Historical patterns]           │    │
    │  │  feature_schema.json     ←── [Expected input format]        │    │
    │  └─────────────────────────────────────────────────────────────┘    │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  2.2 REAL-TIME PREDICTION LOOP (Plugin-Driven)                       │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │     ┌─────────────────────────────────────────────────────────┐     │
    │     │                    EVERY SCHEDULE                         │     │
    │     │              (From factors.yaml config)                  │     │
    │     │                                                        │     │
    │     │  ┌─────────────────────────────────────────────────┐   │     │
    │     │  │                                                 │   │     │
    │     │  │   PLUGIN ORCHESTRATOR                            │   │     │
    │     │  │   ───────────────────                            │   │     │
    │     │  │   1. PluginRegistry.load_from_config()           │   │     │
    │     │  │   2. Dynamic discovery via schedule              │   │     │
    │     │  │                                                 │   │     │
    │     │  │   ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │     │
    │     │  │   │ Weather  │  │  Flood   │  │  Event   │   │   │     │
    │     │  │   │Plugin    │  │ Plugin   │  │ Plugin   │   │   │     │
    │     │  │   │(hourly)  │  │(15 min)  │  │(daily)   │   │   │     │
    │     │  │   └────┬─────┘  └────┬─────┘  └────┬─────┘   │   │     │
    │     │  │        │             │             │            │   │     │
    │     │  │        └──────────┬──┴─────────────┘            │   │     │
    │     │  │                   ▼                              │   │     │
    │     │  │         ┌─────────────────┐                     │   │     │
    │     │  │         │  FEATURE STORE │                     │   │     │
    │     │  │         │  (Unified Sink)│                     │   │     │
    │     │  │         │  hex_id,       │                     │   │     │
    │     │  │         │  datetime_30min,│                     │   │     │
    │     │  │         │  weather, flood,│                     │   │     │
    │     │  │         │  event, ...    │                     │   │     │
    │     │  │         └────────┬────────┘                     │   │     │
    │     │  │                  ▼                              │   │     │
    │     │  │         ┌─────────────────┐                     │   │     │
    │     │  │         │                 │                     │   │     │
    │     │  │         │  MODEL.predict  │                     │   │     │
    │     │  │         │  ──────────────  │                     │   │     │
    │     │  │         │  spike_prob     │                     │   │     │
    │     │  │         │  cause_ranking  │                     │   │     │
    │     │  │         │  confidence     │                     │   │     │
    │     │  │         │                 │                     │   │     │
    │     │  │         └─────────────────┘                     │   │     │
    │     │  │                  │                              │   │     │
    │     │  │                  ▼                              │   │     │
    │     │  │         ┌─────────────────┐                     │   │     │
    │     │  │         │   ALERTS &      │                     │   │     │
    │     │  │         │   ACTIONS       │                     │   │     │
    │     │  │         │                 │                     │   │     │
    │     │  │         │  if prob > 0.7: │                     │   │     │
    │     │  │         │    pre-allocate │                     │   │     │
    │     │  │         │    driver_pool   │                     │   │     │
    │     │  │         │                 │                     │   │     │
    │     │  │         └─────────────────┘                     │   │     │
    │     │  │                                                 │   │     │
    │     │  └─────────────────────────────────────────────────┘   │     │
    │     └─────────────────────────────────────────────────────────┘     │
    │                                                                     │
    │  NOTE: Thêm factor mới = Thêm file plugin + Thêm dòng config        │
    │        Không cần sửa Orchestrator!                                  │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  2.3 VALIDATION IN PRODUCTION (Feedback Loop)                       │
    │  ─────────────────────────────────────────                          │
    │                                                                     │
    │     ┌──────────────────────────────────────────────────────────┐    │
    │     │                                                          │    │
    │     │   Predicted Spike    │   Actual Demand                  │    │
    │     │   ───────────────────┼───────────────────────────       │    │
    │     │   2024-08-15 14:00   │   2024-08-15 14:00                │    │
    │     │   H1: prob=0.85      │   H1: demand=289, base=120       │    │
    │     │                      │   actual_ratio=2.4x  ✓ MATCH    │    │
    │     │                                                          │    │
    │     │   H2: prob=0.23      │   H2: demand=118, base=115       │    │
    │     │                      │   actual_ratio=1.03x  ✓ CORRECT │    │
    │     │                      │   (model correctly low confidence│    │
    │     │                      │    for non-spike)                │    │
    │     │                                                          │    │
    │     │   H3: prob=0.71      │   H3: demand=205, base=98        │    │
    │     │                      │   actual_ratio=2.09x  ✓ MATCH   │    │
    │     │                                                          │    │
    │     └──────────────────────────────────────────────────────────┘    │
    │                                 │                                     │
    │                                 ▼                                     │
    │     ┌──────────────────────────────────────────────────────────┐    │
    │     │              MONITORING & ALERTING                        │    │
    │     │                                                          │    │
    │     │   Metrics:                                               │    │
    │     │   • precision_at_0.7 = 0.89  (89% of high-prob alerts   │    │
    │     │                                  were actual spikes)      │    │
    │     │   • recall_at_0.7 = 0.76    (caught 76% of real spikes)  │    │
    │     │   • latency_p95 = 120ms                                  │    │
    │     │                                                          │    │
    │     │   Drift Detection:                                        │    │
    │     │   • If accuracy drops > 5% → Retrain needed             │    │
    │     │   • If new event types appear → Add to training set      │    │
    │     │   • If new factor needed → Add plugin (no code change)   │    │
    │     │                                                          │    │
    │     └──────────────────────────────────────────────────────────┘    │
    │                                 │                                     │
    │                                 │   If drift detected                │
    │                                 └────────────────┐                   │
    │                                                  │                   │
    │                                                  ▼                   │
    │                              ┌─────────────────────────────────┐      │
    │                              │         RETRAIN LOOP             │      │
    │                              │  (Quay lại Phase 1 với data     │      │
    │                              │   mới từ Phase 2)               │      │
    │                              └─────────────────────────────────┘      │
    └─────────────────────────────────────────────────────────────────────┘
```

## Thêm Factor Mới: Chỉ 3 Bước!

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              HƯỚNG DẪN THÊM FACTOR MỚI (Extensible Architecture)           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Ví dụ: Thêm Air Quality (AQI) Factor                                      │
│  ─────────────────────────────────                                         │
│                                                                             │
│  Bước 1: Tạo file plugin mới                                                │
│  ─────────────────────────────                                              │
│                                                                             │
│  FILE: src/pipeline/plugins/pollution_plugin.py                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  from .base import BaseFactorPlugin, FactorType                             │
│  from .registry import PluginRegistry                                       │
│                                                                             │
│  @PluginRegistry.register("pollution")  # ← ĐĂNG KÝ                       │
│  class PollutionFactorPlugin(BaseFactorPlugin):                             │
│      factor_type = FactorType.POLLUTION                                     │
│      factor_name = "pollution"                                              │
│      schedule = "0 * * * *"                                                  │
│                                                                             │
│      def fetch(self) -> pd.DataFrame:                                       │
│          # Call WAQI API → return DataFrame                                 │
│          ...                                                                │
│                                                                             │
│      def transform(self, df):                                               │
│          # AQI → impact value (0.0-1.0)                                    │
│          df['value'] = df['aqi'].apply(self._aqi_to_impact)                │
│          return df                                                          │
│                                                                             │
│      def map_spatial(self, df):                                             │
│          # lat/lng → H3 hex_id                                              │
│          df['hex_id'] = df.apply(lambda r: h3.latlng_to_cell(...), axis=1)  │
│          return df                                                          │
│                                                                             │
│  ########################################################################  │
│                                                                             │
│  Bước 2: Thêm dòng vào factors.yaml                                        │
│  ─────────────────────────────────────                                      │
│                                                                             │
│  FILE: config/factors.yaml                                                  │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  factors:                                                                    │
│    - name: weather                                                         │
│      ... (existing)                                                        │
│                                                                             │
│  # THÊM MỚI:                                                              │
│    - name: pollution                                                       │
│      type: api                                                             │
│      source: waqi                                                          │
│      schedule: "0 * * * *"           # Mỗi giờ                             │
│      enabled: true                                                         │
│      config:                                                                │
│        city: "Ho_Chi_Minh_City"                                            │
│        threshold_aqi: 100                                                  │
│        api_key: "${WAQI_API_KEY}"  # Environment variable                   │
│                                                                             │
│  ########################################################################  │
│                                                                             │
│  Bước 3: Done! (Không cần sửa gì khác)                                    │
│  ─────────────────────────────────────────                                  │
│                                                                             │
│  $ python -m src.pipeline.orchestrator                                      │
│                                                                             │
│  Output:                                                                    │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │  ✓ weather completed: 4500 records                                  │   │
│  │  ✓ flood completed: 12 records                                     │   │
│  │  ✓ event completed: 28 records                                     │   │
│  │  ✓ holiday completed: 2 records                                    │   │
│  │  ✓ pollution completed: 156 records  ← TỰ ĐỘNG DISCOVER!         │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3 Góc nhìn về "Môi trường" (Environment)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   1. DATA ENVIRONMENT (Dữ liệu)                                            │
│   ───────────────────────────                                               │
│                                                                             │
│      STATIC                         │           DYNAMIC                     │
│      (Training)                     │           (Inference)                  │
│      ──────────                     │           ──────────                   │
│      • Historical data              │           • Live data streams          │
│      • Fixed, immutable             │           • Plugin-driven updates       │
│      • "What happened?"            │           • "What will happen?"          │
│                                     │                                        │
│                                     │                                        │
│   2. MODEL ENVIRONMENT (Mô hình)                                           │
│   ──────────────────────────                                                │
│                                                                             │
│      OFFLINE TRAINING                 │       ONLINE INFERENCE               │
│      ────────────────                 │       ─────────────────               │
│      • Batch processing              │       • Real-time prediction           │
│      • GPU compute                   │       • CPU optimized                  │
│      • Hours to days                 │       • Milliseconds                   │
│      • "Learn patterns"             │       • "Apply patterns"                │
│                                     │                                        │
│                                     │                                        │
│   3. FEEDBACK ENVIRONMENT (Vòng lặp)                                       │
│   ──────────────────────────────────                                        │
│                                                                             │
│      ┌────────────────────────────────────────────────────────────────┐      │
│      │                                                                │      │
│      │    Training Labels    ──────►    Model    ──────►  Predictions │      │
│      │         │                                    │                 │      │
│      │         │                                    │                 │      │
│      │         │              ▲                     │                 │      │
│      │         │              │                     │                 │      │
│      │         │              │                     │                 │      │
│      │    Human                │               Actual Results         │      │
│      │    Expert               │               (Feedback)             │      │
│      │    Review               │                                    │      │
│      │                                                                │      │
│      └────────────────────────────────────────────────────────────────┘      │
│                                    ▲                                         │
│                                    │                                         │
│                       If predictions wrong                                  │
│                       → Add to training set                                  │
│                       → Relabel if needed                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tóm tắt ngắn gọn

| Bước | Environment | Mục đích |
|------|-------------|----------|
| 1. Cào dữ liệu quá khứ | **Static** | Thu thập ground truth (Plugin-driven) |
| 2. Gắn nhãn thủ công | **Static** (nhưng human-in-the-loop) | Tạo training labels |
| 3. Train model | **Offline** | Học pattern từ labels |
| 4. Deploy inference | **Dynamic** | Predict real-time |
| 5. Validate & feedback | **Static + Dynamic hybrid** | Cải thiện model |

## Design Principles

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    5 NGUYÊN TẮC THIẾT KẾ PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. DEPENDENCY INVERSION (Interface thay vì Implementation)                │
│     ─────────────────────────────────────────────────                       │
│     BaseFactorPlugin defines contract                                        │
│     Specific plugins implement contract                                       │
│     Orchestrator depends on abstraction, not concrete classes               │
│                                                                             │
│  2. OPEN-CLOSED PRINCIPLE (Open for extension, Closed for modification)    │
│     ─────────────────────────────────────────────────                       │
│     • Thêm feature = Thêm file mới, không sửa file cũ                       │
│     • Config-driven thay vì hard-coded                                       │
│                                                                             │
│  3. SINGLE RESPONSIBILITY (Mỗi plugin = 1 factor)                          │
│     ─────────────────────────────────                                       │
│     • Plugin này chỉ lo weather, plugin kia chỉ lo flood                    │
│     • Orchestrator chỉ điều phối, không xử lý logic                         │
│                                                                             │
│  4. CONFIGURATION OVER CODE                                                 │
│     ────────────────────────                                                │
│     • Schedule, API keys, thresholds → factors.yaml                          │
│     • Code chỉ định nghĩa behavior, config chỉ định nghĩa parameters      │
│                                                                             │
│  5. STANDARDIZED DATA CONTRACT (FactorRecord)                               │
│     ─────────────────────────────────                                       │
│     • Tất cả plugins trả về cùng format                                     │
│     • Feature Store pivot tự động                                            │
│     • Schema mở rộng không cần migration                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**Tóm tắt workflow**:

```
Static (Offline)     →     Dynamic (Online)
─────────────────────────────────────────────────────────────
Plugin Registry             Plugin Orchestrator
Config: factors.yaml       Load from config
     │                           │
     ▼                           ▼
BaseFactorPlugin ──────────► Feature Store
     │                           │
     ▼                           ▼
Feature Engineering ──────► Model.predict()
     │                           │
     ▼                           ▼
spike_predictor.pkl ◄──────── Alerts & Actions
     │
     ▼
Feedback Loop → Retrain if drift detected
```

Đây là **extensible supervised learning pipeline** với Plugin Architecture.
