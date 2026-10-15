# Plan: Sửa lỗi Event Realtime Pipeline

## Context

Sau khi kiểm tra, pipeline event realtime đã có cấu trúc đầy đủ (crawler, storage, processor, exporter, post-process, cron) nhưng đang **không chạy được ổn định** vì các lỗi sau:

1. **🔴 Lỗi runtime chặn pipeline** — `TypeError: can't subtract offset-naive and offset-aware datetimes` tại [processor.py:221](src/pipeline/event_realtime/processor.py#L221). `state.start_at` từ state.json có `tzinfo` (UTC) nhưng `crawl_time = datetime.now()` naive. Log ghi nhận `crawler failed with exit code: 1` → mỗi chu kỳ 2h đều crash, không có trace mới nào được ghi.
2. **🔴 Scheduled Task chưa cài** — `EventRealtimeCrawler_2h` không tồn tại trong Windows Task Scheduler, nên dù fix được cũng không tự động chạy.
3. **🟡 Dead code gây nhiễu** — `event_realtime_cli.py` (cũ) ở root `src/pipeline/`, `run_crawl.py`, `run_all_sources.py`, `run_crawler.bat`, `run.bat` trùng chức năng.
4. **🟡 ImportError chết người trong code cũ** — `ensemble.py:11` import `EventChange, EventSignature` không tồn tại trong `models.py` → file này là dead code.
5. **🟡 Tính nhất quán tzinfo** — `EventImpactCalculator.calculate` (models.py:453-462) đã strip tzinfo để tính delta, nhưng code khác (processor, state JSON) lại giữ tzinfo. Cần chuẩn hóa một cách xử lý.

## Đề xuất cách sửa

### Phương án được chọn: Sửa tối thiểu + dọn dẹp dead code (không refactor kiến trúc)

Giữ nguyên kiến trúc hiện tại (đã đúng PLAN_event_realtime.md), chỉ sửa điểm lỗi và dọn rác. Lý do: code logic đã ổn, việc refactor lớn sẽ tăng rủi ro break các phần đang chạy được (state.json vẫn được ghi đúng 17:23 ngày 14/10 trước khi crash).

### Thay đổi cụ thể

#### Fix 1: Sửa lỗi tzinfo trong `_check_cancellation`
- **File**: [src/pipeline/event_realtime/processor.py](src/pipeline/event_realtime/processor.py)
- **Dòng 221**: thay vì trừ trực tiếp, dùng helper chuẩn hóa tzinfo (naive hoặc đều UTC). Cùng pattern với `EventImpactCalculator.calculate` (models.py:455-461) đã strip tzinfo về naive để so sánh với `now = datetime.now()`.
- **Helper mới** thêm vào `EventRealtimeProcessor`: `_normalize_dt(val, target_tz=None) -> datetime` để dùng lại ở nhiều nơi.

#### Fix 2: Sửa các chỗ khác có cùng pattern tzinfo
- **File**: [src/pipeline/event_realtime/processor.py](src/pipeline/event_realtime/processor.py)
- Trong `detect_changes` (dòng 100) có `event.start_at[:10] if isinstance(event.start_at, str)` — OK vì isinstance check.
- Trong `_diff_states` (dòng 260-280) cũng có `to_dt()` helper — đã xử lý string nhưng chưa xử lý tzinfo. Chuẩn hóa lại.

#### Fix 3: Cài lại Scheduled Task
- Có 2 cách:
  - **(A)** Chạy script `scripts/install_event_realtime_task.ps1` qua PowerShell (tương tác được).
  - **(B)** Dùng `schtasks /Create` trực tiếp qua Bash với đường dẫn PowerShell hợp lệ.
- **Chọn (A)** vì script đã có sẵn, idempotent (xóa task cũ trước khi tạo), và test ngay sau khi cài. Nhưng vì cần chạy từ Bash với quyền admin, sẽ dùng `powershell.exe -ExecutionPolicy Bypass -File scripts/install_event_realtime_task.ps1`.

#### Fix 4: Xóa dead code
- **Xóa**:
  - [src/pipeline/event_realtime_cli.py](src/pipeline/event_realtime_cli.py) (cũ, dùng `EventRealtimePlugin` không tồn tại)
  - [run_crawl.py](run_crawl.py), [run_all_sources.py](run_all_sources.py), [run_crawler.bat](run_crawler.bat), [run.bat](run.bat) (test thủ công trùng chức năng)
  - [src/pipeline/event_realtime/ensemble.py](src/pipeline/event_realtime/ensemble.py) (import không tồn tại)
  - [src/pipeline/event_realtime/plugin.py](src/pipeline/event_realtime/plugin.py) (dùng `EventChange` không tồn tại trong models)
- **Giữ nguyên**: tất cả các file đang chạy đúng (`crawler.py`, `processor.py`, `storage.py`, `exporter.py`, `models.py`, `cli.py`, `__init__.py`).
- **Cập nhật** [src/pipeline/event_realtime/__init__.py](src/pipeline/event_realtime/__init__.py) nếu có tham chiếu `EventRealtimePlugin` hoặc `EventEnsembleAggregator` — hiện tại file này KHÔNG export các class đó, nhưng cần check `src/pipeline/__init__.py` và `src/pipeline/registry.py` xem có đăng ký gì không.

#### Fix 5: Verify sau khi sửa
- Chạy thử 1 lần: `python -m pipeline.event_realtime.cli --config config/factors_realtime.yaml --once --verbose`
- Kiểm tra state.json được cập nhật, traces có record mới, event_realtime.xlsx được tạo.
- Kiểm tra Scheduled Task xuất hiện: `schtasks /Query /TN "EventRealtimeCrawler_2h"`.

## Files sẽ thay đổi

| File | Hành động |
|---|---|
| [src/pipeline/event_realtime/processor.py](src/pipeline/event_realtime/processor.py) | Sửa `_check_cancellation`, `_diff_states`, thêm helper `_normalize_dt` |
| [src/pipeline/event_realtime/models.py](src/pipeline/event_realtime/models.py) | Không sửa (impact calculator đã đúng pattern) |
| [src/pipeline/event_realtime/__init__.py](src/pipeline/event_realtime/__init__.py) | Kiểm tra, giữ nguyên nếu không có ref |
| [src/pipeline/event_realtime_cli.py](src/pipeline/event_realtime_cli.py) | **Xóa** |
| [src/pipeline/event_realtime/ensemble.py](src/pipeline/event_realtime/ensemble.py) | **Xóa** |
| [src/pipeline/event_realtime/plugin.py](src/pipeline/event_realtime/plugin.py) | **Xóa** |
| [run_crawl.py](run_crawl.py) | **Xóa** |
| [run_all_sources.py](run_all_sources.py) | **Xóa** |
| [run_crawler.bat](run_crawler.bat) | **Xóa** |
| [run.bat](run.bat) | **Xóa** |
| Scheduled Task | Cài qua `install_event_realtime_task.ps1` |

## Verification

1. **Unit-style check** (chạy pipeline 1 lần):
   ```bash
   cd d:/AITHUCCHIEN/Demand-Spike-Detector-v0
   python -m pipeline.event_realtime.cli --config config/factors_realtime.yaml --once --verbose
   ```
   Expect: exit code 0, có log "CRAWL SUMMARY", state.json được cập nhật, traces có record mới.

2. **File output check**:
   - `data/event_realtime/state.json` có `saved_at` mới
   - `data/event_realtime/traces/date=<hôm nay>/traces.csv` có dòng mới
   - `data/event_realtime.xlsx` được tạo/cập nhật
   - `data/event_realtime_fixed.xlsx` được tạo (post-process)

3. **Scheduled Task check**:
   ```bash
   schtasks /Query /TN "EventRealtimeCrawler_2h"
   ```
   Expect: hiện thông tin task với schedule "Every 2 hours".

4. **Verify không còn lỗi**:
   - `grep -r "from .event_realtime import EventRealtimePlugin"` → không có
   - `grep -r "from .event_realtime import EventEnsembleAggregator"` → không có
   - Python import test: `python -c "from pipeline.event_realtime import EventRealtimeCrawler"`
