# Phân Tích & Thiết Kế Data Pipeline

## 1. Thiết Kế Extensible Pipeline

### 1.1 Architecture Tổng Quan

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          EXTENSIBLE DATA PIPELINE ARCHITECTURE                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                      PLUGIN REGISTRY (Factory Pattern)                    │   │
│   │                                                                          │   │
│   │  PluginRegistry.load_from_config() → Dict[plugin_name, plugin_instance]  │   │
│   │                                                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│                                        ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                    BASE PLUGIN (Interface)                               │   │
│   │                                                                          │   │
│   │      BaseFactorPlugin (ABC)                                             │   │
│   │      ├── fetch() → pd.DataFrame                                        │   │
│   │      ├── transform(df) → pd.DataFrame                                  │   │
│   │      ├── map_spatial(df) → pd.DataFrame                               │   │
│   │      └── run_pipeline() → List[FactorRecord]                          │   │
│   │                                                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                     PLUGINS (Implementations)                           │   │
│   │                                                                          │   │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│   │  │   OWM        │  │   HSDC       │  │   NCHMF      │              │   │
│   │  │   Plugin     │  │   Plugin     │  │   Plugin     │              │   │
│   │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│   │                                                                          │   │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│   │  │   VCW        │  │   Holiday    │  │   Event      │              │   │
│   │  │   Plugin     │  │   Plugin     │  │   Plugin     │              │   │
│   │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│   │                                                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│                                        ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                     WEATHER ENSEMBLE                                     │   │
│   │                                                                          │   │
│   │  WeatherEnsembleAggregator                                               │   │
│   │  ├── Continuous: MAE-based weighting                                    │   │
│   │  ├── Classification: F1-score voting                                   │   │
│   │  ├── Time-decay function                                                │   │
│   │  └── Circuit breaker pattern                                            │   │
│   │                                                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│                                        ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                     OUTPUT: Feature Store                               │   │
│   │                                                                          │   │
│   │   Primary Key: (hex_id, datetime_30min)                                 │   │
│   │                                                                          │   │
│   │   ┌────────────┬──────────────┬────────┬────────┬────────┐             │   │
│   │   │ hex_id     │datetime_30min│ weather│ flood  │holiday │             │   │
│   │   ├────────────┼──────────────┼────────┼────────┼────────┤             │   │
│   │   │ 88415... │2026-06-29 00│  0.0   │  0.0   │  0.0   │             │   │
│   │   │ 88415... │2026-06-29 00│  0.6   │  0.0   │  0.0   │             │   │
│   │   └────────────┴──────────────┴────────┴────────┴────────┘             │   │
│   │                                                                          │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Core Components

### 2.1 Base Plugin Interface

```python
# src/pipeline/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd

@dataclass
class FactorRecord:
    """Standardized data contract - TẤT CẢ factor trả về format này."""
    hex_id: str
    datetime_30min: datetime
    factor_type: str
    factor_name: str
    value: float
    severity: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: str = ""

class BaseFactorPlugin(ABC):
    """Abstract Base Class cho tất cả Factor Plugins."""
    
    factor_name: str = "base"
    
    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """Fetch raw data từ nguồn (API, File, etc.)"""
        pass
    
    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform raw data → clean, normalized format"""
        pass
    
    @abstractmethod
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map địa điểm → H3 hex_id"""
        pass
    
    def run_pipeline(self) -> List[FactorRecord]:
        """Template Method - Skeleton của pipeline"""
        self.raw_data = self.fetch()
        df = self.transform(self.raw_data)
        df = self.map_spatial(df)
        return self._to_factor_records(df)
```

### 2.2 Plugin Registry

```python
# src/pipeline/registry.py

class PluginRegistry:
    """
    Registry quản lý tất cả Factor Plugins.
    Design Pattern: Registry Pattern + Factory Pattern
    """
    
    _plugins: Dict[str, Type[BaseFactorPlugin]] = {}
    
    @classmethod
    def register(cls, name: str):
        """Decorator để đăng ký plugin"""
        def decorator(plugin_class: Type[BaseFactorPlugin]):
            cls._plugins[name] = plugin_class
            return plugin_class
        return decorator
    
    @classmethod
    def load_from_config(cls, config_path: str) -> Dict[str, BaseFactorPlugin]:
        """Load plugins từ config file"""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        plugins = {}
        for factor_config in config.get('factors', []):
            factor_name = factor_config['name']
            plugin_class = cls.get_plugin_class(factor_name)
            plugins[factor_name] = plugin_class(factor_config)
        
        return plugins
```

### 2.3 Weather Ensemble

```python
# src/pipeline/weather_ensemble.py

class WeatherEnsembleAggregator:
    """
    Aggregates weather data from multiple sources.
    
    Methods:
    - ensemble_continuous(): MAE-based weighting
    - ensemble_classification(): F1-score voting
    - Time-decay function
    - Circuit breaker pattern
    """
    
    def ensemble_continuous(
        self,
        variable_name: str,
        source_values: Dict[str, float]
    ) -> EnsembleResult:
        """Continuous variable ensemble (temp, humidity, precipitation)."""
        ...
    
    def ensemble_classification(
        self,
        variable_name: str,
        source_values: Dict[str, float]
    ) -> EnsembleResult:
        """Binary classification ensemble (storm, thunderstorm)."""
        ...
```

## 3. Implemented Plugins

### 3.1 Weather Plugins

| Plugin | Source | Code File |
|--------|--------|-----------|
| OWMPlugin | OpenWeatherMap | `src/pipeline/plugins/owm_plugin.py` |
| VCWPlugin | Visual Crossing | `src/pipeline/plugins/vcw_plugin.py` |
| HSDCPlugin | HSDC Rainfall | `src/pipeline/plugins/hsdc_plugin.py` |
| NCHMFPlugin | NCHMF | `src/pipeline/plugins/nchmf_plugin.py` |

### 3.2 Other Plugins

| Plugin | Source | Code File |
|--------|--------|-----------|
| HolidayPlugin | Static Calendar | `src/pipeline/plugins/holiday_plugin.py` |
| EventPlugin | Manual CSV | `src/pipeline/plugins/event_plugin.py` |
| HSDCFloodPlugin | HSDC Flood | `src/pipeline/plugins/hsdc_flood_plugin.py` |
| TomTomPlugin | TomTom Traffic | `src/pipeline/plugins/tomtom_traffic_plugin.py` |

### 3.3 OSM Capacity

| Component | Code File |
|-----------|-----------|
| Fetch | `scripts/fetch_osm_retry.py` |
| Process | `scripts/process_osm_h3api.py` |
| Pipeline | `scripts/osm_batch_pipeline.py` |

## 4. Batch Processing Scripts

### 4.1 Backfill Scripts

```bash
# Fetch historical weather data
python scripts/backfill_weather.py

# Bulk backfill với 8 API keys
python scripts/backfill_with_8keys.py

# Merge holiday data
python scripts/merge_holidays.py
```

### 4.2 OSM Pipeline

```bash
# Full pipeline: Fetch → Process → Verify
python scripts/osm_batch_pipeline.py --full

# Individual steps
python scripts/fetch_osm_retry.py        # Fetch từ Overpass API
python scripts/process_osm_h3api.py      # Process → Parquet
python scripts/osm_batch_pipeline.py --verify  # Verify coverage
```

### 4.3 Real-time Crawler

```bash
# Run crawler
python scripts/realtime_crawler.py

# Windows Task Scheduler
powershell scripts/install_crawler_task.ps1

# Linux Cron
./scripts/install_cron.sh
```

## 5. Data Flow

### 5.1 Batch Pipeline (Training)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  BATCH PIPELINE (Training)                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  Backfill   │    │   Process   │    │   Merge    │                 │
│  │  Weather    │───▶│   (H3)     │───▶│   Holiday  │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│                                                │                          │
│                                                ▼                          │
│                   ┌─────────────────────────────────────────┐            │
│                   │   weather_anchors_30T_merged.parquet    │            │
│                   │   + h3_osm_capacity.parquet            │            │
│                   └─────────────────────────────────────────┘            │
│                                                │                          │
│                                                ▼                          │
│                   ┌─────────────────────────────────────────┐            │
│                   │   Feature Engineering                   │            │
│                   │   Preprocessor                          │            │
│                   └─────────────────────────────────────────┘            │
│                                                │                          │
│                                                ▼                          │
│                   ┌─────────────────────────────────────────┐            │
│                   │   MODEL TRAINING                        │            │
│                   │   spike_predictor.pkl                   │            │
│                   └─────────────────────────────────────────┘            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Real-time Pipeline (Inference)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  REAL-TIME PIPELINE (Inference)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │  EVERY 15 MINUTES (via Task Scheduler / Cron)                      │    │
│  │                                                                   │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │    │
│  │  │   OWM   │  │   VCW   │  │  HSDC   │  │  NCHMF  │            │    │
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │    │
│  │       └───────────┴───────────┴───────────┘                    │    │
│  │                          │                                       │    │
│  │                          ▼                                       │    │
│  │                   ┌─────────────┐                              │    │
│  │                   │  Ensemble   │                              │    │
│  │                   │  Aggregator│                              │    │
│  │                   └──────┬──────┘                              │    │
│  │                          │                                       │    │
│  └──────────────────────────┼───────────────────────────────────────┘    │
│                             │                                          │
│                             ▼                                          │
│                   ┌─────────────────────┐                            │
│                   │   Feature Store     │                            │
│                   │   (realtime_lake/) │                            │
│                   └──────────┬──────────┘                            │
│                              │                                         │
│                              ▼                                         │
│                   ┌─────────────────────┐                            │
│                   │   Model Inference   │                            │
│                   │   spike_predictor  │                            │
│                   └──────────┬──────────┘                            │
│                              │                                         │
│                              ▼                                         │
│                   ┌─────────────────────┐                            │
│                   │   ALERTS            │                            │
│                   │   spike: true/false │                            │
│                   └─────────────────────┘                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 6. Design Principles

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    5 NGUYÊN TẮC THIẾT KẾ                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. DEPENDENCY INVERSION (Interface thay vì Implementation)                      │
│     ─────────────────────────────────────────────────                           │
│     BaseFactorPlugin defines contract                                             │
│     Specific plugins implement contract                                           │
│                                                                                 │
│  2. OPEN-CLOSED PRINCIPLE (Open for extension, Closed for modification)           │
│     ───────────────────────────────────────────────────────────────────────     │
│     Thêm feature = Thêm file mới, không sửa file cũ                            │
│                                                                                 │
│  3. SINGLE RESPONSIBILITY (Mỗi plugin = 1 factor)                               │
│     ──────────────────────────────────────────────────────────────────────     │
│     Plugin này chỉ lo weather, plugin kia chỉ lo flood                        │
│                                                                                 │
│  4. CONFIGURATION OVER CODE                                                     │
│     ─────────────────────────────────────────────────────────────────────     │
│     Schedule, API keys, thresholds → YAML config                                 │
│                                                                                 │
│  5. STANDARDIZED DATA CONTRACT (FactorRecord)                                    │
│     ──────────────────────────────────────────────────────────────────────     │
│     Tất cả plugins trả về cùng format                                          │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 7. Files Structure

```
Demand-Spike-Detector/
├── src/pipeline/
│   ├── base.py                    # BaseFactorPlugin (ABC)
│   ├── registry.py                # PluginRegistry (Factory)
│   ├── orchestrator.py           # PipelineOrchestrator
│   ├── weather_ensemble.py       # WeatherEnsembleAggregator
│   ├── spatial_ensemble_pipeline.py  # H3 spatial mapping
│   ├── nchmf_spatial_lookup.py   # NCHMF O(1) lookup
│   └── plugins/
│       ├── owm_plugin.py        # OpenWeatherMap
│       ├── vcw_plugin.py        # Visual Crossing
│       ├── hsdc_plugin.py       # HSDC Rainfall
│       ├── hsdc_flood_plugin.py # HSDC Flood
│       ├── nchmf_plugin.py      # NCHMF Crawler
│       ├── nchmf_api_plugin.py  # NCHMF API
│       ├── holiday_plugin.py     # Holidays
│       ├── event_plugin.py      # Events
│       └── tomtom_traffic_plugin.py  # TomTom Traffic
│
├── scripts/
│   ├── backfill_weather.py      # Weather backfill
│   ├── backfill_with_8keys.py   # Bulk backfill
│   ├── processor.py             # Data processor
│   ├── demo_pipeline.py         # Demo pipeline
│   ├── merge_holidays.py       # Merge holidays
│   ├── realtime_crawler.py      # Real-time crawler
│   ├── fetch_osm_retry.py       # OSM fetch
│   ├── process_osm_h3api.py    # OSM process
│   └── osm_batch_pipeline.py   # OSM batch pipeline
│
├── src/features/
│   ├── preprocessor.py          # Feature preprocessing
│   ├── feature_engineer.py      # Feature engineering
│   └── holiday_calendar.py      # Holiday calendar
│
└── tests/
    ├── test_weather_ensemble.py # Ensemble tests
    ├── test_weather_plugins.py  # Plugin tests
    ├── test_spatial_ensemble.py # Spatial tests
    └── test_features_preprocessor.py  # Preprocessor tests
```
