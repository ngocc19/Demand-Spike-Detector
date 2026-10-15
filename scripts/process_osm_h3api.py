"""
Process OSM data - Using h3 API directly
=========================================
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Tuple

import h3
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

HANOI_CENTER = (21.0285, 105.8542)
H3_RES = 8

PARQUET_PATH = Path("data/h3_osm_capacity.parquet")
CSV_PATH = Path("data/h3_osm_capacity.csv")
META_PATH = Path("data/h3_osm_capacity_meta.json")

ROAD_WEIGHTS = {
    'motorway': 10.0, 'motorway_link': 8.0, 'trunk': 8.0, 'trunk_link': 6.0,
    'primary': 5.0, 'primary_link': 4.0, 'secondary': 3.0, 'secondary_link': 2.5,
    'tertiary': 2.0, 'tertiary_link': 1.5, 'residential': 1.0, 'unclassified': 0.8, 'service': 0.5,
}


def generate_grid() -> Tuple[List[str], Dict]:
    """Generate H3 hex grid."""
    center = h3.latlng_to_cell(HANOI_CENTER[0], HANOI_CENTER[1], H3_RES)
    hexes = set()
    radius = 1

    while len(hexes) < 3000:
        hexes.update(h3.grid_disk(center, radius))
        radius += 5
        if radius > 150:
            break

    hexes = [h for h in hexes if h3.is_valid_cell(h) and h3.get_resolution(h) == H3_RES]
    centroids = {h: h3.cell_to_latlng(h) for h in hexes}
    logger.info(f"Generated {len(hexes)} hexes")
    return hexes, centroids


def process():
    """Process OSM geometry using h3 API directly."""
    logger.info("Loading OSM data...")
    with open("data/osm_with_geometry.json", 'r') as f:
        data = json.load(f)

    elements = data.get('elements', [])
    ways = [e for e in elements if e['type'] == 'way' and e.get('geometry')]

    logger.info(f"Loaded {len(ways):,} ways with geometry")

    hexes, centroids = generate_grid()

    # Initialize tracking per hex
    hex_scores: Dict[str, Dict] = {
        h: {'score': 0.0, 'count': 0, 'types': set()}
        for h in hexes
    }

    # Process each way
    logger.info("Processing ways...")
    total = len(ways)
    start = time.time()

    for i, way in enumerate(ways):
        if i % 20000 == 0 and i > 0:
            elapsed = time.time() - start
            rate = i / elapsed
            eta = (total - i) / rate
            logger.info(f"  {i:,}/{total:,} ({i/total*100:.1f}%) ETA: {eta:.0f}s")

        hw = way.get('tags', {}).get('highway', '')
        weight = ROAD_WEIGHTS.get(hw, 0.1)
        geom = way.get('geometry', [])

        # Get unique hexes this way passes through
        way_hexes = set()
        for p in geom:
            lat, lon = p['lat'], p['lon']
            hex_id = h3.latlng_to_cell(lat, lon, H3_RES)
            if hex_id in hexes:
                way_hexes.add(hex_id)

        # Assign score to each hex
        if way_hexes:
            score_per_hex = weight / len(way_hexes)
            for hex_id in way_hexes:
                hex_scores[hex_id]['score'] += score_per_hex
                hex_scores[hex_id]['count'] += 1
                hex_scores[hex_id]['types'].add(hw)

    # Build results
    logger.info("Building results...")
    results = []
    for h in hexes:
        lat, lon = centroids[h]
        s = hex_scores[h]
        results.append({
            'hex_id': h,
            'osm_capacity_score': s['score'],
            'osm_road_score': s['score'],
            'road_count': s['count'],
            'hex_lat': lat,
            'hex_lon': lon,
        })

    df = pd.DataFrame(results)

    # Stats
    nonzero = (df['road_count'] > 0).sum()
    logger.info(f"Hexes with roads: {nonzero}/{len(df)}")

    # Normalize
    scores = df['osm_capacity_score']
    min_s, max_s = scores.min(), scores.max()
    logger.info(f"Score range: [{min_s:.2f}, {max_s:.2f}]")

    if max_s > min_s:
        df['osm_capacity_index'] = 0.01 + (scores - min_s) / (max_s - min_s) * 0.99
    else:
        df['osm_capacity_index'] = 0.5

    df['osm_capacity_index'] = df['osm_capacity_index'].clip(0.01, 1.0)
    df['osm_infra_score'] = df['osm_road_score'] * 0.1
    df['infra_count'] = (df['road_count'] * 0.2).astype(int)

    df = df.sort_values('hex_id').reset_index(drop=True)

    # Save
    df.to_parquet(PARQUET_PATH, index=False, compression='snappy')
    df.to_csv(CSV_PATH, index=False)

    meta = {
        'version': '1.0',
        'generated_at': pd.Timestamp.now().isoformat(),
        'source': 'Overpass API (OpenStreetMap)',
        'total_hexes': len(df),
        'hexes_with_roads': int(nonzero),
        'capacity_range': {
            'min': float(df['osm_capacity_index'].min()),
            'max': float(df['osm_capacity_index'].max()),
            'mean': float(df['osm_capacity_index'].mean()),
        },
    }
    with open(META_PATH, 'w') as f:
        json.dump(meta, f, indent=2)

    logger.info("=" * 60)
    logger.info("COMPLETE!")
    logger.info(f"Saved {len(df)} hexes to {PARQUET_PATH}")

    print("\nSample data:")
    print(df[['hex_id', 'osm_capacity_index', 'road_count', 'hex_lat', 'hex_lon']].head(15).to_string(index=False))

    # Verify weather hexes
    weather = pd.read_parquet('data/weather_anchors_30T_merged.parquet')
    weather_hexes = set(weather['h3_index'].dropna().unique())
    osm_hexes = set(df['hex_id'].unique())
    coverage = weather_hexes & osm_hexes

    logger.info(f"\nWeather hexes coverage:")
    logger.info(f"  Weather hexes: {len(weather_hexes)}")
    logger.info(f"  Covered: {len(coverage)}/{len(weather_hexes)}")

    for h in weather_hexes:
        score = df[df['hex_id'] == h]['osm_capacity_index'].values
        count = df[df['hex_id'] == h]['road_count'].values
        if len(score) > 0:
            logger.info(f"  {h}: index={score[0]:.4f}, roads={count[0]}")

    return df


if __name__ == "__main__":
    process()
