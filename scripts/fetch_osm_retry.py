"""
Fetch OSM data with robust retry
================================
"""

import json
import logging
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_RETRIES = 10
RETRY_DELAY = 60  # seconds between retries

HANOI_BOUNDS = {
    'min_lat': 20.90,
    'max_lat': 21.15,
    'min_lon': 105.55,
    'max_lon': 106.00,
}

def fetch_osm():
    """
    Fetch OSM data with automatic retry.
    Waits between retries to avoid rate limiting.
    """
    query = f"""
[out:json][timeout:300];
(
  way["highway"]({HANOI_BOUNDS['min_lat']},{HANOI_BOUNDS['min_lon']},{HANOI_BOUNDS['max_lat']},{HANOI_BOUNDS['max_lon']});
);
out geom;
"""

    headers = {
        'User-Agent': 'DemandSpikeDetector/1.0 (Hanoi Traffic Analysis)',
        'Accept': 'application/json'
    }

    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Attempt {attempt + 1}/{MAX_RETRIES}...")

            response = requests.post(
                OVERPASS_URL,
                data={'data': query},
                timeout=300,
                headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                elements = data.get('elements', [])

                # Check if we have geometry
                ways_with_geom = [e for e in elements if e.get('geometry')]

                logger.info(f"SUCCESS! Got {len(elements)} elements, {len(ways_with_geom)} with geometry")

                # Verify geometry
                if ways_with_geom:
                    sample = ways_with_geom[0]
                    geom = sample.get('geometry', [])
                    if geom:
                        logger.info(f"Sample: lat={geom[0]['lat']}, lon={geom[0]['lon']}")

                # Save
                output_path = Path("data/osm_with_geometry.json")
                with open(output_path, 'w') as f:
                    json.dump(data, f)

                logger.info(f"Saved to: {output_path}")
                return data

            elif response.status_code == 429:
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)

            elif response.status_code == 504:
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Timeout (504). Waiting {wait}s...")
                time.sleep(wait)

            else:
                logger.warning(f"HTTP {response.status_code}. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

        except requests.exceptions.Timeout:
            wait = RETRY_DELAY * (attempt + 1)
            logger.warning(f"Request timeout. Waiting {wait}s...")
            time.sleep(wait)

        except Exception as e:
            logger.warning(f"Error: {e}. Waiting {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error("All attempts failed!")
    return None


if __name__ == "__main__":
    result = fetch_osm()
    if result:
        print("\n✅ OSM data fetched successfully!")
    else:
        print("\n❌ Failed to fetch OSM data.")
