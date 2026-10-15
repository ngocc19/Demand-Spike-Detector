"""
Traffic Data Generator
=====================

Module to simulate and generate traffic status target labels for H3 grid cells.
Uses Anchor Points + IDW interpolation + OSM calibration approach.

Architecture:
    35 Anchor Points (traffic hotspots) → cKDTree + IDW → 1,960 H3 cells → OSM calibration → target_traffic_ratio
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy.spatial import cKDTree
import h3


# ============================================================================
# ANCHOR POINTS DEFINITION
# ============================================================================

@dataclass
class AnchorPoint:
    """Represents a traffic anchor point with coordinates and metadata."""
    id: int
    name: str
    lat: float
    lon: float
    is_control: bool = False  # Control points always have free-flow speed


ANCHOR_POINTS: List[AnchorPoint] = [
    # Main arterial roads & major intersections
    AnchorPoint(1, "Đê La Thành (BV Nhi Trung ương)", 21.0278, 105.8022),
    AnchorPoint(2, "Nút giao Thái Hà – Chùa Bộc – Tây Sơn", 21.0065, 105.8196),
    AnchorPoint(3, "Nút giao Kim Mã – Liễu Giai – Nguyễn Chí Thanh", 21.0285, 105.8232),
    AnchorPoint(4, "Nút giao Nguyễn Chí Thanh – Đường Láng", 21.0341, 105.7877),
    AnchorPoint(5, "Cầu vượt Giảng Võ – Láng Hạ", 21.0234, 105.8123),
    AnchorPoint(6, "Nút giao Ô Chợ Dừa", 21.0342, 105.8356),
    AnchorPoint(7, "Nút giao Ngã Tư Sở", 21.0186, 105.7502),
    AnchorPoint(8, "Nút giao Ngã Tư Vọng – Đại La – Giải Phóng", 21.0138, 105.7824),
    AnchorPoint(9, "Nút giao Trường Chinh – Tôn Thất Tùng", 21.0085, 105.7856),
    AnchorPoint(10, "Nút giao Trương Định – Bạch Mai – Minh Khai", 21.0052, 105.8467),
    AnchorPoint(11, "Cầu Mai Động (Tam Trinh – Minh Khai)", 20.9723, 105.8745),
    AnchorPoint(12, "Nút giao Pháp Vân – Ngọc Hồi", 20.9512, 105.8923),
    AnchorPoint(13, "Vành đai 3 – Bến xe Nước Ngầm", 21.0324, 105.8645),
    AnchorPoint(14, "Nút giao Nguyễn Xiển – Nguyễn Trãi", 21.0067, 105.7889),
    AnchorPoint(15, "Lối lên Vành đai 3 (Thăng Long Number One)", 21.0423, 105.7545),
    AnchorPoint(16, "Nút giao Trần Duy Hưng – Khuất Duy Tiến (BigC)", 21.0178, 105.7895),
    AnchorPoint(17, "Nút giao Phạm Văn Đồng – Hoàng Quốc Việt", 21.0567, 105.7856),
    AnchorPoint(18, "Nút giao Cổ Nhuế – Phạm Văn Đồng", 21.0654, 105.7623),
    AnchorPoint(19, "Nút giao Trần Đăng Ninh – Cầu Giấy", 21.0432, 105.7956),
    AnchorPoint(20, "Cầu 361 – Nguyễn Khang (ven sông Tô Lịch)", 21.0523, 105.8023),
    AnchorPoint(21, "Nút giao Nguyễn Chánh – Dương Đình Nghệ", 21.0198, 105.7634),
    AnchorPoint(22, "Nút giao Cầu Nhật Tân – Võ Chí Công", 21.0765, 105.8324),
    AnchorPoint(23, "Hầm chui Hoàng Minh Giám – Lê Văn Lương", 21.0123, 105.7945),
    AnchorPoint(24, "Nút giao Tố Hữu – Vũ Trọng Khánh", 20.9678, 105.7523),
    AnchorPoint(25, "Nút giao Lê Đức Thọ – Hồ Tùng Mậu", 21.0389, 105.7445),
    AnchorPoint(26, "Ngã tư Geleximco – Lê Trọng Tấn (Hà Đông)", 20.9689, 105.7324),
    AnchorPoint(27, "Nút giao Cầu Chương Dương – Nguyễn Văn Cừ", 21.0145, 105.8556),
    AnchorPoint(28, "Nút giao Cổ Linh – Đàm Quang Trung (Vĩnh Tuy)", 21.0034, 105.8723),
    AnchorPoint(29, "Nút giao Nguyễn Văn Linh – Sài Đồng (QL5)", 21.0234, 105.8845),
    AnchorPoint(30, "Nút giao Lưu Khánh Đàm – Mai Chí Thọ (Việt Hưng)", 21.0489, 105.8645),
    # Control Points (always free-flow)
    AnchorPoint(31, "Đại lộ Thăng Long (Hoài Đức)", 21.0123, 105.6845, is_control=True),
    AnchorPoint(32, "Đường Võ Nguyên Giáp (nút QL5, hướng Nội Bài)", 21.0789, 105.8123, is_control=True),
    AnchorPoint(33, "Đường Trường Sa (giao QL3, Đông Anh)", 21.0923, 105.8234, is_control=True),
    AnchorPoint(34, "Đường dẫn Cao tốc HN-HP (Trâu Quỳ / Vinhomes)", 20.9656, 105.8567, is_control=True),
    AnchorPoint(35, "Trục Nam Hà Nội - Cienco 5 (KĐT Thanh Hà)", 20.9345, 105.7456, is_control=True),
]


# ============================================================================
# TRAFFIC DATA GENERATOR CLASS
# ============================================================================

class TrafficDataGenerator:
    """
    Generates simulated traffic status data for H3 grid cells.

    Pipeline:
        1. Simulate anchor point data (TomTom-style)
        2. Generate H3 hex grid around Hanoi
        3. Interpolate using IDW with cKDTree
        4. Calibrate with OSM capacity index

    Example:
        >>> generator = TrafficDataGenerator()
        >>> df = generator.generate_dataset(start_date="2024-01-01", days=7)
        >>> print(df.head())
              timestamp        hex_id  target_traffic_ratio
        0   2024-01-01    8a2a100d3fffff              0.23
        1   2024-01-01    8a2a100d7fffff              0.45
        2   2024-01-01    8a2a100d9fffff              0.67
    """

    HANOI_CENTER: Tuple[float, float] = (21.0285, 105.8542)  # Hoàn Kiếm lake
    H3_RESOLUTION: int = 8
    TARGET_HEX_COUNT: int = 1960

    def __init__(
        self,
        hanoi_center: Tuple[float, float] = None,
        h3_resolution: int = None,
        target_hex_count: int = None
    ):
        """
        Initialize TrafficDataGenerator.

        Args:
            hanoi_center: (lat, lon) center point for H3 grid
            h3_resolution: H3 resolution (default 8)
            target_hex_count: Target number of H3 hexagons (default 1960)
        """
        self.hanoi_center = hanoi_center or self.HANOI_CENTER
        self.h3_resolution = h3_resolution or self.H3_RESOLUTION
        self.target_hex_count = target_hex_count or self.TARGET_HEX_COUNT

        # Pre-compute anchor point coordinates
        self.anchor_coords = np.array([
            (ap.lat, ap.lon) for ap in ANCHOR_POINTS
        ])
        self.anchor_tree = cKDTree(self.anchor_coords)

        # Generate H3 grid
        self.h3_hexes = self._generate_h3_grid()
        self.hex_centroids = np.array([
            h3.cell_to_latlng(h) for h in self.h3_hexes
        ])  # (lat, lon) pairs

    def _generate_h3_grid(self) -> List[str]:
        """
        Generate H3 hex grid around Hanoi center.

        Returns:
            List of H3 hex IDs
        """
        # Get center cell
        center_cell = h3.latlng_to_cell(
            self.hanoi_center[0],
            self.hanoi_center[1],
            self.h3_resolution
        )

        # Create hex grid using grid_disk
        hexes = set()
        radius = 1

        while len(hexes) < self.target_hex_count:
            try:
                disk = h3.grid_disk(center_cell, radius)
                hexes.update(disk)
            except Exception:
                pass
            radius += 5  # Expand by 5 hexes per iteration

            if radius > 100:  # Safety limit
                break

        # Filter to valid hexes at target resolution
        valid_hexes = [
            h for h in hexes
            if h3.is_valid_cell(h) and h3.get_resolution(h) == self.h3_resolution
        ]

        return valid_hexes[:self.target_hex_count]

    def _get_hanoi_boundary(self) -> List[Tuple[float, float]]:
        """
        Get approximate Hanoi boundary polygon.

        Returns:
            List of (lat, lon) tuples forming the boundary
        """
        center_lat, center_lon = self.hanoi_center
        radius_km = 20  # ~20km radius covers most of Hanoi

        # Approximate boundary points
        coords = []
        num_points = 12

        for i in range(num_points):
            angle = 2 * np.pi * i / num_points
            lat = center_lat + (radius_km / 111) * np.cos(angle)
            lon = center_lon + (radius_km / (111 * np.cos(np.radians(center_lat)))) * np.sin(angle)
            coords.append((lat, lon))

        return coords

    def _simulate_daily_pattern(self, hour: int, is_weekend: bool) -> float:
        """
        Generate congestion multiplier based on time of day.

        Args:
            hour: Hour of day (0-23)
            is_weekend: Whether it's weekend

        Returns:
            Multiplier (0.0 = free flow, 1.0 = complete stop)
        """
        if is_weekend:
            # Softer peaks on weekend
            if 11 <= hour <= 14:  # Lunch
                return 0.35
            elif 18 <= hour <= 21:  # Dinner
                return 0.40
            else:
                return 0.15

        # Weekday pattern
        if 7 <= hour <= 9:  # Morning rush
            return 0.75
        elif 11 <= hour <= 13:  # Lunch
            return 0.45
        elif 17 <= hour <= 20:  # Evening rush
            return 0.85
        elif 22 <= hour or hour <= 5:  # Night
            return 0.10
        else:
            return 0.25

    def fetch_tomtom_anchor_data(
        self,
        start_date: datetime,
        days: int = 56
    ) -> pd.DataFrame:
        """
        Simulate 8-week traffic data for all anchor points.

        Args:
            start_date: Start date for simulation
            days: Number of days to simulate (default 56 = 8 weeks)

        Returns:
            DataFrame with columns: timestamp, anchor_id, anchor_name,
            currentSpeed, freeFlowSpeed, speed_drop_ratio
        """
        # Time slots: 30 minutes intervals
        slots_per_day = 48  # 24 * 2
        total_slots = days * slots_per_day

        # Generate timestamps
        timestamps = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        for _ in range(total_slots):
            timestamps.append(current)
            current += timedelta(minutes=30)

        records = []

        for anchor in ANCHOR_POINTS:
            # Free flow speed depends on road type
            # Control points = highway = 60-80 km/h
            # Regular points = arterial = 30-50 km/h
            base_free_flow = np.random.uniform(60, 80) if anchor.is_control else np.random.uniform(30, 50)

            for ts in timestamps:
                hour = ts.hour
                weekday = ts.weekday()  # 0=Monday, 6=Sunday
                is_weekend = weekday >= 5

                # Base congestion for this time
                base_congestion = self._simulate_daily_pattern(hour, is_weekend)

                # Random variation
                noise = np.random.normal(0, 0.05)
                congestion = np.clip(base_congestion + noise, 0.0, 1.0)

                # Control points always have near-free-flow
                if anchor.is_control:
                    congestion = np.random.uniform(0.05, 0.15)

                # Current speed
                current_speed = base_free_flow * (1 - congestion)

                records.append({
                    'timestamp': ts,
                    'anchor_id': anchor.id,
                    'anchor_name': anchor.name,
                    'lat': anchor.lat,
                    'lon': anchor.lon,
                    'currentSpeed': round(current_speed, 2),
                    'freeFlowSpeed': round(base_free_flow, 2),
                    'speed_drop_ratio': round(congestion, 4),
                    'is_control': anchor.is_control,
                })

        df = pd.DataFrame(records)
        return df

    def spatial_interpolation(self, anchor_df: pd.DataFrame) -> pd.DataFrame:
        """
        Interpolate traffic from anchor points to all H3 cells using IDW.

        Args:
            anchor_df: DataFrame with anchor point traffic data (one timestamp)

        Returns:
            DataFrame with interpolated traffic for all H3 cells
        """
        # Get unique timestamps
        timestamps = anchor_df['timestamp'].unique()

        all_interpolated = []

        for ts in timestamps:
            # Get anchor data for this timestamp
            ts_data = anchor_df[anchor_df['timestamp'] == ts]

            if ts_data.empty:
                continue

            # Build cKDTree for anchor points at this timestamp
            anchor_locs = ts_data[['lat', 'lon']].values
            anchor_values = ts_data['speed_drop_ratio'].values

            anchor_tree = cKDTree(anchor_locs)

            # For each H3 cell centroid, find 3 nearest anchors and interpolate
            for i, hex_id in enumerate(self.h3_hexes):
                hex_lat, hex_lon = self.hex_centroids[i]

                # Find 3 nearest anchors
                distances, indices = anchor_tree.query([hex_lat, hex_lon], k=min(3, len(anchor_locs)))

                # IDW interpolation
                if isinstance(distances, float):
                    distances = [distances]
                    indices = [indices]

                weights = []
                values = []

                for dist, idx in zip(distances, indices):
                    if dist < 1e-6:  # Very close to anchor
                        weights.append(1.0)
                        values.append(anchor_values[idx])
                    else:
                        # Inverse distance weighting: w = 1/d^p
                        p = 2  # Power parameter
                        weight = 1.0 / (dist ** p)
                        weights.append(weight)
                        values.append(anchor_values[idx])

                # Normalize weights
                total_weight = sum(weights)
                if total_weight > 0:
                    normalized_weights = [w / total_weight for w in weights]
                    interpolated_value = sum(w * v for w, v in zip(normalized_weights, values))
                else:
                    interpolated_value = 0.0

                all_interpolated.append({
                    'timestamp': ts,
                    'hex_id': hex_id,
                    'hex_lat': hex_lat,
                    'hex_lon': hex_lon,
                    'interpolated_traffic': round(interpolated_value, 4),
                    'nearest_anchor_count': len(distances),
                })

        return pd.DataFrame(all_interpolated)

    def calibrate_with_osm(
        self,
        interpolated_df: pd.DataFrame,
        seed: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Calibrate traffic with OSM road capacity index.

        The OSM index adjusts for road type:
        - Highway/major roads: capacity = 1.0
        - Residential streets: capacity = 0.5-0.7
        - Small lanes/alleys: capacity = 0.3-0.5

        Args:
            interpolated_df: DataFrame from spatial_interpolation()
            seed: Random seed for reproducibility

        Returns:
            DataFrame with added target_traffic_ratio column
        """
        if seed is not None:
            np.random.seed(seed)

        # Generate OSM capacity index for each hex
        # This is simulated - in production, would query OSM Overpass API
        osm_capacity = np.random.uniform(0.5, 1.0, len(self.h3_hexes))

        # Create mapping hex_id -> osm_capacity
        osm_map = dict(zip(self.h3_hexes, osm_capacity))

        # Add osm_capacity to dataframe
        interpolated_df = interpolated_df.copy()
        interpolated_df['osm_capacity'] = interpolated_df['hex_id'].map(osm_map)

        # Calculate target_traffic_ratio
        # High OSM capacity = traffic can flow even when congestion is high
        # Low OSM capacity =更容易 kẹt xe even with moderate congestion
        interpolated_df['target_traffic_ratio'] = (
            interpolated_df['interpolated_traffic'] *
            interpolated_df['osm_capacity']
        ).clip(0.0, 1.0)

        return interpolated_df

    def generate_dataset(
        self,
        start_date: str = "2024-01-01",
        days: int = 56,
        seed: int = 42
    ) -> pd.DataFrame:
        """
        Generate complete dataset with traffic labels.

        This is the main entry point.

        Args:
            start_date: Start date string (YYYY-MM-DD)
            days: Number of days to simulate (default 56 = 8 weeks)
            seed: Random seed for reproducibility

        Returns:
            DataFrame with columns:
                - timestamp: datetime
                - hex_id: H3 hex ID
                - target_traffic_ratio: final traffic label (0.0-1.0)
        """
        print(f"[TrafficDataGenerator] Generating dataset: {days} days from {start_date}")

        # Set seed for reproducibility
        np.random.seed(seed)

        # Parse start date
        start_dt = pd.to_datetime(start_date)

        # Step 1: Fetch anchor point data
        print(f"[TrafficDataGenerator] Step 1: Simulating {len(ANCHOR_POINTS)} anchor points...")
        anchor_df = self.fetch_tomtom_anchor_data(start_dt, days)
        print(f"[TrafficDataGenerator]   -> {len(anchor_df)} anchor records")

        # Step 2: Spatial interpolation
        print(f"[TrafficDataGenerator] Step 2: IDW interpolation to {len(self.h3_hexes)} H3 cells...")
        interpolated_df = self.spatial_interpolation(anchor_df)
        print(f"[TrafficDataGenerator]   -> {len(interpolated_df)} interpolated records")

        # Step 3: OSM calibration
        print(f"[TrafficDataGenerator] Step 3: OSM capacity calibration...")
        calibrated_df = self.calibrate_with_osm(interpolated_df, seed=seed)

        # Final output
        output_df = calibrated_df[['timestamp', 'hex_id', 'target_traffic_ratio']].copy()
        output_df = output_df.sort_values(['timestamp', 'hex_id']).reset_index(drop=True)

        print(f"[TrafficDataGenerator] Step 4: Complete!")
        print(f"[TrafficDataGenerator]   -> Total records: {len(output_df)}")
        print(f"[TrafficDataGenerator]   -> Unique timestamps: {output_df['timestamp'].nunique()}")
        print(f"[TrafficDataGenerator]   -> Unique hexes: {output_df['hex_id'].nunique()}")
        print(f"[TrafficDataGenerator]   -> target_traffic_ratio range: [{output_df['target_traffic_ratio'].min():.4f}, {output_df['target_traffic_ratio'].max():.4f}]")

        return output_df

    def get_anchor_summary(self) -> pd.DataFrame:
        """
        Get summary of anchor points.

        Returns:
            DataFrame with anchor point information
        """
        data = [
            {
                'anchor_id': ap.id,
                'name': ap.name,
                'lat': ap.lat,
                'lon': ap.lon,
                'is_control': ap.is_control,
            }
            for ap in ANCHOR_POINTS
        ]
        return pd.DataFrame(data)

    def get_h3_grid_info(self) -> Dict:
        """
        Get information about the H3 grid.

        Returns:
            Dict with grid statistics
        """
        return {
            'hex_count': len(self.h3_hexes),
            'resolution': self.h3_resolution,
            'center': self.hanoi_center,
            'sample_hexes': self.h3_hexes[:5],
        }


# ============================================================================
# STANDALONE FUNCTIONS
# ============================================================================

def generate_traffic_dataset(
    start_date: str = "2024-01-01",
    days: int = 56,
    seed: int = 42
) -> pd.DataFrame:
    """
    Convenience function to generate traffic dataset.

    Args:
        start_date: Start date string
        days: Number of days
        seed: Random seed

    Returns:
        DataFrame with traffic labels
    """
    generator = TrafficDataGenerator()
    return generator.generate_dataset(start_date, days, seed)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Traffic Data Generator - Standalone Test")
    print("=" * 60)

    # Initialize
    generator = TrafficDataGenerator()

    # Show anchor points
    print("\n[1] Anchor Points Summary:")
    anchors = generator.get_anchor_summary()
    print(f"    Total: {len(anchors)} points")
    print(f"    Control points: {anchors['is_control'].sum()}")

    # Show H3 grid info
    print("\n[2] H3 Grid Info:")
    grid_info = generator.get_h3_grid_info()
    for k, v in grid_info.items():
        print(f"    {k}: {v}")

    # Generate small dataset (1 day)
    print("\n[3] Generating test dataset (1 day)...")
    df = generator.generate_dataset(start_date="2024-01-01", days=1, seed=42)

    print("\n[4] Sample Output:")
    print(df.head(10).to_string(index=False))

    print("\n[5] Statistics:")
    print(df['target_traffic_ratio'].describe())

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
