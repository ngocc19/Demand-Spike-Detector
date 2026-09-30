"""
H3 Spatial Mapper
================

Maps H3 hexagons to nearest anchor points using Haversine distance.
Also provides reverse mapping for data interpolation.

Usage:
    from h3_mapper import H3Mapper

    mapper = H3Mapper()

    # Get nearest anchor for a hex
    nearest = mapper.get_nearest_anchor('88415cb4e5fffff')
    # Returns: {'name': 'HoanKiem', 'distance_km': 2.3, ...}

    # Get all nearby anchors within radius
    nearby = mapper.get_nearby_anchors('88415cb4e5fffff', radius_km=10)

    # Get anchor data for a hex
    anchor_data = mapper.get_anchor_for_hex('88415cb4e5fffff')
"""

import h3
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class H3Mapper:
    """
    Maps H3 hexagons to anchor points using Haversine distance.

    Features:
    - Find nearest anchor for any H3 hex
    - Calculate Haversine distance
    - Weight-based interpolation from multiple anchors
    - Batch processing for large datasets
    """

    EARTH_RADIUS_KM = 6371.0  # Earth's radius in kilometers

    def __init__(self, anchors: List[Dict] = None):
        """
        Initialize H3 mapper.

        Args:
            anchors: List of anchor dictionaries with 'name', 'lat', 'lon'
        """
        # Default anchors for Hanoi
        self.anchors = anchors or [
            {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542, "region": "center"},
            {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925, "region": "west"},
            {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454, "region": "south"},
            {"name": "LongBien", "lat": 21.0470, "lon": 105.8920, "region": "east"},
            {"name": "TayHo", "lat": 21.0664, "lon": 105.8176, "region": "north"},
            {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042, "region": "airport"},
        ]

        # Pre-compute anchor coordinates as arrays for faster distance calculation
        self.anchor_names = [a['name'] for a in self.anchors]
        self.anchor_lats = np.array([a['lat'] for a in self.anchors])
        self.anchor_lons = np.array([a['lon'] for a in self.anchors])
        self.anchor_regions = {a['name']: a.get('region', '') for a in self.anchors}

        # Create lookup dictionary
        self.anchor_lookup = {a['name']: a for a in self.anchors}

        logger.info(f"H3Mapper initialized with {len(self.anchors)} anchors")

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate Haversine distance between two points.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Distance in kilometers
        """
        # Convert to radians
        lat1_rad = np.radians(lat1)
        lat2_rad = np.radians(lat2)
        delta_lat = np.radians(lat2 - lat1)
        delta_lon = np.radians(lon2 - lon1)

        # Haversine formula
        a = np.sin(delta_lat / 2) ** 2 + \
            np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2) ** 2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

        return H3Mapper.EARTH_RADIUS_KM * c

    def get_hex_center(self, hex_id: str) -> Tuple[float, float]:
        """
        Get center coordinates of a H3 hex.

        Args:
            hex_id: H3 index string

        Returns:
            Tuple of (lat, lon)
        """
        try:
            lat, lon = h3.h3_to_geo(hex_id)
            return lat, lon
        except Exception as e:
            logger.error(f"Invalid hex_id {hex_id}: {e}")
            return None, None

    def get_nearest_anchor(self, hex_id: str) -> Dict:
        """
        Get the nearest anchor point for a H3 hex.

        Args:
            hex_id: H3 index string

        Returns:
            Dictionary with anchor info and distance
        """
        lat, lon = self.get_hex_center(hex_id)
        if lat is None:
            return None

        # Calculate distance to all anchors
        distances = []
        for i, name in enumerate(self.anchor_names):
            dist = self.haversine_distance(lat, lon, self.anchor_lats[i], self.anchor_lons[i])
            distances.append((name, dist))

        # Sort by distance and return nearest
        distances.sort(key=lambda x: x[1])
        nearest_name, nearest_dist = distances[0]

        return {
            'hex_id': hex_id,
            'hex_lat': lat,
            'hex_lon': lon,
            'anchor_name': nearest_name,
            'anchor_lat': self.anchor_lookup[nearest_name]['lat'],
            'anchor_lon': self.anchor_lookup[nearest_name]['lon'],
            'anchor_region': self.anchor_lookup[nearest_name].get('region', ''),
            'distance_km': round(nearest_dist, 2),
        }

    def get_nearby_anchors(self, hex_id: str, radius_km: float = 10.0) -> List[Dict]:
        """
        Get all anchors within a radius of a H3 hex.

        Args:
            hex_id: H3 index string
            radius_km: Search radius in kilometers

        Returns:
            List of anchor dictionaries with distance info
        """
        lat, lon = self.get_hex_center(hex_id)
        if lat is None:
            return []

        nearby = []
        for i, name in enumerate(self.anchor_names):
            dist = self.haversine_distance(lat, lon, self.anchor_lats[i], self.anchor_lons[i])
            if dist <= radius_km:
                nearby.append({
                    'anchor_name': name,
                    'anchor_lat': self.anchor_lats[i],
                    'anchor_lon': self.anchor_lons[i],
                    'distance_km': round(dist, 2),
                    'weight': 1.0 / (dist + 0.1)  # Inverse distance weighting
                })

        # Sort by distance
        nearby.sort(key=lambda x: x['distance_km'])
        return nearby

    def get_inverse_distance_weight(self, hex_id: str, k: int = 3) -> List[Dict]:
        """
        Get k-nearest anchors with inverse distance weights.

        Args:
            hex_id: H3 index string
            k: Number of nearest anchors to return

        Returns:
            List of anchors with weights for interpolation
        """
        lat, lon = self.get_hex_center(hex_id)
        if lat is None:
            return []

        # Calculate all distances
        distances = []
        for i, name in enumerate(self.anchor_names):
            dist = self.haversine_distance(lat, lon, self.anchor_lats[i], self.anchor_lons[i])
            distances.append((name, dist, i))

        # Sort and take k nearest
        distances.sort(key=lambda x: x[1])
        nearest = distances[:k]

        # Calculate inverse distance weights
        result = []
        total_weight = sum(1.0 / (d[1] + 0.1) for d in nearest)

        for name, dist, idx in nearest:
            weight = (1.0 / (dist + 0.1)) / total_weight
            result.append({
                'anchor_name': name,
                'distance_km': round(dist, 2),
                'weight': round(weight, 4),
                'lat': self.anchor_lats[idx],
                'lon': self.anchor_lons[idx],
            })

        return result

    def map_hex_to_anchor(self, hex_id: str) -> str:
        """
        Get anchor name for a hex (simple mapping).

        Args:
            hex_id: H3 index string

        Returns:
            Anchor name string
        """
        nearest = self.get_nearest_anchor(hex_id)
        return nearest['anchor_name'] if nearest else None

    def map_h3_resolution(self, resolution: int = 8) -> List[str]:
        """
        Generate all H3 hexagons for a resolution covering Hanoi area.

        Args:
            resolution: H3 resolution (default 8)

        Returns:
            List of H3 hex IDs
        """
        # Hanoi bounding box
        min_lat, max_lat = 20.85, 21.25
        min_lon, max_lon = 105.70, 105.95

        # Generate hexagons
        hexes = h3.polyfill_geojson({
            "type": "Polygon",
            "coordinates": [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat]
            ]]
        }, resolution)

        logger.info(f"Generated {len(hexes)} H3 hexagons at resolution {resolution}")
        return list(hexes)

    def batch_map_anchors(self, hex_ids: List[str]) -> pd.DataFrame:
        """
        Batch map hexagons to anchors.

        Args:
            hex_ids: List of H3 hex IDs

        Returns:
            DataFrame with mapping results
        """
        results = []
        for hex_id in hex_ids:
            nearest = self.get_nearest_anchor(hex_id)
            if nearest:
                results.append(nearest)

        df = pd.DataFrame(results)
        logger.info(f"Mapped {len(results)} hexagons to anchors")
        return df

    def create_anchor_mapping_table(self, resolution: int = 8) -> pd.DataFrame:
        """
        Create a complete mapping table for all H3 hexagons.

        Args:
            resolution: H3 resolution

        Returns:
            DataFrame with hex_id, anchor_name, distance, etc.
        """
        hex_ids = self.map_h3_resolution(resolution)
        df = self.batch_map_anchors(hex_ids)

        # Add interpolation weights for top 3 anchors
        weights = []
        for _, row in df.iterrows():
            k_weights = self.get_inverse_distance_weight(row['hex_id'], k=3)
            weights.append(k_weights)

        # Flatten and create columns
        df['interpolation_weights'] = weights

        logger.info(f"Created mapping table with {len(df)} entries")
        return df

    def interpolate_value(self, hex_id: str, anchor_values: Dict[str, float],
                         method: str = 'inverse_distance') -> float:
        """
        Interpolate a value for a hex from anchor values.

        Args:
            hex_id: H3 hex ID
            anchor_values: Dictionary mapping anchor names to values
            method: Interpolation method ('inverse_distance' or 'nearest')

        Returns:
            Interpolated value
        """
        if method == 'nearest':
            nearest = self.get_nearest_anchor(hex_id)
            anchor_name = nearest['anchor_name']
            return anchor_values.get(anchor_name)

        elif method == 'inverse_distance':
            idw_weights = self.get_inverse_distance_weight(hex_id, k=len(self.anchors))
            total = 0.0
            total_weight = 0.0

            for item in idw_weights:
                anchor_name = item['anchor_name']
                weight = item['weight']
                value = anchor_values.get(anchor_name)

                if value is not None:
                    total += value * weight
                    total_weight += weight

            if total_weight > 0:
                return total / total_weight
            return None

        return None

    def __repr__(self):
        return f"H3Mapper(anchors={len(self.anchors)})"


# Convenience functions for direct usage
def get_nearest_anchor(hex_id: str, anchors: List[Dict] = None) -> Dict:
    """Get nearest anchor for a hex."""
    mapper = H3Mapper(anchors)
    return mapper.get_nearest_anchor(hex_id)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Haversine distance between two points."""
    return H3Mapper.haversine_distance(lat1, lon1, lat2, lon2)
