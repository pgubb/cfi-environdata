"""Indicator 8: Built-up surface fraction from JRC GHSL."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress,
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

    # One frame per radius, merged at the end. Each radius checkpoints under its
    # own name so an interrupted run resumes at the radius and batch it stopped
    # on. (This also replaced a linear scan over accumulated results per feature,
    # which was quadratic in the number of businesses.)
    result = df[["business_id"]].drop_duplicates().copy()

    for radius in bu_cfg["buffer_radii_m"]:
        suffix = f"{radius}m"
        indicator_name = f"builtup_{suffix}"
        print(f"  Buffer radius: {radius}m...")

        remaining = filter_remaining_points(
            df, load_checkpoint(indicator_name, config))
        progress = BatchProgress(len(remaining), label=f"{suffix} ")

        for batch in batch_points(remaining, gee_cfg["batch_size"]):
            batch_rows = []
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

            for f in safe_getinfo(sampled)["features"]:
                props = f["properties"]
                batch_rows.append({
                    "business_id": props["business_id"],
                    f"builtup_fraction_{suffix}": props.get("mean"),
                })

            append_checkpoint(batch_rows, indicator_name, config)
            progress.update(len(batch))

        radius_df = finish_indicator(indicator_name, config)
        result = result.merge(radius_df, on="business_id", how="left")

    return result


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
