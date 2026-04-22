"""Indicator 8: Built-up surface fraction from JRC GHSL."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def extract_builtup(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute mean built-up surface fraction within a buffer around each
    business using JRC Global Human Settlement Layer (GHSL).

    Returns DataFrame with columns:
    - business_id
    - builtup_fraction_50m: mean built-up fraction within 50m buffer (0-1)
    - builtup_fraction_150m: mean built-up fraction within 150m buffer (0-1)
    """
    bu_cfg = config["builtup"]
    gee_cfg = config["gee"]

    ghsl = ee.Image(bu_cfg["dataset"]).select(bu_cfg["band"])

    # GHSL built-up surface is a percentage (0-100); normalise to 0-1
    ghsl_frac = ghsl.divide(100)

    all_results = []
    for radius in bu_cfg["buffer_radii_m"]:
        suffix = f"{radius}m"
        print(f"  Buffer radius: {radius}m...")

        for batch in batch_points(df, gee_cfg["batch_size"]):
            features = []
            for _, row in batch.iterrows():
                point = ee.Geometry.Point([row["longitude"], row["latitude"]])
                buffered = point.buffer(radius)
                features.append(ee.Feature(buffered, {
                    "business_id": str(row["business_id"]),
                }))
            fc = ee.FeatureCollection(features)

            sampled = ghsl_frac.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=bu_cfg.get("scale_m", 10),
            )

            for f in sampled.getInfo()["features"]:
                props = f["properties"]
                bid = props["business_id"]
                # Find or create row for this business
                existing = next((r for r in all_results if r["business_id"] == bid), None)
                if existing is None:
                    existing = {"business_id": bid}
                    all_results.append(existing)
                existing[f"builtup_fraction_{suffix}"] = props.get("mean")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting built-up surface fraction (GHSL)...")
    result = extract_builtup(df, config)
    save_output(result, "builtup", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
