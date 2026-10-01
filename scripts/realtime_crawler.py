"""
Realtime Weather Crawler - Production Version
==========================================

Script thu thap du lieu real-time cho Demand Spike Detector vung Ha Noi.
Su dung cac API that:
- OpenWeatherMap (OWM) - thoi tiet
- VisualCrossing (VCW) - thoi tiet (ho tro nhieu API keys)
- NCHMF - canh bao bao
- HSDC - diem ngap (adaptive polling)

Tinh nang:
- Ensemble 4 nguon su dung WeatherEnsembleAggregator
- KDTree broadcast thoi tiet cho H3 Res 8
- Adaptive Polling HSDC
- Xoay vong API Keys VCW khi bi rate limit
- Luu vao Parquet theo partition (00-05, 06-11, 12-17, 18-23)
- Mutex lock de tranh chay song song

Chay 1-shot moi 15 phut (Task Scheduler/Cron goi script nay).

Usage:
    python scripts/realtime_crawler.py              # Chay tat ca cac buoc
    python scripts/realtime_crawler.py --step a1    # Chi chay buoc A.1
    python scripts/realtime_crawler.py --step a2    # Chi chay buoc A.2
    python scripts/realtime_crawler.py --step all   # Chay tat ca (mac dinh)
"""

import os
import sys
import h3
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from scipy.spatial import KDTree
from typing import Dict, List, Tuple, Set, Optional, Any
import logging
import requests
import json
from itertools import cycle
from threading import Lock
import argparse
import sys

# File locking - platform specific
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    # Windows alternative: use msvcrt
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False

# Load .env file
from dotenv import load_dotenv
load_dotenv()

# Import Ensemble
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from pipeline.weather_ensemble import WeatherEnsembleAggregator, EnsembleConfig, SourceStatus

# Setup console logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# PHAN 1: HANG SO VA CAU HINH
# =============================================================================

# 6 Anchor Points cho Ha Noi
ANCHOR_POINTS = [
    {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
    {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
    {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
    {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
    {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
    {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
]

# Polygon bao phu Ha Noi
HANOI_POLYGON = h3.LatLngPoly([
    (21.1483, 105.5563),
    (21.1483, 106.0200),
    (20.8528, 106.0200),
    (20.8528, 105.5563),
    (21.1483, 105.5563),
])

# Duong dan output - use absolute path from project root
import os
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
OUTPUT_DIR = PROJECT_ROOT / "data" / "realtime_lake"
H3_RESOLUTION = 8

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# File lock path for mutex
LOCK_FILE = OUTPUT_DIR / ".crawler.lock"


def acquire_lock(timeout: int = 5) -> Optional[Any]:
    """
    Acquire exclusive lock to prevent parallel execution.
    Returns lock file handle if successful, None if lock cannot be acquired.

    Uses fcntl on Unix/Linux/Mac, msvcrt on Windows.
    """
    lock_path = str(LOCK_FILE)

    try:
        lock_handle = open(lock_path, 'w')

        if HAS_FCNTL:
            # Unix/Linux/Mac
            start_time = datetime.now()
            while True:
                try:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_handle.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
                    lock_handle.flush()
                    logger.info(f"[MUTEX] Acquired lock (fcntl): {lock_path}")
                    return lock_handle
                except (IOError, OSError):
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= timeout:
                        lock_handle.close()
                        logger.error(f"[MUTEX] Cannot acquire lock after {timeout}s - another instance is running")
                        return None
                    import time
                    time.sleep(0.5)

        elif HAS_MSVCRT:
            # Windows
            start_time = datetime.now()
            while True:
                try:
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
                    lock_handle.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
                    lock_handle.flush()
                    logger.info(f"[MUTEX] Acquired lock (msvcrt): {lock_path}")
                    return lock_handle
                except (IOError, OSError):
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= timeout:
                        lock_handle.close()
                        logger.error(f"[MUTEX] Cannot acquire lock after {timeout}s - another instance is running")
                        return None
                    import time
                    time.sleep(0.5)
        else:
            # Fallback: no locking (just log warning)
            logger.warning("[MUTEX] No file locking available on this platform")
            lock_handle.close()
            return None

    except Exception as e:
        logger.error(f"[MUTEX] Error acquiring lock: {e}")
        return None


def release_lock(lock_handle: Any):
    """Release the exclusive lock."""
    if lock_handle:
        try:
            if HAS_FCNTL:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            elif HAS_MSVCRT:
                try:
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except:
                    pass
            lock_handle.close()
            # Remove lock file
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
            logger.info("[MUTEX] Released lock")
        except Exception as e:
            logger.warning(f"[MUTEX] Error releasing lock: {e}")

# Add file handler to logger
LOG_FILE = OUTPUT_DIR / "crawler_cron.log"
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# API Endpoints
OWM_BASE_URL = "https://api.openweathermap.org/data/2.5"
VCW_BASE_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
HSDC_BASE_URL = "https://thoatnuochanoi.vn"

# HTTP Session
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/html',
})


# =============================================================================
# PHAN 2: API KEY ROTATOR (HO TRO 9+ KEYS)
# =============================================================================

class APIKeyRotator:
    """
    Rotator cho cac API Keys.

    Features:
    - Ho tro nhieu API keys
    - Tu dong xoay vong khi gap rate limit
    - Danh dau key nao bi rate limit de tam thoi bo qua
    - Fallback sang OWM khi tat ca VCW keys deu het
    """

    def __init__(self, source_name: str, env_prefix: str):
        """
        Khoi tao Rotator.

        Args:
            source_name: Ten nguon (VD: 'VCW')
            env_prefix: Prefix cua bien moi truong (VD: 'VISUALCROSSING_API_KEY')
        """
        self.source_name = source_name
        self.env_prefix = env_prefix

        # Load tat ca API keys
        self.api_keys: List[Tuple[str, str]] = []  # (key, status)
        self._load_keys()

        # Cyclic iterator cho vong lap
        self._key_cycle: Optional[cycle] = None
        self._current_key: Optional[str] = None
        self._lock = Lock()

        # Statistics
        self.stats = {
            'total_keys': len(self.api_keys),
            'available_keys': len([k for k in self.api_keys if k[1] == 'active']),
            'rate_limited_keys': 0,
            'failed_keys': 0,
        }

        if self.api_keys:
            self._reset_cycle()
            self._current_key = self._key_cycle.__next__()

    def _load_keys(self):
        """Load tat ca API keys tu environment."""
        # Key chinh (khong co so)
        main_key = os.getenv(f'{self.env_prefix}', '').strip()
        if main_key:
            self.api_keys.append((main_key, 'active'))

        # Key phu (co so 1-9)
        for i in range(1, 10):
            key = os.getenv(f'{self.env_prefix}_{i}', '').strip()
            if key:
                self.api_keys.append((key, 'active'))

        logger.info(f"[{self.source_name}] Loaded {len(self.api_keys)} API keys")

    def _reset_cycle(self):
        """Reset cyclic iterator voi cac key con active."""
        active_keys = [k for k, s in self.api_keys if s == 'active']
        if active_keys:
            self._key_cycle = cycle(active_keys)
        else:
            self._key_cycle = None

    def get_current_key(self) -> Optional[str]:
        """Lay API key hien tai."""
        return self._current_key

    def mark_rate_limited(self, key: str):
        """Danh dau key bi rate limit."""
        with self._lock:
            for i, (k, status) in enumerate(self.api_keys):
                if k == key:
                    self.api_keys[i] = (k, 'rate_limited')
                    logger.warning(f"[{self.source_name}] Key marked as RATE LIMITED: {key[:8]}...")
                    self.stats['rate_limited_keys'] += 1
                    break

            # Neu key hien tai bi rate limit, chuyen sang key tiep theo
            if self._current_key == key:
                self._rotate()

    def mark_failed(self, key: str):
        """Danh dau key bi loi."""
        with self._lock:
            for i, (k, status) in enumerate(self.api_keys):
                if k == key:
                    self.api_keys[i] = (k, 'failed')
                    logger.warning(f"[{self.source_name}] Key marked as FAILED: {key[:8]}...")
                    self.stats['failed_keys'] += 1
                    break

            if self._current_key == key:
                self._rotate()

    def _rotate(self):
        """Xoay sang key tiep theo."""
        if self._key_cycle:
            try:
                self._current_key = self._key_cycle.__next__()
                logger.info(f"[{self.source_name}] Rotated to key: {self._current_key[:8]}...")
            except StopIteration:
                self._reset_cycle()
                if self._key_cycle:
                    self._current_key = self._key_cycle.__next__()
                else:
                    self._current_key = None

    def get_next_key(self) -> Optional[str]:
        """Lay key tiep theo (dung cho goi API tiep)."""
        with self._lock:
            self._rotate()
            return self._current_key

    def has_keys(self) -> bool:
        """Kiem tra con key nao khong."""
        return len([k for k, s in self.api_keys if s == 'active']) > 0

    def reset_rate_limits(self):
        """Reset lai tat ca rate limits (goi sau 1 khoang thoi gian)."""
        with self._lock:
            for i, (k, status) in enumerate(self.api_keys):
                if status in ['rate_limited', 'failed']:
                    self.api_keys[i] = (k, 'active')
                    logger.info(f"[{self.source_name}] Reset key: {k[:8]}...")

            self.stats['rate_limited_keys'] = 0
            self.stats['failed_keys'] = 0
            self._reset_cycle()
            if self._key_cycle:
                self._current_key = self._key_cycle.__next__()

    def get_stats(self) -> Dict:
        """Lay thong ke."""
        active = len([k for k, s in self.api_keys if s == 'active'])
        rate_limited = len([k for k, s in self.api_keys if s == 'rate_limited'])
        failed = len([k for k, s in self.api_keys if s == 'failed'])

        return {
            'total': len(self.api_keys),
            'active': active,
            'rate_limited': rate_limited,
            'failed': failed,
            'current_key': self._current_key[:8] + '...' if self._current_key else None,
        }


# =============================================================================
# PHAN 3: KHOI TAO API KEY ROTATORS
# =============================================================================

# OWM - Mot key
OWM_API_KEY = os.getenv('OPENWEATHERMAP_API_KEY', '').strip()
if not OWM_API_KEY:
    logger.warning("OPENWEATHERMAP_API_KEY khong ton tai trong .env")

# VCW - Nhieu keys
vcw_rotator = APIKeyRotator('VCW', 'VISUALCROSSING_API_KEY')

logger.info(f"[VCW] API Key Stats: {vcw_rotator.get_stats()}")


# =============================================================================
# PHAN 4: HAM GOI API THAT
# =============================================================================

def fetch_owm_weather(lat: float, lon: float, api_key: str) -> Optional[Dict]:
    """
    Lay du lieu thoi tiet tu OpenWeatherMap API.
    """
    try:
        url = f"{OWM_BASE_URL}/weather"
        params = {
            'lat': lat,
            'lon': lon,
            'appid': api_key,
            'units': 'metric',
        }

        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        weather = data.get('weather', [{}])[0]
        weather_code = weather.get('id', 800)
        weather_main = weather.get('main', '')
        weather_desc = weather.get('description', '')

        # Rainfall
        rain = data.get('rain', {})
        precip = rain.get('1h', rain.get('3h', 0)) or 0
        pop = data.get('pop', 0) or 0

        # Visibility
        vis_m = data.get('visibility')
        visibility_km = (vis_m / 1000) if vis_m else 10

        # Wind direction
        wind_deg = data.get('wind', {}).get('deg', 0) or 0

        impact = _owm_code_to_impact(weather_code)

        return {
            'temp_c': data.get('main', {}).get('temp'),
            'feels_like': data.get('main', {}).get('feels_like'),
            'humidity_pct': data.get('main', {}).get('humidity'),
            'pressure': data.get('main', {}).get('pressure'),
            'wind_speed': data.get('wind', {}).get('speed', 0) or 0,
            'wind_dir': _deg_to_cardinal(wind_deg),
            'cloud_cover': data.get('clouds', {}).get('all', 0) or 0,
            'visibility': visibility_km,
            'weather_code': str(weather_code),
            'weather_main': weather_main,
            'weather_conditions': weather_desc,
            'precip': precip,
            'precip_prob': pop * 100,
            'weather_impact': impact,
            'source': 'OWM',
        }

    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 429:
            logger.warning(f"[OWM] Rate limited for ({lat}, {lon})")
        else:
            logger.warning(f"[OWM] HTTP Error: {e}")
        return None
    except requests.exceptions.Timeout:
        logger.warning(f"[OWM] Timeout for ({lat}, {lon})")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"[OWM] Request Error: {e}")
        return None
    except Exception as e:
        logger.error(f"[OWM] Unexpected error: {e}")
        return None


def fetch_vcw_weather_realtime(lat: float, lon: float) -> Optional[Dict]:
    """
    Lay du lieu thoi tiet tu VisualCrossing API voi rotation key.

    Su dung APIKeyRotator de xoay vong qua cac keys khi gap rate limit.
    Fallback sang OWM neu tat ca keys deu loi.

    Retry logic:
    - 3 retries voi delay khi gap DNS/network error
    - Xoay key khi gap rate limit
    """
    max_retries = vcw_rotator.stats['available_keys'] if vcw_rotator.stats['available_keys'] > 0 else 1
    tried_keys = set()
    network_retries = 0
    max_network_retries = 3

    while network_retries < max_network_retries:
        for attempt in range(max_retries):
            api_key = vcw_rotator.get_current_key()

            if not api_key:
                logger.warning(f"[VCW] No more API keys available")
                break

            if api_key in tried_keys:
                vcw_rotator.get_next_key()
                continue

            tried_keys.add(api_key)

            try:
                result = _fetch_vcw_single(api_key, lat, lon)
                if result:
                    return result
                else:
                    vcw_rotator.get_next_key()

            except Exception as e:
                error_str = str(e).lower()

                # Network errors - retry
                if 'name resolution' in error_str or 'resolve' in error_str or \
                   'connection' in error_str or 'timeout' in error_str or \
                   'network' in error_str:
                    logger.warning(f"[VCW] Network error ({api_key[:8]}...): {e}")
                    network_retries += 1
                    if network_retries < max_network_retries:
                        import time
                        delay = 2 ** network_retries  # Exponential backoff
                        logger.info(f"[VCW] Retrying in {delay}s... (attempt {network_retries}/{max_network_retries})")
                        time.sleep(delay)
                    continue

                # Rate limit - rotate key
                if '429' in error_str or 'rate limit' in error_str or 'too many' in error_str:
                    vcw_rotator.mark_rate_limited(api_key)
                    vcw_rotator.get_next_key()
                    continue

                # Other errors - mark failed and continue
                vcw_rotator.mark_failed(api_key)
                vcw_rotator.get_next_key()

        # Neu da thu tat ca keys, break
        if len(tried_keys) >= max_retries:
            break

        # Reset tried keys for network retry
        if network_retries < max_network_retries:
            tried_keys = set()

    logger.warning(f"[VCW] All keys exhausted after {network_retries} network retries, will fallback to OWM")
    return None


def fetch_vcw_weather_with_rotation(lat: float, lon: float) -> Optional[Dict]:
    """
    Lay du lieu thoi tiet tu VisualCrossing API voi key rotation.

    Thu tu:
    1. Thu key hien tai
    2. Neu rate limit -> thu key tiep theo
    3. Neu het keys -> fallback ve OWM
    """
    return fetch_vcw_weather_realtime(lat, lon)


def _fetch_vcw_single(api_key: str, lat: float, lon: float) -> Optional[Dict]:
    """
    Lay du lieu tu VCW voi mot API key cu the.
    """
    try:
        url = f"{VCW_BASE_URL}/{lat},{lon}/today"
        params = {
            'unitGroup': 'metric',
            'include': 'current',
            'key': api_key,
            'contentType': 'json',
        }

        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data.get('currentConditions', {})
        conditions = current.get('conditions', '').lower()

        # Handle None values
        precip_val = current.get('precip')
        precip = precip_val if precip_val is not None else 0
        precip_prob = current.get('precipprob', 0) or 0
        visibility = current.get('visibility', 10) or 10
        wind_dir = str(current.get('winddir', ''))
        cloud_cover = current.get('cloudcover', 0) or 0

        return {
            'temp_c': current.get('temp'),
            'feels_like': current.get('feelslike'),
            'humidity_pct': current.get('humidity'),
            'pressure': current.get('pressure'),
            'wind_speed': current.get('windspeed'),
            'wind_dir': wind_dir,
            'cloud_cover': cloud_cover,
            'visibility': visibility,
            'precip': precip,
            'precip_prob': precip_prob,
            'weather_code': conditions.replace(' ', '_'),
            'weather_conditions': current.get('conditions', ''),
            'weather_impact': _vcw_conditions_to_impact(conditions),
            'source': 'VCW',
        }

    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 429:
            logger.warning(f"[VCW] Rate limited for key: {api_key[:8]}...")
            raise Exception("429 Rate Limit")
        else:
            logger.warning(f"[VCW] HTTP Error: {e}")
            return None
    except requests.exceptions.Timeout:
        logger.warning(f"[VCW] Timeout for ({lat}, {lon})")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"[VCW] Request Error: {e}")
        return None
    except Exception as e:
        logger.error(f"[VCW] Unexpected error: {e}")
        return None


def fetch_nchmf_storm_warning() -> Tuple[bool, int]:
    """
    Lay canh bao bao tu NCHMF.
    """
    try:
        url = "https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html"

        response = session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = 'utf-8'

        text = response.text.lower()

        # Check for storm warnings
        storm_keywords = ['cảnh báo', 'bão', 'giông', 'lốc', 'áp thấp nhiệt đới']
        no_warning_keywords = ['không có cảnh báo', 'khong co canh bao', 'không cảnh báo']

        # Check negation first
        for neg in no_warning_keywords:
            if neg in text:
                return False, 0

        # Check positive matches
        for keyword in storm_keywords:
            if keyword in text:
                logger.warning(f"[NCHMF] Storm warning detected: {keyword}")
                return True, 1

        return False, 0

    except requests.exceptions.RequestException as e:
        logger.warning(f"[NCHMF] Error fetching storm warning: {e}")
        return False, 0
    except Exception as e:
        logger.error(f"[NCHMF] Unexpected error: {e}")
        return False, 0


def fetch_hsdc_full_data() -> Optional[Dict]:
    """
    Lay TOAN BO du lieu tu HSDC API (62 tram rainfall + flood).
    Returns:
        Dict voi keys:
        - 'stations': list cac tram (id, lat, lon, ten)
        - 'rainfall': dict {station_id: {LuongMua_HT, LuongMua_1h, LuongMua_24h}}
        - 'flood_points': list (lat, lon) cua cac tram co luong mua > 0
    Returns None neu API loi.
    """
    try:
        url = f"{HSDC_BASE_URL}/luongmua/api/getAllData"

        response = session.post(url, timeout=15)
        response.raise_for_status()

        data = response.json()

        if data.get('code') != 1:
            logger.warning("[HSDC] API returned error code")
            return None

        # Parse station data
        stations_str = data.get('data', {}).get('tram', '[]')
        stations = json.loads(stations_str) if stations_str else []

        rainfall_str = data.get('data', {}).get('data', '[]')
        rainfall_data = json.loads(rainfall_str) if rainfall_str else []

        station_lookup = {s['Id']: s for s in stations}

        # Build rainfall dict
        rainfall_by_station = {}
        flood_points = []

        for record in rainfall_data:
            station_id = record.get('TramId')
            rainfall_ht = record.get('LuongMua_HT', 0) or 0

            rainfall_by_station[station_id] = {
                'LuongMua_HT': rainfall_ht,
                'LuongMua_1h': record.get('LuongMua_1h', 0) or 0,
                'LuongMua_24h': record.get('LuongMua_24h', 0) or 0,
            }

            if rainfall_ht > 0:
                station = station_lookup.get(station_id, {})
                lat = station.get('Lat')
                lon = station.get('Lng')
                if lat and lon:
                    flood_points.append((float(lat), float(lon)))

        logger.info(f"[HSDC] Loaded {len(stations)} stations, {len(rainfall_by_station)} rainfall records, {len(flood_points)} flood points")

        return {
            'stations': stations,
            'rainfall': rainfall_by_station,
            'station_lookup': station_lookup,
            'flood_points': flood_points,
        }

    except requests.exceptions.RequestException as e:
        logger.warning(f"[HSDC] Error fetching data: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"[HSDC] JSON parse error: {e}")
        return None
    except Exception as e:
        logger.error(f"[HSDC] Unexpected error: {e}")
        return None


def fetch_hsdc_flood_points() -> List[Tuple[float, float]]:
    """Backward-compatible wrapper."""
    result = fetch_hsdc_full_data()
    if result:
        return result['flood_points']
    return []


# =============================================================================
# PHAN 5: HAM CHUYEN DOI TRANG THAI
# =============================================================================

def _owm_code_to_impact(code: int) -> float:
    """Map OWM weather code to impact (0-1)."""
    if 200 <= code < 300:
        return 0.9
    elif 300 <= code < 400:
        return 0.3
    elif 500 <= code < 600:
        if code == 500:
            return 0.3
        elif code == 501:
            return 0.5
        elif code in [502, 503, 504]:
            return 0.8
        return 0.5
    elif 600 <= code < 700:
        return 0.4
    elif 700 <= code < 800:
        return 0.2
    elif code == 800:
        return 0.0
    return 0.0


def _vcw_conditions_to_impact(conditions: str) -> float:
    """Map VCW conditions to impact (0-1)."""
    conditions = conditions.lower()

    if 'thunder' in conditions:
        return 0.9
    elif 'rain' in conditions:
        if 'heavy' in conditions:
            return 0.9
        elif 'light' in conditions:
            return 0.3
        return 0.5
    elif 'drizzle' in conditions:
        return 0.3
    elif 'snow' in conditions:
        return 0.4
    elif 'fog' in conditions or 'mist' in conditions:
        return 0.2
    elif 'cloud' in conditions:
        return 0.1
    return 0.0


def _deg_to_cardinal(deg: float) -> str:
    """Convert wind degrees to cardinal direction."""
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    idx = round(deg / 45) % 8
    return directions[idx]


# =============================================================================
# PHAN 6: CAC BUOC CHINH
# =============================================================================

def step_a1_storm_warning() -> Tuple[bool, int]:
    """BUOC A.1: Lay canh bao bao tu NCHMF."""
    logger.info("\n" + "="*60)
    logger.info("BUOC A.1: Lay canh bao bao (NCHMF)")
    logger.info("="*60)

    has_storm, storm_warning = fetch_nchmf_storm_warning()
    logger.info(f"  -> storm_warning = {storm_warning} ({'CO BAO' if has_storm else 'BINH THUONG'})")

    return has_storm, storm_warning


def step_a2_generate_h3_hexes() -> List[str]:
    """BUOC A.2: Sinh danh sach H3 Res 8 cho Ha Noi."""
    logger.info("\n" + "="*60)
    logger.info("BUOC A.2: Sinh danh sach H3 Res 8 cho Ha Noi")
    logger.info("="*60)

    hex_ids = list(h3.polygon_to_cells(HANOI_POLYGON, H3_RESOLUTION))
    logger.info(f"  -> Tong so Hex: {len(hex_ids)}")

    return hex_ids


def step_a3_fetch_anchor_weather_ensemble(aggregator: WeatherEnsembleAggregator) -> Tuple[List[Tuple[float, float]], List[Dict]]:
    """
    BUOC A.3: Lay thoi tiet 6 Anchor Points + ENSEMBLE.

    Thu tu uu tien:
    1. VCW (nhieu keys, xoay vong)
    2. OWM (fallback)
    """
    logger.info("\n" + "="*60)
    logger.info("BUOC A.3: Lay thoi tiet + ENSEMBLE cho 6 Anchor Points")
    logger.info("="*60)

    # Log VCW key stats
    vcw_stats = vcw_rotator.get_stats()
    logger.info(f"  [VCW] Available keys: {vcw_stats['active']}/{vcw_stats['total']}")
    logger.info(f"  [VCW] Rate limited: {vcw_stats['rate_limited']}, Failed: {vcw_stats['failed']}")

    anchor_coords = []
    weather_stations = []

    for anchor in ANCHOR_POINTS:
        lat, lon = anchor["lat"], anchor["lon"]
        name = anchor["name"]

        logger.info(f"\n  [{name}] ({lat}, {lon})")

        # Lay du lieu tu VCW voi rotation
        vcw_data = fetch_vcw_weather_with_rotation(lat, lon)

        # Lay du lieu tu OWM
        owm_data = None
        if OWM_API_KEY:
            owm_data = fetch_owm_weather(lat, lon, OWM_API_KEY)

        # Fallback neu ca 2 deu that bai
        if not owm_data and not vcw_data:
            logger.warning(f"  -> Both OWM and VCW failed, using fallback")
            weather = _create_fallback_weather(name)
        else:
            weather = _compute_ensemble_for_station(
                name, lat, lon, owm_data, vcw_data, aggregator
            )

        anchor_coords.append((lat, lon))
        weather_stations.append(weather)

    logger.info(f"\n  -> Fetched + Ensembled weather for {len(weather_stations)} stations")

    return anchor_coords, weather_stations


def _compute_ensemble_for_station(
    name: str,
    lat: float,
    lon: float,
    owm_data: Optional[Dict],
    vcw_data: Optional[Dict],
    aggregator: WeatherEnsembleAggregator
) -> Dict:
    """Tinh ensemble cho mot station."""

    # Update source status
    if owm_data:
        aggregator.update_source_status('OWM', SourceStatus.HEALTHY)
    else:
        aggregator.update_source_status('OWM', SourceStatus.FAILED)

    if vcw_data:
        aggregator.update_source_status('VCW', SourceStatus.HEALTHY)
    else:
        aggregator.update_source_status('VCW', SourceStatus.FAILED)

    # Lay gia tri tu cac nguon
    temps = {}
    humids = {}
    precips = {}
    impacts = {}

    if owm_data:
        temps['OWM'] = owm_data.get('temp_c', 30)
        humids['OWM'] = owm_data.get('humidity_pct', 70)
        precips['OWM'] = owm_data.get('precip', 0)
        impacts['OWM'] = owm_data.get('weather_impact', 0)
        logger.info(f"  -> OWM: {temps['OWM']}C, precip={precips['OWM']}mm")

    if vcw_data:
        temps['VCW'] = vcw_data.get('temp_c', 30)
        humids['VCW'] = vcw_data.get('humidity_pct', 70)
        precips['VCW'] = vcw_data.get('precip', 0)
        impacts['VCW'] = vcw_data.get('weather_impact', 0)
        logger.info(f"  -> VCW: {temps['VCW']}C, precip={precips['VCW']}mm")

    # Neu chi co 1 nguon, tra ve truc tiep
    # BLENDED_* = RAW value (single source = no blending needed)
    if len(temps) == 1:
        source_name = list(temps.keys())[0]
        data = owm_data if source_name == 'OWM' else vcw_data

        precip_impact = min(1.0, data.get('precip', 0) / 20)
        value = max(data.get('weather_impact', 0), precip_impact)

        return {
            'anchor_name': name,
            'lat': lat,
            'lon': lon,
            'temp_c': data.get('temp_c', 30),
            'feels_like': data.get('feels_like', 32),
            'humidity_pct': data.get('humidity_pct', 70),
            'precip': data.get('precip', 0),
            'precip_prob': data.get('precip_prob', 0),
            'wind_speed': data.get('wind_speed', 3),
            'wind_dir': data.get('wind_dir', 'E'),
            'pressure': data.get('pressure', 1013),
            'cloud_cover': data.get('cloud_cover', 50),
            'visibility': data.get('visibility', 10),
            'uv_index': 5,
            'weather_code': data.get('weather_code', 'unknown'),
            'weather_conditions': data.get('weather_conditions', 'Unknown'),
            'weather_impact': data.get('weather_impact', 0),
            'precip_impact': precip_impact,
            'value': value,
            'severity': _get_severity(value),
            'source': source_name,
            # BLENDED COLUMNS - Match training schema (single source = blended = raw)
            'blended_temp_c': data.get('temp_c', 30),
            'blended_humidity_pct': data.get('humidity_pct', 70),
            'blended_precip': data.get('precip', 0),
            'blended_weather_impact': data.get('weather_impact', 0),
            # OWM RAW COLUMNS - For consistency with historical data
            'owm_temp_c': owm_data.get('temp_c') if owm_data else None,
            'owm_feels_like': owm_data.get('feels_like') if owm_data else None,
            'owm_humidity_pct': owm_data.get('humidity_pct') if owm_data else None,
            'owm_precip': owm_data.get('precip') if owm_data else 0,
            'owm_wind_speed': owm_data.get('wind_speed') if owm_data else None,
            'owm_cloud_cover': owm_data.get('cloud_cover') if owm_data else None,
            'owm_weather_code': owm_data.get('weather_code') if owm_data else None,
            'owm_weather_impact': owm_data.get('weather_impact') if owm_data else 0,
        }

    # Ensemble cho tat ca features
    temp_result = aggregator.ensemble_continuous('temperature', temps)
    humid_result = aggregator.ensemble_continuous('humidity', humids)
    precip_result = aggregator.ensemble_continuous('precipitation', precips)
    impact_result = aggregator.ensemble_continuous('weather_impact', impacts)

    # Log tat ca ket qua ensemble
    logger.info(f"  -> OWM: temp={temps.get('OWM', 'N/A')}C, humidity={humids.get('OWM', 'N/A')}%, precip={precips.get('OWM', 'N/A')}mm")
    logger.info(f"  -> VCW: temp={temps.get('VCW', 'N/A')}C, humidity={humids.get('VCW', 'N/A')}%, precip={precips.get('VCW', 'N/A')}mm")
    logger.info(f"  -> ENSEMBLE: temp={temp_result.ensemble_value:.2f}C, humidity={humid_result.ensemble_value:.2f}%, precip={precip_result.ensemble_value:.2f}mm, impact={impact_result.ensemble_value:.2f}, weights={temp_result.source_weights}")

    # Su dung gia tri tu nguon co san
    primary_data = owm_data if owm_data else vcw_data

    precip_impact = min(1.0, precip_result.ensemble_value / 20)
    ensemble_value = max(impact_result.ensemble_value, precip_impact)

    return {
        'anchor_name': name,
        'lat': lat,
        'lon': lon,
        'temp_c': round(temp_result.ensemble_value, 2),
        'feels_like': round(temp_result.ensemble_value + 2, 2),
        'humidity_pct': round(humid_result.ensemble_value, 2),
        'precip': round(precip_result.ensemble_value, 2),
        'precip_prob': round(precip_result.ensemble_value * 20, 2),
        'wind_speed': round(primary_data.get('wind_speed', 3), 2),
        'wind_dir': primary_data.get('wind_dir', 'E'),
        'pressure': round(primary_data.get('pressure', 1013), 2),
        'cloud_cover': round(primary_data.get('cloud_cover', 50), 2),
        'visibility': round(primary_data.get('visibility', 10), 2),
        'uv_index': round(primary_data.get('uv_index', 5), 2),
        'weather_code': primary_data.get('weather_code', 'ensemble'),
        'weather_conditions': primary_data.get('weather_conditions', 'Ensemble'),
        'weather_impact': round(impact_result.ensemble_value, 2),
        'precip_impact': round(precip_impact, 2),
        'value': round(ensemble_value, 2),
        'severity': _get_severity(ensemble_value),
        'source': 'ENSEMBLE',
        # BLENDED COLUMNS - Match training schema (ensemble values)
        'blended_temp_c': round(temp_result.ensemble_value, 2),
        'blended_humidity_pct': round(humid_result.ensemble_value, 2),
        'blended_precip': round(precip_result.ensemble_value, 2),
        'blended_weather_impact': round(impact_result.ensemble_value, 2),
        # OWM RAW COLUMNS - For consistency with historical data
        'owm_temp_c': owm_data.get('temp_c') if owm_data else None,
        'owm_feels_like': owm_data.get('feels_like') if owm_data else None,
        'owm_humidity_pct': owm_data.get('humidity_pct') if owm_data else None,
        'owm_precip': owm_data.get('precip') if owm_data else 0,
        'owm_wind_speed': owm_data.get('wind_speed') if owm_data else None,
        'owm_cloud_cover': owm_data.get('cloud_cover') if owm_data else None,
        'owm_weather_code': owm_data.get('weather_code') if owm_data else None,
        'owm_weather_impact': owm_data.get('weather_impact') if owm_data else 0,
    }


def _create_fallback_weather(name: str) -> Dict:
    """Tao weather data fallback."""
    return {
        'anchor_name': name,
        'lat': 0,
        'lon': 0,
        'temp_c': 30,
        'feels_like': 32,
        'humidity_pct': 70,
        'precip': 0,
        'precip_prob': 0,
        'wind_speed': 3,
        'wind_dir': 'E',
        'pressure': 1013,
        'cloud_cover': 50,
        'visibility': 10,
        'uv_index': 5,
        'weather_code': 'fallback',
        'weather_conditions': 'Unknown (API unavailable)',
        'weather_impact': 0,
        'precip_impact': 0,
        'value': 0,
        'severity': 'LOW',
        'source': 'FALLBACK',
        # BLENDED COLUMNS - Fallback values (no real data)
        'blended_temp_c': 30,
        'blended_humidity_pct': 70,
        'blended_precip': 0,
        'blended_weather_impact': 0,
        # OWM RAW COLUMNS - Fallback values
        'owm_temp_c': None,
        'owm_feels_like': None,
        'owm_humidity_pct': None,
        'owm_precip': 0,
        'owm_wind_speed': None,
        'owm_cloud_cover': None,
        'owm_weather_code': None,
        'owm_weather_impact': 0,
    }


def _get_severity(value: float) -> str:
    """Map value to severity."""
    if value >= 0.8:
        return "SEVERE"
    elif value >= 0.5:
        return "HIGH"
    elif value >= 0.2:
        return "MEDIUM"
    return "LOW"


def step_a4_broadcast_weather_kdtree(
    hex_ids: List[str],
    anchor_coords: List[Tuple[float, float]],
    weather_stations: List[Dict]
) -> pd.DataFrame:
    """BUOC A.4: Broadcast thoi tiet tu 6 anchor -> tat ca Hex bang KDTree."""
    logger.info("\n" + "="*60)
    logger.info("BUOC A.4: Broadcast thoi tiet bang KDTree")
    logger.info("="*60)

    anchor_array = np.array(anchor_coords)
    kdtree = KDTree(anchor_array)

    records = []
    for hex_id in hex_ids:
        centroid = h3.cell_to_latlng(hex_id)
        hex_lat, hex_lon = centroid[0], centroid[1]

        dist, idx = kdtree.query((hex_lat, hex_lon))
        weather = weather_stations[idx]

        record = {
            'hex_id': hex_id,
            'lat': hex_lat,
            'lon': hex_lon,
            'nearest_anchor': weather['anchor_name'],
            'distance_to_anchor_km': round(dist, 3),
            'temp_c': weather['temp_c'],
            'feels_like': weather['feels_like'],
            'humidity_pct': weather['humidity_pct'],
            'precip': weather['precip'],
            'precip_prob': weather['precip_prob'],
            'wind_speed': weather['wind_speed'],
            'wind_dir': weather['wind_dir'],
            'pressure': weather['pressure'],
            'cloud_cover': weather['cloud_cover'],
            'visibility': weather['visibility'],
            'uv_index': weather['uv_index'],
            'weather_code': weather['weather_code'],
            'weather_conditions': weather['weather_conditions'],
            'weather_impact': weather['weather_impact'],
            'precip_impact': weather['precip_impact'],
            'value': weather['value'],
            'severity': weather['severity'],
            # BLENDED COLUMNS - Match training schema
            'blended_temp_c': weather.get('blended_temp_c', weather['temp_c']),
            'blended_humidity_pct': weather.get('blended_humidity_pct', weather['humidity_pct']),
            'blended_precip': weather.get('blended_precip', weather['precip']),
            'blended_weather_impact': weather.get('blended_weather_impact', weather['weather_impact']),
            # OWM RAW COLUMNS - For consistency with historical data
            'owm_temp_c': weather.get('owm_temp_c'),
            'owm_feels_like': weather.get('owm_feels_like'),
            'owm_humidity_pct': weather.get('owm_humidity_pct'),
            'owm_precip': weather.get('owm_precip', 0),
            'owm_wind_speed': weather.get('owm_wind_speed'),
            'owm_cloud_cover': weather.get('owm_cloud_cover'),
            'owm_weather_code': weather.get('owm_weather_code'),
            'owm_weather_impact': weather.get('owm_weather_impact', 0),
        }
        records.append(record)

    df = pd.DataFrame(records)
    logger.info(f"  -> Broadcasted to {len(df)} hexes")

    return df


def step_b_adaptive_flood_check(df: pd.DataFrame, has_storm: bool) -> pd.DataFrame:
    """
    BUOC B: Adaptive Polling + Uu tien HSDC cho precip.

    Uu tien du lieu:
    1. HSDC (62 tram rainfall that) - uu tien hang dau
    2. OWM + VCW Ensemble - fallback neu HSDC loi
    """
    logger.info("\n" + "="*60)
    logger.info("BUOC B: Adaptive Polling HSDC (Ngap lut + Precip)")
    logger.info("="*60)

    max_precip_owm_vcw = df["precip"].max()
    should_call_hsdc = (max_precip_owm_vcw > 0.5) or has_storm

    logger.info(f"  -> precip hien tai (OWM/VCW ensemble) max = {max_precip_owm_vcw} mm")
    logger.info(f"  -> has_storm = {has_storm}")
    logger.info(f"  -> should_call_hsdc = {should_call_hsdc}")

    hsdc_data = None
    if should_call_hsdc:
        logger.info("  -> GOI HSDC API (uu tien)...")
        hsdc_data = fetch_hsdc_full_data()

    # Cap nhat precip tu HSDC neu co du lieu
    if hsdc_data and hsdc_data['stations'] and hsdc_data['rainfall']:
        logger.info("  -> Dung HSDC lam nguon precip CHINH")

        # Build KDTree tu 62 tram HSDC
        station_coords = []
        station_rainfall = []

        for station in hsdc_data['stations']:
            lat = station.get('Lat')
            lon = station.get('Lng')
            station_id = station.get('Id')

            if lat and lon and station_id in hsdc_data['rainfall']:
                station_coords.append((float(lat), float(lon)))
                station_rainfall.append(hsdc_data['rainfall'][station_id]['LuongMua_HT'])

        if station_coords:
            station_array = np.array(station_coords)
            kdtree = KDTree(station_array)

            # Broadcast HSDC rainfall den tung hex
            new_precip = []
            new_precip_prob = []
            for hex_id in df['hex_id']:
                centroid = h3.cell_to_latlng(hex_id)
                dist, idx = kdtree.query(centroid)
                rainfall_ht = station_rainfall[idx]

                new_precip.append(rainfall_ht)
                # Neu co mua thi prob = 100, neu khong thi giu OWM/VCW prob
                if rainfall_ht > 0:
                    new_precip_prob.append(100.0)
                else:
                    new_precip_prob.append(df.loc[df['hex_id'] == hex_id, 'precip_prob'].iloc[0])

            df['precip'] = new_precip
            df['precip_prob'] = new_precip_prob
            df['precip_source'] = 'HSDC'

            logger.info(f"  -> Da cap nhat precip tu {len(station_coords)} tram HSDC")
        else:
            logger.warning("  -> HSDC khong co station coords hop le, giu OWM/VCW")
            df['precip_source'] = 'OWM+VCW'

        # Cap nhat flood points tu HSDC
        flood_points = hsdc_data['flood_points']
        flooded_hex_set = set()
        for lat, lon in flood_points:
            hex_id = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
            flooded_hex_set.add(hex_id)

        logger.info(f"  -> {len(flooded_hex_set)} hex bi ngap (tu HSDC)")
        df["is_flooded"] = df["hex_id"].apply(lambda x: 1 if x in flooded_hex_set else 0)

    elif should_call_hsdc:
        # HSDC loi, fallback ve OWM/VCW
        logger.warning("  -> HSDC API loi! Fallback ve OWM/VCW ensemble")
        df['precip_source'] = 'OWM+VCW (HSDC failed)'
        df["is_flooded"] = 0
    else:
        # Khong goi HSDC
        logger.info("  -> BO QUA HSDC API (khong co mua, khong co bao)")
        df['precip_source'] = 'OWM+VCW (HSDC skipped)'
        df["is_flooded"] = 0

    flooded_count = df["is_flooded"].sum()
    logger.info(f"  -> Tong hex bi ngap: {flooded_count}/{len(df)}")

    return df


def step_c_add_metadata(df: pd.DataFrame, storm_warning: int) -> pd.DataFrame:
    """BUOC C: Them metadata."""
    logger.info("\n" + "="*60)
    logger.info("BUOC C: Them metadata")
    logger.info("="*60)

    now = datetime.now()

    df["crawled_at"] = now
    df["day_of_week"] = now.weekday()
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["storm_warning"] = storm_warning

    logger.info(f"  -> crawled_at = {now.isoformat()}")
    logger.info(f"  -> day_of_week = {now.strftime('%A')} ({now.weekday()})")
    logger.info(f"  -> is_weekend = {df['is_weekend'].iloc[0]}")
    logger.info(f"  -> storm_warning = {storm_warning}")

    return df


def _get_time_partition() -> str:
    """
    Lay partition key theo gio trong ngay.
    Chia nho 4 lan/ngan (00, 06, 12, 18) de tranh file >50MB.
    """
    hour = datetime.now().hour
    if hour < 6:
        return "00_05"
    elif hour < 12:
        return "06_11"
    elif hour < 18:
        return "12_17"
    else:
        return "18_23"


def step_d_save_parquet(df: pd.DataFrame) -> List[Path]:
    """BUOC D: Luu DataFrame vao Parquet (chia theo thoi gian trong ngay)."""
    logger.info("\n" + "="*60)
    logger.info("BUOC D: Luu vao Parquet (partitioned by time-of-day)")
    logger.info("="*60)

    # Ensure consistent types
    if 'weather_code' in df.columns:
        df['weather_code'] = df['weather_code'].astype(str)

    numeric_cols = [
        # Core weather features
        'temp_c', 'feels_like', 'humidity_pct', 'precip', 'precip_prob',
        'wind_speed', 'pressure', 'cloud_cover', 'visibility', 'uv_index',
        'weather_impact', 'precip_impact', 'value',
        # BLENDED COLUMNS - Match training schema (Train-Serving Skew fix)
        'blended_temp_c', 'blended_humidity_pct', 'blended_precip', 'blended_weather_impact',
        # OWM RAW COLUMNS - For consistency with historical data
        'owm_temp_c', 'owm_feels_like', 'owm_humidity_pct', 'owm_precip',
        'owm_wind_speed', 'owm_cloud_cover', 'owm_weather_impact',
        # Spatial features
        'lat', 'lon', 'distance_to_anchor_km',
        # Other numeric
        'is_flooded', 'storm_warning', 'day_of_week', 'is_weekend',
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Lay partition hien tai
    time_partition = _get_time_partition()
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"weather_{date_str}_{time_partition}.parquet"

    # Kiem tra so luong record hien tai trong partition
    # Moi crawl tao ra ~1,960 records (1 record/hex x 1960 hexes)
    # Moi partition co 6 tieng (24/4 = 6h)
    # So crawl toi da trong 6h = 24 (moi 15 phut)
    # 24 crawls x 1,960 records = 47,040 records/partition
    # File 47K records ≈ ~2 MB, van duoi 50MB
    # Dat max = 50,000 de backfill data khong bi split
    max_records_per_partition = 50000  # ~2MB/file, duoi 50MB limit

    if output_file.exists():
        existing_df = pd.read_parquet(output_file)
        existing_count = len(existing_df)

        # Neu da co max records trong partition nay, luu vao file tiep theo
        if existing_count >= max_records_per_partition:
            # Dat ten file voi timestamp cu the
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
            output_file = OUTPUT_DIR / f"weather_{date_str}_{time_partition}_{timestamp_str}.parquet"
            combined_df = df  # <-- FIX: must assign combined_df for new file
            logger.warning(f"  -> Partition full ({existing_count} records), using timestamped file: {output_file.name}")
        else:
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            logger.info(f"  -> Appended {len(df)} to existing {existing_count} records")
    else:
        combined_df = df
        logger.info(f"  -> Created new file with {len(df)} records")

    combined_df.to_parquet(output_file, index=False)
    logger.info(f"  -> Saved to: {output_file}")

    # Tinh toan kich thuoc file
    file_size_mb = output_file.stat().st_size / (1024 * 1024)
    logger.info(f"  -> File size: {file_size_mb:.2f} MB")

    if file_size_mb > 45:
        logger.warning(f"  -> WARNING: File approaching 50MB limit! Consider archiving older data.")

    return [output_file]


# =============================================================================
# PHAN 7: MAIN FUNCTION
# =============================================================================

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Realtime Weather Crawler for Hanoi Demand Spike Detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python realtime_crawler.py                    # Run all steps
  python realtime_crawler.py --step a1           # Only storm warning
  python realtime_crawler.py --step a2           # Only generate hexes
  python realtime_crawler.py --step a3           # Only fetch weather
  python realtime_crawler.py --step a4           # Only broadcast
  python realtime_crawler.py --step b            # Only flood check
  python realtime_crawler.py --step c            # Only add metadata
  python realtime_crawler.py --step d            # Only save parquet
  python realtime_crawler.py --no-lock           # Skip mutex lock (for debugging)
        """
    )
    parser.add_argument(
        '--step', '-s',
        type=str,
        default='all',
        choices=['all', 'a1', 'a2', 'a3', 'a4', 'b', 'c', 'd'],
        help='Which step to run (default: all)'
    )
    parser.add_argument(
        '--no-lock',
        action='store_true',
        help='Skip mutex lock check (for debugging parallel runs)'
    )
    parser.add_argument(
        '--lock-timeout',
        type=int,
        default=5,
        help='Lock timeout in seconds (default: 5)'
    )
    return parser.parse_args()


def run_step(step_name: str, config: dict):
    """
    Run a specific step or all steps.

    Args:
        step_name: 'all', 'a1', 'a2', 'a3', 'a4', 'b', 'c', 'd'
        config: dict containing step results/inputs
    """
    if step_name in ['all', 'a1']:
        has_storm, storm_warning = step_a1_storm_warning()
        config['storm_warning'] = storm_warning
        config['has_storm'] = has_storm
        logger.info(f"[STEP A.1] Completed: has_storm={has_storm}, storm_warning={storm_warning}")

    if step_name in ['all', 'a2']:
        hex_ids = step_a2_generate_h3_hexes()
        config['hex_ids'] = hex_ids
        logger.info(f"[STEP A.2] Completed: {len(hex_ids)} hexes")

    if step_name in ['all', 'a3']:
        # Initialize aggregator if needed (lazy initialization)
        if config.get('aggregator') is None:
            config['aggregator'] = WeatherEnsembleAggregator(EnsembleConfig())
        anchor_coords, weather_stations = step_a3_fetch_anchor_weather_ensemble(config['aggregator'])
        config['anchor_coords'] = anchor_coords
        config['weather_stations'] = weather_stations
        logger.info(f"[STEP A.3] Completed: {len(weather_stations)} stations")

    if step_name in ['all', 'a4']:
        if 'hex_ids' not in config or 'anchor_coords' not in config or 'weather_stations' not in config:
            logger.error("[STEP A.4] Missing required data from previous steps (run with --step all or --step a2,a3 first)")
            return None
        df = step_a4_broadcast_weather_kdtree(config['hex_ids'], config['anchor_coords'], config['weather_stations'])
        config['df'] = df
        logger.info(f"[STEP A.4] Completed: {len(df)} rows")

    if step_name in ['all', 'b']:
        if 'df' not in config:
            logger.error("[STEP B] Missing dataframe from previous steps")
            return None
        has_storm = config.get('has_storm', False)
        df = step_b_adaptive_flood_check(config['df'], has_storm)
        config['df'] = df
        logger.info(f"[STEP B] Completed: {len(df)} rows")

    if step_name in ['all', 'c']:
        if 'df' not in config:
            logger.error("[STEP C] Missing dataframe from previous steps")
            return None
        storm_warning = config.get('storm_warning', 0)
        df = step_c_add_metadata(config['df'], storm_warning)
        config['df'] = df
        logger.info(f"[STEP C] Completed: {len(df)} rows")

    if step_name in ['all', 'd']:
        if 'df' not in config:
            logger.error("[STEP D] Missing dataframe from previous steps")
            return None
        output_paths = step_d_save_parquet(config['df'])
        config['output_paths'] = output_paths
        logger.info(f"[STEP D] Completed: {output_paths}")

    return config


def main():
    """Main entry point."""
    args = parse_args()

    logger.info("\n" + "="*70)
    logger.info("REALTIME CRAWLER - PRODUCTION VERSION")
    logger.info(f"Thoi gian: {datetime.now().isoformat()}")
    logger.info(f"Step: {args.step}")
    logger.info("="*70)

    # Acquire mutex lock (unless --no-lock is specified)
    lock_handle = None
    if not args.no_lock:
        lock_handle = acquire_lock(timeout=args.lock_timeout)
        if not lock_handle:
            logger.error("Another instance is already running. Exiting.")
            return 1

    try:
        # Kiem tra API keys
        if not OWM_API_KEY:
            logger.warning("OPENWEATHERMAP_API_KEY khong ton tai trong .env")

        vcw_stats = vcw_rotator.get_stats()
        logger.info(f"VCW API Keys: {vcw_stats['active']}/{vcw_stats['total']} available")

        # Initialize config for step data passing
        config = {
            'aggregator': None,
        }

        # Run steps
        result = run_step(args.step, config)

        if result is None:
            logger.error("Step execution failed")
            return 1

        logger.info("\n" + "="*70)
        logger.info("REALTIME CRAWLER - HOAN THANH")
        logger.info("="*70)

        # Final stats
        if 'df' in config:
            final_vcw_stats = vcw_rotator.get_stats()

            summary = {
                "total_hexes": len(config['df']),
                "flooded_hexes": int(config['df']["is_flooded"].sum()),
                "storm_warning": config.get('storm_warning', 0),
                "output_files": [str(p) for p in config.get('output_paths', [])],
                "crawled_at": config['df']["crawled_at"].iloc[0].isoformat(),
                "vcw_keys_used": f"{final_vcw_stats['rate_limited']} rate-limited, {final_vcw_stats['failed']} failed",
            }
            logger.info(f"Summary: {summary}")

        return 0

    except Exception as e:
        logger.error(f"LOI: {e}", exc_info=True)
        return 1

    finally:
        # Always release lock
        if lock_handle:
            release_lock(lock_handle)


if __name__ == "__main__":
    sys.exit(main())
