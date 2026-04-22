"""Indicator 3: Flood vulnerability from HAND + JRC Global Surface Water."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    df_to_ee_feature_collection, batch_points, save_output,
)


def load_hand(config: dict) -> ee.Image:
    """Load pre-computed HAND from MERIT Hydro (Yamazaki et al., 2019).

    HAND represents the vertical distance from each pixel to the nearest
    stream channel, following the drainage network downhill. Low HAND values
    indicate floodplain proximity.

    Resolution: ~90m. Coverage: global (60S–90N).
    """
    hand_cfg = config["flood"]["hand"]
    return ee.Image(hand_cfg["dataset"]).select(hand_cfg["band"])


def extract_flood(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract flood vulnerability indicators at each business point.

    Returns DataFrame with columns:
    - business_id
    - hand_m: Height Above Nearest Drainage (metres)
    - hand_flood_vulnerable: 1 if HAND <= threshold, else 0
    - jrc_max_extent: 1 if location within JRC max water extent, else 0
    - jrc_recurrence: Water recurrence percentage (0-100)
    - coastal_lowland: 1 if in coastal city and elevation < threshold
    """
    flood_cfg = config["flood"]
    gee_cfg = config["gee"]

    # HAND image (pre-computed from MERIT Hydro)
    hand_img = load_hand(config)

    # JRC Global Surface Water
    jrc_cfg = flood_cfg["jrc"]
    jrc = ee.Image(jrc_cfg["dataset"])
    jrc_max = jrc.select("max_extent")
    jrc_rec = jrc.select("recurrence")

    # Elevation (SRTM for coastal flag)
    elev_cfg = config["elevation"]
    elev = ee.Image(elev_cfg["dataset"]).select(elev_cfg["band"])

    # Stack all bands
    stacked = ee.Image.cat([
        hand_img.rename("hand_m"),
        jrc_max.rename("jrc_max_extent"),
        jrc_rec.rename("jrc_recurrence"),
        elev.rename("elevation_for_coastal"),
    ])

    all_results = []
    for batch in batch_points(df, gee_cfg["batch_size"]):
        fc = df_to_ee_feature_collection(batch)

        sampled = stacked.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.first(),
            scale=gee_cfg["default_scale_m"],
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            hand_val = props.get("hand_m")
            elev_val = props.get("elevation_for_coastal")
            city = props.get("city", "")

            # Binary HAND threshold
            hand_threshold = flood_cfg["hand"]["threshold_m"]
            flood_vulnerable = (
                1 if hand_val is not None and hand_val <= hand_threshold
                else 0
            )

            # Coastal lowland flag
            coastal_cities = flood_cfg.get("coastal_cities", [])
            coastal_threshold = flood_cfg.get("coastal_threshold_m", 10)
            coastal_flag = (
                1 if (city in coastal_cities
                      and elev_val is not None
                      and elev_val < coastal_threshold)
                else 0
            )

            all_results.append({
                "business_id": props["business_id"],
                "hand_m": hand_val,
                "hand_flood_vulnerable": flood_vulnerable,
                "jrc_max_extent": props.get("jrc_max_extent"),
                "jrc_recurrence": props.get("jrc_recurrence"),
                "coastal_lowland": coastal_flag,
            })

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting flood vulnerability (HAND + JRC)...")
    result = extract_flood(df, config)
    save_output(result, "flood", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
