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
# safe_getinfo and its settings are re-exported from the point pipeline's utils
# rather than duplicated here. This file previously carried its own copy, which
# drifted: its `with ThreadPoolExecutor(...)` blocked in __exit__ until the
# worker finished, so a "timeout" still waited out the full server-side request
# before retrying, and it slept the backoff even after the final attempt. One
# definition means one place to fix.
from utils import (  # noqa: E402,F401
    load_config, init_gee, save_output, safe_getinfo,
    GETINFO_TIMEOUT_SEC, GETINFO_MAX_RETRIES, GETINFO_RETRY_BACKOFF,
)


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


# --- Checkpoint / resume support ---

def _checkpoint_path(indicator_name: str, config: dict) -> Path:
    """Return the path for an indicator's checkpoint CSV."""
    out_dir = Path(__file__).parent.parent.parent / config["blocks"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f".checkpoint_{indicator_name}.csv"


def load_checkpoint(indicator_name: str, config: dict) -> pd.DataFrame | None:
    """Load a partial-results checkpoint if it exists.

    Returns a DataFrame of already-processed rows, or None if no
    checkpoint exists.
    """
    cp = _checkpoint_path(indicator_name, config)
    if cp.exists():
        df = pd.read_csv(cp)
        print(f"  Resuming from checkpoint: {len(df)} blocks already processed")
        return df
    return None


def append_checkpoint(rows: list[dict], indicator_name: str, config: dict):
    """Append a batch of result rows to the checkpoint CSV.

    Creates the file with headers on first write; appends without
    headers on subsequent writes.
    """
    cp = _checkpoint_path(indicator_name, config)
    df = pd.DataFrame(rows)
    write_header = not cp.exists()
    df.to_csv(cp, mode="a", header=write_header, index=False)


def clear_checkpoint(indicator_name: str, config: dict):
    """Remove the checkpoint file after successful completion."""
    cp = _checkpoint_path(indicator_name, config)
    if cp.exists():
        cp.unlink()


def filter_remaining_blocks(
    blocks_gdf: gpd.GeoDataFrame,
    checkpoint_df: pd.DataFrame | None,
    block_id_field: str = "block_id",
) -> gpd.GeoDataFrame:
    """Return only blocks that haven't been processed yet."""
    if checkpoint_df is None or checkpoint_df.empty:
        return blocks_gdf
    done_ids = set(checkpoint_df["block_id"])
    remaining = blocks_gdf[~blocks_gdf[block_id_field].isin(done_ids)]
    print(f"  {len(remaining)} blocks remaining after checkpoint filter")
    return remaining
