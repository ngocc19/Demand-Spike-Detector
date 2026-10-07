# Scripts Documentation

Thư mục chứa các script để thu thập dữ liệu, xử lý batch, và real-time crawling.

## Scripts Overview

```
scripts/
├── backfill_weather.py           # Backfill historical weather data
├── backfill_with_8keys.py      # Bulk backfill với 8 API keys
├── processor.py                # Process raw data → features
├── demo_pipeline.py             # Demo pipeline execution
├── demo_preprocessor.py        # Demo preprocessor
├── merge_holidays.py           # Merge holiday data
├── checkpoint.py               # Checkpoint utilities
├── extractor.py                # Data extraction
├── h3_mapper.py               # H3 mapping utilities
│
├── realtime_crawler.py         # Real-time crawler (15 min)
├── run_crawler.ps1            # Windows wrapper
├── run_crawler.sh             # Linux wrapper
├── install_crawler_task.ps1    # Windows Task Scheduler setup
├── uninstall_crawler_task.ps1  # Uninstall Windows task
└── check_crawler_status.ps1   # Status checker
│
├── fetch_osm_retry.py          # Fetch OSM from Overpass API
├── process_osm_h3api.py        # Process OSM → Parquet (H3 API)
└── osm_batch_pipeline.py       # OSM batch pipeline (main entry)
```

---

## Weather Backfill Scripts

### backfill_weather.py

Fetch historical weather data từ VCW, OWM, HSDC.

```bash
python scripts/backfill_weather.py
```

### backfill_with_8keys.py

Bulk backfill với multiple API keys (8 keys).

```bash
python scripts/backfill_with_8keys.py
```

---

## OSM Batch Pipeline

### Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  OSM BATCH PIPELINE                                                       │
│                                                                             │
│  ONE-TIME API CALL → PARQUET STORAGE → OFFLINE MULTI-USE                 │
│                                                                             │
│  Step 1: python scripts/fetch_osm_retry.py (Fetch OSM data)              │
│  Step 2: python scripts/process_osm_h3api.py (Process → Parquet)         │
│  Step 3: python scripts/osm_batch_pipeline.py --verify (Verify)          │
│                                                                             │
│  OR: python scripts/osm_batch_pipeline.py --full (Run all at once)        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Commands

```bash
# Check status
python scripts/osm_batch_pipeline.py --status

# Full pipeline: Fetch → Process → Verify
python scripts/osm_batch_pipeline.py --full

# Individual steps
python scripts/osm_batch_pipeline.py --fetch    # Fetch từ Overpass API
python scripts/osm_batch_pipeline.py --process  # Process → Parquet
python scripts/osm_batch_pipeline.py --verify   # Verify coverage
python scripts/osm_batch_pipeline.py --load     # Load OSM data
python scripts/osm_batch_pipeline.py --demo      # Demo merge to weather
```

### Usage in Training Code

```python
from scripts.osm_batch_pipeline import merge_osm_to_weather

# Load weather data
weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')

# Add OSM capacity features
weather_df = merge_osm_to_weather(weather_df)

# Ready for training!
```

### Output Files

| File | Size | Description |
|------|------|-------------|
| `data/h3_osm_capacity.parquet` | ~168KB | **Main file for training** |
| `data/h3_osm_capacity.csv` | ~400KB | Human readable |
| `data/h3_osm_capacity_meta.json` | 268B | Metadata |

### Statistics

| Metric | Value |
|--------|-------|
| Total hexes | 3,997 |
| Hexes with roads | 1,806 |
| Weather anchors | 6 (HoanKiem, CauGiay, HoangMai, LongBien, TayHo, NoiBai) |
| Weather hexes covered | 6/6 (100%) |
| Coverage | ✅ Full |

---

## Real-time Crawler

### Windows Setup

```powershell
# Install Task Scheduler
cd D:\Demand-Spike-Detector\scripts
.\install_crawler_task.ps1

# Check status
.\check_crawler_status.ps1

# Uninstall
.\uninstall_crawler_task.ps1
```

### Linux Setup

```bash
# Install cron
./scripts/install_cron.sh

# Uninstall
./scripts/uninstall_cron.sh
```

### Manual Run

```bash
python scripts/realtime_crawler.py
```

### Cron Schedule

```
*/15 * * * *  # Every 15 minutes
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BATCH PIPELINE                                                            │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │
│  │  Backfill   │───▶│   Process    │───▶│   Merge      │            │
│  │  Weather    │    │   (H3)      │    │   OSM        │            │
│  └──────────────┘    └──────────────┘    └──────────────┘            │
│                                              │                           │
│                                              ▼                           │
│                             ┌──────────────────────────────┐              │
│                             │  weather_anchors_30T_merged │              │
│                             │  + h3_osm_capacity.parquet  │              │
│                             └──────────────────────────────┘              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  REAL-TIME PIPELINE                                                        │
│                                                                             │
│  Every 15 min:                                                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                   │
│  │   OWM   │  │   VCW   │  │  HSDC   │  │  NCHMF  │                   │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘                   │
│       └─────────────┴─────────────┴─────────────┘                       │
│                              │                                           │
│                              ▼                                           │
│                   ┌──────────────────┐                                 │
│                   │  Ensemble        │                                 │
│                   │  Aggregator      │                                 │
│                   └────────┬─────────┘                                 │
│                            │                                            │
│                            ▼                                            │
│                   ┌──────────────────┐                                 │
│                   │  realtime_lake/  │                                 │
│                   │  weather_*.parquet│                                 │
│                   └──────────────────┘                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### OSM Pipeline

**"Static OSM data not found"**
```bash
python scripts/osm_batch_pipeline.py --full
```

**"Permission denied" on Windows**
```powershell
# Run as Administrator
```

### Real-time Crawler

**"Task not found"**
```powershell
.\install_crawler_task.ps1
```

**"API timeout"**
- Check internet connection
- Verify API keys are valid
- Check API rate limits

---

## Output Locations

| Data Type | Location |
|-----------|----------|
| Weather backfill | `data/weather_anchors_30T_merged.parquet` |
| OSM capacity | `data/h3_osm_capacity.parquet` |
| Real-time data | `data/realtime_lake/weather_YYYY-MM-DD.parquet` |
| Logs (Windows) | `data/crawler_cron.log` |
| Logs (Linux) | `/opt/demand-spike-detector/data/crawler_cron.log` |
