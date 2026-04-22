"""Indicator 6: Air quality from MODIS MAIAC Aerosol Optical Depth (AOD)."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def extract_airquality(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract AOD indicators for all businesses.

    Groups by city to build one MAIAC aggregation per city rather than
    per fieldwork date, since AOD at 1km varies spatially more than it
    varies over a few weeks.
    """
    aq_cfg = config["airquality"]
    gee_cfg = config["gee"]
    thresholds = aq_cfg["thresholds_aod"]
    scale_factor = aq_cfg["scale_factor"]
    trailing_years = aq_cfg["trailing_years"]

    all_results = []

    for city, city_df in df.groupby("city"):
        dates = city_df["fieldwork_date"]
        end_date = dates.max().strftime("%Y-%m-%d")
        start_date = (dates.min() - pd.DateOffset(years=trailing_years)).strftime("%Y-%m-%d")

        print(f"  {city}: {len(city_df)} businesses, window {start_date} to {end_date}")

        maiac = (
            ee.ImageCollection(aq_cfg["dataset"])
            .filterDate(start_date, end_date)
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

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
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

            for f in sampled.getInfo()["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for bn in band_names:
                    row[bn] = props.get(bn)
                row["aod_window_start"] = start_date
                row["aod_window_end"] = end_date
                all_results.append(row)

    return pd.DataFrame(all_results)


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
