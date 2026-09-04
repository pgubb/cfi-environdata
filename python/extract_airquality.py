"""Indicator 6: Air quality from MODIS MAIAC Aerosol Optical Depth (AOD)."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window, GETINFO_TIMEOUT_SEC,
)

INDICATOR_NAME = "airquality"


def extract_airquality(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract AOD indicators for all businesses.

    Groups by city to build one MAIAC aggregation per city rather than
    per fieldwork date, since AOD at 1km varies spatially more than it
    varies over a few weeks.
    """
    aq_cfg = config["airquality"]
    gee_cfg = config["gee"]
    # Per-indicator overrides — see the airquality section of config.yaml for
    # why this indicator wants a much larger batch than the other seven.
    batch_size = aq_cfg.get("batch_size", gee_cfg["batch_size"])
    getinfo_timeout = aq_cfg.get("getinfo_timeout_sec", GETINFO_TIMEOUT_SEC)
    thresholds = aq_cfg["thresholds_aod"]
    scale_factor = aq_cfg["scale_factor"]
    trailing_years = aq_cfg["trailing_years"]

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        # Fixed-length window (see utils.get_city_window). Previously this
        # spanned min(date)-2yr to max(date), which is ~4 weeks LONGER than two
        # years and differed per city — inflating the *_days_gt* counts and
        # making them non-comparable across cities.
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=trailing_years)

        print(f"  {city}: {len(city_df)} businesses, window {start_date} to {end_date}")

        # filterBounds is ESSENTIAL here, unlike heat/rainfall. Those read daily
        # GRIDDED composites (one global image per day = 730 in a 2-year
        # window), so filterDate alone is enough. MCD19A2 is a GRANULE
        # collection with many overlapping swaths per day: filterDate alone
        # leaves 1,019,444 images to reduce over, against 55,098 once
        # restricted to one city — every request was reducing the entire global
        # MAIAC archive to sample a handful of points, which pushed each call
        # past GEE's ~5 min server limit.
        bounds = ee.Geometry.Rectangle([
            float(city_df["longitude"].min()), float(city_df["latitude"].min()),
            float(city_df["longitude"].max()), float(city_df["latitude"].max()),
        ])
        maiac = (
            ee.ImageCollection(aq_cfg["dataset"])
            .filterDate(start_date, end_date)
            .filterBounds(bounds)
            .select(aq_cfg["band"])
        )

        def to_aod(img):
            return img.multiply(scale_factor).copyProperties(img, ["system:time_start"])

        maiac_scaled = maiac.map(to_aod)

        bands = []
        band_names = []

        for t in thresholds:
            count_img = maiac_scaled.map(lambda img, t=t: img.gt(t)).sum()
            bands.append(count_img)
            band_names.append(f"aod_days_gt{str(t).replace('.', 'p')}")

        bands.append(maiac_scaled.mean())
        band_names.append("aod_mean")
        bands.append(maiac_scaled.max())
        band_names.append("aod_max")
        bands.append(maiac_scaled.median())
        band_names.append("aod_median")
        bands.append(maiac_scaled.count())
        band_names.append("aod_valid_obs")

        stacked = ee.Image.cat(bands).rename(band_names)

        for batch in batch_points(city_df, batch_size):
            batch_rows = []
            features = []
            for _, row in batch.iterrows():
                geom = ee.Geometry.Point([row["longitude"], row["latitude"]])
                features.append(ee.Feature(geom, {
                    "business_id": str(row["business_id"]),
                }))
            fc = ee.FeatureCollection(features)

            sampled = stacked.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.first(),
                scale=1000,
            )

            for f in safe_getinfo(sampled, timeout=getinfo_timeout)["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for bn in band_names:
                    row[bn] = props.get(bn)
                row["aod_window_start"] = start_date
                row["aod_window_end"] = end_date
                batch_rows.append(row)

            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting air quality (MODIS MAIAC AOD)...")
    result = extract_airquality(df, config)
    save_output(result, "airquality", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
