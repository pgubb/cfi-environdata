"""Indicator 5: Heavy rainfall days from CHIRPS Daily precipitation."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def extract_rainfall(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract rainfall indicators for all businesses.

    Groups businesses by city to reduce redundant GEE computations —
    at CHIRPS 5.5km resolution, businesses within the same city share
    very few unique pixels, so per-date windows add negligible precision.
    Uses the city's full fieldwork date range (earliest - 2yr to latest).
    """
    rain_cfg = config["rainfall"]
    gee_cfg = config["gee"]
    thresholds = rain_cfg["thresholds_mm"]
    trailing_years = rain_cfg["trailing_years"]

    all_results = []

    for city, city_df in df.groupby("city"):
        # Use the widest window that covers all businesses in this city
        dates = city_df["fieldwork_date"]
        end_date = dates.max().strftime("%Y-%m-%d")
        start_date = (dates.min() - pd.DateOffset(years=trailing_years)).strftime("%Y-%m-%d")

        print(f"  {city}: {len(city_df)} businesses, window {start_date} to {end_date}")

        chirps = (
            ee.ImageCollection(rain_cfg["dataset"])
            .filterDate(start_date, end_date)
            .select(rain_cfg["band"])
        )

        bands = []
        band_names = []

        for t in thresholds:
            count_img = chirps.map(lambda img, t=t: img.gt(t)).sum()
            bands.append(count_img)
            band_names.append(f"rain_days_gt{t}mm")

        bands.append(chirps.sum())
        band_names.append("rain_total_mm")
        bands.append(chirps.max())
        band_names.append("rain_max_day_mm")
        bands.append(chirps.mean())
        band_names.append("rain_mean_daily_mm")
        bands.append(chirps.count())
        band_names.append("rain_valid_obs")

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
                scale=rain_cfg.get("scale_m", 5566),
            )

            for f in sampled.getInfo()["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for bn in band_names:
                    row[bn] = props.get(bn)
                row["rain_window_start"] = start_date
                row["rain_window_end"] = end_date
                all_results.append(row)

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting rainfall (CHIRPS Daily)...")
    result = extract_rainfall(df, config)
    save_output(result, "rainfall", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
