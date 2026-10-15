# Event Realtime Processing

## Giới thiệu

Event Realtime là module xử lý thay đổi sự kiện theo thời gian thực, được thiết kế dựa trên kiến trúc của Weather Ensemble nhưng được điều chỉnh cho discrete events.

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  EVENT REALTIME SYSTEM                                        │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                           │
│  BACKFILL PIPELINE                          REALTIME PIPELINE                              │
│  (Daily/Weekly)                             (Every 2 hours)                                │
│  ────────────────                           ─────────────────────                          │
│                                                                                           │
│  ┌─────────┐  ┌─────────┐                  ┌─────────────────────────────────────────┐   │
│  │ VanMieu │  │Ticketbox│                  │  EventRealtimePlugin                      │   │
│  │ Plugin  │  │ Plugin  │                  │  ─────────────────────────────────────  │   │
│  └────┬────┘  └────┬────┘                  │                                          │   │
│       │             │                       │  ┌────────────────────────────────────┐  │   │
│       └─────┬───────┘                       │  │  EventEnsembleAggregator           │  │   │
│             │                               │  │  ──────────────────────────────  │  │   │
│             ▼                               │  │                                    │  │   │
│  ┌───────────────────────┐                 │  │  • Fetch from 8 sources           │  │   │
│  │  Store to Database    │                 │  │  • Track source status            │  │   │
│  │  (events.jsonl)       │                 │  │  • Circuit breaker               │  │   │
│  └───────────────────────┘                 │  │                                    │  │   │
│                                            │  └──────────────┬─────────────────────┘  │   │
│                                            │                 │                        │   │
│                                            │                 ▼                        │   │
│                                            │  ┌────────────────────────────────────┐  │   │
│                                            │  │  EventRealtimeProcessor            │  │   │
│                                            │  │  ──────────────────────────────    │  │   │
│                                            │  │                                    │  │   │
│                                            │  │  • Signature matching              │  │   │
│                                            │  │  • NEW/UPDATED/CONFIRMED/         │  │   │
│                                            │  │    CANCELLED detection             │  │   │
│                                            │  │  • Impact scoring                 │  │   │
│                                            │  │                                    │  │   │
│                                            │  └────────────────────────────────────┘  │   │
│                                            └─────────────────────────────────────────┘   │
│                                                                                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Cấu trúc File

```
src/pipeline/event_realtime/
├── __init__.py          # Package exports
├── models.py            # EventSignature, EventState, EventChange, EventChangeType
├── processor.py         # EventRealtimeProcessor (core logic)
├── ensemble.py          # EventEnsembleAggregator (fetch & merge)
└── plugin.py           # EventRealtimePlugin (orchestrator integration)
```

## Các thành phần

### 1. Models

| Class | Mô tả |
|-------|-------|
| `EventSignature` | Signature để matching events (title + date + venue) |
| `EventState` | Trạng thái của một event trong hệ thống |
| `EventChange` | Một thay đổi được phát hiện |
| `EventChangeType` | Enum: NEW, CONFIRMED, UPDATED, CANCELLED |

### 2. EventRealtimeProcessor

Logic xử lý chính:
- **process_source()**: Xử lý events từ một source
- **calculate_impact()**: Tính impact score
- **_check_cancellations()**: Phát hiện events bị hủy

### 3. EventEnsembleAggregator

Tương tự Weather Ensemble:
- **fetch_all_sources()**: Fetch events từ tất cả 8 sources
- **ensemble()**: Merge events bằng signature matching
- **Circuit breaker**: Track và skip failed sources

### 4. EventRealtimePlugin

Plugin wrapper cho orchestrator:
- Schedule: `0 */2 * * *` (every 2 hours)
- State persistence: Lưu state giữa các lần chạy
- Notification: Gửi notification cho high-impact changes

## Cách sử dụng

### Chạy backfill (như cũ)
```bash
python -m src.pipeline --config config/factors.yaml
```

### Chạy realtime
```bash
python -m src.pipeline --config config/factors.yaml --realtime --realtime-load-baseline
```

### Chạy realtime với CLI riêng
```bash
python -m src.pipeline.event_realtime_cli --config config/factors.yaml --load-baseline --horizon-days 14
```

## Cấu hình

```yaml
events:
  event_date_window:
    start_date: "2026-06-29"
    end_date: "2026-09-28"

  sources:
    van_mieu:
      enabled: true
      calendars:
        "V-League": "https://..."
      hanoi_venue_allowlist:
        - "Hà Nội"
      timezone: "Asia/Ho_Chi_Minh"

    ticketbox_all:
      enabled: true
      api_key: "..."
```

## Luồng xử lý

```
1. LOAD STATE        ← Load known events từ database (baseline)
       │
       ▼
2. FETCH SOURCES     ← Fetch từ 8 sources
       │
       ▼
3. CHANGE DETECT    ← Signature matching: NEW/CONFIRMED/UPDATED
       │
       ▼
4. CANCELLATIONS    ← Check events disappeared
       │
       ▼
5. IMPACT SCORE     ← Tính impact: category × confidence × time
       │
       ▼
6. SAVE + NOTIFY    ← Lưu state, gửi notifications
```

## Impact Scoring

```
impact = category_impact × confidence × time_factor × change_type_bonus

Trong đó:
- category_impact: concert=0.9, festival=0.8, sports=0.7, ...
- confidence: 1 source=0.5, 2 sources=0.75, 3+ sources=1.0
- time_factor: sigmoid peak ở 48h trước event
- change_type_bonus: NEW=1.2, CONFIRMED=1.0, UPDATED=1.5, CANCELLED=1.3
```

## Files được tạo mới

| File | Mô tả |
|------|--------|
| `event_realtime/__init__.py` | Package exports |
| `event_realtime/models.py` | Data models |
| `event_realtime/processor.py` | Core logic |
| `event_realtime/ensemble.py` | Aggregator |
| `event_realtime/plugin.py` | Plugin wrapper |
| `event_realtime_cli.py` | CLI entry point |

## Files được sửa

| File | Thay đổi |
|------|-----------|
| `storage.py` | Thêm methods cho realtime state |
| `__main__.py` | Thêm --realtime flags |

## Files giữ nguyên

- `plugins/event_plugin.py`
- `plugins/ticketbox_*.py`
- `plugins/festival.py`
- `plugins/football.py`
- `plugins/other.py`
