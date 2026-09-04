"""Indicator 10: Population density from Meta's High Resolution Settlement Layer.

A second, independent population estimate alongside indicator 9 (WorldPop).
HRSL allocates census population only to cells where a CNN detected a building
footprint, at ~31m — a different method and a finer grid than WorldPop's
covariate-based disaggregation at ~93m. The two disagree enough (see the hrsl
section of config.yaml) that carrying both is a deliberate sensitivity check.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress,
)

INDICATOR_NAME = "hrsl"


def build_density_image(config: dict, bounds: ee.Geometry) -> ee.Image:
    """People per km2 from HRSL, over `bounds`.

    HRSL ships as global COG tiles, so the collection is restricted to the area
    of interest before mosaicking — without filterBounds the mosaic spans every
    tile on Earth.

    The band is a COUNT PER CELL, so it is divided by the pixel's true area.
    ee.Image.pixelArea() is used rather than a constant ~31m cell because HRSL
    is on a geographic grid whose cells narrow away from the equator.

    NOTE: the result is only meaningful when reduced at the native scale
    (hrsl.scale_m). pixelArea() reports the area of a pixel AT THE REQUESTED
    SCALE, while the band still holds a count per native cell, so reducing at a
    finer scale shrinks the denominator without shrinking the numerator and
    inflates the density.
    """
    hrsl_cfg = config["hrsl"]
    counts = (
        ee.ImageCollection(hrsl_cfg["dataset"])
        .filterBounds(bounds)
        .select(hrsl_cfg["band"])
        .mosaic()
    )
    return counts.divide(ee.Image.pixelArea()).multiply(1e6).rename("hrsl_density")


def _extract_at_radius(df: pd.DataFrame, radius: int, config: dict) -> pd.DataFrame:
    """Mean HRSL population density within one buffer radius, for all points."""
    gee_cfg = config["gee"]
    hrsl_cfg = config["hrsl"]
    suffix = f"{radius}m"
    indicator_name = f"{INDICATOR_NAME}_{suffix}"
    scale = hrsl_cfg.get("scale_m", 31)

    remaining = filter_remaining_points(
        df, load_checkpoint(indicator_name, config))
    progress = BatchProgress(len(remaining), label=f"{suffix} ")

    for city, city_df in remaining.groupby("city"):
        bounds = ee.Geometry.Rectangle([
            float(city_df["longitude"].min()), float(city_df["latitude"].min()),
            float(city_df["longitude"].max()), float(city_df["latitude"].max()),
        ])
        density = build_density_image(config, bounds)

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
            batch_rows = []
            features = []
            for _, row in batch.iterrows():
                point = ee.Geometry.Point([row["longitude"], row["latitude"]])
                features.append(ee.Feature(point.buffer(radius), {
                    "business_id": str(row["business_id"]),
                }))

            sampled = density.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.mean(),
                scale=scale,
            )

            for f in safe_getinfo(sampled)["features"]:
                props = f["properties"]
                batch_rows.append({
                    "business_id": props["business_id"],
                    f"hrsl_density_{suffix}": props.get("mean"),
                })

            append_checkpoint(batch_rows, indicator_name, config)
            progress.update(len(batch))

    return finish_indicator(indicator_name, config)


def extract_hrsl(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """HRSL population density around each business.

    Returns DataFrame with columns:
    - business_id
    - hrsl_density_{r}m: mean residents per km2 within each buffer radius
    """
    hrsl_cfg = config["hrsl"]

    result = df[["business_id"]].drop_duplicates().copy()
    for radius in hrsl_cfg["buffer_radii_m"]:
        print(f"  Buffer radius: {radius}m...")
        result = result.merge(
            _extract_at_radius(df, radius, config), on="business_id", how="left")
    return result


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting population density (Meta HRSL ~31m)...")
    result = extract_hrsl(df, config)
    save_output(result, "hrsl", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
