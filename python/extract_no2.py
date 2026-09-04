"""Indicator 13: Traffic-related air pollution from Sentinel-5P NO2.

Aerosol Optical Depth (indicator 6) is column-integrated particulate loading,
which mixes traffic exhaust with regional dust, sea salt and biomass haze.
Tropospheric NO2 is specific to combustion — vehicles, generators, industry —
so it separates street-level sources from regional background. At ~1.1km it
also resolves finer than the survey's city strata.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window, GETINFO_TIMEOUT_SEC,
)

INDICATOR_NAME = "no2"


def build_no2_image(config: dict, bounds: ee.Geometry,
                    start_date: str, end_date: str):
    """Stack of NO2 summaries for one city-window. Returns (image, names)."""
    cfg = config["no2"]
    # filterBounds matters: this collection holds ~10,200 images in a two-year
    # window over one city and far more globally.
    coll = (ee.ImageCollection(cfg["dataset"])
            .filterDate(start_date, end_date)
            .filterBounds(bounds)
            .select(cfg["band"]))
    scaled = coll.map(lambda img: img.multiply(cfg["scale_factor"])
                      .copyProperties(img, ["system:time_start"]))
    bands = [scaled.mean(), scaled.max(), scaled.median(), scaled.count()]
    names = ["no2_mean", "no2_max", "no2_median", "no2_valid_obs"]
    return ee.Image.cat(bands).rename(names), names


def extract_no2(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Tropospheric NO2 per business, grouped by city."""
    gee_cfg = config["gee"]
    cfg = config["no2"]
    scale = cfg.get("scale_m", 1113)
    batch_size = cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = cfg.get("getinfo_timeout_sec", GETINFO_TIMEOUT_SEC)

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=cfg["trailing_years"])
        bounds = ee.Geometry.Rectangle([
            float(city_df["longitude"].min()), float(city_df["latitude"].min()),
            float(city_df["longitude"].max()), float(city_df["latitude"].max()),
        ])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")
        stacked, names = build_no2_image(config, bounds, start_date, end_date)

        for batch in batch_points(city_df, batch_size):
            features = [
                ee.Feature(ee.Geometry.Point([r["longitude"], r["latitude"]]),
                           {"business_id": str(r["business_id"])})
                for _, r in batch.iterrows()]
            sampled = stacked.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.first(), scale=scale)

            batch_rows = []
            for f in safe_getinfo(sampled, timeout=timeout)["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for nm in names:
                    row[nm] = props.get(nm)
                batch_rows.append(row)
            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)
    print("Extracting traffic-related NO2 (Sentinel-5P)...")
    result = extract_no2(df, config)
    save_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
