"""Indicator 7: Nighttime lights from VIIRS monthly composites."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def extract_nightlights(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute mean nighttime radiance within a buffer around each business
    using VIIRS monthly nighttime lights.

    Uses the 12-month period ending at each record's fieldwork_date.

    Returns DataFrame with columns:
    - business_id
    - ntl_mean_radiance: mean radiance within buffer (nW/cm2/sr)
    - ntl_median_radiance: median monthly radiance within buffer
    - ntl_max_radiance: max monthly radiance within buffer
    """
    ntl_cfg = config["nightlights"]
    gee_cfg = config["gee"]
    buffer_radius = ntl_cfg["buffer_radius_m"]

    all_results = []

    for date_val, group in df.groupby("fieldwork_date"):
        end_date = date_val.strftime("%Y-%m-%d")
        start_date = (date_val - pd.DateOffset(months=ntl_cfg["trailing_months"])).strftime("%Y-%m-%d")

        print(f"  Processing nightlights for fieldwork_date={date_val.date()} "
              f"({len(group)} businesses)...")

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

        for batch in batch_points(group, gee_cfg["batch_size"]):
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

            for f in sampled.getInfo()["features"]:
                props = f["properties"]
                all_results.append({
                    "business_id": props["business_id"],
                    "ntl_mean_radiance": props.get("ntl_mean_radiance"),
                    "ntl_median_radiance": props.get("ntl_median_radiance"),
                    "ntl_max_radiance": props.get("ntl_max_radiance"),
                })

    return pd.DataFrame(all_results)


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
