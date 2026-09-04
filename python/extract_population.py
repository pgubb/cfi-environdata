"""Indicator 9: Population density from WorldPop Global Project 100m."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress,
)

INDICATOR_NAME = "population"


def check_for_newer_year(config: dict) -> int | None:
    """Warn if WorldPop has published a year newer than the pinned one.

    Returns the newest available year. The pinned year is deliberately NOT
    auto-advanced: resolving "latest" at runtime would change the extracted
    values without changing the config fingerprint, so cached rows from an
    older year would be silently mixed with new ones.
    """
    pop_cfg = config["population"]
    pinned = int(pop_cfg["year"])
    try:
        years = (ee.ImageCollection(pop_cfg["dataset"])
                 .aggregate_array("year").distinct().getInfo())
    except Exception as e:  # never fail the run over a version check
        print(f"  (could not check for newer WorldPop years: {e})")
        return None

    newest = int(max(years))
    if newest > pinned:
        print(f"  ! WorldPop now has {newest} data; config pins {pinned}. "
              f"Update population.year in config.yaml to use it "
              f"(this invalidates the cached population column and recomputes).")
    return newest


def build_density_image(config: dict, bounds: ee.Geometry) -> ee.Image:
    """People per km2 for the configured year, over `bounds`.

    WorldPop ships one image per country per year, so the collection is
    filtered to the year, restricted to the area of interest, and mosaicked.
    filterBounds matters: without it the mosaic spans every country in the
    collection.

    The `population` band is a COUNT PER GRID CELL, so it is divided by the
    pixel's true area to give a density. Using ee.Image.pixelArea() rather than
    a constant cell size keeps this correct as cells narrow away from the
    equator.
    """
    pop_cfg = config["population"]
    counts = (
        ee.ImageCollection(pop_cfg["dataset"])
        .filter(ee.Filter.eq("year", int(pop_cfg["year"])))
        .filterBounds(bounds)
        .select(pop_cfg["band"])
        .mosaic()
    )
    # people per cell / (m2 per cell) * 1e6 m2 per km2 -> people per km2
    return counts.divide(ee.Image.pixelArea()).multiply(1e6).rename("pop_density")


def _extract_at_radius(df: pd.DataFrame, radius: int, config: dict) -> pd.DataFrame:
    """Mean population density within one buffer radius, for all points."""
    gee_cfg = config["gee"]
    pop_cfg = config["population"]
    suffix = f"{radius}m"
    indicator_name = f"{INDICATOR_NAME}_{suffix}"
    scale = pop_cfg.get("scale_m", 93)

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
            fc = ee.FeatureCollection(features)

            sampled = density.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=scale,
            )

            for f in safe_getinfo(sampled)["features"]:
                props = f["properties"]
                batch_rows.append({
                    "business_id": props["business_id"],
                    f"pop_density_{suffix}": props.get("mean"),
                })

            append_checkpoint(batch_rows, indicator_name, config)
            progress.update(len(batch))

    return finish_indicator(indicator_name, config)


def extract_population(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Population density around each business from WorldPop 100m.

    Returns DataFrame with columns:
    - business_id
    - pop_density_{r}m: mean residents per km2 within each buffer radius
    - pop_year: the WorldPop year the values came from
    """
    pop_cfg = config["population"]
    check_for_newer_year(config)

    result = df[["business_id"]].drop_duplicates().copy()
    for radius in pop_cfg["buffer_radii_m"]:
        print(f"  Buffer radius: {radius}m...")
        result = result.merge(
            _extract_at_radius(df, radius, config), on="business_id", how="left")

    result["pop_year"] = int(pop_cfg["year"])
    return result


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting population density (WorldPop 100m)...")
    result = extract_population(df, config)
    save_output(result, "population", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
