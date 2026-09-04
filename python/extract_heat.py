"""Indicator 2: Extreme heat days from MODIS Land Surface Temperature."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "heat"


def _build_heat_image(config: dict, start_date: str, end_date: str):
    """Build the stacked heat-summary image for one time window.

    Built ONCE PER CITY rather than once per batch: the reduction runs over
    ~730 MODIS images, so rebuilding it for every 50 points was the dominant
    cost of this indicator.

    Returns (stacked_image, band_names).
    """
    heat_cfg = config["heat"]
    thresholds = heat_cfg["thresholds_celsius"]
    scale_factor = heat_cfg["scale_factor"]
    offset = heat_cfg["offset_kelvin_to_celsius"]

    modis = (
        ee.ImageCollection(heat_cfg["dataset"])
        .filterDate(start_date, end_date)
        .select(heat_cfg["band"])
    )

    # Convert raw DN to Celsius: DN * scale_factor + offset
    def to_celsius(img):
        return (
            img.multiply(scale_factor)
            .add(offset)
            .copyProperties(img, ["system:time_start"])
        )

    modis_c = modis.map(to_celsius)

    bands = []
    band_names = []

    # Threshold counts: for each threshold, count images where LST > threshold
    for t in thresholds:
        bands.append(modis_c.map(lambda img, t=t: img.gt(t)).sum())
        band_names.append(f"heat_days_gt{t}c")

    # Mean and max LST
    if heat_cfg.get("compute_continuous", True):
        bands.append(modis_c.mean())
        band_names.append("lst_mean_c")
        bands.append(modis_c.max())
        band_names.append("lst_max_c")

    # Valid observation count (non-masked pixels)
    bands.append(modis_c.count())
    band_names.append("lst_valid_obs")

    return ee.Image.cat(bands).rename(band_names), band_names


def _sample_heat_batch(batch_df, stacked, band_names, start_date, end_date):
    """Sample the stacked heat image at one batch of points."""
    features = []
    for _, row in batch_df.iterrows():
        geom = ee.Geometry.Point([row["longitude"], row["latitude"]])
        features.append(ee.Feature(geom, {
            "business_id": str(row["business_id"]),
        }))
    fc = ee.FeatureCollection(features)

    # MODIS LST is 1km, so sample at 1000m
    sampled = stacked.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.first(),
        scale=1000,
    )

    results = []
    for f in safe_getinfo(sampled)["features"]:
        props = f["properties"]
        row = {"business_id": props["business_id"]}
        for bn in band_names:
            row[bn] = props.get(bn)
        row["heat_window_start"] = start_date
        row["heat_window_end"] = end_date
        results.append(row)
    return results


def extract_heat(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract heat indicators for all businesses, grouped by city.

    Each city gets one fixed-length window (see utils.get_city_window and the
    time_window section of config.yaml), so `heat_days_gt*` counts are directly
    comparable across cities.
    """
    gee_cfg = config["gee"]
    trailing_years = config["heat"]["trailing_years"]

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=trailing_years)
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")

        stacked, band_names = _build_heat_image(config, start_date, end_date)

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
            append_checkpoint(
                _sample_heat_batch(batch, stacked, band_names,
                                   start_date, end_date),
                INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting extreme heat days (MODIS LST)...")
    result = extract_heat(df, config)
    save_output(result, "heat", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
