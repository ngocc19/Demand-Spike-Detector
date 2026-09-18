# Phân tích & Thiết kế Data Pipeline Tối ưu

---



## 2. Thiết kế Extensible Pipeline (Thiết kế đề xuất)

### 2.1 Architecture Tổng quan

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          EXTENSIBLE DATA PIPELINE ARCHITECTURE                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                      PLUGIN REGISTRY (Configuration)                    │   │
│   │  ┌─────────────────────────────────────────────────────────────────┐   │   │
│   │  │  factors.yaml                                                   │   │   │
│   │  │  ─────────────                                                  │   │   │
│   │  │  - name: weather        source: api        schedule: "0 * * * *"│   │   │
│   │  │  - name: flood          source: rss        schedule: "*/15 * * *"| │   │
│   │  │  - name: event          source: scraper    schedule: "0 23 * * *"| │   │
│   │  │  - name: holiday        source: file       schedule: "0 0 1 1 *"| │   │
│   │  │  - name: AOE_SALE       source: api        schedule: "0 0 * * 5" │   │   │
│   │  │  - name: concert        source: api        schedule: "0 23 * * *"| │   │
│   │  │  # Thêm factor mới chỉ cần thêm dòng config ở đây!              │   │   │
│   │  └─────────────────────────────────────────────────────────────────┘   │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│                                        ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                    PLUGIN LOADER (Dynamic Discovery)                   │   │
│   │                                                                          │   │
│   │      ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │   │
│   │      │  Plugin    │  │  Plugin    │  │  Plugin    │  │  Plugin    │     │   │
│   │      │  Weather   │  │  Flood     │  │  Event     │  │  Holiday   │     │   │
│   │      └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘     │   │
│   │            │              │              │              │              │   │
│   │            └──────────────┴──────────────┴──────────────┘              │   │
│   │                               │                                          │   │
│   │                               ▼                                          │   │
│   │                   ┌──────────────────────┐                              │   │
│   │                   │  Standardized Factor │                              │   │
│   │                   │       Contract       │                              │   │
│   │                   │  ──────────────────  │                              │   │
│   │                   │  hex_id: str         │                              │   │
│   │                   │  datetime_30min: str │                              │   │
│   │                   │  factor_type: str    │                              │   │
│   │                   │  value: float        │                              │   │
│   │                   │  metadata: dict      │                              │   │
│   │                   └──────────────────────┘                              │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                        │                                         │
│                                        ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                     FEATURE STORE (Unified Sink)                        │   │
│   │                                                                          │   │
│   │   Primary Key: (hex_id, datetime_30min)                                 │   │
│   │                                                                          │   │
│   │   ┌────────────┬──────────────┬────────┬────────┬────────┬────────┐     │   │
│   │   │ hex_id     │datetime_30min│ weather│ flood  │ event  │holiday │     │   │
│   │   ├────────────┼──────────────┼────────┼────────┼────────┼────────┤     │   │
│   │   │ 8a2a100... │2024-08-15 14│  0.3   │  0.0   │  0.0   │  0.0   │     │   │
│   │   │ 8a2a100... │2024-08-15 14│  0.0   │  0.85  │  0.0   │  0.0   │     │   │
│   │   │ 8a2a100... │2024-08-15 14│  0.0   │  0.0   │  1.0   │  0.0   │     │   │
│   │   └────────────┴──────────────┴────────┴────────┴────────┴────────┘     │   │
│   │                                                                          │   │
│   │   # Schema tự động mở rộng khi thêm factor mới!                         │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Components (Code Implementation)

#### A. Base Class & Contract

```python
# ============================================================
# FILE: src/pipeline/base.py
# Mục đích: Định nghĩa interface chuẩn cho tất cả các Factor Plugin
# ============================================================

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import pandas as pd


class FactorType(Enum):
    """Enum định nghĩa các loại factor có thể có"""
    WEATHER = "weather"
    FLOOD = "flood"
    EVENT = "event"
    HOLIDAY = "holiday"
    AOE_SALE = "aoe_sale"          # Flash sale Affect-Of-Offer
    CONCERT = "concert"            # Concert/Performance
    SPORT_MATCH = "sport_match"    # Sports event
    NEWS = "news"                  # Breaking news
    TRAFFIC = "traffic"            # Traffic congestion
    POLLUTION = "pollution"        # AQI level
    # Thêm factor mới ở đây → KHÔNG CẦN SỬA CODE KHÁC!


@dataclass
class FactorRecord:
    """
    Standardized data contract - TẤT CẢ factor phải trả về format này.
    
    Đây là "lingua franca" của pipeline, đảm bảo tính thống nhất.
    """
    hex_id: str                           # H3 hex ID
    datetime_30min: datetime              # Thời điểm (align 30 min)
    factor_type: FactorType               # Loại factor
    factor_name: str                      # Tên cụ thể: "heavy_rain", "vff_match"
    value: float                          # Giá trị impact (0.0 → 1.0 hoặc raw)
    severity: Optional[str] = None        # LOW, MEDIUM, HIGH, SEVERE
    metadata: Dict[str, Any] = field(default_factory=dict)  # Raw data gốc
    confidence: float = 1.0              # Độ tin cậy của dữ liệu
    source: str = ""                      # Nguồn dữ liệu
    ingested_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        """Convert sang dict để lưu vào Feature Store"""
        return {
            "hex_id": self.hex_id,
            "datetime_30min": self.datetime_30min.strftime("%Y-%m-%d %H:%M:%S"),
            "factor_type": self.factor_type.value,
            "factor_name": self.factor_name,
            "value": self.value,
            "severity": self.severity,
            "metadata": str(self.metadata),  # JSON stringify
            "confidence": self.confidence,
            "source": self.source,
            "ingested_at": self.ingested_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class BaseFactorPlugin(ABC):
    """
    Abstract Base Class cho tất cả Factor Plugins.
    
    Design Pattern: Template Method + Strategy
    - Template Method: define_pipeline() quy định skeleton
    - Strategy: fetch(), transform(), map_spatial() là strategy được implement riêng
    """
    
    # Class variables - override ở subclass
    factor_type: FactorType = FactorType.WEATHER
    factor_name: str = "base"
    schedule: str = "0 * * * *"  # Cron format
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Configuration dict từ factors.yaml
        """
        self.config = config
        self.raw_data: Optional[pd.DataFrame] = None
        self.processed_data: List[FactorRecord] = []
        
    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """
        Bước 1: Fetch raw data từ nguồn (API, RSS, File, etc.)
        
        Returns:
            DataFrame với raw data
        """
        pass
    
    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bước 2: Transform raw data → clean, normalized format
        
        Args:
            df: Raw data từ fetch()
            
        Returns:
            DataFrame đã được clean và normalize
        """
        pass
    
    @abstractmethod
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bước 3: Map địa điểm → H3 hex_id
        
        Args:
            df: Cleaned data từ transform()
            
        Returns:
            DataFrame đã thêm column 'hex_id'
        """
        pass
    
    def align_temporal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bước 4: Align thời gian về 30-min grid
        
        Args:
            df: DataFrame với 'datetime' column
            
        Returns:
            DataFrame với 'datetime_30min' column
        """
        df = df.copy()
        
        if 'datetime' not in df.columns:
            raise ValueError("DataFrame must have 'datetime' column")
        
        # Resample về 30-min grid
        df['datetime_30min'] = df['datetime'].dt.floor('30min')
        
        return df
    
    def validate(self, df: pd.DataFrame) -> bool:
        """
        Bước 5: Validate output
        
        Args:
            df: Final DataFrame
            
        Returns:
            True if valid, raise exception otherwise
        """
        required_cols = ['hex_id', 'datetime_30min', 'value']
        missing = [col for col in required_cols if col not in df.columns]
        
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        return True
    
    def run_pipeline(self) -> List[FactorRecord]:
        """
        Template Method - Skeleton của pipeline
        
        Flow: fetch → transform → map_spatial → align_temporal → validate → output
        """
        print(f"[{self.factor_name}] Starting pipeline...")
        
        # Step 1: Fetch
        self.raw_data = self.fetch()
        print(f"[{self.factor_name}] Fetched {len(self.raw_data)} records")
        
        # Step 2: Transform
        df = self.transform(self.raw_data)
        print(f"[{self.factor_name}] Transformed to {len(df)} clean records")
        
        # Step 3: Spatial mapping
        df = self.map_spatial(df)
        print(f"[{self.factor_name}] Mapped to H3 hex_ids")
        
        # Step 4: Temporal alignment
        df = self.align_temporal(df)
        
        # Step 5: Validate
        self.validate(df)
        print(f"[{self.factor_name}] Validation passed")
        
        # Step 6: Convert to FactorRecord
        self.processed_data = self._to_factor_records(df)
        print(f"[{self.factor_name}] Generated {len(self.processed_data)} FactorRecords")
        
        return self.processed_data
    
    def _to_factor_records(self, df: pd.DataFrame) -> List[FactorRecord]:
        """Convert DataFrame rows to FactorRecord objects"""
        records = []
        
        for _, row in df.iterrows():
            record = FactorRecord(
                hex_id=row['hex_id'],
                datetime_30min=row['datetime_30min'],
                factor_type=self.factor_type,
                factor_name=self.factor_name,
                value=row['value'],
                severity=row.get('severity'),
                metadata=row.get('metadata', {}),
                confidence=row.get('confidence', 1.0),
                source=self.config.get('source', ''),
            )
            records.append(record)
        
        return records
    
    def get_records_df(self) -> pd.DataFrame:
        """Get processed data as DataFrame for direct Feature Store insertion"""
        return pd.DataFrame([r.to_dict() for r in self.processed_data])
```

#### B. Plugin Implementations

```python
# ============================================================
# FILE: src/pipeline/plugins/weather_plugin.py
# ============================================================

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any
import h3
from .base import BaseFactorPlugin, FactorType, FactorRecord


class WeatherFactorPlugin(BaseFactorPlugin):
    """
    Plugin thu thập dữ liệu thời tiết từ Open-Meteo API.
    """
    
    factor_type = FactorType.WEATHER
    factor_name = "weather"
    schedule = "0 * * * *"  # Mỗi giờ
    
    # Mapping Open-Meteo weather codes → impact values
    WEATHER_IMPACT_MAP = {
        0: 0.0,    # Clear sky
        1: 0.0,    # Mainly clear
        2: 0.0,    # Partly cloudy
        3: 0.0,    # Overcast
        45: 0.2,   # Fog
        48: 0.2,   # Depositing rime fog
        51: 0.3,   # Light drizzle
        53: 0.5,   # Moderate drizzle
        55: 0.7,   # Dense drizzle
        61: 0.5,   # Slight rain
        63: 0.7,   # Moderate rain
        65: 0.9,   # Heavy rain
        71: 0.4,   # Slight snow
        73: 0.6,   # Moderate snow
        75: 0.8,   # Heavy snow
        80: 0.7,   # Slight rain showers
        81: 0.85,  # Moderate rain showers
        82: 1.0,   # Violent rain showers
        95: 0.9,   # Thunderstorm
        96: 1.0,   # Thunderstorm with slight hail
        99: 1.0,   # Thunderstorm with heavy hail
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.hcm_coords = (10.8231, 106.6297)  # Ho Chi Minh City center
        self.radius_km = config.get('radius_km', 30)
        
    def fetch(self) -> pd.DataFrame:
        """Fetch weather data from Open-Meteo API"""
        params = {
            "latitude": self.hcm_coords[0],
            "longitude": self.hcm_coords[1],
            "hourly": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
            "forecast_days": 2,
            "timezone": "Asia/Ho_Chi_Minh",
        }
        
        # Handle rate limiting with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(self.base_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                print(f"Retry {attempt + 1} after error: {e}")
                
        # Parse response
        hourly = data['hourly']
        df = pd.DataFrame({
            'datetime': pd.to_datetime(hourly['time']),
            'temp_c': hourly['temperature_2m'],
            'humidity_pct': hourly['relative_humidity_2m'],
            'precip_mm': hourly['precipitation'],
            'weather_code': hourly['weather_code'],
        })
        
        return df
    
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform raw weather → normalized impact score"""
        df = df.copy()
        
        # Map weather code → impact value
        df['weather_impact'] = df['weather_code'].map(self.WEATHER_IMPACT_MAP).fillna(0)
        
        # Map precipitation → impact (log scale để smooth)
        df['precip_impact'] = df['precip_mm'].apply(
            lambda x: min(1.0, x / 20) if x > 0 else 0.0
        )
        
        # Combined weather impact score
        df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)
        
        # Severity classification
        def classify_severity(row):
            if row['value'] >= 0.8:
                return 'SEVERE'
            elif row['value'] >= 0.5:
                return 'HIGH'
            elif row['value'] >= 0.2:
                return 'MEDIUM'
            else:
                return 'LOW'
        
        df['severity'] = df.apply(classify_severity, axis=1)
        df['metadata'] = df.apply(
            lambda r: {'temp_c': r['temp_c'], 'humidity': r['humidity_pct'], 
                       'precip_mm': r['precip_mm'], 'weather_code': r['weather_code']}, 
            axis=1
        )
        
        return df
    
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Weather ảnh hưởng toàn bộ thành phố.
        → Tạo hex_id coverage cho toàn bộ HCMC
        """
        df = df.copy()
        
        # HCMC H3 coverage (resolution 8 ≈ 460m hex)
        hcm_center = self.hcm_coords
        hex_ids = list(h3.grid_disk(h3.latlng_to_cell(hcm_center[0], hcm_center[1], 8), 
                                     self.radius_km * 1000 / 460))
        
        # Expand df: mỗi datetime có impact cho TẤT CẢ hex trong coverage
        records = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)
        
        return pd.DataFrame(records)
```

```python
# ============================================================
# FILE: src/pipeline/plugins/flood_plugin.py  
# ============================================================

import feedparser
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from datetime import datetime
from typing import Dict, List, Tuple
import h3
from .base import BaseFactorPlugin, FactorType


class FloodFactorPlugin(BaseFactorPlugin):
    """
    Plugin thu thập tin ngập từ RSS feeds (VNExpress, VFF)
    """
    
    factor_type = FactorType.FLOOD
    factor_name = "flood"
    schedule = "*/15 * * * *"  # 15 phút/lần
    
    # Location patterns cho NLP extraction
    # NOTE: Tiếng Việt có 2 bộ ký tự hoàn toàn khác nhau (hoa/thường),
    # nên cần liệt kê CẢ hai, KHÔNG dùng IGNORECASE cho tiếng Việt
    LOCATION_PATTERNS = [
        # Đường - bắt tên đường (nhiều từ, bao gồm dấu cách)
        r"đường\s+([A-Za-zÀ-ỹ\s]{2,})",
        # Quận số (District 1, District 2...)
        r"quận\s+(\d+)",
        # Quận tên (Quận Bình Thạnh, Quận 1)
        r"quận\s+([A-Za-zÀ-ỹ\s]{2,})",
        # TP / Thành phố
        r"tp\.?\s+([A-Za-zÀ-ỹ\s]{2,})",
    ]
    
    # Severity keywords
    SEVERITY_KEYWORDS = {
        'SEVERE': ['ngập nặng', 'ngập sâu', 'ngập trắng', 'chìm xe', 'ùn tắc nghiêm trọng'],
        'HIGH': ['ngập', 'ngập lụt', 'ứ đọng', 'tắc đường'],
        'MEDIUM': ['ngập nhẹ', 'xe khó đi', 'nước ngang bánh'],
        'LOW': ['có nước', 'ẩm ướt'],
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.rss_sources = config.get('rss_sources', [
            'https://vnexpress.net/rss/thoi-su.rss',
            'https://vff.org.vn/feed/',
        ])
        self.geocoding_api = config.get('geocoding_api', 'osmnames')
        self.geocoding_api_key = config.get('geocoding_api_key', '')
        
    def fetch(self) -> pd.DataFrame:
        """Fetch flood news from RSS feeds"""
        all_entries = []
        
        for source_url in self.rss_sources:
            try:
                feed = feedparser.parse(source_url)
                
                for entry in feed.entries[:50]:  # Latest 50 entries
                    # Filter by flood-related keywords
                    if self._is_flood_related(entry.get('title', '') + entry.get('summary', '')):
                        all_entries.append({
                            'title': entry.get('title', ''),
                            'summary': entry.get('summary', ''),
                            'link': entry.get('link', ''),
                            'published': pd.to_datetime(entry.get('published', datetime.now())),
                            'source': source_url,
                        })
            except Exception as e:
                print(f"Error fetching {source_url}: {e}")
                
        return pd.DataFrame(all_entries)
    
    def _is_flood_related(self, text: str) -> bool:
        """Check if text is flood-related"""
        flood_keywords = ['ngập', 'lụt', 'mưa lớn', 'nước dâng', 'triều cường', 'thoát nước']
        text_lower = text.lower()
        return any(kw in text_lower for kw in flood_keywords)
    
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract locations and severity from news"""
        df = df.copy()
        
        # Extract locations
        df['locations'] = df['title'].apply(self._extract_locations)
        
        # Extract severity
        df['severity'] = df['title'].apply(self._extract_severity)
        
        # Calculate impact value from severity
        severity_map = {'SEVERE': 1.0, 'HIGH': 0.75, 'MEDIUM': 0.5, 'LOW': 0.25}
        df['value'] = df['severity'].map(severity_map)
        
        # Metadata
        df['metadata'] = df.apply(
            lambda r: {'title': r['title'], 'link': r['link']}, axis=1
        )
        
        df['datetime'] = df['published']
        
        return df
    
    def _extract_locations(self, text: str) -> List[str]:
        """NLP extraction of location names"""
        locations = []
        
        for pattern in self.LOCATION_PATTERNS:
            matches = re.findall(pattern, text)
            locations.extend(matches)
            
        return list(set(locations))
    
    def _extract_severity(self, text: str) -> str:
        """Extract severity level from text"""
        text_lower = text.lower()
        
        for severity, keywords in self.SEVERITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return severity
                
        return 'LOW'
    
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Map extracted locations → H3 hex_ids via Geocoding
        
        ĐÂY LÀ BƯỚC PHỨC TẠP NHẤT - Cần Geocoding API
        """
        df = df.copy()
        
        # Lưu trữ tạm hex_ids đã resolve
        df['hex_ids'] = None
        
        for idx, row in df.iterrows():
            if not row['locations']:
                # Nếu không extract được location → assume ảnh hưởng toàn TP
                row['hex_ids'] = self._get_hcm_default_hex_ids()
            else:
                hex_ids = []
                for loc in row['locations']:
                    resolved = self._geocode_location(loc)
                    if resolved:
                        hex_ids.extend(resolved)
                
                if hex_ids:
                    row['hex_ids'] = list(set(hex_ids))
                else:
                    row['hex_ids'] = self._get_hcm_default_hex_ids()
        
        # Expand rows: 1 news → N rows (1 per hex_id)
        expanded_rows = []
        for _, row in df.iterrows():
            if row['hex_ids']:
                for hex_id in row['hex_ids']:
                    new_row = row.copy()
                    new_row['hex_id'] = hex_id
                    expanded_rows.append(new_row)
            else:
                row['hex_id'] = None
                expanded_rows.append(row)
                
        return pd.DataFrame(expanded_rows)
    
    def _geocode_location(self, location: str) -> List[str]:
        """
        Geocode location string → H3 hex_ids
        
        Sử dụng OSM Nominatim hoặc Goong API
        """
        # Approximate: sử dụng search OSM
        try:
            # OSM Nominatim (free, rate limited)
            url = f"https://nominatim.openstreetmap.org/search"
            params = {
                'q': f"{location}, Ho Chi Minh City, Vietnam",
                'format': 'json',
                'limit': 1,
            }
            headers = {'User-Agent': 'DemandPredictionPipeline/1.0'}
            
            response = requests.get(url, params=params, headers=headers, timeout=5)
            data = response.json()
            
            if data:
                lat, lon = float(data[0]['lat']), float(data[0]['lon'])
                # Get H3 hex at resolution 9 (~460m)
                return [h3.latlng_to_cell(lat, lon, 9)]
        except Exception as e:
            print(f"Geocoding failed for '{location}': {e}")
            
        return []
    
    def _get_hcm_default_hex_ids(self) -> List[str]:
        """Get default hex coverage for HCMC center"""
        center = (10.8231, 106.6297)
        return list(h3.grid_disk(h3.latlng_to_cell(center[0], center[1], 9), 10))
```

```python
# ============================================================
# FILE: src/pipeline/plugins/event_plugin.py
# ============================================================

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List
import h3
from .base import BaseFactorPlugin, FactorType


class EventFactorPlugin(BaseFactorPlugin):
    """
    Plugin thu thập sự kiện từ Ticketbox API + Manual CSV
    """
    
    factor_type = FactorType.EVENT
    factor_name = "event"
    schedule = "0 23 * * *"  # Daily batch lúc 23:00
    
    # Event type → demand impact
    EVENT_IMPACT_MAP = {
        'concert': 1.0,
        'football': 0.8,
        'festival': 0.9,
        'conference': 0.5,
        'exhibition': 0.4,
        'sports': 0.7,
        'default': 0.5,
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.ticketbox_api = config.get('ticketbox_api')
        self.manual_csv_path = config.get('manual_csv_path', '/data/events_manual.csv')
        
    def fetch(self) -> pd.DataFrame:
        """Fetch events from Ticketbox + Manual CSV"""
        events = []
        
        # Source 1: Ticketbox API
        if self.ticketbox_api:
            events.extend(self._fetch_ticketbox())
            
        # Source 2: Manual CSV/Google Sheets
        events.extend(self._fetch_manual())
        
        return pd.DataFrame(events)
    
    def _fetch_ticketbox(self) -> List[Dict]:
        """Fetch from Ticketbox API"""
        # Implement Ticketbox API call here
        # Endpoint: GET /api/events
        pass
    
    def _fetch_manual(self) -> List[Dict]:
        """Fetch from manual CSV file"""
        try:
            df = pd.read_csv(self.manual_csv_path)
            return df.to_dict('records')
        except FileNotFoundError:
            return []
    
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform events → demand impact scores"""
        df = df.copy()
        
        # Normalize columns
        df['start_time'] = pd.to_datetime(df.get('start_time', df.get('datetime')))
        df['end_time'] = pd.to_datetime(df.get('end_time', df['start_time'] + timedelta(hours=3)))
        
        # Calculate duration in 30-min slots
        df['duration_slots'] = ((df['end_time'] - df['start_time']).dt.total_seconds() / 1800).astype(int)
        
        # Map event type → impact
        df['event_type'] = df.get('event_type', 'default')
        df['value'] = df['event_type'].map(self.EVENT_IMPACT_MAP).fillna(0.5)
        
        # Severity
        df['severity'] = df['value'].apply(
            lambda x: 'HIGH' if x >= 0.8 else 'MEDIUM' if x >= 0.5 else 'LOW'
        )
        
        df['metadata'] = df.apply(
            lambda r: {'event_name': r.get('name'), 'venue': r.get('venue'),
                       'event_type': r.get('event_type')}, axis=1
        )
        
        return df
    
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Map event venue → H3 hex_ids
        
        Cần geocode venue locations
        """
        df = df.copy()
        
        # Known venue coordinates (cache để tránh gọi API nhiều)
        VENUE_CACHE = {
            'svd_my_dinh': (21.0285, 105.8195),  # Sân vận động Mỹ Đình
            'ben_thanh': (10.7798, 106.6989),
            'landmark_81': (10.7952, 106.7215),
            'saigon_exhibition_center': (10.7876, 106.7616),
            # Thêm venue mới vào đây
        }
        
        df['hex_id'] = df['venue'].apply(
            lambda v: self._venue_to_hex(v, VENUE_CACHE)
        )
        
        # Expand time slots: event kéo dài N giờ → N*2 records (30 min each)
        expanded_rows = []
        for _, row in df.iterrows():
            start = row['start_time']
            for i in range(row['duration_slots']):
                slot_time = start + timedelta(minutes=30*i)
                new_row = row.copy()
                new_row['datetime'] = slot_time
                expanded_rows.append(new_row)
                
        return pd.DataFrame(expanded_rows)
    
    def _venue_to_hex(self, venue: str, cache: Dict) -> str:
        """Convert venue name to H3 hex ID"""
        venue_key = venue.lower().replace(' ', '_')
        
        if venue_key in cache:
            lat, lng = cache[venue_key]
            return h3.latlng_to_cell(lat, lng, 9)
        
        # Fallback: HCMC center
        return h3.latlng_to_cell(10.8231, 106.6297, 9)
```

```python
# ============================================================
# FILE: src/pipeline/plugins/holiday_plugin.py
# ============================================================

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any
import h3
from .base import BaseFactorPlugin, FactorType


class HolidayFactorPlugin(BaseFactorPlugin):
    """
    Plugin thu thập ngày lễ từ file tĩnh
    """
    
    factor_type = FactorType.HOLIDAY
    factor_name = "holiday"
    schedule = "0 0 1 1 *"  # Nạp ngày đầu năm + khi có cập nhật
    
    # Tet phase definitions
    TET_PHASES = {
        'pre_tet': (-21, -7),   # 21-7 ngày trước Tết
        'during_tet': (-7, 7),   # 7 ngày trước → 7 ngày sau Tết
        'post_tet': (7, 21),      # 7-21 ngày sau Tết
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.holiday_file = config.get('holiday_file', '/data/holidays.csv')
        self.tet_start_date = datetime(config.get('tet_year', 2024), 2, 10)  # Ngày mùng 1 Tết
        
    def fetch(self) -> pd.DataFrame:
        """Fetch holiday data from CSV file"""
        df = pd.read_csv(self.holiday_file)
        df['date'] = pd.to_datetime(df['date'])
        return df
    
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform holidays → tet_phase + impact"""
        df = df.copy()
        
        # Calculate tet_phase
        def get_tet_phase(date: datetime) -> str:
            days_from_tet = (date - self.tet_start_date).days
            
            for phase, (start, end) in self.TET_PHASES.items():
                if start <= days_from_tet <= end:
                    return phase
            return 'normal'
        
        df['tet_phase'] = df['date'].apply(get_tet_phase)
        
        # Impact values
        phase_impact = {
            'normal': 0.0,
            'pre_tet': 0.6,     # Người về quê, rush
            'during_tet': 0.9,  # Cầu nguyện, đi lễ
            'post_tet': 0.4,    # Quay lại bình thường
        }
        
        df['value'] = df['tet_phase'].map(phase_impact)
        df['severity'] = df['value'].apply(
            lambda x: 'HIGH' if x >= 0.7 else 'MEDIUM' if x >= 0.3 else 'LOW'
        )
        df['metadata'] = df.apply(
            lambda r: {'holiday_name': r.get('name'), 'tet_phase': r['tet_phase']}, axis=1
        )
        df['datetime'] = df['date']
        
        return df
    
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Holidays ảnh hưởng toàn TP nhưng đặc biệt:
        - Đền, chùa: ảnh hưởng local
        - Phố đi bộ: ảnh hưởng local
        
        → Ảnh hưởng toàn bộ với giá trị thấp hơn
        """
        df = df.copy()
        
        # Full HCMC coverage
        center = (10.8231, 106.6297)
        hex_ids = list(h3.grid_disk(h3.latlng_to_cell(center[0], center[1], 9), 50))
        
        # Assign to all hex_ids
        expanded_rows = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                expanded_rows.append(new_row)
                
        return pd.DataFrame(expanded_rows)
```

#### C. Plugin Registry & Loader (Điểm mấu chốt cho Extensibility)

```python
# ============================================================
# FILE: src/pipeline/registry.py
# CẤU TRÚC NÀY ĐẢM BẢO: Thêm factor mới = Thêm file + Thêm dòng config
# ============================================================

import yaml
from pathlib import Path
from typing import Dict, List, Type, Any
import importlib
import inspect

from .base import BaseFactorPlugin, FactorType
from .plugins.weather_plugin import WeatherFactorPlugin
from .plugins.flood_plugin import FloodFactorPlugin
from .plugins.event_plugin import EventFactorPlugin
from .plugins.holiday_plugin import HolidayFactorPlugin


class PluginRegistry:
    """
    Registry quản lý tất cả Factor Plugins.
    
    Design Pattern: Registry Pattern + Factory Pattern
    - Plugin đăng ký qua @register decorator
    - Load plugins từ config file
    - Factory tạo instance dựa trên config
    """
    
    # Class-level registry
    _plugins: Dict[str, Type[BaseFactorPlugin]] = {}
    
    @classmethod
    def register(cls, name: str):
        """Decorator để đăng ký plugin"""
        def decorator(plugin_class: Type[BaseFactorPlugin]):
            cls._plugins[name] = plugin_class
            return plugin_class
        return decorator
    
    @classmethod
    def get_plugin_class(cls, name: str) -> Type[BaseFactorPlugin]:
        """Get plugin class by name"""
        if name not in cls._plugins:
            raise ValueError(f"Unknown plugin: {name}. Available: {list(cls._plugins.keys())}")
        return cls._plugins[name]
    
    @classmethod
    def list_plugins(cls) -> List[str]:
        """List all registered plugins"""
        return list(cls._plugins.keys())
    
    @classmethod
    def load_from_config(cls, config_path: str) -> Dict[str, BaseFactorPlugin]:
        """
        Load plugins từ config file (factors.yaml)
        
        Args:
            config_path: Path to factors.yaml
            
        Returns:
            Dict mapping factor_name → plugin instance
        """
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            
        plugins = {}
        
        for factor_config in config.get('factors', []):
            factor_name = factor_config['name']
            
            # Get plugin class from registry
            plugin_class = cls.get_plugin_class(factor_name)
            
            # Instantiate with config
            plugins[factor_name] = plugin_class(factor_config)
            
        return plugins
    
    @classmethod
    def auto_discover_plugins(cls, plugins_dir: str = "src/pipeline/plugins"):
        """
        Auto-discover plugins in plugins directory.
        Khi thêm plugin file mới → Tự động discover
        """
        plugins_path = Path(plugins_dir)
        
        for py_file in plugins_path.glob("*_plugin.py"):
            # Import module dynamically
            module_name = f"src.pipeline.plugins.{py_file.stem}"
            module = importlib.import_module(module_name)
            
            # Find plugin classes in module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseFactorPlugin) and obj != BaseFactorPlugin:
                    # Auto-register
                    cls._plugins[obj.factor_name] = obj


# ============================================================
# DECORATOR REGISTRATION (Thay vì hard-code trong __init__)
# ============================================================

# Đặt decorator này ở đầu mỗi plugin file
# VD: Trong weather_plugin.py:
# @PluginRegistry.register("weather")
# class WeatherFactorPlugin(BaseFactorPlugin):
#     ...

# Tự động register các plugin có sẵn
PluginRegistry.register("weather")(WeatherFactorPlugin)
PluginRegistry.register("flood")(FloodFactorPlugin)
PluginRegistry.register("event")(EventFactorPlugin)
PluginRegistry.register("holiday")(HolidayFactorPlugin)
```

#### D. Orchestrator (Điều phối tất cả plugins)

```python
# ============================================================
# FILE: src/pipeline/orchestrator.py
# ============================================================

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from pathlib import Path

from .registry import PluginRegistry
from .base import BaseFactorPlugin, FactorRecord


class PipelineOrchestrator:
    """
    Điều phối tất cả plugins và ghi vào Feature Store.
    
    THIẾT KẾ KEY: 
    - Không hard-code plugin names
    - Plugin được load từ config động
    - Thêm factor mới = Thêm dòng trong factors.yaml
    """
    
    def __init__(self, config_path: str, feature_store_path: str):
        """
        Args:
            config_path: Path to factors.yaml
            feature_store_path: Path to output Feature Store
        """
        self.config_path = config_path
        self.feature_store_path = feature_store_path
        
        # Load all plugins from config
        self.plugins: Dict[str, BaseFactorPlugin] = PluginRegistry.load_from_config(config_path)
        
        # Feature Store cache (in-memory)
        self.feature_store: Optional[pd.DataFrame] = None
        
    def run_plugin(self, plugin_name: str) -> pd.DataFrame:
        """
        Chạy một plugin cụ thể
        
        Args:
            plugin_name: Tên plugin (phải khớp với config)
            
        Returns:
            DataFrame với factor records
        """
        if plugin_name not in self.plugins:
            raise ValueError(f"Plugin '{plugin_name}' not found in config")
            
        plugin = self.plugins[plugin_name]
        
        print(f"\n{'='*60}")
        print(f"Running plugin: {plugin_name}")
        print(f"{'='*60}")
        
        # Run pipeline
        records = plugin.run_pipeline()
        
        # Get DataFrame output
        df = plugin.get_records_df()
        
        print(f"✓ {plugin_name} completed: {len(df)} records")
        
        return df
    
    def run_all_plugins(self) -> pd.DataFrame:
        """
        Chạy tất cả plugins và merge vào Feature Store
        
        Returns:
            Combined Feature Store DataFrame
        """
        all_dfs = []
        
        for plugin_name in self.plugins.keys():
            try:
                df = self.run_plugin(plugin_name)
                all_dfs.append(df)
            except Exception as e:
                print(f"✗ Error running {plugin_name}: {e}")
                # Continue với plugins khác
                continue
                
        if not all_dfs:
            print("Warning: No plugins completed successfully")
            return pd.DataFrame()
            
        # Concatenate all
        combined_df = pd.concat(all_dfs, ignore_index=True)
        
        # Pivot to wide format (feature per column)
        # hex_id, datetime_30min, weather_value, flood_value, event_value, ...
        feature_store = self._pivot_to_feature_store(combined_df)
        
        # Save to file
        self._save_feature_store(feature_store)
        
        return feature_store
    
    def _pivot_to_feature_store(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pivot long format → wide format
        
        Input:  hex_id, datetime_30min, factor_name, value
        Output: hex_id, datetime_30min, weather, flood, event, holiday, ...
        """
        # Aggregate: lấy max value nếu duplicate (có thể có nhiều events cùng lúc)
        agg_df = df.groupby(['hex_id', 'datetime_30min', 'factor_name'])['value'].max().reset_index()
        
        # Pivot
        pivoted = agg_df.pivot_table(
            index=['hex_id', 'datetime_30min'],
            columns='factor_name',
            values='value',
            aggfunc='first'
        ).reset_index()
        
        # Flatten column names
        pivoted.columns.name = None
        
        # Fill NaN với 0 (no impact)
        pivoted = pivoted.fillna(0)
        
        return pivoted
    
    def _save_feature_store(self, df: pd.DataFrame):
        """Save Feature Store to disk"""
        output_path = Path(self.feature_store_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Append to existing or create new
        if output_path.exists():
            existing = pd.read_parquet(output_path)
            # Merge: update existing, append new
            combined = pd.concat([existing, df]).drop_duplicates(
                subset=['hex_id', 'datetime_30min'],
                keep='last'
            )
            combined.to_parquet(output_path)
            print(f"✓ Updated Feature Store: {len(combined)} total records")
        else:
            df.to_parquet(output_path)
            print(f"✓ Created Feature Store: {len(df)} records")


# ============================================================
# AIRFLOW DAG INTEGRATION
# ============================================================

def create_airflow_dag():
    """
    Tạo Airflow DAG từ config
    """
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    from datetime import datetime, timedelta
    
    default_args = {
        'owner': 'data_team',
        'depends_on_past': False,
        'start_date': datetime(2024, 1, 1),
        'retries': 3,
        'retry_delay': timedelta(minutes=5),
    }
    
    with DAG(
        'factor_pipeline_dag',
        default_args=default_args,
        description='Extensible Factor Pipeline DAG',
        schedule_interval='@hourly',  # Master schedule
        catchup=False,
    ) as dag:
        
        # Load config
        def load_config(**context):
            from src.pipeline.registry import PluginRegistry
            
            # Auto-discover plugins
            PluginRegistry.auto_discover_plugins()
            
            # Load from config
            plugins = PluginRegistry.load_from_config('/config/factors.yaml')
            
            # Push to XCom for downstream tasks
            context['ti'].xcom_push(key='plugins', value=list(plugins.keys()))
            
            return plugins
        
        # Run each plugin as separate task
        def run_plugin_task(plugin_name: str):
            def _run(**context):
                orchestrator = PipelineOrchestrator(
                    config_path='/config/factors.yaml',
                    feature_store_path='/data/feature_store.parquet'
                )
                return orchestrator.run_plugin(plugin_name)
            return _run
        
        # Initial task: load config
        load_config_task = PythonOperator(
            task_id='load_config',
            python_callable=load_config,
        )
        
        # Dynamic task generation
        # Khi thêm plugin mới trong config → Task mới tự động được tạo
        plugin_tasks = {}
        
        for schedule, plugins in get_plugins_by_schedule().items():
            for plugin_name in plugins:
                task_id = f'run_{plugin_name}'
                
                task = PythonOperator(
                    task_id=task_id,
                    python_callable=run_plugin_task(plugin_name),
                    dag=dag,
                )
                
                plugin_tasks[plugin_name] = task
                load_config_task >> task
                
        # Final task: merge and validate
        def merge_task(**context):
            orchestrator = PipelineOrchestrator(
                config_path='/config/factors.yaml',
                feature_store_path='/data/feature_store.parquet'
            )
            return orchestrator.run_all_plugins()
        
        merge_task = PythonOperator(
            task_id='merge_to_feature_store',
            python_callable=merge_task,
            dag=dag,
        )
        
        # Dependencies
        for task in plugin_tasks.values():
            task >> merge_task


def get_plugins_by_schedule() -> Dict[str, List[str]]:
    """
    Group plugins by schedule for scheduling optimization.
    
    Returns:
        Dict mapping schedule → list of plugin names
        {
            "*/15 * * * *": ["flood"],
            "0 * * * *": ["weather"],
            "0 23 * * *": ["event"],
            "0 0 1 1 *": ["holiday"],
        }
    """
    # Load from config
    import yaml
    with open('/config/factors.yaml') as f:
        config = yaml.safe_load(f)
        
    schedule_groups = {}
    
    for factor in config.get('factors', []):
        schedule = factor.get('schedule', '0 * * * *')
        name = factor['name']
        
        if schedule not in schedule_groups:
            schedule_groups[schedule] = []
        schedule_groups[schedule].append(name)
        
    return schedule_groups
```

#### E. Config File (factors.yaml)

```yaml
# ============================================================
# FILE: config/factors.yaml
# THÊM FACTOR MỚI = THÊM DÒNG Ở ĐÂY, KHÔNG CẦN SỬA CODE!
# ============================================================

factors:
  # ---- WEATHER ----
  - name: weather
    type: api
    source: open_meteo
    schedule: "0 * * * *"           # Mỗi giờ
    enabled: true
    config:
      radius_km: 30
      base_url: "https://api.open-meteo.com/v1/forecast"
      timezone: "Asia/Ho_Chi_Minh"
      retry_count: 3
    
  # ---- FLOOD ----
  - name: flood
    type: rss
    source: news
    schedule: "*/15 * * * *"        # 15 phút/lần
    enabled: true
    config:
      rss_sources:
        - "https://vnexpress.net/rss/thoi-su.rss"
        - "https://vff.org.vn/feed/"
      geocoding_api: osmnames
      max_age_hours: 24
    
  # ---- EVENTS ----
  - name: event
    type: scraper
    source: ticketbox
    schedule: "0 23 * * *"          # Daily batch
    enabled: true
    config:
      ticketbox_api: "https://api.ticketbox.vn/v1/events"
      manual_csv_path: "/data/events_manual.csv"
    
  # ---- HOLIDAYS ----
  - name: holiday
    type: file
    source: static
    schedule: "0 0 1 1 *"           # Năm mới
    enabled: true
    config:
      holiday_file: "/data/holidays.csv"
      tet_year: 2024
    
  # ============================================================
  # THÊM FACTOR MỚI Ở ĐÂY - KHÔNG CẦN SỬA CODE KHÁC!
  # ============================================================
  
  # Ví dụ: Flash Sale (AOE - Affect-Of-Offer)
  - name: aoe_sale
    type: api
    source: shopee_api
    schedule: "0 0 * * 5"           # Thứ 6 hàng tuần
    enabled: true
    config:
      api_endpoint: "https://api.shopee.vn/flash_sales"
      impact_radius_km: 5
    
  # Ví dụ: Concert từ TikTok/Ticketbox
  - name: concert
    type: api
    source: ticketbox
    schedule: "0 23 * * *"
    enabled: false                   # Disable until ready
    config:
      event_type_filter: ["concert", "music_festival"]
      impact_multiplier: 1.2
    
  # Ví dụ: Sport Match
  - name: sport_match
    type: api
    source: vff_api
    schedule: "0 12 * * *"          # Check trưa hàng ngày
    enabled: false
    config:
      league_filter: ["V-League", "National Cup"]
    
  # Ví dụ: Air Quality (AQI > 100 = Stay Home)
  - name: pollution
    type: api
    source: waqi
    schedule: "0 * * * *"
    enabled: false
    config:
      city: "Ho_Chi_Minh_City"
      threshold_aqi: 100
```

---

## 3. Đặc điểm Thiết kế Mới (Extensible)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     ĐẶC ĐIỂM THIẾT KẾ MỚI                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  1. Plugin Registry + Factory Pattern                                      │ │
│  ├─────────────────────────────────────────────────────────────────────────────┤ │
│  │  • PluginRegistry.load_from_config()                                       │ │
│  │  • Config driven, no code changes                                          │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  2. BaseFactorPlugin Interface Chuẩn                                      │ │
│  ├─────────────────────────────────────────────────────────────────────────────┤ │
│  │  class WeatherPlugin(BaseFactorPlugin)                                     │ │
│  │  class FloodPlugin(BaseFactorPlugin)                                       │ │
│  │  class EventPlugin(BaseFactorPlugin)                                       │ │
│  │  class HolidayPlugin(BaseFactorPlugin)                                     │ │
│  │  → Cùng interface, dễ maintain                                            │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  3. Thêm Factor Mới = Thêm File + Dòng Config                             │ │
│  ├─────────────────────────────────────────────────────────────────────────────┤ │
│  │  Bước 1: Tạo new_factor_plugin.py                                         │ │
│  │  Bước 2: Thêm @PluginRegistry.register("new_factor")                      │ │
│  │  Bước 3: Thêm dòng trong factors.yaml                                     │ │
│  │  → Done! Không cần sửa orchestrator                                        │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  4. Dynamic Schema (Pivot Table)                                           │ │
│  ├─────────────────────────────────────────────────────────────────────────────┤ │
│  │  • Columns tự động thêm từ factor_name                                    │ │
│  │  • Không cần schema migration                                              │ │
│  │  • Feature Store tự mở rộng khi thêm factor mới                           │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  5. Test Dễ Dàng                                                          │ │
│  ├─────────────────────────────────────────────────────────────────────────────┤ │
│  │  • Mock BaseFactorPlugin interface                                          │ │
│  │  • Swap implementation dễ dàng                                            │ │
│  │  • Mock tập trung, không phải mock từng source riêng biệt                 │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Minh họa: Thêm Factor Mới (Ví dụ: Air Quality)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│              HƯỚNG DẪN THÊM FACTOR MỚI (Air Quality - AQI)                       │
│                                                                                 │
│  Bước 1: Tạo file plugin mới                                                     │
│  ─────────────────────────────────                                              │
│                                                                                 │
│  FILE: src/pipeline/plugins/pollution_plugin.py                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                 │
│  import pandas as pd                                                            │
│  from datetime import datetime                                                  │
│  import h3                                                                      │
│  from ..base import BaseFactorPlugin, FactorType                               │
│  from ..registry import PluginRegistry  # ← IMPORT decorator                    │
│                                                                                 │
│  @PluginRegistry.register("pollution")  # ← ĐĂNG KÝ VÀO REGISTRY               │
│  class PollutionFactorPlugin(BaseFactorPlugin):                                 │
│      """Plugin thu thập chất lượng không khí từ WAQI API"""                      │
│                                                                                 │
│      factor_type = FactorType.POLLUTION   # ← Thêm enum mới nếu cần            │
│      factor_name = "pollution"                                                  │
│      schedule = "0 * * * *"                  # Mỗi giờ                         │
│                                                                                  │
│      def fetch(self) -> pd.DataFrame:                                           │
│          # Implement API call → return DataFrame                                │
│          ...                                                                    │
│                                                                                  │
│      def transform(self, df: pd.DataFrame) -> pd.DataFrame:                    │
│          # AQI > 150 = SEVERE, > 100 = HIGH, etc.                               │
│          df['value'] = df['aqi'].apply(self._aqi_to_impact)                     │
│          return df                                                              │
│                                                                                  │
│      def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:                  │
│          # WAQI đã có lat/lng → convert thẳng sang H3                            │
│          df['hex_id'] = df.apply(lambda r: h3.latlng_to_cell(r['lat'], r['lng'], 9), axis=1) │
│          return df                                                              │
│                                                                                  │
│  ########################################################################        │
│                                                                                  │
│  Bước 2: Thêm dòng vào factors.yaml                                              │
│  ─────────────────────────────────                                              │
│                                                                                  │
│  FILE: config/factors.yaml                                                       │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  factors:                                                                        │
│    - name: weather                                                              │
│      ... (existing)                                                             │
│                                                                                  │
│  # THÊM MỚI:                                                                    │
│    - name: pollution                                                           │
│      type: api                                                                 │
│      source: waqi                                                               │
│      schedule: "0 * * * *"           # Mỗi giờ                                 │
│      enabled: true                                                               │
│      config:                                                                    │
│        city: "Ho_Chi_Minh_City"                                                 │
│        threshold_aqi: 100                                                       │
│        api_key: "${WAQI_API_KEY}"  # Environment variable                       │
│                                                                                  │
│  ########################################################################        │
│                                                                                  │
│  Bước 3: Build và deploy (KHÔNG CẦN SỬA GÌ KHÁC!)                                │
│  ─────────────────────────────────                                              │
│                                                                                  │
│  $ python -m src.pipeline.orchestrator                                           │
│                                                                                  │
│  Output:                                                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐     │
│  │  Running plugin: weather                                               │     │
│  │  ✓ weather completed: 4500 records                                     │     │
│  │  Running plugin: flood                                                 │     │
│  │  ✓ flood completed: 12 records                                         │     │
│  │  Running plugin: event                                                 │     │
│  │  ✓ event completed: 28 records                                         │     │
│  │  Running plugin: holiday                                                │     │
│  │  ✓ holiday completed: 2 records                                        │     │
│  │  Running plugin: pollution              ← TỰ ĐỘNG ĐƯỢC DISCOVER!        │     │
│  │  ✓ pollution completed: 156 records     ← KHÔNG CẦN SỬA ORCHESTRATOR   │     │
│  └────────────────────────────────────────────────────────────────────────┘     │
│                                                                                  │
│  Feature Store output:                                                           │
│  ┌────────────┬─────────────────┬────────┬────────┬────────┬─────────┐          │
│  │ hex_id     │ datetime_30min  │ weather│ flood  │ event  │pollution│          │
│  ├────────────┼─────────────────┼────────┼────────┼────────┼─────────┤          │
│  │ 8a2a100... │2024-08-15 14:00 │  0.3   │  0.0   │  0.0   │   0.0   │          │
│  │ 8a2a100... │2024-08-15 14:00 │  0.0   │  0.85  │  0.0   │   0.0   │          │
│  │ 8a2a100... │2024-08-15 14:00 │  0.0   │  0.0   │  0.0   │   0.75  │  ← NEW!  │
│  └────────────┴─────────────────┴────────┴────────┴────────┴─────────┘          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Tổng kết: Design Principles

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    5 NGUYÊN TẮC THIẾT KẾ EXTENSIBLE PIPELINE                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. DEPENDENCY INVERSION (Interface thay vì Implementation)                      │
│     ─────────────────────────────────────────────────                           │
│     BaseFactorPlugin defines contract                                            │
│     Specific plugins implement contract                                         │
│     Orchestrator depends on abstraction, not concrete classes                   │
│                                                                                 │
│                              ┌───────────────┐                                   │
│                              │ Orchestrator  │                                   │
│                              └───────┬───────┘                                   │
│                                      │ depends on                                 │
│                                      ▼                                           │
│                          ┌───────────────────────┐                              │
│                          │  BaseFactorPlugin     │  ← ABSTRACTION                │
│                          │  (Abstract Interface) │                              │
│                          └───────────────────────┘                              │
│                                      ▲                                          │
│           ┌──────────────────────────┼──────────────────────────┐               │
│           │                          │                          │               │
│           ▼                          ▼                          ▼               │
│  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐         │
│  │ WeatherPlugin   │      │ FloodPlugin     │      │ PollutionPlugin │         │
│  └─────────────────┘      └─────────────────┘      └─────────────────┘         │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                 │
│  2. OPEN-CLOSED PRINCIPLE (Open for extension, Closed for modification)          │
│     ─────────────────────────────────────────────────                          │
│     • Thêm feature = Thêm file mới, không sửa file cũ                           │
│     • Config-driven thay vì hard-coded                                         │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  3. SINGLE RESPONSIBILITY (Mỗi plugin = 1 factor)                                │
│     ─────────────────────────────────                                         │
│     • Plugin này chỉ lo weather, plugin kia chỉ lo flood                        │
│     • Orchestrator chỉ điều phối, không xử lý logic                             │
│     • Registry chỉ quản lý registration                                        │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  4. CONFIGURATION OVER CODE                                                     │
│     ────────────────────────                                                   │
│     • Schedule, API keys, thresholds → YAML config                               │
│     • Code chỉ định nghĩa behavior, config chỉ định nghĩa parameters            │
│     • Environment variables cho secrets                                          │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  5. STANDARDIZED DATA CONTRACT (FactorRecord)                                    │
│     ─────────────────────────────────                                           │
│     • Tất cả plugins trả về cùng format                                         │
│     • Feature Store pivot tự động                                              │
│     • Schema mở rộng không cần migration                                        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Checklist khi review thiết kế của bạn

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        CHECKLIST REVIEW THIẾT KẾ CỦA BẠN                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ✅ Phân chia module rõ ràng (Ingestion → Transform → Storage → Orchestration) │
│  ✅ Feature Store PK (hex_id, datetime_30min) - Good!                           │
│  ✅ Schedule tiers phù hợp với data freshness requirements                     │
│                                                                                 │
│  ⚠️ CẦN CẢI THIỆN:                                                              │
│  ────────────────                                                              │
│  □ Plugin pattern thay vì if/elif chain                                        │
│  □ Abstract base class cho các connectors                                       │
│  □ Config-driven thay vì hard-coded schedule/logic                             │
│  □ Standardized data contract (FactorRecord)                                   │
│  □ Auto-discovery mechanism cho plugins                                        │
│  □ Dynamic schema trong Feature Store                                          │
│                                                                                 │
│  📋 ƯU TIÊN SỬA ĐỔI:                                                            │
│  ─────────────────                                                             │
│  1. [CAO] Thêm PluginRegistry + BaseFactorPlugin                              │
│     → Cho phép thêm factor mới mà không sửa orchestrator                        │
│                                                                                 │
│  2. [CAO] Tái cấu trúc Flood News Parser thành plugin                          │
│     → Phần phức tạp nhất, cần cleanest code                                    │
│                                                                                 │
│  3. [TRUNG] Externalize config sang YAML                                       │
│     → Giảm hard-coded, dễ deploy environments khác nhau                       │
│                                                                                 │
│  4. [THẤP] Thêm Airflow DAG generation tự động                                │
│     → Khi config thay đổi → DAG tự update                                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

**Tóm lại**: Thiết kế của bạn đã đi đúng hướng về mặt cấu trúc module. Vấn đề chính là **tính extensibility**. Với Plugin Registry Pattern + Config-driven approach, bạn có thể thêm bất kỳ factor mới nào (AOE Sale, Concert, Air Quality, Traffic, News, v.v.) chỉ bằng cách:

1. Tạo 1 file plugin mới (`xxx_plugin.py`)
2. Thêm 1 dòng trong `factors.yaml`

**Không cần sửa orchestrator, không cần sửa feature store schema, không cần sửa test cases cũ.**