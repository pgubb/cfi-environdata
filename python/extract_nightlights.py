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

        layers = [
            ntl_mean.rename("ntl_mean_radiance"),
            ntl_median.rename("ntl_median_radiance"),
            ntl_max.rename("ntl_max_radiance"),
        ]
        # Month-to-month spread of radiance. See the data dictionary: monthly
        # compositing means this measures sustained lighting instability, NOT
        # short power outages.
        if ntl_cfg.get("compute_variability"):
            layers.append(viirs.reduce(ee.Reducer.stdDev())
                          .rename("ntl_sd_radiance"))
        stacked = ee.Image.cat(layers)

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
                row = {
                    "business_id": props["business_id"],
                    "ntl_mean_radiance": props.get("ntl_mean_radiance"),
                    "ntl_median_radiance": props.get("ntl_median_radiance"),
                    "ntl_max_radiance": props.get("ntl_max_radiance"),
                }
                if ntl_cfg.get("compute_variability"):
                    row["ntl_sd_radiance"] = props.get("ntl_sd_radiance")
                batch_rows.append(row)

            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    result = finish_indicator(INDICATOR_NAME, config)

    # Coefficient of variation: SD relative to level, so a dim street and a
    # bright one are comparable. Undefined (NaN) where mean radiance is <= 0.
    if ntl_cfg.get("compute_variability") and "ntl_sd_radiance" in result.columns:
        mean = result["ntl_mean_radiance"].where(result["ntl_mean_radiance"] > 0)
        result["ntl_cv_radiance"] = result["ntl_sd_radiance"] / mean
    return result


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
