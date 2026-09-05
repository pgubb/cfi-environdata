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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
    """Load sampling-grid block polygons for the configured cities.

    Reads one GeoJSON per country from the blockexplorer repo, adds a `city`
    column, and prefixes block_id with the city name — the raw files use simple
    numeric ids that collide across cities, and every downstream merge is on
    block_id alone.

    Honours `blocks.include_cities` (null = all five) and
    `blocks.final_sample_only`. The latter is false by default: the flag marks
    only ~100 blocks per city, which is the fieldwork sample, not enough to draw
    a citywide map.
    """
    blocks_cfg = config["blocks"]
    source_dir = Path(__file__).resolve().parent.parent.parent / blocks_cfg["source_dir"]
    block_id_field = blocks_cfg["block_id_field"]
    country_city = blocks_cfg.get("country_city_map", DEFAULT_COUNTRY_CITY_MAP)
    wanted = blocks_cfg.get("include_cities") or list(country_city.values())
    unknown = [c for c in wanted if c not in country_city.values()]
    if unknown:
        raise ValueError(f"Unknown cities in blocks.include_cities: {unknown}")

    frames = []
    for country_dir, city in country_city.items():
        if city not in wanted:
            continue
        geojson_path = source_dir / country_dir / "final_sampling_grid_2026.geojson"
        if not geojson_path.exists():
            # include_cities is an explicit request, so a missing file is an
            # error: silently continuing would write an output file quietly
            # missing a city the caller asked for.
            raise FileNotFoundError(
                f"{city} was requested via blocks.include_cities but "
                f"{geojson_path} does not exist.")

        gdf = gpd.read_file(geojson_path)
        n_all = len(gdf)
        if blocks_cfg.get("final_sample_only") and "in_final_sample" in gdf:
            gdf = gdf[gdf["in_final_sample"].astype(bool)]

        gdf[block_id_field] = city + "_" + gdf[block_id_field].astype(str)
        gdf["city"] = city
        frames.append(gdf[[block_id_field, "city", "geometry"]])
        note = f" (of {n_all:,} in the grid)" if len(gdf) != n_all else ""
        print(f"  Loaded {len(gdf):,} blocks for {city}{note}")

    if not frames:
        raise FileNotFoundError(
            f"No block GeoJSON found in {source_dir} for cities {wanted}.")

    all_blocks = pd.concat(frames, ignore_index=True)
    if not all_blocks[block_id_field].is_unique:
        dupes = int(all_blocks[block_id_field].duplicated().sum())
        raise ValueError(f"{dupes} duplicate block ids after city prefixing.")
    print(f"Total: {len(all_blocks):,} blocks across "
          f"{all_blocks['city'].nunique()} cities")
    return all_blocks


def batch_blocks(gdf: gpd.GeoDataFrame, batch_size: int):
    """Yield successive batches of rows from the GeoDataFrame."""
    for start in range(0, len(gdf), batch_size):
        yield gdf.iloc[start:start + batch_size]


def get_analysis_window(config: dict, trailing_years: int = None,
                       trailing_months: int = None):
    """Return (start_date, end_date) for the analysis window.

    Reads time_window.analysis_end_date — THE SAME SETTING THE POINT PIPELINE
    USES. This pipeline previously had its own blocks.analysis_end_date, which
    silently put block maps and business-level values on different periods.
    """
    if (trailing_years is None) == (trailing_months is None):
        raise ValueError("Pass exactly one of trailing_years / trailing_months")
    end_date = (config.get("time_window", {}) or {}).get("analysis_end_date")
    if not end_date:
        raise ValueError(
            "time_window.analysis_end_date must be set for the block pipeline; "
            "blocks have no fieldwork date to anchor a window to.")
    end = pd.Timestamp(end_date)
    offset = (pd.DateOffset(years=trailing_years) if trailing_years is not None
              else pd.DateOffset(months=trailing_months))
    return (end - offset).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def save_block_output(df: pd.DataFrame, name: str, config: dict):
    """Save a block-level DataFrame to the configured block output directory."""
    out_dir = Path(__file__).resolve().parent.parent.parent / config["blocks"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")
    return out_path


# --- Checkpoint / resume support ---

def _checkpoint_path(indicator_name: str, config: dict) -> Path:
    """Return the path for an indicator's checkpoint CSV."""
    out_dir = Path(__file__).resolve().parent.parent.parent / config["blocks"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f".checkpoint_{indicator_name}.csv"


def load_checkpoint(indicator_name: str, config: dict,
                    verbose: bool = True) -> pd.DataFrame | None:
    """Load a partial-results checkpoint, or None if there is none.

    Signature mirrors utils.load_checkpoint (the point pipeline's) so the two
    are interchangeable; `verbose` exists so reading the checkpoint back at the
    END of a run does not print a misleading "resuming" line.
    """
    cp = _checkpoint_path(indicator_name, config)
    if not cp.exists():
        return None
    df = pd.read_csv(cp, dtype={"block_id": str})
    if verbose and len(df):
        print(f"  Resuming from checkpoint: {len(df):,} blocks already done")
    return df


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


