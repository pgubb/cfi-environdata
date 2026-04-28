"""Utilities for the block-level aggregation pipeline.

Loads sampling frame block polygons from GeoJSON, converts them to GEE
FeatureCollections, and provides batching helpers for zonal reductions.
"""

import json
import sys
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd

# Allow imports from parent package (python/)
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee, save_output  # noqa: E402


# Country directory name → city name
DEFAULT_COUNTRY_CITY_MAP = {
    "Brazil": "Sao Paulo",
    "Ethiopia": "Addis Ababa",
    "India": "Delhi",
    "Indonesia": "Jakarta",
    "Nigeria": "Lagos",
}


def load_blocks(config: dict) -> gpd.GeoDataFrame:
    """Load all block polygons from GeoJSON files.

    Reads one GeoJSON per country from the configured source directory,
    adds a ``city`` column derived from the country directory name, and
    returns a single GeoDataFrame with all blocks across cities.

    Block IDs are prefixed with the city name to ensure uniqueness across
    cities (the raw GeoJSON files use simple numeric IDs that collide).
    """
    blocks_cfg = config["blocks"]
    source_dir = Path(__file__).parent.parent.parent / blocks_cfg["source_dir"]
    block_id_field = blocks_cfg["block_id_field"]
    country_city = blocks_cfg.get("country_city_map", DEFAULT_COUNTRY_CITY_MAP)

    frames = []
    for country_dir, city in country_city.items():
        geojson_path = source_dir / country_dir / "final_sampling_grid_2026.geojson"
        if not geojson_path.exists():
            print(f"  Warning: {geojson_path} not found, skipping {city}")
            continue

        gdf = gpd.read_file(geojson_path)

        # Prefix block_id with city to ensure global uniqueness
        gdf[block_id_field] = city + "_" + gdf[block_id_field].astype(str)
        gdf["city"] = city

        frames.append(gdf)
        print(f"  Loaded {len(gdf)} blocks for {city}")

    if not frames:
        raise FileNotFoundError(
            f"No block GeoJSON files found in {source_dir}. "
            f"Expected subdirectories: {list(country_city.keys())}"
        )

    all_blocks = pd.concat(frames, ignore_index=True)
    print(f"Total: {len(all_blocks)} blocks across {all_blocks['city'].nunique()} cities")
    return all_blocks


def blocks_to_fc(gdf: gpd.GeoDataFrame, block_id_field: str = "block_id") -> ee.FeatureCollection:
    """Convert a GeoDataFrame of block polygons to a GEE FeatureCollection.

    Each row becomes an ee.Feature with the polygon geometry and block_id
    as a property.
    """
    features = []
    for _, row in gdf.iterrows():
        geo_if = row.geometry.__geo_interface__
        geom = ee.Geometry(geo_if)
        features.append(ee.Feature(geom, {
            "block_id": str(row[block_id_field]),
        }))
    return ee.FeatureCollection(features)


def batch_blocks(gdf: gpd.GeoDataFrame, batch_size: int):
    """Yield successive batches of rows from the GeoDataFrame."""
    for start in range(0, len(gdf), batch_size):
        yield gdf.iloc[start:start + batch_size]


def get_analysis_window(config: dict, trailing_years: int = 2):
    """Return (start_date, end_date) strings for the fixed analysis period.

    Uses blocks.analysis_end_date from config and the indicator's
    trailing_years to compute the start date.
    """
    end_date = config["blocks"]["analysis_end_date"]
    end = pd.Timestamp(end_date)
    start = end - pd.DateOffset(years=trailing_years)
    return start.strftime("%Y-%m-%d"), end_date


def get_analysis_window_months(config: dict, trailing_months: int = 12):
    """Return (start_date, end_date) strings for a month-based window."""
    end_date = config["blocks"]["analysis_end_date"]
    end = pd.Timestamp(end_date)
    start = end - pd.DateOffset(months=trailing_months)
    return start.strftime("%Y-%m-%d"), end_date


def save_block_output(df: pd.DataFrame, name: str, config: dict):
    """Save a block-level DataFrame to the configured block output directory."""
    out_dir = Path(__file__).parent.parent.parent / config["blocks"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")
    return out_path
