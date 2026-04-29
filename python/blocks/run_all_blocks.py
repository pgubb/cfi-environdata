"""Orchestrator: run all block-level extraction steps and merge into a single output CSV."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_config, init_gee
from utils_blocks import load_blocks, save_block_output


def main():
    config = load_config()
    init_gee(config)
    blocks_cfg = config["blocks"]
    block_id_field = blocks_cfg["block_id_field"]

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    city_lookup = blocks_gdf.set_index(block_id_field)["city"]

    # --- Indicator 1: Elevation ---
    print("\n=== Block Indicator 1: Elevation (SRTM 30m) ===")
    from extract_elevation_blocks import extract_elevation_blocks
    elevation_df = extract_elevation_blocks(blocks_gdf, config)
    elevation_df["city"] = elevation_df["block_id"].map(city_lookup)
    save_block_output(elevation_df, "elevation_blocks", config)

    # --- Indicator 2: Extreme Heat Days ---
    print("\n=== Block Indicator 2: Extreme Heat Days (MODIS LST) ===")
    from extract_heat_blocks import extract_heat_blocks
    heat_df = extract_heat_blocks(blocks_gdf, config)
    heat_df["city"] = heat_df["block_id"].map(city_lookup)
    save_block_output(heat_df, "heat_blocks", config)

    # --- Indicator 3: Flood Vulnerability ---
    print("\n=== Block Indicator 3: Flood Vulnerability (HAND + JRC) ===")
    from extract_flood_blocks import extract_flood_blocks
    flood_df = extract_flood_blocks(blocks_gdf, config)
    flood_df["city"] = flood_df["block_id"].map(city_lookup)
    save_block_output(flood_df, "flood_blocks", config)

    # --- Indicator 4: Tree Canopy Cover ---
    print("\n=== Block Indicator 4: Tree Canopy Cover (ESA WorldCover 10m) ===")
    from extract_canopy_blocks import extract_canopy_blocks
    canopy_df = extract_canopy_blocks(blocks_gdf, config)
    canopy_df["city"] = canopy_df["block_id"].map(city_lookup)
    save_block_output(canopy_df, "canopy_blocks", config)

    # --- Indicator 5: Rainfall ---
    print("\n=== Block Indicator 5: Heavy Rainfall Days (CHIRPS Daily) ===")
    from extract_rainfall_blocks import extract_rainfall_blocks
    rainfall_df = extract_rainfall_blocks(blocks_gdf, config)
    rainfall_df["city"] = rainfall_df["block_id"].map(city_lookup)
    save_block_output(rainfall_df, "rainfall_blocks", config)

    # --- Indicator 6: Air Quality ---
    print("\n=== Block Indicator 6: Air Quality (MODIS MAIAC AOD) ===")
    from extract_airquality_blocks import extract_airquality_blocks
    airquality_df = extract_airquality_blocks(blocks_gdf, config)
    airquality_df["city"] = airquality_df["block_id"].map(city_lookup)
    save_block_output(airquality_df, "airquality_blocks", config)

    # --- Indicator 7: Nighttime Lights ---
    print("\n=== Block Indicator 7: Nighttime Lights (VIIRS) ===")
    from extract_nightlights_blocks import extract_nightlights_blocks
    nightlights_df = extract_nightlights_blocks(blocks_gdf, config)
    nightlights_df["city"] = nightlights_df["block_id"].map(city_lookup)
    save_block_output(nightlights_df, "nightlights_blocks", config)

    # --- Indicator 8: Built-up Surface Fraction ---
    print("\n=== Block Indicator 8: Built-up Surface Fraction (GHSL) ===")
    from extract_builtup_blocks import extract_builtup_blocks
    builtup_df = extract_builtup_blocks(blocks_gdf, config)
    builtup_df["city"] = builtup_df["block_id"].map(city_lookup)
    save_block_output(builtup_df, "builtup_blocks", config)

    # --- Merge all indicators ---
    print("\n=== Merging all block indicators ===")
    merged = blocks_gdf[[block_id_field, "city"]].copy()
    merged = merged.rename(columns={block_id_field: "block_id"})

    for indicator_df in [elevation_df, heat_df, flood_df, canopy_df,
                         rainfall_df, airquality_df, nightlights_df, builtup_df]:
        # Drop 'city' from indicator dfs to avoid merge conflicts
        cols_to_merge = [c for c in indicator_df.columns if c != "city"]
        merged = merged.merge(indicator_df[cols_to_merge], on="block_id", how="left")

    save_block_output(merged, "all_block_indicators", config)

    print(f"\nFinal dataset: {merged.shape[0]} rows x {merged.shape[1]} columns")
    print(f"Columns: {list(merged.columns)}")
    print("\nAll done.")


if __name__ == "__main__":
    main()
