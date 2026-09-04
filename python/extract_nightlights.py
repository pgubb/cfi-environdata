"""Indicator 7: Nighttime lights from VIIRS monthly composites."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "nightlights"


def extract_nightlights(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute mean nighttime radiance within a buffer around each business
    using VIIRS monthly nighttime lights.

    Grouped by city, each with one fixed-length window (see
    utils.get_city_window and the time_window section of config.yaml).

    Returns DataFrame with columns:
    - business_id
    - ntl_mean_radiance: mean radiance within buffer (nW/cm2/sr)
    - ntl_median_radiance: median monthly radiance within buffer
    - ntl_max_radiance: max monthly radiance within buffer
    """
    ntl_cfg = config["nightlights"]
    gee_cfg = config["gee"]
    buffer_radius = ntl_cfg["buffer_radius_m"]

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_months=ntl_cfg["trailing_months"])

        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")

        viirs = (
            ee.ImageCollection(ntl_cfg["dataset"])
            .filterDate(start_date, end_date)
            .select(ntl_cfg["band"])
        )

        # Temporal composites
        ntl_mean = viirs.mean()
        ntl_median = viirs.median()
        ntl_max = viirs.max()

        stacked = ee.Image.cat([
            ntl_mean.rename("ntl_mean_radiance"),
            ntl_median.rename("ntl_median_radiance"),
            ntl_max.rename("ntl_max_radiance"),
        ])

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
            batch_rows = []
            features = []
            for _, row in batch.iterrows():
                point = ee.Geometry.Point([row["longitude"], row["latitude"]])
                buffered = point.buffer(buffer_radius)
                features.append(ee.Feature(buffered, {
                    "business_id": str(row["business_id"]),
                }))
            fc = ee.FeatureCollection(features)

            # Use mean reducer within the buffer (zonal mean of radiance)
            sampled = stacked.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=ntl_cfg.get("scale_m", 500),
            )

            for f in safe_getinfo(sampled)["features"]:
                props = f["properties"]
                batch_rows.append({
                    "business_id": props["business_id"],
                    "ntl_mean_radiance": props.get("ntl_mean_radiance"),
                    "ntl_median_radiance": props.get("ntl_median_radiance"),
                    "ntl_max_radiance": props.get("ntl_max_radiance"),
                })

            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting nighttime lights (VIIRS)...")
    result = extract_nightlights(df, config)
    save_output(result, "nightlights", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
