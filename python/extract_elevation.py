"""Indicator 1: Elevation above sea level from SRTM 30m."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    df_to_ee_feature_collection, batch_points, fc_to_dataframe, save_output,
)


def extract_elevation(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Sample SRTM elevation at each business point.

    Returns DataFrame with columns: business_id, elevation_m.
    """
    elev_cfg = config["elevation"]
    gee_cfg = config["gee"]
    srtm = ee.Image(elev_cfg["dataset"]).select(elev_cfg["band"])

    all_results = []
    for batch in batch_points(df, gee_cfg["batch_size"]):
        fc = df_to_ee_feature_collection(batch)

        sampled = srtm.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.first(),
            scale=gee_cfg["default_scale_m"],
        )

        features = sampled.getInfo()["features"]
        for f in features:
            props = f["properties"]
            all_results.append({
                "business_id": props["business_id"],
                "elevation_m": props.get("first"),
            })

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting elevation (SRTM 30m)...")
    result = extract_elevation(df, config)
    save_output(result, "elevation", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
