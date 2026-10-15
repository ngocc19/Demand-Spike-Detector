# Plan: Event Realtime Crawler System

## Context

Cần thiết kế lại hệ thống crawl events realtime với các yêu cầu:
1. Crawl events từ ngày **29/09/2026** (sau backfill 29/06-28/09)
2. Mỗi **2 giờ** crawl 1 lần tự động
3. Kết quả update vào **event_realtime.xlsx**
4. Normalize data giống event_fixed.xlsx (12 cột)
5. Ghi lại trace khi có thay đổi: thời gian crawl, nguồn bài viết

---

## Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     EVENT REALTIME CRAWLER SYSTEM                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                │
│  │   SOURCES   │    │   CRAWLER   │    │  PROCESSOR  │                │
│  │  van_mieu   │───▶│  (2h poll) │───▶│  (changes)  │                │
│  │  ticketbox  │    │             │    │             │                │
│  │  football   │    └─────────────┘    └──────┬──────┘                │
│  │  lehoivn   │                             │                        │
│  └─────────────┘                             ▼                        │
│                                         ┌─────────────┐                │
│  ┌─────────────┐    ┌─────────────┐   │   STORAGE   │                │
│  │   EXPORT    │◀───│   STATE     │◀──│  (Parquet)  │                │
│  │  .xlsx/.csv │    │  (JSON/DB)  │   │             │                │
│  └──────┬──────┘    └──────┬──────┘   └─────────────┘                │
│         │                   │                                          │
│         ▼                   ▼                                          │
│  ┌─────────────┐    ┌─────────────┐                                  │
│  │ event_realtime│    │ event_trace │                                  │
│  │   .xlsx     │    │   .csv      │                                  │
│  └─────────────┘    └─────────────┘                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/pipeline/
├── event_realtime/
│   ├── __init__.py
│   ├── cli.py                    # CLI entry point
│   ├── crawler.py                # Main crawler (2h poll)
│   ├── processor.py              # Change detection
│   ├── models.py                # Data models
│   ├── storage.py               # Storage layer (Parquet)
│   ├── exporter.py              # Export to .xlsx/.csv
│   └── trace.py                 # Trace logging

scripts/
└── event_realtime_cron.py        # Cron wrapper (2h)

config/
└── factors.yaml                  # Cập nhật config cho realtime
```

### Data Flow

```
1. SCHEDULER (cron: 0 */2 * * *)
       │
       ▼
2. CRAWLER.fetch_all_sources()
   - van_mieu: API call
   - ticketbox: API call
   - football: Web scrape
   - lehoivietnam: Web scrape
       │
       ▼
3. PROCESSOR.detect_changes()
   - NEW: Event mới chưa từng thấy
   - UPDATED: Event đã known bị thay đổi
   - CANCELLED: Event không còn trong source
   - CONFIRMED: Event được xác nhận bởi source khác
       │
       ▼
4. TRACE.log()
   - Lưu: trace_id, crawl_time, source, event_id, change_type, old_state, new_state
       │
       ▼
5. STORAGE.save()
   - Lưu events vào Parquet partitioned by date
   - Lưu state vào JSON
       │
       ▼
6. EXPORTER.to_xlsx()
   - Export 12 cột: event_name, venue, start_date, start_time, end_time,
     type, estimate_attendence, source_url, attendance_source_url,
     latitude, longitude, h3_index
```

---

## Implementation Steps

### Step 1: Update Data Models

**File:** `src/pipeline/event_realtime/models.py`

```python
@dataclass
class RealtimeEvent:
    """Event từ crawl realtime."""
    event_id: str
    source: str
    source_url: str
    
    # Event info
    title: str
    venue: str
    start_at: datetime
    end_at: Optional[datetime]
    category: str
    
    # Attendance (nullable)
    estimated_attendees: Optional[int]
    attendance_source_url: Optional[str]
    
    # Location
    latitude: Optional[float]
    longitude: Optional[float]
    h3_index: Optional[str]
    
    # Metadata
    fetched_at: datetime
    source_event_id: str


@dataclass
class EventTrace:
    """Trace cho một thay đổi."""
    trace_id: str
    crawl_time: datetime
    source: str
    
    # Event identity
    event_id: str
    title: str
    
    # Change info
    change_type: EventChangeType
    old_state: Optional[Dict]
    new_state: Optional[Dict]
    changes_detail: Dict[str, Tuple[Any, Any]]  # field: (old, new)
    
    # Source URLs
    source_url: str
    source_urls_history: List[str]  # Các URL đã thay đổi
    
    # Impact
    impact: float
    should_notify: bool
```

### Step 2: Create Storage Layer

**File:** `src/pipeline/event_realtime/storage.py`

```python
class EventRealtimeStore:
    """Storage layer cho event realtime - theo kiểu weather_realtime."""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.events_dir = self.data_dir / "event_realtime" / "events"
        self.state_file = self.data_dir / "event_realtime" / "state.json"
        self.trace_file = self.data_dir / "event_realtime" / "traces.csv"
    
    def save_events(self, events: List[RealtimeEvent]):
        """Lưu events vào Parquet partitioned by date."""
        # Partition: date=2026-09-29/part-00000.parquet
        ...
    
    def load_known_events(self) -> Dict[str, EventState]:
        """Load known events từ state file."""
        ...
    
    def save_state(self, events: Dict[str, EventState]):
        """Save state JSON."""
        ...
    
    def log_trace(self, trace: EventTrace):
        """Append trace vào CSV file."""
        # Cấu trúc CSV:
        # trace_id,crawl_time,source,event_id,title,change_type,
        # old_start_at,new_start_at,old_venue,new_venue,
        # source_url,impact,should_notify
```

### Step 3: Create Crawler

**File:** `src/pipeline/event_realtime/crawler.py`

```python
class EventRealtimeCrawler:
    """
    Crawler chính - inspired by realtime_crawler.py (weather).
    
    Features:
    - Poll 2h một lần
    - Sử dụng lại source plugins từ backfill
    - Mutex lock để tránh chạy song song
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.sources = self._build_sources()
        self.store = EventRealtimeStore(config['data_dir'])
        self.processor = EventRealtimeProcessor()
    
    def run(self):
        """Main crawl cycle."""
        # 1. Acquire lock
        # 2. Load known events
        # 3. Fetch all sources
        # 4. Detect changes
        # 5. Log traces
        # 6. Save to storage
        # 7. Export to .xlsx
        # 8. Release lock
    
    def fetch_all_sources(self) -> Dict[str, List[RealtimeEvent]]:
        """Fetch tất cả sources."""
        ...
```

### Step 4: Create Processor (Change Detection)

**File:** `src/pipeline/event_realtime/processor.py`

```python
class EventRealtimeProcessor:
    """
    Processor cho change detection - cải tiến từ phiên bản cũ.
    
    Changes:
    - Thêm trace_id generation
    - Lưu history của source_url changes
    - Better diff detection
    """
    
    def detect_changes(
        self,
        known_events: Dict[str, EventState],
        new_events: List[RealtimeEvent],
        source: str,
        crawl_time: datetime
    ) -> Tuple[List[EventTrace], Dict[str, EventState]]:
        """
        Detect changes và generate traces.
        
        Returns:
        - List of traces
        - Updated state dict
        """
        traces = []
        new_state = dict(known_events)
        
        for event in new_events:
            # Check if event exists
            existing = new_state.get(event.event_id)
            
            if existing is None:
                # NEW EVENT
                trace = self._create_trace_new(event, crawl_time)
                traces.append(trace)
                new_state[event.event_id] = EventState.from_event(event)
            
            elif existing.source != source:
                # CONFIRMED BY ANOTHER SOURCE
                trace = self._create_trace_confirmed(existing, event, crawl_time)
                traces.append(trace)
                # Update source_urls_history
                existing.source_urls_history.append(event.source_url)
            
            else:
                # CHECK FOR UPDATES
                diff = self._diff(existing, event)
                if diff:
                    # UPDATED
                    trace = self._create_trace_updated(existing, event, diff, crawl_time)
                    traces.append(trace)
                    existing.update_from(event)
                    existing.source_urls_history.append(event.source_url)
        
        # CHECK FOR CANCELLATIONS
        current_ids = {e.event_id for e in new_events}
        for event_id, state in new_state.items():
            if event_id not in current_ids and state.source == source:
                # Check if event is upcoming (not past)
                if state.start_at > datetime.now() - timedelta(hours=2):
                    trace = self._create_trace_cancelled(state, crawl_time)
                    traces.append(trace)
        
        return traces, new_state
```

### Step 5: Create Exporter

**File:** `src/pipeline/event_realtime/exporter.py`

```python
class EventRealtimeExporter:
    """
    Exporter cho event realtime - giống cấu trúc event_csv.py.
    
    Output columns (12):
    - event_name
    - venue
    - start_date (DD/MM/YY)
    - start_time (HH:MM)
    - end_time (HH:MM)
    - type (category)
    - estimate_attendence (nullable)
    - source_url
    - attendance_source_url (nullable)
    - latitude (nullable)
    - longitude (nullable)
    - h3_index (nullable)
    """
    
    def __init__(self, data_dir: str, timezone: str = "Asia/Ho_Chi_Minh"):
        self.data_dir = Path(data_dir)
        self.timezone = ZoneInfo(timezone)
        self.output_xlsx = self.data_dir / "event_realtime.xlsx"
        self.output_csv = self.data_dir / "event_realtime.csv"
    
    def export(self, events: List[RealtimeEvent]):
        """
        Export events ra .xlsx và .csv.
        
        Events chưa diễn ra: estimate_attendence = empty
        """
        rows = self._to_rows(events)
        self._write_xlsx(rows)
        self._write_csv(rows)
```

### Step 6: Create CLI

**File:** `src/pipeline/event_realtime/cli.py`

```python
def main():
    parser = argparse.ArgumentParser(description="Event Realtime Crawler")
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true", help="Chạy 1 lần (không loop)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    
    config = load_config(args.config)
    crawler = EventRealtimeCrawler(config)
    
    if args.once:
        crawler.run()
    else:
        # Loop mỗi 2 giờ
        while True:
            crawler.run()
            time.sleep(2 * 60 * 60)  # 2 hours
```

### Step 7: Create Cron Script

**File:** `scripts/event_realtime_cron.py`

```python
"""
Cron wrapper cho event realtime.
Chạy mỗi 2 giờ qua Task Scheduler (Windows) hoặc Cron (Linux).
"""
import subprocess
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "factors.yaml"
    
    cmd = [
        sys.executable, "-m", "pipeline.event_realtime.cli",
        "--config", str(config_path),
        "--once"  # Chạy 1 lần, cron sẽ gọi lại sau 2h
    ]
    
    result = subprocess.run(cmd, cwd=str(project_root))
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
```

### Step 8: Update Config

**File:** `config/factors.yaml`

```yaml
event_realtime:
  enabled: true
  schedule: "0 */2 * * *"  # Mỗi 2 giờ
  start_date: "2026-09-29"  # Bắt đầu sau backfill
  horizon_days: 90
  notify_threshold: 0.5
  export:
    xlsx: "data/event_realtime.xlsx"
    csv: "data/event_realtime.csv"
    trace: "data/event_realtime_traces.csv"
  storage:
    format: "parquet"
    partition_by: "date"
```

---

## Trace Format

**File:** `data/event_realtime_traces.csv` (CSV - simple, easy to read)

### Append Strategy
- Mỗi lần crawl có changes → append vào file CSV
- Format: `date=YYYY-MM-DD/event_realtime_traces.csv` (partitioned by date)
- Hoặc đơn giản: 1 file `data/event_realtime_traces.csv` (append mode)

| Column | Type | Description |
|--------|------|-------------|
| trace_id | UUID | Unique trace ID |
| crawl_time | ISO8601 | Thời gian crawl |
| source | String | Nguồn (van_mieu, ticketbox, etc.) |
| event_id | String | Event ID |
| title | String | Tên sự kiện |
| change_type | Enum | NEW/UPDATED/CANCELLED/CONFIRMED |
| old_start_at | ISO8601 | Giờ bắt đầu cũ (nullable) |
| new_start_at | ISO8601 | Giờ bắt đầu mới (nullable) |
| old_venue | String | Địa điểm cũ (nullable) |
| new_venue | String | Địa điểm mới (nullable) |
| source_url | URL | URL bài viết gốc |
| source_urls_history | JSON | Lịch sử các URL đã thay đổi |
| impact | Float | Impact score |
| should_notify | Bool | Có cần notify không |

---

## Verification

### Test Commands

```bash
# Chạy 1 lần (manual test)
python -m pipeline.event_realtime.cli --config config/factors.yaml --once -v

# Chạy loop (production)
python -m pipeline.event_realtime.cli --config config/factors.yaml -v

# Kiểm tra output
python -c "
import pandas as pd
df = pd.read_excel('data/event_realtime.xlsx')
print(df.columns.tolist())
print(df.head())
"

# Kiểm tra traces
python -c "
import pandas as pd
df = pd.read_csv('data/event_realtime_traces.csv')
print(df[df['change_type'] != 'CONFIRMED'])
"
```

### Expected Output

1. **event_realtime.xlsx**: 12 cột như event_fixed.xlsx
2. **event_realtime_traces.csv**: Lịch sử thay đổi
3. **event_realtime/events/**: Parquet partitioned by date
4. **event_realtime/state.json**: Known events state

---

## Key Differences từ Version Cũ

| Aspect | Old | New |
|--------|-----|-----|
| **Trigger** | Plugin-based | Cron + CLI |
| **Storage** | JSON/CSV (append) | Parquet (partitioned) |
| **Trace** | Không có | Full trace CSV |
| **Export** | Không có | .xlsx + .csv |
| **State** | In-memory | JSON file |
| **Lock** | Không có | Mutex lock |

---

## Schedule Integration

### Windows (Task Scheduler)
```powershell
# Tạo scheduled task
schtasks /create /tn "EventRealtime" /tr "python scripts/event_realtime_cron.py" /sc minute /mo 120
```

### Linux (Cron)
```bash
# Thêm vào crontab
0 */2 * * * cd /path/to/project && python scripts/event_realtime_cron.py >> logs/cron.log 2>&1
```

---

## Dependencies

Cần thêm vào `requirements.txt`:
- pandas
- openpyxl (cho .xlsx)
- pyarrow (cho Parquet)

---

## Files to Modify/Create

### Create (New Files)
- [ ] `src/pipeline/event_realtime/cli.py`
- [ ] `src/pipeline/event_realtime/crawler.py`
- [ ] `src/pipeline/event_realtime/storage.py`
- [ ] `src/pipeline/event_realtime/exporter.py`
- [ ] `src/pipeline/event_realtime/processor.py`
- [ ] `src/pipeline/event_realtime/models.py` (update)
- [ ] `scripts/event_realtime_cron.py`

### Modify
- [ ] `config/factors.yaml` (thêm event_realtime config)
- [ ] `src/pipeline/__init__.py` (export)
- [ ] `src/pipeline/registry.py` (register plugin)
