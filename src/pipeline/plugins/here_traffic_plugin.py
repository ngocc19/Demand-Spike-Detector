"""
HERE Traffic Plugin
==================

Plugin for fetching real-time traffic data using HERE Traffic Flow API.
Integrates with the existing Factor Plugin pattern.

Data Source:
- HERE Traffic Flow API v6.3: Real-time traffic speed and congestion
- HERE Traffic Incidents API: Traffic incidents and alerts

Output:
- 35 Anchor Points → 1,960 H3 hexes (via IDW interpolation)
- Data Lake: data/traffic/YYYY-MM-DD.parquet
- Schedule: every 30 minutes

Usage:
    config = {
        'api_key': 'your_here_api_key',
        'data_lake_dir': 'data/traffic',
    }
    plugin = HERETrafficPlugin(config)
    records = plugin.run_pipeline()
"""

import os
import time
from pathlib import Path
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import logging
import re

from ..base import BaseFactorPlugin, FactorType
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# 35 ANCHOR POINTS (Hanoi Traffic Monitoring Points)
# =============================================================================

ANCHOR_POINTS: List[Dict] = [
    # Regular monitoring points (30 points)
    {"id": 1, "name": "De La Thanh (BV Nhi Trung uong)", "lat": 21.0278, "lon": 105.8022, "is_control": False},
    {"id": 2, "name": "Thai Ha - Chua Boc - Tay Son", "lat": 21.0065, "lon": 105.8196, "is_control": False},
    {"id": 3, "name": "Kim Ma - Lieu Giai - Nguyen Chi Thanh", "lat": 21.0285, "lon": 105.8232, "is_control": False},
    {"id": 4, "name": "Nguyen Chi Thanh - Duong Lang", "lat": 21.0341, "lon": 105.7877, "is_control": False},
    {"id": 5, "name": "Cau vuot Giang Vo - Lang Ha", "lat": 21.0234, "lon": 105.8123, "is_control": False},
    {"id": 6, "name": "O Cho Dua", "lat": 21.0342, "lon": 105.8356, "is_control": False},
    {"id": 7, "name": "Nga Tu So", "lat": 21.0186, "lon": 105.7502, "is_control": False},
    {"id": 8, "name": "Nga Tu Vong - Dai La - Giai Phong", "lat": 21.0138, "lon": 105.7824, "is_control": False},
    {"id": 9, "name": "Truong Chinh - Ton That Tung", "lat": 21.0085, "lon": 105.7856, "is_control": False},
    {"id": 10, "name": "Truong Dinh - Bach Mai - Minh Khai", "lat": 21.0052, "lon": 105.8467, "is_control": False},
    {"id": 11, "name": "Cau Mai Dong (Tam Trinh - Minh Khai)", "lat": 20.9723, "lon": 105.8745, "is_control": False},
    {"id": 12, "name": "Phap Van - Ngoc Hoi", "lat": 20.9512, "lon": 105.8923, "is_control": False},
    {"id": 13, "name": "Vanh dai 3 - Ben xe Nuoc Ngam", "lat": 21.0324, "lon": 105.8645, "is_control": False},
    {"id": 14, "name": "Nguyen Xien - Nguyen Trai", "lat": 21.0067, "lon": 105.7889, "is_control": False},
    {"id": 15, "name": "Vanh dai 3 (Thang Long)", "lat": 21.0423, "lon": 105.7545, "is_control": False},
    {"id": 16, "name": "Tran Duy Hung - Khuat Duy Tien (BigC)", "lat": 21.0178, "lon": 105.7895, "is_control": False},
    {"id": 17, "name": "Pham Van Dong - Hoang Quoc Viet", "lat": 21.0567, "lon": 105.7856, "is_control": False},
    {"id": 18, "name": "Co Nhue - Pham Van Dong", "lat": 21.0654, "lon": 105.7623, "is_control": False},
    {"id": 19, "name": "Tran Dang Ninh - Cau Giay", "lat": 21.0432, "lon": 105.7956, "is_control": False},
    {"id": 20, "name": "Cau 361 - Nguyen Khang (To Lich)", "lat": 21.0523, "lon": 105.8023, "is_control": False},
    {"id": 21, "name": "Nguyen Chanh - Duong Dinh Nghe", "lat": 21.0198, "lon": 105.7634, "is_control": False},
    {"id": 22, "name": "Nga Tu Nhat Tan - Vo Chi Cong", "lat": 21.0765, "lon": 105.8324, "is_control": False},
    {"id": 23, "name": "Ham chui Hoang Minh Giam - Le Van Luong", "lat": 21.0123, "lon": 105.7945, "is_control": False},
    {"id": 24, "name": "To Huu - Vu Trong Khanh", "lat": 20.9678, "lon": 105.7523, "is_control": False},
    {"id": 25, "name": "Le Duc Tho - Ho Tung Mau", "lat": 21.0389, "lon": 105.7445, "is_control": False},
    {"id": 26, "name": "Nga tu Geleximco - Le Trong Tan (Ha Dong)", "lat": 20.9689, "lon": 105.7324, "is_control": False},
    {"id": 27, "name": "Cau Chuong Duong - Nguyen Van Cu", "lat": 21.0145, "lon": 105.8556, "is_control": False},
    {"id": 28, "name": "Co Linh - Dam Quang Trung (Vinh Tuy)", "lat": 21.0034, "lon": 105.8723, "is_control": False},
    {"id": 29, "name": "Nguyen Van Linh - Sai Dong (QL5)", "lat": 21.0234, "lon": 105.8845, "is_control": False},
    {"id": 30, "name": "Luu Khanh Dam - Mai Chi Tho (Viet Hung)", "lat": 21.0489, "lon": 105.8645, "is_control": False},
    # Control points (always free-flow) - highways and expressways
    {"id": 31, "name": "Dai lo Thang Long (Hoai Duc)", "lat": 21.0123, "lon": 105.6845, "is_control": True},
    {"id": 32, "name": "Vo Nguyen Giap (Noi Bai)", "lat": 21.0789, "lon": 105.8123, "is_control": True},
    {"id": 33, "name": "Truong Sa (Dong Anh)", "lat": 21.0923, "lon": 105.8234, "is_control": True},
    {"id": 34, "name": "Cao toc HN-HP (Trau Quy)", "lat": 20.9656, "lon": 105.8567, "is_control": True},
    {"id": 35, "name": "Cienco 5 (Thanh Ha)", "lat": 20.9345, "lon": 105.7456, "is_control": True},
]

# Free-flow speeds by road type (km/h)
FREE_FLOW_SPEEDS = {
    'highway': 100,    # Expressways/highways
    'major': 60,       # Major arterial roads
    'secondary': 40,   # Secondary roads
    'local': 30,       # Local roads
    'default': 50,      # Default
}

# Road type detection patterns
ROAD_TYPE_PATTERNS = {
    'highway': ['highway', 'motorway', 'expressway', 'đường cao tốc', 'ct', 'cao toc'],
    'major': ['primary', 'trunk', 'đường chính', 'quốc lộ', 'ql', 'quoc lo', 'national highway'],
    'secondary': ['secondary', 'đường secondary', 'tỉnh lộ', 'tl', 'provincial highway'],
    'local': ['residential', 'service', 'đường nội bộ', 'ngõ'],
}


# =============================================================================
# HERE TRAFFIC PLUGIN
# =============================================================================

@PluginRegistry.register("here_traffic")
class HERETrafficPlugin(BaseFactorPlugin):
    """
    HERE API Traffic Plugin using Traffic Flow API.

    Fetches REAL-TIME traffic data using HERE Traffic Flow API.
    Data includes:
    - Current traffic speed
    - Jam factor (0-10)
    - Travel time
    - Road incidents

    Outputs:
    - current_speed: Real-time speed in km/h
    - jam_factor: 0.0 (free flow) to 10.0 (full jam)
    - speed_drop_ratio: 0.0 (free flow) to 1.0 (congestion)
    """

    factor_type = FactorType.TRAFFIC
    factor_name = "here_traffic"
    schedule = "*/30 * * * *"  # Every 30 minutes

    # HERE Traffic Flow API endpoints (v6.3)
    TRAFFIC_FLOW_API = "https://traffic.ls.hereapi.com/traffic/6.3/flow.json"
    TRAFFIC_INCIDENTS_API = "https://traffic.ls.hereapi.com/traffic/6.3/incidents.json"

    TIMEOUT = 30
    REQUEST_DELAY = 0.5  # Delay between API calls
    MAX_RETRIES = 3

    # Default center point (Hanoi)
    DEFAULT_CENTER_LAT = 21.0285
    DEFAULT_CENTER_LON = 105.8542
    DEFAULT_RADIUS_M = 25000  # 25km radius

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # API key from config or env
        self.api_key = config.get('api_key') or os.environ.get('HERE_API_KEY', '')

        if not self.api_key:
            raise ValueError("HERE_API_KEY is required. Set it in .env or config.")

        # Data lake directory
        self.data_lake_dir = Path(config.get('data_lake_dir', 'data/traffic'))
        self.data_lake_dir.mkdir(parents=True, exist_ok=True)

        # Anchor points
        self.anchor_points = config.get('anchor_points', ANCHOR_POINTS)

        # Center point for API requests
        self.center_lat = config.get('center_lat', self.DEFAULT_CENTER_LAT)
        self.center_lon = config.get('center_lon', self.DEFAULT_CENTER_LON)
        self.radius_m = config.get('radius_m', self.DEFAULT_RADIUS_M)

        # Session for HTTP requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Demand-Spike-Detector/1.0',
            'Accept': 'application/json',
        })

        # Cache for traffic data
        self.traffic_cache: Dict[str, Dict] = {}
        self.last_cache_update: Optional[datetime] = None
        self.cache_ttl_minutes = config.get('cache_ttl_minutes', 15)

    # =========================================================================
    # STEP 1: FETCH (REAL-TIME TRAFFIC FLOW)
    # =========================================================================

    def fetch(self) -> pd.DataFrame:
        """
        Fetch real-time traffic data from HERE Traffic Flow API.

        Returns:
            DataFrame with real-time traffic data for each anchor point
        """
        if not self.api_key:
            logger.error("HERE_API_KEY not set!")
            return self._create_empty_result()

        timestamp = datetime.now()

        # Check cache
        if self._is_cache_valid():
            logger.info("Using cached traffic data")
            return self._get_cached_results(timestamp)

        logger.info(f"Fetching real-time traffic data for {len(self.anchor_points)} anchor points...")

        # Fetch real-time traffic flow data
        flow_data = self._fetch_traffic_flow()

        # Fetch traffic incidents
        incidents_data = self._fetch_traffic_incidents()

        # Combine with anchor points
        records = []
        for anchor in self.anchor_points:
            anchor_traffic = self._get_anchor_traffic(anchor, flow_data, incidents_data)
            records.append(anchor_traffic)

        # Cache results
        self._update_cache(records)

        df = pd.DataFrame(records)
        df['datetime'] = timestamp
        self.last_crawl = timestamp

        logger.info(f"Fetched traffic data for {len(df)} anchor points")
        return df

    def _fetch_traffic_flow(self) -> Dict[str, Any]:
        """
        Fetch real-time traffic flow data from HERE Traffic Flow API.

        API: https://traffic.ls.hereapi.com/traffic/6.3/flow.json?prox=21.0285,105.8542,25000&apiKey=...

        Response structure:
        {
          "RWS": [
            {
              "RW": [
                {
                  "FIS": [
                    {
                      "FI": [
                        {
                          "TMC": {...},
                          "CF": [
                            {
                              "SP": 45.2,  // Speed in km/h
                              "JF": 2.5,   // Jam factor 0-10
                              "CN": 0.85,  // Confidence 0-1
                              "FF": 60.0   // Free flow speed
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
        """
        params = {
            'prox': f'{self.center_lat},{self.center_lon},{self.radius_m}',
            'apiKey': self.api_key,
            'responseattributes': 'shp,fc',  # Include shape points and flow confidence
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(f"Requesting HERE Traffic Flow API (attempt {attempt + 1})...")
                response = self.session.get(
                    self.TRAFFIC_FLOW_API,
                    params=params,
                    timeout=self.TIMEOUT
                )

                if response.status_code == 429:
                    wait = (attempt + 1) * 30
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if response.status_code == 401:
                    logger.error("Invalid HERE API key!")
                    raise ValueError("Invalid HERE API key")

                response.raise_for_status()
                data = response.json()

                # Parse traffic flow data
                return self._parse_traffic_flow_response(data)

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout (attempt {attempt + 1})")
                time.sleep(2 ** attempt)

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed: {e}")
                time.sleep(2 ** attempt)

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return {}

        logger.error("Failed to fetch traffic flow data after all retries")
        return {}

    def _parse_traffic_flow_response(self, data: Dict) -> Dict[str, Any]:
        """
        Parse HERE Traffic Flow API response.

        Returns dict mapping location (lat,lon) to traffic data.
        """
        traffic_data = {}

        try:
            rws = data.get('RWS', [])
            for rw_entry in rws:
                rw = rw_entry.get('RW', [])
                for road_way in rw:
                    fis = road_way.get('FIS', [])
                    for fis_entry in fis:
                        fi_list = fis_entry.get('FI', [])
                        for flow_info in fi_list:
                            # Traffic Message Channel info
                            tmc = flow_info.get('TMC', {})

                            # Current flow conditions
                            cf_list = flow_info.get('CF', [])
                            if not cf_list:
                                continue

                            cf = cf_list[0]

                            # Extract location from TMC
                            lat = tmc.get('lat', 0)
                            lon = tmc.get('lon', 0)

                            if lat and lon:
                                # Get road name if available
                                road_name = self._extract_road_name(road_way, flow_info)

                                # Get road type
                                road_type = self._detect_road_type(road_name)

                                traffic_data[(lat, lon)] = {
                                    'speed_kmh': cf.get('SP', 0),
                                    'jam_factor': cf.get('JF', 0),
                                    'confidence': cf.get('CN', 0),
                                    'free_flow_speed': cf.get('FF', FREE_FLOW_SPEEDS.get(road_type, 50)),
                                    'road_name': road_name,
                                    'road_type': road_type,
                                    'pc': cf.get('PC', ''),  # Jam pattern code
                                }

                            # Also extract from shape points if available
                            if 'SHP' in cf:
                                for shp_entry in cf['SHP']:
                                    shp_points = shp_entry.get('value', '')
                                    # Parse shape points (format: "lat,lon,lat,lon,...")
                                    coords = self._parse_shape_points(shp_points)
                                    for lat, lon in coords:
                                        if (lat, lon) not in traffic_data:
                                            traffic_data[(lat, lon)] = {
                                                'speed_kmh': cf.get('SP', 0),
                                                'jam_factor': cf.get('JF', 0),
                                                'confidence': cf.get('CN', 0),
                                                'free_flow_speed': cf.get('FF', 50),
                                                'road_name': road_name,
                                                'road_type': road_type,
                                                'pc': cf.get('PC', ''),
                                            }

        except Exception as e:
            logger.error(f"Error parsing traffic flow response: {e}")

        logger.info(f"Parsed {len(traffic_data)} traffic flow points")
        return traffic_data

    def _parse_shape_points(self, shp_value: str) -> List[Tuple[float, float]]:
        """Parse HERE shape points string to lat,lon tuples."""
        coords = []
        try:
            # Shape points are comma-separated lat,lon pairs
            parts = shp_value.split(' ')
            for part in parts:
                if ',' in part:
                    coord_parts = part.split(',')
                    if len(coord_parts) >= 2:
                        lat = float(coord_parts[0])
                        lon = float(coord_parts[1])
                        coords.append((lat, lon))
        except Exception:
            pass
        return coords

    def _extract_road_name(self, road_way: Dict, flow_info: Dict) -> str:
        """Extract road name from traffic data."""
        # Try DE (description) field
        if 'DE' in road_way:
            return road_way['DE']
        if 'DE' in flow_info.get('TMC', {}):
            return flow_info['TMC']['DE']
        return ''

    def _detect_road_type(self, road_name: str) -> str:
        """Detect road type from road name."""
        road_lower = road_name.lower()
        for road_type, patterns in ROAD_TYPE_PATTERNS.items():
            for pattern in patterns:
                if pattern in road_lower:
                    return road_type
        return 'default'

    def _fetch_traffic_incidents(self) -> Dict[str, Any]:
        """
        Fetch traffic incidents from HERE Traffic Incidents API.

        API: https://traffic.ls.hereapi.com/traffic/6.3/incidents.json?prox=21.0285,105.8542,25000&apiKey=...
        """
        params = {
            'prox': f'{self.center_lat},{self.center_lon},{self.radius_m}',
            'apiKey': self.api_key,
            'responseattributes': 'fc',  # Flow confidence
        }

        try:
            response = self.session.get(
                self.TRAFFIC_INCIDENTS_API,
                params=params,
                timeout=self.TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                return self._parse_incidents_response(data)

        except Exception as e:
            logger.warning(f"Failed to fetch incidents: {e}")

        return {}

    def _parse_incidents_response(self, data: Dict) -> Dict[str, Any]:
        """Parse traffic incidents response."""
        incidents = {}

        try:
            tmc_data = data.get('TMC', [])
            for incident in tmc_data:
                loc = incident.get('loc', {})
                lat = loc.get('lat', 0)
                lon = loc.get('lon', 0)

                if lat and lon:
                    incidents[(lat, lon)] = {
                        'type': incident.get('ty', ''),
                        'severity': incident.get('sev', ''),
                        'description': incident.get('d', ''),
                        'start_time': incident.get('st', ''),
                        'end_time': incident.get('et', ''),
                    }

        except Exception as e:
            logger.warning(f"Error parsing incidents: {e}")

        return incidents

    def _get_anchor_traffic(
        self,
        anchor: Dict,
        flow_data: Dict[str, Any],
        incidents_data: Dict[str, Any]
    ) -> Dict:
        """
        Get traffic data for a specific anchor point.

        Uses nearest traffic flow points to estimate anchor traffic.
        """
        anchor_lat = anchor['lat']
        anchor_lon = anchor['lon']
        anchor_id = anchor['id']

        # Control points are always free-flow
        if anchor.get('is_control', False):
            return {
                'anchor_id': anchor_id,
                'anchor_name': anchor['name'],
                'lat': anchor_lat,
                'lon': anchor_lon,
                'current_speed': FREE_FLOW_SPEEDS['highway'],
                'free_flow_speed': FREE_FLOW_SPEEDS['highway'],
                'jam_factor': 0.0,
                'speed_drop_ratio': 0.0,
                'confidence': 1.0,
                'is_control': True,
                'road_name': '',
                'road_type': 'highway',
                'has_incident': False,
                'incident_type': '',
            }

        # Find nearest traffic flow points
        nearest_points = self._find_nearest_flow_points(anchor_lat, anchor_lon, flow_data)

        if not nearest_points:
            # No traffic data available, use default
            logger.warning(f"No traffic data for anchor {anchor_id}, using default")
            return {
                'anchor_id': anchor_id,
                'anchor_name': anchor['name'],
                'lat': anchor_lat,
                'lon': anchor_lon,
                'current_speed': FREE_FLOW_SPEEDS['default'],
                'free_flow_speed': FREE_FLOW_SPEEDS['default'],
                'jam_factor': 0.0,
                'speed_drop_ratio': 0.0,
                'confidence': 0.0,  # Low confidence - no data
                'is_control': False,
                'road_name': '',
                'road_type': 'default',
                'has_incident': False,
                'incident_type': '',
            }

        # Calculate weighted average from nearest points
        weighted_speed = 0
        weighted_jam = 0
        weighted_ff = 0
        total_weight = 0
        total_confidence = 0

        for (lat, lon), data in nearest_points:
            distance = self._haversine_distance(anchor_lat, anchor_lon, lat, lon)

            if distance == 0:
                distance = 0.001  # Avoid division by zero

            # Weight by inverse distance squared (IDW)
            weight = 1 / (distance ** 2)

            # Weight by confidence
            confidence = data.get('confidence', 0.5)
            effective_weight = weight * confidence

            weighted_speed += effective_weight * data['speed_kmh']
            weighted_jam += effective_weight * data['jam_factor']
            weighted_ff += effective_weight * data['free_flow_speed']
            total_weight += effective_weight
            total_confidence += confidence * weight

        if total_weight > 0:
            current_speed = weighted_speed / total_weight
            jam_factor = weighted_jam / total_weight
            free_flow_speed = weighted_ff / total_weight
            avg_confidence = total_confidence / total_weight
        else:
            current_speed = 0
            jam_factor = 0
            free_flow_speed = FREE_FLOW_SPEEDS['default']
            avg_confidence = 0.5

        # Calculate speed drop ratio
        speed_drop_ratio = self._calculate_speed_drop_ratio(current_speed, free_flow_speed)

        # Check for nearby incidents
        has_incident, incident_type = self._check_nearby_incident(
            anchor_lat, anchor_lon, incidents_data
        )

        # If incident nearby, increase jam factor
        if has_incident:
            jam_factor = min(10.0, jam_factor + 3.0)
            speed_drop_ratio = min(1.0, speed_drop_ratio + 0.3)

        return {
            'anchor_id': anchor_id,
            'anchor_name': anchor['name'],
            'lat': anchor_lat,
            'lon': anchor_lon,
            'current_speed': current_speed,
            'free_flow_speed': free_flow_speed,
            'jam_factor': jam_factor,
            'speed_drop_ratio': speed_drop_ratio,
            'confidence': min(1.0, avg_confidence),
            'is_control': False,
            'road_name': nearest_points[0][1].get('road_name', '') if nearest_points else '',
            'road_type': nearest_points[0][1].get('road_type', 'default') if nearest_points else 'default',
            'has_incident': has_incident,
            'incident_type': incident_type,
        }

    def _find_nearest_flow_points(
        self,
        lat: float,
        lon: float,
        flow_data: Dict[str, Any],
        max_points: int = 5
    ) -> List[Tuple[Tuple[float, float], Dict]]:
        """Find nearest traffic flow points to given location."""
        distances = []

        for (flow_lat, flow_lon), data in flow_data.items():
            distance = self._haversine_distance(lat, lon, flow_lat, flow_lon)
            distances.append(((flow_lat, flow_lon), data, distance))

        # Sort by distance
        distances.sort(key=lambda x: x[2])

        # Return top k nearest with data
        return [(d[0], d[1]) for d in distances[:max_points] if d[1].get('speed_kmh', 0) > 0]

    def _check_nearby_incident(
        self,
        lat: float,
        lon: float,
        incidents_data: Dict[str, Any],
        radius_km: float = 0.5
    ) -> Tuple[bool, str]:
        """Check if there's a traffic incident near the location."""
        for (inc_lat, inc_lon), incident in incidents_data.items():
            distance = self._haversine_distance(lat, lon, inc_lat, inc_lon)
            if distance <= radius_km:
                return True, incident.get('type', 'UNKNOWN')
        return False, ''

    def _calculate_speed_drop_ratio(
        self,
        current_speed: float,
        free_flow_speed: float
    ) -> float:
        """
        Calculate speed drop ratio.

        Formula: Speed_Drop_Ratio = 1 - (currentSpeed / freeFlowSpeed)
        If currentSpeed > freeFlowSpeed, ratio = 0
        """
        if free_flow_speed <= 0:
            return 0.0

        if current_speed > free_flow_speed:
            return 0.0

        return max(0.0, min(1.0, 1 - (current_speed / free_flow_speed)))

    # =========================================================================
    # STEP 2: TRANSFORM
    # =========================================================================

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform raw traffic data to clean format.

        Steps:
        1. Ensure datetime column
        2. Calculate severity
        3. Add congestion level
        """
        if df.empty:
            return df

        df = df.copy()

        # Ensure datetime
        df['datetime'] = pd.to_datetime(df['datetime'])

        # Calculate severity based on jam factor
        def get_severity_from_jam(jam_factor):
            if pd.isna(jam_factor):
                return 'UNKNOWN'
            if jam_factor >= 7.0:
                return 'SEVERE'
            elif jam_factor >= 4.0:
                return 'HIGH'
            elif jam_factor >= 2.0:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df['jam_factor'].apply(get_severity_from_jam)

        # Congestion level (human readable)
        def get_congestion_level(jam_factor):
            if pd.isna(jam_factor):
                return 'UNKNOWN'
            if jam_factor >= 8.0:
                return 'GRIDLOCK'
            elif jam_factor >= 6.0:
                return 'HEAVY'
            elif jam_factor >= 3.0:
                return 'MODERATE'
            elif jam_factor >= 1.0:
                return 'LIGHT'
            return 'FREE_FLOW'

        df['congestion_level'] = df['jam_factor'].apply(get_congestion_level)

        # Value for feature store (normalized 0-1)
        df['value'] = df['speed_drop_ratio']

        return df

    # =========================================================================
    # STEP 3: SPATIAL MAPPING (IDW Interpolation)
    # =========================================================================

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Map traffic data to 1,960 H3 hexes using IDW interpolation.

        Since we only have 35 anchor points, we need to interpolate
        to all H3 hex cells using Inverse Distance Weighting.
        """
        if df.empty:
            return df

        try:
            import h3
        except ImportError:
            logger.error("h3 library not installed")
            return df

        # Hanoi center
        hanoi_center = (21.0285, 105.8542)
        center_hex = h3.latlng_to_cell(hanoi_center[0], hanoi_center[1], 8)

        # Get ~1,960 hexes
        hex_ids = list(h3.grid_disk(center_hex, 25))[:1960]

        # Get valid anchor data
        valid_anchors = df[df['speed_drop_ratio'].notna()].copy()

        if valid_anchors.empty:
            logger.warning("No valid traffic data for interpolation")
            return self._create_empty_result()

        # IDW interpolation for each hex
        hex_records = []

        for hex_id in hex_ids:
            hex_lat, hex_lon = h3.cell_to_latlng(hex_id)

            # Calculate weighted average from nearby anchors
            weighted_sum = 0
            weight_sum = 0
            weighted_jam = 0

            for _, anchor in valid_anchors.iterrows():
                distance = self._haversine_distance(
                    anchor['lat'], anchor['lon'], hex_lat, hex_lon
                )

                if distance == 0:
                    distance = 0.001  # Avoid division by zero

                weight = 1 / (distance ** 2)  # IDW power=2
                weighted_sum += weight * anchor['speed_drop_ratio']
                weighted_jam += weight * anchor['jam_factor']
                weight_sum += weight

            interpolated_value = weighted_sum / weight_sum if weight_sum > 0 else 0
            interpolated_jam = weighted_jam / weight_sum if weight_sum > 0 else 0

            # Get severity from interpolated jam factor
            if interpolated_jam >= 7.0:
                severity = 'SEVERE'
            elif interpolated_jam >= 4.0:
                severity = 'HIGH'
            elif interpolated_jam >= 2.0:
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            hex_records.append({
                'hex_id': hex_id,
                'lat': hex_lat,
                'lon': hex_lon,
                'datetime': df['datetime'].iloc[0],
                'value': interpolated_value,
                'speed_drop_ratio': interpolated_value,
                'jam_factor': interpolated_jam,
                'severity': severity,
                'confidence': 0.8,  # Lower confidence for interpolated
                'source': 'here_traffic_idw',
            })

        return pd.DataFrame(hex_records)

    def _haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """Calculate Haversine distance in km."""
        R = 6371  # Earth radius in km

        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))

        return R * c

    # =========================================================================
    # STEP 4: CACHE MANAGEMENT
    # =========================================================================

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid."""
        if self.last_cache_update is None:
            return False

        age = (datetime.now() - self.last_cache_update).total_seconds() / 60
        return age < self.cache_ttl_minutes

    def _update_cache(self, records: List[Dict]):
        """Update traffic data cache."""
        self.traffic_cache = {r['anchor_id']: r for r in records}
        self.last_cache_update = datetime.now()

    def _get_cached_results(self, timestamp: datetime) -> pd.DataFrame:
        """Get cached traffic results."""
        df = pd.DataFrame(list(self.traffic_cache.values()))
        df['datetime'] = timestamp
        return df

    # =========================================================================
    # STEP 5: SAVE TO DATA LAKE
    # =========================================================================

    def save_to_data_lake(
        self,
        df: pd.DataFrame,
        output_type: str = 'hex'
    ) -> Optional[Path]:
        """
        Save data to data lake partitioned by date.

        Output: data/traffic/YYYY-MM-DD.parquet

        Args:
            df: DataFrame to save
            output_type: 'anchor' or 'hex'

        Returns:
            Path to saved file
        """
        if df.empty:
            return None

        # Get date from timestamp
        date_col = 'datetime' if 'datetime' in df.columns else df.index[0]
        if hasattr(df[date_col], 'iloc'):
            date_str = pd.to_datetime(df[date_col].iloc[0]).strftime('%Y-%m-%d')
        else:
            date_str = pd.to_datetime(date_col).strftime('%Y-%m-%d')

        output_path = self.data_lake_dir / f"{date_str}_{output_type}.parquet"

        # Append if exists
        if output_path.exists():
            existing = pd.read_parquet(output_path)
            df = pd.concat([existing, df], ignore_index=True)
            # Deduplicate
            if 'anchor_id' in df.columns:
                df = df.drop_duplicates(subset=['anchor_id', 'datetime'], keep='last')
            elif 'hex_id' in df.columns:
                df = df.drop_duplicates(subset=['hex_id', 'datetime'], keep='last')

        df.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(df)} records to {output_path}")

        return output_path

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame."""
        return pd.DataFrame(columns=[
            'datetime', 'anchor_id', 'anchor_name', 'lat', 'lon',
            'current_speed', 'free_flow_speed', 'jam_factor', 'speed_drop_ratio',
            'severity', 'congestion_level', 'confidence', 'is_control',
            'road_name', 'road_type', 'has_incident', 'incident_type'
        ])

    # =========================================================================
    # ALIGN TEMPORAL (required by base class)
    # =========================================================================

    def align_temporal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Align time to 30-minute grid."""
        df = df.copy()

        if 'datetime' not in df.columns:
            return df

        df['datetime_30min'] = pd.to_datetime(df['datetime']).dt.floor('30min')
        return df

    # =========================================================================
    # VALIDATE (required by base class)
    # =========================================================================

    def validate(self, df: pd.DataFrame) -> bool:
        """Validate output DataFrame."""
        return True  # Accept any result

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_traffic_summary(self, df: pd.DataFrame) -> Dict:
        """Get summary statistics of traffic data."""
        if df.empty:
            return {}

        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_anchors': len(df),
            'control_anchors': int(df['is_control'].sum()),
            'avg_speed': round(df['current_speed'].mean(), 1),
            'avg_jam_factor': round(df['jam_factor'].mean(), 1),
            'avg_speed_drop': round(df['speed_drop_ratio'].mean(), 2),
            'severe_count': int((df['severity'] == 'SEVERE').sum()),
            'high_count': int((df['severity'] == 'HIGH').sum()),
            'incidents_count': int(df['has_incident'].sum()) if 'has_incident' in df.columns else 0,
        }

        return summary
