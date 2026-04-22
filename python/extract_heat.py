"""Indicator 2: Extreme heat days from MODIS Land Surface Temperature."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def _date_range_for_row(fieldwork_date: str, trailing_years: int):
    """Return (start_date, end_date) strings for the trailing window."""
    end = pd.Timestamp(fieldwork_date)
    start = end - pd.DateOffset(years=trailing_years)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def extract_heat_for_group(group_df: pd.DataFrame, config: dict) -> list[dict]:
    """Extract heat indicators for a group of businesses sharing the same
    fieldwork_date (and therefore the same MODIS time window).

    Returns a list of result dicts.
    """
    heat_cfg = config["heat"]
    gee_cfg = config["gee"]
    thresholds = heat_cfg["thresholds_celsius"]
    scale_factor = heat_cfg["scale_factor"]
    offset = heat_cfg["offset_kelvin_to_celsius"]

    fieldwork_date = group_df["fieldwork_date"].iloc[0].strftime("%Y-%m-%d")
    start_date, end_date = _date_range_for_row(
        fieldwork_date, heat_cfg["trailing_years"]
    )

    # Load and filter MODIS LST collection for this time window
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

    # Build a multi-band image with all summary statistics
    bands = []
    band_names = []

    # Threshold counts: for each threshold, count images where LST > threshold
    for t in thresholds:
        count_img = modis_c.map(lambda img, t=t: img.gt(t)).sum()
        bands.append(count_img)
        band_names.append(f"heat_days_gt{t}c")

    # Mean and max LST
    if heat_cfg.get("compute_continuous", True):
        bands.append(modis_c.mean())
        band_names.append("lst_mean_c")
        bands.append(modis_c.max())
        band_names.append("lst_max_c")

    # Valid observation count (non-masked pixels)
    valid_count = modis_c.count()
    bands.append(valid_count)
    band_names.append("lst_valid_obs")

    # Stack all bands into a single image
    stacked = ee.Image.cat(bands).rename(band_names)

    # Build FeatureCollection for this group
    features = []
    for _, row in group_df.iterrows():
        geom = ee.Geometry.Point([row["longitude"], row["latitude"]])
        features.append(ee.Feature(geom, {
            "business_id": str(row["business_id"]),
        }))
    fc = ee.FeatureCollection(features)

    # Sample at each point (MODIS is 1km, so use 1000m scale)
    sampled = stacked.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.first(),
        scale=1000,
    )

    results = []
    for f in sampled.getInfo()["features"]:
        props = f["properties"]
        row = {"business_id": props["business_id"]}
        for bn in band_names:
            row[bn] = props.get(bn)
        row["heat_window_start"] = start_date
        row["heat_window_end"] = end_date
        results.append(row)

    return results


def extract_heat(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract heat indicators for all businesses, grouping by fieldwork_date
    to reuse MODIS time windows.
    """
    gee_cfg = config["gee"]
    all_results = []

    # Group by fieldwork_date so we build the MODIS collection once per date
    for date_val, group in df.groupby("fieldwork_date"):
        print(f"  Processing heat for fieldwork_date={date_val.date()} "
              f"({len(group)} businesses)...")
        # Sub-batch within each date group
        for batch in batch_points(group, gee_cfg["batch_size"]):
            results = extract_heat_for_group(batch, config)
            all_results.extend(results)

    return pd.DataFrame(all_results)


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
