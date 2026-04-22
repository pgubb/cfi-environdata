"""Indicator 4: Tree canopy cover from ESA WorldCover 10m."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
)


def _extract_canopy_at_radius(
    df: pd.DataFrame, tree_mask: ee.Image, radius: int,
    scale: int, gee_cfg: dict,
) -> pd.DataFrame:
    """Compute tree cover fraction within a given buffer radius for all points.

    Returns DataFrame with columns named with the radius suffix, e.g.
    canopy_fraction_150m, canopy_pixel_count_150m, canopy_tree_pixels_150m.
    """
    suffix = f"{radius}m"
    all_results = []

    for batch in batch_points(df, gee_cfg["batch_size"]):
        features = []
        for _, row in batch.iterrows():
            point = ee.Geometry.Point([row["longitude"], row["latitude"]])
            buffered = point.buffer(radius)
            features.append(ee.Feature(buffered, {
                "business_id": str(row["business_id"]),
            }))
        fc = ee.FeatureCollection(features)

        sampled = tree_mask.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean().combine(
                ee.Reducer.count(), sharedInputs=True
            ).combine(
                ee.Reducer.sum(), sharedInputs=True
            ),
            scale=scale,
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            all_results.append({
                "business_id": props["business_id"],
                f"canopy_fraction_{suffix}": props.get("mean"),
                f"canopy_pixel_count_{suffix}": props.get("count"),
                f"canopy_tree_pixels_{suffix}": props.get("sum"),
            })

    return pd.DataFrame(all_results)


def extract_canopy(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Compute fraction of tree cover at multiple buffer radii around each
    business point using ESA WorldCover 10m.

    Returns DataFrame with columns per radius:
    - canopy_fraction_{r}m, canopy_pixel_count_{r}m, canopy_tree_pixels_{r}m
    """
    canopy_cfg = config["canopy"]
    gee_cfg = config["gee"]

    # Load ESA WorldCover and create a binary tree mask
    worldcover = (
        ee.ImageCollection(canopy_cfg["dataset"])
        .mosaic()
        .select(canopy_cfg["band"])
    )
    tree_mask = worldcover.eq(canopy_cfg["tree_class_value"]).rename("is_tree")

    radii = canopy_cfg["buffer_radii_m"]
    scale = canopy_cfg["scale_m"]

    result = df[["business_id"]].drop_duplicates().copy()
    for radius in radii:
        print(f"  Buffer radius: {radius}m...")
        radius_df = _extract_canopy_at_radius(
            df, tree_mask, radius, scale, gee_cfg
        )
        result = result.merge(radius_df, on="business_id", how="left")

    return result


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting tree canopy cover (ESA WorldCover 10m)...")
    result = extract_canopy(df, config)
    save_output(result, "canopy", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
