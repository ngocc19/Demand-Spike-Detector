# Demand Spike Detector - Architecture Design (Option C)

## 1. Overview

**Option C: Progressive Ensemble Expansion**

| Phase | Timeline | Model | Features | Inference Method |
|-------|----------|-------|----------|-----------------|
| MVP | Week 1-3 | Model v1 | VCW + OWM only | Model + Rule Override |
| Production | Week 4+ | Model v2 | ALL 4 sources | Full Ensemble |

**Principle:** Train-Serve Consistency - Model chỉ thấy features trong training.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEMAND SPIKE DETECTOR                               │
│                         OPTION C ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    EXTERNAL DATA SOURCES                             │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │   │
│  │  │   VCW    │ │   OWM    │ │   HSDC   │ │  NCHMF   │           │   │
│  │  │(Weather) │ │(Weather) │ │(Rainfall)│ │ (Storm)  │           │   │
│  │  │ Visual   │ │ Open     │ │ Hà Nội   │ │ National │           │   │
│  │  │Crossing  │ │Weather   │ │API       │ │Climate   │           │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │   │
│  └─────────┼────────────┼────────────┼────────────┼───────────────────┘   │
│              │            │            │            │                        │
│              └────────────┴─────┬──────┴────────────┘                        │
│                                │                                           │
│                                ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    API GATEWAY                                       │   │
│  │                 (FastAPI / Flask)                                    │   │
│  │  ┌───────────────────────────────────────────────────────────────┐ │   │
│  │  │  POST /predict                                              │ │   │
│  │  │  { hex_id, timestamp }                                      │ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └───────────────────────────────┬─────────────────────────────────────┘   │
│                                  │                                           │
│              ┌───────────────────┼───────────────────┐                       │
│              │                   │                   │                       │
│              ▼                   ▼                   ▼                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐        │
│  │   Model v1       │  │   Model v2       │  │  Data Lake       │        │
│  │   (Week 1-3)    │  │   (Week 4+)      │  │  (Async Log)     │        │
│  │                  │  │                  │  │                  │        │
│  │  VCW + OWM      │  │  ALL 4 sources  │  │  Raw data        │        │
│  │  Ensemble only   │  │  Full Ensemble   │  │  predictions     │        │
│  │                  │  │                  │  │                  │        │
│  │  + Rule Override │  │  No override     │  │  → Model v3      │        │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Phase 1: MVP (Week 1-3)

### 3.1 Training Data Collection

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: TRAINING DATA COLLECTION                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DATA SOURCES:                                                            │
│  ┌──────────┐ ┌──────────┐                                                │
│  │   VCW    │ │   OWM    │  ← Model v1 chỉ học 2 sources này           │
│  │(History) │ │(History) │                                                │
│  └────┬─────┘ └────┬─────┘                                                │
│       │            │                                                       │
│       └─────┬──────┘                                                       │
│             │                                                               │
│             ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │              ENSEMBLE MODEL FEATURES                               │       │
│  │  ┌─────────────────────────────────────────────────────────┐   │       │
│  │  │  blended_weather = w1×VCW + w2×OWM                    │   │       │
│  │  │  (chỉ 2 sources, không có HSDC/NCHMF)                 │   │       │
│  │  └─────────────────────────────────────────────────────────┘   │       │
│  └───────────────────────────────┬─────────────────────────────────┘       │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                    TRAINING DATASET                                │       │
│  │  ┌─────────────────────────────────────────────────────────┐   │       │
│  │  │  hex_id | datetime | blended_weather | is_spike | ...   │   │       │
│  │  │  88415.. | 2026-04-20 | 0.45 | 1 | ...              │   │       │
│  │  │  88415.. | 2026-04-20 | 0.12 | 0 | ...              │   │       │
│  │  │  ...                                                    │   │       │
│  │  └─────────────────────────────────────────────────────────┘   │       │
│  └───────────────────────────────┬─────────────────────────────────┘       │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                    TRAIN LIGHTGBM                                   │       │
│  │  ┌─────────────────────────────────────────────────────────┐   │       │
│  │  │  Model v1: spike_predictor_v1.pkl                       │   │       │
│  │  │  Features: blended_weather, time, lags, rolling         │   │       │
│  │  └─────────────────────────────────────────────────────────┘   │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Inference Pipeline (MVP)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: INFERENCE PIPELINE                             │
│                         (Week 1-3)                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Request: POST /predict                                                    │
│  Body: { hex_id: "88415cb4e5fffff", timestamp: "2026-09-25 14:00" }   │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 1: FETCH ALL DATA (Parallel)                                │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │      ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌───────┐ │    │
│  │      │   VCW   │     │   OWM   │     │  HSDC  │     │ NCHMF │ │    │
│  │      │ Real-  │     │ Real-   │     │ Real-  │     │Real-  │ │    │
│  │      │ time   │     │ time    │     │ time   │     │time   │ │    │
│  │      └────┬────┘     └────┬────┘     └────┬────┘     └───┬───┘ │    │
│  │           └──────────────┼───────────────┼──────────────┘       │    │
│  │                          │               │                       │    │
│  │                          └───────────────┼───────────────────────┘    │
│  │                                          │                            │    │
│  └──────────────────────────────────────────┼────────────────────────────┘    │
│                                             │                              │
│                                             ▼                              │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 2: SPLIT DATA                                              │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  ┌─────────────────────────────────┐  ┌─────────────────────┐    │    │
│  │  │  MODEL FEATURES (v1)            │  │  OVERRIDE RULES    │    │    │
│  │  │  ─────────────────────         │  │  ─────────────────  │    │    │
│  │  │  VCW: temp, rain, humidity     │  │  HSDC: flood_level │    │    │
│  │  │  OWM: temp, rain, humidity    │  │  NCHMF: warning    │    │    │
│  │  │                                 │  │                     │    │    │
│  │  │  → ensemble =                  │  │  → if flood >= 3:   │    │    │
│  │  │    w1×VCW + w2×OWM            │  │    override = True  │    │    │
│  │  └──────────────┬──────────────────┘  └──────────┬──────────┘    │    │
│  │                 │                               │                 │    │
│  └─────────────────┼───────────────────────────────┼─────────────────┘    │
│                    │                               │                       │
│                    │                               │                       │
│                    ▼                               ▼                       │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 3: PREDICT + OVERRIDE                                        │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  ┌─────────────────────────────────────────────────────────────┐ │    │
│  │  │  MODEL PREDICTION                                          │ │    │
│  │  │  ─────────────────────────                               │ │    │
│  │  │  features = {                                             │ │    │
│  │  │    blended_weather: 0.35,    ← from ensemble (v1)       │ │    │
│  │  │    hour_of_day: 14,                                       │ │    │
│  │  │    ...                                                     │ │    │
│  │  │  }                                                         │ │    │
│  │  │  model_prob = model_v1.predict(features) → 0.35            │ │    │
│  │  └──────────────────────────────┬────────────────────────────┘ │    │
│  │                                 │                              │    │
│  │                                 ▼                              │    │
│  │  ┌─────────────────────────────────────────────────────────────┐ │    │
│  │  │  DECISION MATRIX                                          │ │    │
│  │  │  ─────────────────────────                               │ │    │
│  │  │                                                           │ │    │
│  │  │  model_prob=0.35, hsd_flood=2, nchmf=false              │ │    │
│  │  │  → model_prob < 0.5 AND hsd_flood < 3                  │ │    │
│  │  │  → NO_OVERRIDE                                           │ │    │
│  │  │  → Final: NO_SPIKE (severity=LOW)                       │ │    │
│  │  │                                                           │ │    │
│  │  │  model_prob=0.35, hsd_flood=3, nchmf=false             │ │    │
│  │  │  → hsd_flood >= 3                                      │ │    │
│  │  │  → OVERRIDE: SPIKE (severity=HIGH, cause=flood)        │ │    │
│  │  │                                                           │ │    │
│  │  │  model_prob=0.35, hsd_flood=2, nchmf=true              │ │    │
│  │  │  → nchmf_warning = True                                 │ │    │
│  │  │  → OVERRIDE: SPIKE (severity=HIGH, cause=storm)         │ │    │
│  │  │                                                           │ │    │
│  │  │  model_prob=0.75, hsd_flood=0, nchmf=false            │ │    │
│  │  │  → model_prob >= 0.5                                   │ │    │
│  │  │  → NO_OVERRIDE                                          │ │    │
│  │  │  → Final: SPIKE (severity=MEDIUM, cause=model)         │ │    │
│  │  │                                                           │ │    │
│  │  └─────────────────────────────────────────────────────────────┘ │    │
│  │                                                                   │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│                                  │                                          │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 4: RETURN RESPONSE                                          │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  Response:                                                       │    │
│  │  {                                                               │    │
│  │    "alert_id": "SPK-20260925-1400-001",                        │    │
│  │    "hex_id": "88415cb4e5fffff",                                │    │
│  │    "timestamp": "2026-09-25 14:00",                            │    │
│  │    "spike": true,                                               │    │
│  │    "severity": "HIGH",                                          │    │
│  │    "model_prob": 0.35,                                         │    │
│  │    "override_triggered": true,                                  │    │
│  │    "override_cause": "flood",                                  │    │
│  │    "deviation_pct": 45.2                                       │    │
│  │  }                                                              │    │
│  │                                                                   │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Decision Matrix

```python
# PHASE 1: Model v1 + Rule Override

DECISION_RULES = [
    # Priority 1: NCHMF Storm Warning → ALWAYS spike
    {
        "condition": "nchmf_warning == True",
        "action": "SPIKE",
        "severity": "CRITICAL",
        "cause": "storm",
        "reason": "NCHMF official storm warning"
    },

    # Priority 2: HSDC Flood Level >= 3 → spike
    {
        "condition": "hsd_flood_level >= 3",
        "action": "SPIKE",
        "severity": "HIGH",
        "cause": "flood",
        "reason": "Severe flooding detected"
    },

    # Priority 3: HSDC Flood Level 2 → medium spike
    {
        "condition": "hsd_flood_level == 2",
        "action": "SPIKE",
        "severity": "MEDIUM",
        "cause": "flood",
        "reason": "Moderate flooding"
    },

    # Priority 4: Model probability >= threshold
    {
        "condition": "model_prob >= 0.5",
        "action": "SPIKE",
        "severity": "MEDIUM",
        "cause": "model",
        "reason": "Model prediction"
    },

    # Priority 5: No spike
    {
        "condition": "else",
        "action": "NO_SPIKE",
        "severity": "LOW",
        "cause": None,
        "reason": "No significant factors"
    }
]
```

---

## 4. Phase 2: Model v2 (Week 4+)

### 4.1 Retrain Criteria

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: RETRAIN TRIGGER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TRIGGER CONDITIONS:                                                       │
│  ──────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  □ Time-based:    ≥ 4 weeks of data collected                            │
│  □ Volume:        ≥ 10,000 spike events in data lake                      │
│  □ Diversity:      ≥ 3 different weather patterns detected                  │
│  □ Quality:       Data freshness < 24 hours                               │
│                                                                             │
│  ──────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  RETRAIN SCHEDULE:                                                        │
│  - Weekly: Auto-retrain every Sunday at 02:00                             │
│  - Manual: Trigger via API / CI-CD pipeline                               │
│  - Drift: Auto-retrain when accuracy drops > 5%                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Training Data for Model v2

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: MODEL V2 TRAINING                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DATA SOURCES (From Data Lake):                                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │   VCW    │ │   OWM    │ │  HSDC    │ │  NCHMF   │                    │
│  │(History) │ │(History) │ │(History) │ │(History) │                    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘                    │
│       └─────────────┼─────────────┼─────────────┘                         │
│                     │             │                                         │
│                     └──────┬──────┘                                        │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────┐      │
│  │              FULL ENSEMBLE FEATURES                               │      │
│  │  ┌─────────────────────────────────────────────────────────┐   │      │
│  │  │  blended = w1×VCW + w2×OWM + w3×HSDC + w4×NCHMF       │   │      │
│  │  │  (4 sources, đầy đủ cho Model v2)                       │   │      │
│  │  │                                                           │   │      │
│  │  │  Weights:                                                  │   │      │
│  │  │  - w1 (VCW): 0.30   (weather data)                     │   │      │
│  │  │  - w2 (OWM): 0.25   (weather data)                     │   │      │
│  │  │  - w3 (HSDC): 0.35  (ground truth rainfall)           │   │      │
│  │  │  - w4 (NCHMF): 0.10  (storm warnings)                │   │      │
│  │  └─────────────────────────────────────────────────────────┘   │      │
│  └───────────────────────────────┬─────────────────────────────────┘      │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐      │
│  │                    TRAINING DATASET                                │      │
│  │  ┌─────────────────────────────────────────────────────────┐   │      │
│  │  │  hex_id | datetime | blended_full | is_spike | ...     │   │      │
│  │  │  88415.. | 2026-04-20 | 0.65 | 1 | ...              │   │      │
│  │  │  ...                                                    │   │      │
│  │  │  (4 tuần data đã collect từ Phase 1)                   │   │      │
│  │  └─────────────────────────────────────────────────────────┘   │      │
│  └───────────────────────────────┬─────────────────────────────────┘      │
│                                  │                                          │
│                                  ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐      │
│  │                    TRAIN LIGHTGBM                                   │      │
│  │  ┌─────────────────────────────────────────────────────────┐   │      │
│  │  │  Model v2: spike_predictor_v2.pkl                       │   │      │
│  │  │  Features: blended_full, time, lags, rolling             │   │      │
│  │  │  ← Tất cả 4 sources!                                   │   │      │
│  │  └─────────────────────────────────────────────────────────┘   │      │
│  └─────────────────────────────────────────────────────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Inference Pipeline (Model v2)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: INFERENCE PIPELINE                             │
│                         (Week 4+)                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Request: POST /predict                                                    │
│  Body: { hex_id: "88415cb4e5fffff", timestamp: "2026-09-25 14:00" }   │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 1: FETCH ALL DATA (Parallel)                                │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │      ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐              │    │
│  │      │   VCW   │ │   OWM   │ │  HSDC  │ │ NCHMF │              │    │
│  │      └────┬────┘ └────┬────┘ └────┬────┘ └───┬───┘              │    │
│  │           └──────────┼───────────┼──────────┘                      │    │
│  │                      └───────────┼──────────────────────────────────┘    │
│  │                                  │                                  │    │
│  └──────────────────────────────────┼──────────────────────────────────┘    │
│                                     │                                     │
│                                     ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 2: FULL ENSEMBLE                                            │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  blended_full = w1×VCW + w2×OWM + w3×HSDC + w4×NCHMF         │    │
│  │                                                                   │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │  blended_full = 0.35 + 0.20 + 0.30 + 0.10 = 0.95   │   │    │
│  │  │  (scaled to 0-1)                                     │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                                                                   │    │
│  └─────────────────────────────────┬───────────────────────────────┘    │
│                                    │                                     │
│                                    ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 3: MODEL V2 PREDICTION                                       │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  features = {                                                      │    │
│  │    blended_full: 0.95,    ← from full ensemble                  │    │
│  │    hsd_flood: 3,           ← NEW: model đã học feature này!   │    │
│  │    nchmf_warning: true,    ← NEW: model đã học feature này!   │    │
│  │    hour_of_day: 14,                                             │    │
│  │    ...                                                           │    │
│  │  }                                                               │    │
│  │                                                                   │    │
│  │  model_prob = model_v2.predict(features) → 0.87                 │    │
│  │  ← Model v2 đã học pattern HSDC + NCHMF!                       │    │
│  │                                                                   │    │
│  └─────────────────────────────────┬───────────────────────────────┘    │
│                                    │                                     │
│                                    ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  STEP 4: RETURN RESPONSE (No Override Needed!)                     │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  model_prob = 0.87 >= 0.5                                       │    │
│  │  → Final: SPIKE (severity=HIGH, cause=model)                     │    │
│  │  ← KHÔNG CẦN RULE OVERRIDE! Model đã capture đầy đủ!          │    │
│  │                                                                   │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Automated Labeling Loop

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUTOMATED LABELING LOOP                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CRONJOB: Nightly at 01:00 AM                                              │
│  ──────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  1. FETCH ACTUAL DEMAND                                            │  │
│  │  ────────────────────────────────────────────────────────────────│  │
│  │                                                                     │  │
│  │  Query: "SELECT hex_id, timestamp, SUM(requests)"                │  │
│  │  FROM demand_actual                                                │  │
│  │  WHERE timestamp >= NOW() - 24h                                   │  │
│  │  GROUP BY hex_id, timestamp"                                      │  │
│  │                                                                     │  │
│  │  Result:                                                           │  │
│  │  ┌──────────┬────────────────┬───────────┐                        │  │
│  │  │ hex_id   │ timestamp      │ requests   │                        │  │
│  │  ├──────────┼────────────────┼───────────┤                        │  │
│  │  │ 88415.. │ 2026-09-25 14 │ 78        │                        │  │
│  │  │ 88415.. │ 2026-09-25 15 │ 45        │                        │  │
│  │  └──────────┴────────────────┴───────────┘                        │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  2. CALCULATE BASELINE & SPIKE                                    │  │
│  │  ────────────────────────────────────────────────────────────────│  │
│  │                                                                     │  │
│  │  For each (hex_id, hour, dow):                                   │  │
│  │    baseline = median(last_4_weeks)                                │  │
│  │    threshold = baseline × 1.3                                      │  │
│  │    is_spike = (demand > threshold)                                │  │
│  │                                                                     │  │
│  │  Example:                                                         │  │
│  │    hex=88415.., hour=14, dow=Friday                               │  │
│  │    baseline = 45 (median of 4 Fridays at 2PM)                    │  │
│  │    threshold = 45 × 1.3 = 58.5                                    │  │
│  │    demand = 78 > 58.5 → is_spike = TRUE ✓                         │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  3. UPDATE DATABASE                                               │  │
│  │  ────────────────────────────────────────────────────────────────│  │
│  │                                                                     │  │
│  │  UPDATE weather_predictions                                        │  │
│  │  SET is_spike = TRUE,                                             │  │
│  │      actual_demand = 78,                                         │  │
│  │      baseline_demand = 45,                                        │  │
│  │      spike_ratio = 78/45 = 1.73,                                │  │
│  │      labeled_at = NOW()                                           │  │
│  │  WHERE hex_id = '88415..'                                        │  │
│  │    AND timestamp = '2026-09-25 14:00'                            │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Labeling Database Schema Update

```sql
-- Add columns for automated labeling
ALTER TABLE weather_predictions 
ADD COLUMN actual_demand INTEGER,
ADD COLUMN baseline_demand FLOAT,
ADD COLUMN spike_ratio FLOAT,
ADD COLUMN labeled_at TIMESTAMPTZ;

-- Update indexing for labeling queries
CREATE INDEX idx_predictions_unlabeled ON weather_predictions (created_at DESC) 
WHERE is_spike IS NULL;
```

### 5.2 Labeling Cronjob Code

```python
# scripts/labeling_job.py
"""
Automated Labeling Cronjob
Runs nightly to label spike data based on actual demand
"""

from datetime import datetime, timedelta
import pandas as pd

def run_labeling_job():
    """Main labeling job - runs at 01:00 AM daily"""
    
    # 1. Fetch unlabeled predictions from last 24h
    unlabeled = fetch_unlabeled_predictions(last_24h=True)
    
    # 2. Fetch actual demand data
    actual_demand = fetch_actual_demand(unlabeled['hex_id'].unique())
    
    # 3. Calculate baseline for each (hex_id, hour, dow)
    baseline = calculate_baseline(actual_demand)
    
    # 4. Label each prediction
    for _, pred in unlabeled.iterrows():
        is_spike, ratio = calculate_spike(
            actual_demand.get(pred['hex_id'], {}).get(pred['timestamp']),
            baseline.get((pred['hex_id'], pred['hour'], pred['dow']))
        )
        
        update_prediction_label(
            hex_id=pred['hex_id'],
            timestamp=pred['timestamp'],
            is_spike=is_spike,
            actual_demand=actual_demand.get(pred['hex_id'], {}).get(pred['timestamp']),
            baseline_demand=baseline.get((pred['hex_id'], pred['hour'], pred['dow'])),
            spike_ratio=ratio
        )
    
    return len(unlabeled)
```

---

## 6. Shadow Mode (Pre-A/B Testing)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SHADOW MODE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PURPOSE:                                                                 │
│  Validate Model v2 offline before deploying to production traffic          │
│                                                                             │
│  HOW IT WORKS:                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Request: POST /predict                                           │  │
│  │  ────────────────────────────────────────────────────────────────│  │
│  │                                                                     │  │
│  │  ┌────────────────────────────────────────────────────────────┐  │  │
│  │  │  1. Model v1 runs (ALWAYS)                              │  │  │
│  │  │     - Returns result to client                           │  │  │
│  │  │     - client sees Model v1 output                       │  │  │
│  │  └────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                    │  │
│  │                              ▼                                    │  │
│  │  ┌────────────────────────────────────────────────────────────┐  │  │
│  │  │  2. Model v2 runs (SHADOW)                             │  │  │
│  │  │     - Does NOT return to client                        │  │  │
│  │  │     - Prediction saved to model_v2_prob column         │  │  │
│  │  │     - Only used for offline evaluation                 │  │  │
│  │  └────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                    │  │
│  │                              ▼                                    │  │
│  │  ┌────────────────────────────────────────────────────────────┐  │  │
│  │  │  3. LOG TO DATABASE                                     │  │  │
│  │  │     ┌─────────────────────────────────────────────┐   │  │  │
│  │  │     │  model_v1_prob: 0.35 (used for response)   │   │  │  │
│  │  │     │  model_v2_prob: 0.87 (shadow, logged)      │   │  │  │
│  │  │     │  final_prediction: v1 (used)                │   │  │  │
│  │  │     └─────────────────────────────────────────────┘   │  │  │
│  │  └────────────────────────────────────────────────────────────┘  │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  OFFLINE EVALUATION (after 1 week):                                      │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  Compare predictions vs actual (is_spike):                        │  │
│  │                                                                     │  │
│  │  ┌─────────────────┬─────────────────┐                         │  │
│  │  │    Model v1     │    Model v2     │                         │  │
│  │  ├─────────────────┼─────────────────┤                         │  │
│  │  │  Accuracy: 72%  │  Accuracy: 89%  │ ← Model v2 BETTER!  │  │
│  │  │  Recall: 68%    │  Recall: 85%    │                         │  │
│  │  │  Precision: 78% │  Precision: 92% │                         │  │
│  │  └─────────────────┴─────────────────┘                         │  │
│  │                                                                     │  │
│  │  Result: Model v2 accuracy > Model v1                           │  │
│  │  → PROCEED to A/B Testing (10% traffic)                         │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.1 Shadow Mode API Implementation

```python
# api/predict.py
def predict(hex_id: str, timestamp: str, shadow_mode: bool = True):
    """
    Prediction endpoint with shadow mode support.
    
    Args:
        hex_id: H3 hexagon ID
        timestamp: Request timestamp
        shadow_mode: If True, Model v2 also runs in background
    """
    
    # Always fetch all data
    data = fetch_all_sources(hex_id, timestamp)
    
    # === Model v1 (ALWAYS runs) ===
    features_v1 = extract_features_v1(data)  # VCW + OWM
    model_v1_prob = model_v1.predict(features_v1)
    model_v1_result = apply_decision_matrix(model_v1_prob, data)
    
    # === Model v2 (SHADOW mode) ===
    model_v2_prob = None
    if shadow_mode and model_v2_available:
        features_v2 = extract_features_v2(data)  # ALL 4 sources
        model_v2_prob = model_v2.predict(features_v2)
    
    # === Log to database (async) ===
    log_prediction(
        hex_id=hex_id,
        timestamp=timestamp,
        model_v1_prob=model_v1_prob,
        model_v2_prob=model_v2_prob,  # NULL if shadow mode off
        final_prob=model_v1_prob,
        final_result=model_v1_result
    )
    
    # === Return to client (Model v1 result) ===
    return model_v1_result
```

### 6.2 Shadow Mode Timeline

```
Week 3          Week 3.5         Week 4
─────────────────────────────────────────────────────────────

┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  SHADOW      │  │  OFFLINE        │  │  A/B TESTING    │
│  MODE        │  │  EVALUATION     │  │  (10% traffic)  │
│  ─────────   │  │  ────────────  │  │  ────────────   │
│              │  │                  │  │                  │
│ Model v2 runs│  │ Calculate:       │  │ 10% → v2       │
│ in background│  │ - v1 vs actual  │  │ 90% → v1       │
│              │  │ - v2 vs actual  │  │                  │
│ Model v1     │  │                  │  │ Monitor for     │
│ returns to   │  │ v2 accuracy > v1 │  │ 1 week          │
│ client       │  │ → Proceed        │  │                  │
│              │  │ → or Rollback    │  │ Week 5: 50%     │
│ Log:         │  │                  │  │ Week 6: 100%    │
│ - v1_prob   │  │                  │  │                  │
│ - v2_prob   │  │                  │  │                  │
└──────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 7. Data Flow: Async Logging

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ASYNC DATA COLLECTION FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │                      API RESPONSE                                   │    │
│  │  ───────────────────────────────────────────────────────────────│    │
│  │                                                                   │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │  Return to Client (FAST - < 100ms)                    │   │    │
│  │  │  { spike: true, severity: "HIGH" }                     │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                              │                                │    │
│  │                              │ (non-blocking)                │    │
│  │                              ▼                                │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │  Publish to Message Queue                              │   │    │
│  │  │  Topic: weather-events                                │   │    │
│  │  │  Message: { hex_id, timestamp, vcw, owm, hsd, nchmf } │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                              │                                │    │
│  └──────────────────────────────┼────────────────────────────────┘    │
│                                 │                                       │
│                                 ▼                                       │
│  ┌──────────────────────────────┼────────────────────────────────┐     │
│  │                    MESSAGE QUEUE                                  │     │
│  │  ┌─────────────────────────────────────────────────────────┐   │     │
│  │  │  Kafka / RabbitMQ / AWS SQS                           │   │     │
│  │  │  - At-least-once delivery                             │   │     │
│  │  │  - Retry mechanism                                     │   │     │
│  │  │  - Dead letter queue                                   │   │     │
│  │  └─────────────────────────────────────────────────────────┘   │     │
│  │                              │                                │     │
│  └──────────────────────────────┼────────────────────────────────┘     │
│                                 │                                       │
│                                 ▼                                       │
│  ┌──────────────────────────────┼────────────────────────────────┐     │
│  │                  CONSUMER WORKER                               │     │
│  │  ┌─────────────────────────────────────────────────────────┐   │     │
│  │  │  Background Process                                    │   │     │
│  │  │  - Consume messages from queue                        │   │     │
│  │  │  - Batch writes (every 5 min)                         │   │     │
│  │  │  - Transform to analytical format                     │   │     │
│  │  └─────────────────────────────────────────────────────────┘   │     │
│  │                              │                                │     │
│  └──────────────────────────────┼────────────────────────────────┘     │
│                                 │                                       │
│                                 ▼                                       │
│  ┌──────────────────────────────┼────────────────────────────────┐     │
│  │                    DATA LAKE                                     │     │
│  │  ┌─────────────────────────────────────────────────────────┐   │     │
│  │  │  TimescaleDB / PostgreSQL / S3 Parquet                 │   │     │
│  │  │  ─────────────────────────────────────────────────     │   │     │
│  │  │  Table: weather_predictions                           │   │     │
│  │  │  Columns:                                             │   │     │
│  │  │    - hex_id                                          │   │     │
│  │  │    - timestamp                                       │   │     │
│  │  │    - vcw_data (JSONB)                               │   │     │
│  │  │    - owm_data (JSONB)                               │   │     │
│  │  │    - hsd_data (JSONB)                               │   │     │
│  │  │    - nchmf_data (JSONB)                            │   │     │
│  │  │    - model_prediction                                │   │     │
│  │  │    - actual_spike (labeled later)                    │   │     │
│  │  │    - created_at                                      │   │     │
│  │  └─────────────────────────────────────────────────────────┘   │     │
│  │                              │                                │     │
│  └──────────────────────────────┼────────────────────────────────┘     │
│                                 │                                       │
│                                 ▼                                       │
│  ┌──────────────────────────────┼────────────────────────────────┐     │
│  │                    MODEL RETRAIN                                 │     │
│  │  ┌─────────────────────────────────────────────────────────┐   │     │
│  │  │  Weekly Job: Pull from Data Lake → Train Model v3      │   │     │
│  │  └─────────────────────────────────────────────────────────┘   │     │
│  └───────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Database Schema

```sql
-- Data Lake: weather_predictions
CREATE TABLE weather_predictions (
    id BIGSERIAL PRIMARY KEY,
    hex_id VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    
    -- Raw data (JSONB for flexibility)
    vcw_data JSONB,
    owm_data JSONB,
    hsd_data JSONB,
    nchmf_data JSONB,
    
    -- Processed features
    blended_weather_v1 FLOAT,  -- VCW + OWM only
    blended_weather_v2 FLOAT,  -- ALL 4 sources
    
    -- Predictions
    model_v1_prob FLOAT,
    model_v2_prob FLOAT,
    final_prediction BOOLEAN,
    
    -- Override tracking (Phase 1)
    override_triggered BOOLEAN DEFAULT FALSE,
    override_cause VARCHAR(50),
    
    -- Labels (automated labeling)
    is_spike BOOLEAN,
    primary_cause VARCHAR(50),
    actual_demand INTEGER,
    baseline_demand FLOAT,
    spike_ratio FLOAT,
    labeled_at TIMESTAMPTZ,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    UNIQUE (hex_id, timestamp)
);

-- Partitioning by time for performance
CREATE INDEX idx_predictions_hex_time ON weather_predictions (hex_id, timestamp DESC);
CREATE INDEX idx_predictions_created ON weather_predictions (created_at DESC);
CREATE INDEX idx_predictions_unlabeled ON weather_predictions (created_at DESC) WHERE is_spike IS NULL;
```

---

## 9. API Endpoints

### 9.1 Prediction API

```yaml
POST /api/v1/predict
---
Request:
{
  "hex_id": "88415cb4e5fffff",
  "timestamp": "2026-09-25T14:00:00Z"
}

Response (Phase 1 - MVP):
{
  "alert_id": "SPK-20260925-1400-001",
  "hex_id": "88415cb4e5fffff",
  "timestamp": "2026-09-25T14:00:00Z",
  "spike": true,
  "severity": "HIGH",
  "model_prob": 0.35,
  "model_version": "v1",
  "override_triggered": true,
  "override_cause": "flood",
  "data_sources": {
    "vcw": { "temp": 32.5, "rain": 0.5 },
    "owm": { "temp": 31.8, "rain": 0.3 },
    "hsdc": { "flood_level": 3, "rainfall": 45.2 },
    "nchmf": { "warning": false }
  },
  "inference_time_ms": 45
}

Response (Phase 2 - Production):
{
  "alert_id": "SPK-20260925-1400-001",
  "hex_id": "88415cb4e5fffff",
  "timestamp": "2026-09-25T14:00:00Z",
  "spike": true,
  "severity": "HIGH",
  "model_prob": 0.87,
  "model_version": "v2",
  "override_triggered": false,
  "data_sources": { ... },
  "inference_time_ms": 52
}

Response (Shadow Mode - Week 3):
{
  "alert_id": "SPK-20260925-1400-001",
  "hex_id": "88415cb4e5fffff",
  "spike": true,
  "severity": "HIGH",
  "model_prob": 0.35,           # v1 result (returned to client)
  "model_version": "v1",
  "shadow_prob": 0.87,           # v2 result (shadow, logged only)
  "shadow_version": "v2",
  "inference_time_ms": 68         # slightly slower due to v2
}
```

### 9.2 Admin APIs

```yaml
# Get current model version
GET /api/v1/model/version
Response: { 
  "model_version": "v1", 
  "active_since": "2026-09-01", 
  "features": ["vcw", "owm"],
  "shadow_mode": true,
  "shadow_version": "v2"
}

# Get model accuracy comparison
GET /api/v1/model/accuracy
Response: {
  "model_v1": { "accuracy": 0.72, "recall": 0.68, "precision": 0.78 },
  "model_v2": { "accuracy": 0.89, "recall": 0.85, "precision": 0.92 },
  "winner": "v2",
  "recommendation": "Deploy v2 to 10% traffic"
}

# Trigger retrain
POST /api/v1/model/retrain
Response: { "job_id": "retrain-20260925-001", "status": "queued" }

# Get retrain status
GET /api/v1/model/retrain/{job_id}
Response: { "job_id": "retrain-20260925-001", "status": "running", "progress": "45%" }

# Control shadow mode
POST /api/v1/model/shadow
Body: { "enabled": true, "version": "v2" }
Response: { "shadow_mode": "enabled", "version": "v2" }
```

---

## 10. Timeline Summary (Updated)

```
Week 1                    Week 2                    Week 3                    Week 3.5                  Week 4
─────────────────────────────────────────────────────────────────────────────────────────────────────────
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  MVP LAUNCH    │    │  DATA LAKE      │    │  SHADOW MODE   │    │  OFFLINE       │    │  A/B TESTING   │
│  + Collection  │    │  Collection     │    │  Model v2      │    │  EVALUATION    │    │  10% traffic   │
│                 │    │                 │    │  in background │    │                │    │                 │
│  All 4 sources │    │  All 4 sources │    │  All 4 sources │    │  Compare v1    │    │  Week 5: 50%   │
│  → Storage     │    │  → Storage     │    │  → Storage     │    │  vs v2         │    │  Week 6: 100%  │
│                 │    │                 │    │                 │    │                │    │                 │
│  ┌───────────┐ │    │  ┌───────────┐ │    │  ┌───────────┐ │    │  ┌───────────┐ │    │  ┌───────────┐ │
│  │ Model v1  │ │    │  │ Model v1  │ │    │  │ Model v1  │ │    │  │ v1: 72%  │ │    │  │ Model v2  │ │
│  │ Inference │ │    │  │ Inference │ │    │  │ Inference │ │    │  │ v2: 89%  │ │    │  │ Inference │ │
│  │ + Override│ │    │  │ + Override│ │    │  │ + Override│ │    │  │           │ │    │  │ No Override│ │
│  └───────────┘ │    │  └───────────┘ │    │  └───────────┘ │    │  └───────────┘ │    │  └───────────┘ │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
                                                                                                    │
                                                                                                    ▼
                                                                                    ┌─────────────────────────────────────┐
                                                                                    │         DEPLOY MODEL v2            │
                                                                                    │    Full Ensemble (4 sources)        │
                                                                                    │    Automated Labeling Loop Active   │
                                                                                    └─────────────────────────────────────┘
```

### 10.1 Labeling Loop Timeline

```
Daily at 01:00 AM:
┌─────────────────────────────────────────────────────────────┐
│  CRONJOB: Automated Labeling                              │
│  ─────────────────────────────────────────────────────── │
│                                                             │
│  1. Query unlabeled predictions from last 24h           │
│  2. Fetch actual demand data                             │
│  3. Calculate baseline & spike ratio                   │
│  4. UPDATE weather_predictions.is_spike                  │
│                                                             │
│  Result: Training data ready for Model v3 retrain     │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 Retrain Schedule

| Event | Timing | Trigger |
|-------|--------|---------|
| Model v1 → v2 | Week 4 | ≥4 weeks data + Shadow Mode validation |
| Model v2 → v3 | Weekly | Cronjob + New labeled data |
| Emergency retrain | On-demand | API trigger / accuracy drift >5% |

---

## 11. Key Differences: Phase 1 vs Phase 2

| Aspect | Phase 1 (MVP) | Phase 2 (Production) |
|--------|----------------|----------------------|
| **Model** | Model v1 | Model v2 |
| **Training Data** | Historical VCW + OWM | All 4 sources |
| **Features** | blended_v1 (2 sources) | blended_v2 (4 sources) |
| **Inference** | Model + Rule Override | Model only |
| **HSDC/NCHMF** | Rule Override | Model Features |
| **Shadow Mode** | Model v2 running | Evaluated |
| **Labeling** | Manual | Automated (nightly cronjob) |
| **Override** | Required | Not needed |
| **Accuracy** | Baseline (~72%) | Expected (~89%) |

---

## 12. Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Model v1 miss spikes | Medium | High | Rule Override catches them |
| Model v2 worse than v1 | Low | High | Shadow Mode validates offline first |
| Data quality issues | Low | Medium | Validation before training |
| Retrain delay | Medium | Low | Manual trigger available |
| Labeling errors | Low | Medium | Threshold tuning + human review |
| Shadow mode delay | Low | Low | Async, doesn't block response |

---

## 13. Next Steps (Updated)

### Phase 1: MVP Implementation
1. **Backfill VCW/OWM historical data**
   - Date range: 2026-04-20 to 2026-09-22
   - API: Visual Crossing historical endpoint

2. **Train Model v1 (VCW + OWM)**
   - Features: blended_v1, time features, lags, rolling
   - Validate on held-out data

3. **Build inference API with rule override**
   - Decision matrix implementation
   - Response time target: <100ms

4. **Set up async logging to Data Lake**
   - Message queue (Kafka/RabbitMQ/SQS)
   - Schema: weather_predictions table

5. **Deploy MVP to production**
   - Monitor alert quality
   - Start Shadow Mode after Week 3

### Phase 2: Shadow Mode & Validation
6. **Enable Shadow Mode**
   - Model v2 runs in background
   - Log model_v2_prob to database

7. **Automated Labeling Cronjob**
   - Nightly at 01:00 AM
   - Calculate baseline & spike ratio
   - UPDATE is_spike column

8. **Offline Evaluation**
   - Week 3.5: Compare v1 vs v2 accuracy
   - If v2 > v1: Proceed to A/B
   - If v2 < v1: Debug & retrain

### Phase 3: A/B Testing & Deploy
9. **A/B Testing**
   - Week 4: 10% traffic → v2
   - Week 5: 50% traffic → v2
   - Week 6: 100% traffic → v2

10. **Continuous Improvement**
    - Weekly retrain (Model v3, v4, ...)
    - Monitor accuracy drift
    - Add new data sources as needed

---

## 14. Summary

### Architecture Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OPTION C: COMPLETE FLOW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                   │
│  │  Data       │    │  Inference  │    │  Feedback   │                   │
│  │  Collection │    │  Pipeline   │    │  Loop       │                   │
│  │             │    │             │    │             │                   │
│  │  VCW       │───▶│  Model v1   │───▶│  Labeling   │                   │
│  │  OWM       │    │  + Override │    │  Cronjob    │                   │
│  │  HSDC      │    │             │    │             │                   │
│  │  NCHMF     │    │  Model v2   │    │  Data Lake │                   │
│  │             │    │  (Shadow)   │    │             │                   │
│  └─────────────┘    └──────┬──────┘    └──────┬──────┘                   │
│                            │                   │                            │
│                            │                   ▼                            │
│                            │            ┌─────────────┐                     │
│                            │            │  Retrain    │                     │
│                            │            │  (Weekly)  │                     │
│                            │            └──────┬──────┘                     │
│                            │                   │                            │
│                            │                   ▼                            │
│                            │            ┌─────────────┐                     │
│                            │            │  Model v3   │                     │
│                            │            │  v4, v5... │                     │
│                            │            └─────────────┘                     │
│                            │                   │                            │
│                            ▼                   │                            │
│                     ┌─────────────┐            │                            │
│                     │   Alerts   │◀───────────┘                            │
│                     │  to Ops    │                                          │
│                     └─────────────┘                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Metrics

| Metric | Phase 1 (MVP) | Phase 2 (Production) |
|--------|----------------|----------------------|
| Model Version | v1 | v2+ |
| Data Sources | 2 (VCW, OWM) | 4 (ALL) |
| Override | Yes | No |
| Labeling | Manual | Automated |
| Accuracy Target | ~70-75% | ~85-90% |
| Data Latency | Real-time | Real-time |
| Retrain Frequency | N/A | Weekly |

### Files to Implement

| Component | File | Priority |
|-----------|------|----------|
| Weather Backfill | `scripts/backfill_weather.py` | P0 |
| Model v1 Training | `scripts/train_model_v1.py` | P0 |
| Inference API | `src/api/predict.py` | P0 |
| Rule Override | `src/ensemble/decision_matrix.py` | P0 |
| Async Logging | `src/workers/async_logger.py` | P1 |
| Shadow Mode | `src/ensemble/shadow_mode.py` | P1 |
| Labeling Cronjob | `scripts/labeling_job.py` | P1 |
| Model v2 Training | `scripts/train_model_v2.py` | P1 |
| A/B Testing | `src/api/ab_router.py` | P2 |

