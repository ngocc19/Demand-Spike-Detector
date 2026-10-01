"""
Demand Spike Detector - Data Simulation Pipeline
================================================

Simulates Proxy Demand Index (D_proxy) for Hanoi H3 Hexagon Grid
based on NYC taxi/Uber research methodology adapted for Vietnam.

Proxy Formula:
    D_proxy(hex_i, t) = D_base(hex_i, Hour, Weekday) × (1 + Δ_traffic + Δ_weather_flood + Δ_event)

Components:
- D_base: Baseline demand from POI density
- Δ_traffic: Traffic congestion factor
- Δ_weather_flood: Weather + flood impact
- Δ_event: Event-based demand spike

Author: Demand Spike Detector Team
Reference: Correa & Moyano (2023) - NYC Taxi/Uber Demand Prediction
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import h3
import logging
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class SimulationConfig:
    """Configuration for demand simulation."""
    # H3 Grid
    h3_resolution: int = 8  # ~0.7 km² per hexagon

    # Hanoi bounds
    hanoi_center: Tuple[float, float] = (21.0285, 105.8542)  # Hoan Kiem
    hanoi_radius_km: float = 15.0

    # Time range (8 weeks for model training)
    weeks_of_data: int = 8
    time_window_minutes: int = 30  # 30-min windows as specified

    # Baseline demand parameters
    base_demand_mean: float = 50.0  # Average requests per window
    base_demand_std: float = 15.0

    # Impact factors (multiplicative)
    traffic_impact_range: Tuple[float, float] = (-0.2, 0.3)  # -20% to +30%
    weather_impact_range: Tuple[float, float] = (-0.3, 0.5)
    flood_impact_range: Tuple[float, float] = (-0.6, 0.2)
    event_impact_range: Tuple[float, float] = (0.0, 1.5)  # Up to 150% spike

    # Seasonal adjustments
    monsoon_season: Tuple[int, int] = (5, 10)  # May-October


# =============================================================================
# H3 GRID GENERATOR
# =============================================================================

class HanoiHexGrid:
    """Generate and manage H3 hexagon grid for Hanoi."""

    def __init__(self, resolution: int = 8):
        self.resolution = resolution
        self._hexagons: Optional[List[str]] = None
        self._centroids: Optional[Dict[str, Tuple[float, float]]] = None
        self._poi_density: Optional[Dict[str, float]] = None

    @property
    def hexagons(self) -> List[str]:
        """Get all hexagon IDs in the grid."""
        if self._hexagons is None:
            self._generate_grid()
        return self._hexagons

    @property
    def centroids(self) -> Dict[str, Tuple[float, float]]:
        """Get centroid (lat, lon) for each hexagon."""
        if self._centroids is None:
            self._generate_grid()
        return self._centroids

    @property
    def poi_density(self) -> Dict[str, float]:
        """Get POI density for each hexagon (0-1 normalized)."""
        if self._poi_density is None:
            self._generate_grid()
        return self._poi_density

    def _generate_grid(self) -> None:
        """Generate hexagon grid for Hanoi metropolitan area."""
        # Hanoi approximate bounds
        HANOI_BOUNDS = {
            'min_lat': 20.85,
            'max_lat': 21.15,
            'min_lng': 105.65,
            'max_lng': 105.95,
        }

        hexagons = set()
        centroids = {}

        # Generate hexagons covering Hanoi
        lat_step = 0.005
        lng_step = 0.005

        lat = HANOI_BOUNDS['min_lat']
        while lat <= HANOI_BOUNDS['max_lat']:
            lng = HANOI_BOUNDS['min_lng']
            while lng <= HANOI_BOUNDS['max_lng']:
                try:
                    hex_id = h3.latlng_to_cell(lat, lng, self.resolution)
                    hexagons.add(hex_id)

                    # Calculate centroid
                    boundary = h3.cell_to_boundary(hex_id)
                    lats = [p[0] for p in boundary]
                    lngs = [p[1] for p in boundary]
                    centroids[hex_id] = (np.mean(lats), np.mean(lngs))
                except Exception:
                    pass
                lng += lng_step
            lat += lat_step

        self._hexagons = list(hexagons)
        self._centroids = centroids

        # Calculate POI density based on distance from center
        # Higher density near center (Hoan Kiem, Ba Dinh, Dong Da)
        center_lat, center_lng = 21.0285, 105.8542
        distances = []

        for hex_id in self._hexagons:
            lat, lng = self._centroids[hex_id]
            dist = np.sqrt((lat - center_lat)**2 + (lng - center_lng)**2)
            distances.append((hex_id, dist))

        # Normalize distances to 0-1 (1 = highest density)
        max_dist = max(d[1] for d in distances)
        self._poi_density = {
            hex_id: 1.0 - (dist / max_dist) * 0.8  # Range: 0.2-1.0
            for hex_id, dist in distances
        }

        logger.info(f"Generated {len(self._hexagons)} hexagons for Hanoi grid")

    def get_hex_at_latlon(self, lat: float, lon: float) -> Optional[str]:
        """Get hexagon ID for a given lat/lon."""
        return h3.latlng_to_cell(lat, lon, self.resolution)

    def get_neighbors(self, hex_id: str, ring: int = 1) -> List[str]:
        """Get neighboring hexagons."""
        return list(h3.grid_disk(hex_id, ring))

    def get_event_affected_hexes(
        self,
        center_lat: float,
        center_lng: float,
        radius_km: float
    ) -> List[str]:
        """Get all hexagons within a radius of an event location."""
        affected = []

        for hex_id in self._hexagons:
            lat, lng = self._centroids[hex_id]
            # Haversine approximation for short distances
            dist_km = 111 * np.sqrt((lat - center_lat)**2 + (lng - center_lng)**2)
            if dist_km <= radius_km:
                affected.append(hex_id)

        return affected


# =============================================================================
# DEMAND COMPONENT SIMULATORS
# =============================================================================

class BaseDemandSimulator:
    """Simulate baseline demand D_base based on time patterns."""

    def __init__(self, config: SimulationConfig):
        self.config = config

    def generate(
        self,
        hex_id: str,
        poi_density: float,
        hour: int,
        day_of_week: int,  # 0=Monday, 6=Sunday
        is_weekend: bool,
        is_holiday: bool,
        is_monsoon: bool
    ) -> float:
        """
        Generate baseline demand for a hexagon at a specific time.

        Inspired by NYC research: hour and day_of_week are top features.
        """
        # Base demand from POI density
        base = self.config.base_demand_mean * poi_density

        # Hour pattern (typical urban mobility)
        hour_factor = self._get_hour_factor(hour, is_weekend)

        # Day pattern
        day_factor = self._get_day_factor(day_of_week, is_weekend, is_holiday)

        # Seasonal adjustment
        monsoon_factor = 1.2 if is_monsoon else 1.0

        # Calculate D_base
        d_base = base * hour_factor * day_factor * monsoon_factor

        # Add random noise
        noise = np.random.normal(0, self.config.base_demand_std * 0.1)

        return max(0, d_base + noise)

    def _get_hour_factor(self, hour: int, is_weekend: bool) -> float:
        """Get demand multiplier based on hour of day."""
        if is_weekend:
            # Weekend pattern: later peak, more spread
            hour_pattern = {
                range(0, 6): 0.3,    # Early morning: low
                range(6, 9): 0.6,    # Morning: moderate
                range(9, 12): 1.0,   # Late morning: peak
                range(12, 14): 0.9,  # Lunch: slightly lower
                range(14, 17): 1.1,  # Afternoon: high
                range(17, 20): 1.3,  # Evening rush: peak
                range(20, 24): 0.8,  # Night: declining
            }
        else:
            # Weekday pattern: classic rush hours
            hour_pattern = {
                range(0, 6): 0.2,    # Early morning: very low
                range(6, 7): 0.4,    # 6-7 AM: rising
                range(7, 9): 1.2,    # Morning rush: high peak
                range(9, 12): 0.9,   # Late morning: normal
                range(12, 13): 0.8,   # Noon: slight dip
                range(13, 17): 1.0,  # Afternoon: normal
                range(17, 19): 1.4,  # Evening rush: highest peak
                range(19, 22): 0.9,  # Evening: declining
                range(22, 24): 0.5,  # Night: low
            }

        for hour_range, factor in hour_pattern.items():
            if hour in hour_range:
                return factor
        return 0.5

    def _get_day_factor(
        self,
        day_of_week: int,
        is_weekend: bool,
        is_holiday: bool
    ) -> float:
        """Get demand multiplier based on day of week."""
        if is_holiday:
            return 0.3  # Major reduction on holidays (people leave city)

        if is_weekend:
            return 0.8  # Weekend: ~20% less demand

        # Weekday pattern
        if day_of_week == 0:  # Monday
            return 0.9
        elif day_of_week == 4:  # Friday
            return 1.1  # Higher on Friday
        elif day_of_week == 5:  # Saturday (in is_weekend)
            return 0.8
        elif day_of_week == 6:  # Sunday
            return 0.7  # Lowest
        else:
            return 1.0


class WeatherFloodSimulator:
    """Simulate weather and flood impact factors."""

    def __init__(self, config: SimulationConfig):
        self.config = config

    def generate_weather_impact(
        self,
        temp_c: float,
        humidity_pct: float,
        precip_mm: float,
        is_monsoon: bool
    ) -> float:
        """
        Generate weather impact factor (Δ_weather).

        Based on NYC research: temperature and rainfall are key factors.
        """
        impact = 0.0

        # Temperature effect (comfortable range: 22-28°C)
        if temp_c < 20:
            impact -= 0.2  # Cold: people stay home
        elif temp_c < 22:
            impact -= 0.1
        elif temp_c > 32:
            impact -= 0.15  # Hot: people avoid going out
        elif temp_c > 35:
            impact -= 0.25  # Extreme heat
        else:
            impact += 0.05  # Comfortable

        # Humidity effect
        if humidity_pct > 85:
            impact -= 0.1
        elif humidity_pct > 90:
            impact -= 0.2

        # Rainfall effect (positive for ride-hailing)
        if precip_mm > 0:
            if precip_mm < 2:
                impact += 0.1  # Light rain: slight increase
            elif precip_mm < 10:
                impact += 0.2  # Moderate rain: significant increase
            elif precip_mm < 25:
                impact += 0.35  # Heavy rain: major increase
            else:
                impact -= 0.1  # Extreme: people stay home

        # Monsoon synergy
        if is_monsoon and precip_mm > 0:
            impact *= 1.2  # Amplify rain effect during monsoon

        # Clip to valid range
        return np.clip(impact, -0.5, 0.5)

    def generate_flood_impact(
        self,
        is_flooded: bool,
        flood_severity: int  # 1-3: minor, moderate, severe
    ) -> float:
        """
        Generate flood impact factor (Δ_flood).

        Hanoi-specific: flooding causes major demand disruption.
        """
        if not is_flooded:
            return 0.0

        if flood_severity == 1:  # Minor
            return -0.3
        elif flood_severity == 2:  # Moderate
            return -0.5
        else:  # Severe
            return -0.8


class TrafficSimulator:
    """Simulate traffic congestion impact."""

    def __init__(self, config: SimulationConfig):
        self.config = config

    def generate_impact(
        self,
        hour: int,
        is_rush_hour: bool,
        is_weekend: bool
    ) -> float:
        """Generate traffic congestion impact factor."""
        impact = 0.0

        # Rush hour congestion
        if is_rush_hour:
            if is_weekend:
                impact += 0.1  # Less severe on weekends
            else:
                impact += 0.2  # Major congestion on weekday rush

        # General hourly traffic pattern
        if hour in [7, 8, 17, 18]:
            impact += 0.1  # Peak congestion
        elif hour in [9, 10, 11, 13, 14, 15, 16, 19, 20]:
            impact += 0.05  # Moderate

        return np.clip(impact, -0.3, 0.3)


class EventSimulator:
    """Simulate event-based demand spikes."""

    # Common Hanoi events (date, name, radius_km, impact_multiplier)
    KNOWN_EVENTS = [
        # Football matches at My Dinh
        ('2026-06-15', 'Vietnam vs Thailand', 5.0, 1.2),
        ('2026-06-20', 'Vietnam vs Indonesia', 5.0, 1.3),
        # Weekend festivals
        ('2026-05-10', 'Hoan Kiem Festival', 2.0, 0.8),
        ('2026-09-02', 'National Day', 10.0, 0.6),  # Ngay Quoc khanh
        # Tet holiday migration
        ('2026-01-25', 'Pre-Tet Rush', 15.0, 0.4),
        ('2026-02-01', 'Tet Week', 15.0, -0.5),  # People leave
        # Rainy day simulation
        ('2026-07-15', 'Heavy Rain', 15.0, 0.5),
    ]

    def __init__(self, config: SimulationConfig):
        self.config = config
        self._random_events_enabled = True

    def generate_events(self, start_date: datetime, days: int) -> List[Dict]:
        """Generate random events for simulation period."""
        events = []

        # Add known events
        for date_str, name, radius, impact in self.KNOWN_EVENTS:
            event_date = datetime.strptime(date_str, '%Y-%m-%d')
            if start_date <= event_date <= start_date + timedelta(days=days):
                events.append({
                    'date': event_date,
                    'name': name,
                    'radius_km': radius,
                    'impact': impact,
                    'lat': 21.0285 + np.random.uniform(-0.05, 0.05),
                    'lon': 105.8542 + np.random.uniform(-0.05, 0.05),
                })

        # Add random events
        if self._random_events_enabled:
            n_random = int(days / 3)  # ~1 event per 3 days
            for _ in range(n_random):
                event_date = start_date + timedelta(
                    days=np.random.randint(0, days),
                    hours=np.random.randint(8, 20)
                )
                events.append({
                    'date': event_date,
                    'name': f'Random Event {np.random.randint(1, 100)}',
                    'radius_km': np.random.uniform(2, 8),
                    'impact': np.random.uniform(0.3, 1.0),
                    'lat': 21.0285 + np.random.uniform(-0.1, 0.1),
                    'lon': 105.8542 + np.random.uniform(-0.1, 0.1),
                })

        return sorted(events, key=lambda x: x['date'])

    def get_event_impact(
        self,
        hex_id: str,
        centroid: Tuple[float, float],
        timestamp: datetime,
        events: List[Dict],
        hex_grid: HanoiHexGrid
    ) -> float:
        """Calculate total event impact for a hexagon at a time."""
        total_impact = 0.0

        for event in events:
            # Check if within event time window (±2 hours)
            time_diff = abs((timestamp - event['date']).total_seconds() / 3600)
            if time_diff > 2:
                continue

            # Check if within event radius
            lat, lon = centroid
            dist_km = 111 * np.sqrt(
                (lat - event['lat'])**2 + (lon - event['lon'])**2
            )

            if dist_km <= event['radius_km']:
                # Linear decay with distance
                distance_factor = 1.0 - (dist_km / event['radius_km'])
                impact = event['impact'] * distance_factor
                total_impact += impact

        return total_impact


# =============================================================================
# MAIN DATA SIMULATOR
# =============================================================================

class DemandDataSimulator:
    """
    Complete demand data simulation pipeline.

    Generates synthetic demand data for training the baseline model.

    Usage:
        simulator = DemandDataSimulator()
        df = simulator.generate_dataset(
            start_date=datetime(2026, 7, 1),
            n_weeks=8
        )
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self.hex_grid = HanoiHexGrid(self.config.h3_resolution)
        self.base_demand = BaseDemandSimulator(self.config)
        self.weather_flood = WeatherFloodSimulator(self.config)
        self.traffic = TrafficSimulator(self.config)
        self.event_sim = EventSimulator(self.config)

        # Supply proxy (will be filled after generation)
        self.supply_proxy: Optional[pd.DataFrame] = None

    def generate_dataset(
        self,
        start_date: datetime,
        n_weeks: int = 8
    ) -> pd.DataFrame:
        """
        Generate complete demand dataset.

        Args:
            start_date: Start of simulation period
            n_weeks: Number of weeks to simulate

        Returns:
            DataFrame with columns:
            - hex_id, lat, lon
            - timestamp
            - D_base (baseline demand)
            - D_proxy (actual demand with impacts)
            - Delta components (Δ_traffic, Δ_weather, Δ_flood, Δ_event)
            - Supply_proxy (simulated supply)
        """
        logger.info(f"Generating {n_weeks} weeks of demand data...")

        # Generate events
        events = self.event_sim.generate_events(start_date, n_weeks * 7)
        logger.info(f"Generated {len(events)} events")

        # Generate time series
        n_windows = n_weeks * 7 * 24 * (60 // self.config.time_window_minutes)
        timestamps = [
            start_date + timedelta(minutes=i * self.config.time_window_minutes)
            for i in range(n_windows)
        ]

        rows = []

        for hex_id in self.hex_grid.hexagons:
            lat, lon = self.hex_grid.centroids[hex_id]
            poi_density = self.hex_grid.poi_density[hex_id]

            for ts in timestamps:
                # Time features
                hour = ts.hour
                day_of_week = ts.weekday()
                is_weekend = day_of_week >= 5
                is_holiday = self._is_holiday(ts)
                is_monsoon = self.config.monsoon_season[0] <= ts.month <= self.config.monsoon_season[1]
                is_rush_hour = (7 <= hour <= 9) or (17 <= hour <= 19)

                # Generate weather data
                weather_data = self._generate_weather(ts, is_monsoon)

                # Calculate impact factors
                d_base = self.base_demand.generate(
                    hex_id=hex_id,
                    poi_density=poi_density,
                    hour=hour,
                    day_of_week=day_of_week,
                    is_weekend=is_weekend,
                    is_holiday=is_holiday,
                    is_monsoon=is_monsoon
                )

                delta_traffic = self.traffic.generate_impact(
                    hour=hour,
                    is_rush_hour=is_rush_hour,
                    is_weekend=is_weekend
                )

                delta_weather = self.weather_flood.generate_weather_impact(
                    temp_c=weather_data['temp_c'],
                    humidity_pct=weather_data['humidity_pct'],
                    precip_mm=weather_data['precip_mm'],
                    is_monsoon=is_monsoon
                )

                # Simulate flood (random)
                is_flooded, flood_severity = self._simulate_flood(ts, lat, lon)
                delta_flood = self.weather_flood.generate_flood_impact(
                    is_flooded=is_flooded,
                    flood_severity=flood_severity
                )

                delta_event = self.event_sim.get_event_impact(
                    hex_id=hex_id,
                    centroid=(lat, lon),
                    timestamp=ts,
                    events=events,
                    hex_grid=self.hex_grid
                )

                # Calculate D_proxy
                d_proxy = d_base * (1 + delta_traffic + delta_weather + delta_flood + delta_event)
                d_proxy = max(0, d_proxy + np.random.normal(0, d_base * 0.05))

                # Simulate supply (typically ~85% of demand)
                supply_ratio = np.random.uniform(0.75, 0.95)
                supply_proxy = d_proxy * supply_ratio

                rows.append({
                    'hex_id': hex_id,
                    'lat': lat,
                    'lon': lon,
                    'poi_density': poi_density,
                    'timestamp': ts,
                    'hour': hour,
                    'day_of_week': day_of_week,
                    'is_weekend': int(is_weekend),
                    'is_holiday': int(is_holiday),
                    'is_monsoon': int(is_monsoon),
                    'is_rush_hour': int(is_rush_hour),
                    # Weather
                    'temp_c': weather_data['temp_c'],
                    'humidity_pct': weather_data['humidity_pct'],
                    'precip_mm': weather_data['precip_mm'],
                    # Demand
                    'D_base': d_base,
                    'Delta_traffic': delta_traffic,
                    'Delta_weather': delta_weather,
                    'Delta_flood': delta_flood,
                    'Delta_event': delta_event,
                    'D_proxy': d_proxy,
                    # Supply
                    'Supply_proxy': supply_proxy,
                    'Deficit_ratio': d_proxy / max(supply_proxy, 1),
                    # Flood
                    'is_flooded': int(is_flooded),
                    'flood_severity': flood_severity,
                })

        df = pd.DataFrame(rows)
        logger.info(f"Generated {len(df)} rows ({len(self.hex_grid.hexagons)} hex × {len(timestamps)} time windows)")

        # Store supply for later use
        self.supply_proxy = df[['hex_id', 'timestamp', 'Supply_proxy']].copy()

        return df

    def _generate_weather(
        self,
        ts: datetime,
        is_monsoon: bool
    ) -> Dict:
        """Generate synthetic weather data."""
        # Base temperature (Hanoi climate)
        month_temps = {
            1: 17, 2: 19, 3: 23, 4: 27, 5: 30, 6: 32,
            7: 32, 8: 31, 9: 29, 10: 26, 11: 22, 12: 18
        }

        temp_c = month_temps.get(ts.month, 28) + np.random.uniform(-3, 3)
        humidity_pct = np.random.uniform(60, 95)

        # Precipitation
        if is_monsoon:
            precip_mm = np.random.exponential(5) if np.random.random() < 0.6 else 0
        else:
            precip_mm = np.random.exponential(2) if np.random.random() < 0.2 else 0

        return {
            'temp_c': temp_c,
            'humidity_pct': humidity_pct,
            'precip_mm': precip_mm,
        }

    def _simulate_flood(
        self,
        ts: datetime,
        lat: float,
        lon: float
    ) -> Tuple[bool, int]:
        """Simulate flood conditions (rare event)."""
        # Low probability of flooding (except during monsoon)
        is_monsoon = self.config.monsoon_season[0] <= ts.month <= self.config.monsoon_season[1]

        if is_monsoon:
            prob = 0.02  # 2% per time window
        else:
            prob = 0.005  # 0.5%

        if np.random.random() < prob:
            severity = np.random.choice([1, 2, 3], p=[0.5, 0.35, 0.15])
            return True, severity

        return False, 0

    def _is_holiday(self, ts: datetime) -> bool:
        """Check if date is a holiday (simplified)."""
        # Major Vietnamese holidays
        holidays = [
            (1, 1),   # Tet Duong lich
            (4, 30),  # Ngay Giai phong
            (5, 1),   # Ngay Quoc te Lao dong
            (9, 2),   # Ngay Quoc khanh
            (9, 3),   # Mid-Autumn (approximate)
        ]

        # Check if weekend
        if ts.weekday() >= 5:
            return np.random.random() < 0.3  # Some weekends have effects

        return (ts.month, ts.day) in holidays

    def save_dataset(self, df: pd.DataFrame, path: str) -> None:
        """Save dataset to parquet."""
        df.to_parquet(path, index=False)
        logger.info(f"Saved dataset to {path}")

    def get_training_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract features for LightGBM model training.

        Target: D_proxy (actual demand)
        Features: Time + Weather + Flood + Event factors
        """
        features = df[[
            'hex_id', 'lat', 'lon', 'timestamp',
            'hour', 'day_of_week', 'is_weekend', 'is_holiday',
            'is_monsoon', 'is_rush_hour',
            'temp_c', 'humidity_pct', 'precip_mm',
            'is_flooded', 'flood_severity',
            'poi_density',
        ]].copy()

        features['D_proxy'] = df['D_proxy']
        features['D_base'] = df['D_base']

        return features


# =============================================================================
# STANDALONE SIMULATION
# =============================================================================

def run_simulation():
    """Run standalone simulation and save data."""
    print("="*70)
    print("DEMAND SPIKE DETECTOR - DATA SIMULATION")
    print("="*70)

    config = SimulationConfig(
        weeks_of_data=8,
        time_window_minutes=30,
    )

    simulator = DemandDataSimulator(config)

    # Generate 8 weeks of data starting July 2026
    start_date = datetime(2026, 7, 1)
    df = simulator.generate_dataset(start_date, n_weeks=8)

    # Show sample
    print("\nSample Data:")
    print(df.head(10).to_string())

    print("\nData Statistics:")
    print(f"  Total rows: {len(df):,}")
    print(f"  Hexagons: {df['hex_id'].nunique()}")
    print(f"  Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    print("\nDemand Statistics:")
    print(f"  D_base: mean={df['D_base'].mean():.1f}, std={df['D_base'].std():.1f}")
    print(f"  D_proxy: mean={df['D_proxy'].mean():.1f}, std={df['D_proxy'].std():.1f}")
    print(f"  Supply: mean={df['Supply_proxy'].mean():.1f}, std={df['Supply_proxy'].std():.1f}")

    print("\nImpact Factors (mean):")
    print(f"  Δ_traffic: {df['Delta_traffic'].mean():.3f}")
    print(f"  Δ_weather: {df['Delta_weather'].mean():.3f}")
    print(f"  Δ_flood: {df['Delta_flood'].mean():.3f}")
    print(f"  Δ_event: {df['Delta_event'].mean():.3f}")

    # Save to file
    output_path = 'data/simulated_demand_8w.parquet'
    simulator.save_dataset(df, output_path)

    print(f"\n✓ Dataset saved to {output_path}")

    return df, simulator


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    df, simulator = run_simulation()
