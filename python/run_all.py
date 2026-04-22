"""Orchestrator: run all extraction steps and merge into a single output CSV."""

import sys
from pathlib import Path

import pandas as pd

from utils import load_config, init_gee, load_business_points, save_output


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    # --- Indicator 1: Elevation ---
    print("\n=== Indicator 1: Elevation (SRTM 30m) ===")
    from extract_elevation import extract_elevation
    elevation_df = extract_elevation(df, config)
    save_output(elevation_df, "elevation", config)

    # --- Indicator 2: Extreme Heat Days ---
    print("\n=== Indicator 2: Extreme Heat Days (MODIS LST) ===")
    from extract_heat import extract_heat
    heat_df = extract_heat(df, config)
    save_output(heat_df, "heat", config)

    # --- Indicator 3: Flood Vulnerability ---
    print("\n=== Indicator 3: Flood Vulnerability (HAND + JRC) ===")
    from extract_flood import extract_flood
    flood_df = extract_flood(df, config)
    save_output(flood_df, "flood", config)

    # --- Indicator 4: Tree Canopy Cover ---
    print("\n=== Indicator 4: Tree Canopy Cover (ESA WorldCover 10m) ===")
    from extract_canopy import extract_canopy
    canopy_df = extract_canopy(df, config)
    save_output(canopy_df, "canopy", config)

    # --- Indicator 5: Rainfall ---
    print("\n=== Indicator 5: Heavy Rainfall Days (CHIRPS Daily) ===")
    from extract_rainfall import extract_rainfall
    rainfall_df = extract_rainfall(df, config)
    save_output(rainfall_df, "rainfall", config)

    # --- Indicator 6: Air Quality ---
    print("\n=== Indicator 6: Air Quality (MODIS MAIAC AOD) ===")
    from extract_airquality import extract_airquality
    airquality_df = extract_airquality(df, config)
    save_output(airquality_df, "airquality", config)

    # --- Indicator 7: Nighttime Lights ---
    print("\n=== Indicator 7: Nighttime Lights (VIIRS) ===")
    from extract_nightlights import extract_nightlights
    nightlights_df = extract_nightlights(df, config)
    save_output(nightlights_df, "nightlights", config)

    # --- Indicator 8: Built-up Surface Fraction ---
    print("\n=== Indicator 8: Built-up Surface Fraction (GHSL) ===")
    from extract_builtup import extract_builtup
    builtup_df = extract_builtup(df, config)
    save_output(builtup_df, "builtup", config)

    # --- Merge all indicators ---
    print("\n=== Merging all indicators ===")
    merged = df[["business_id", "latitude", "longitude",
                  "fieldwork_date", "city"]].copy()
    merged["fieldwork_date"] = merged["fieldwork_date"].dt.strftime("%Y-%m-%d")

    for indicator_df in [elevation_df, heat_df, flood_df, canopy_df,
                         rainfall_df, airquality_df, nightlights_df, builtup_df]:
        merged = merged.merge(indicator_df, on="business_id", how="left")

    save_output(merged, "all_indicators", config)

    print(f"\nFinal dataset: {merged.shape[0]} rows x {merged.shape[1]} columns")
    print(f"Columns: {list(merged.columns)}")
    print("\nAll done.")


if __name__ == "__main__":
    main()
