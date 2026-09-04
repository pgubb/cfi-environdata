"""Indicator 13: Building density from Google Open Buildings 2.5D Temporal.

`builtup_fraction` (indicator 8) measures the SHARE OF GROUND covered by built
surface. It cannot distinguish one large warehouse from forty small kiosks at
the same coverage — a distinction that matters for micro and small enterprises,
where small, dense, irregular footprints are a plausible signature of informal
commercial density.

This counts discrete buildings, measures their height, and derives their
typical footprint area, all from a 0.5m raster.
"""

import math

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress,
)

INDICATOR_NAME = "buildings"


def check_for_newer_year(config: dict):
    """Warn if Open Buildings has published a year newer than the pinned one."""
    cfg = config["buildings"]
    pinned = int(cfg["year"])
    try:
        ids = ee.ImageCollection(cfg["dataset"]).aggregate_array(
            "system:index").getInfo()
    except Exception as e:
        print(f"  (could not check for newer building years: {e})")
        return
    years = {int(i[-10:-6]) for i in ids if i[-10:-6].isdigit()}
    if years and max(years) > pinned:
        print(f"  ! Open Buildings now has {max(years)} data; config pins "
              f"{pinned}. Update buildings.year to use it (this invalidates "
              f"the cached building columns and recomputes them).")


def build_buildings_image(config: dict, bounds: ee.Geometry):
    """Three-band image: fractional count, presence, and building-masked height."""
    cfg = config["buildings"]
    b = cfg["bands"]
    year = str(int(cfg["year"]))

    # One mosaic per city-year. The collection is tiled by UTM zone and year,
    # with the year at the tail of system:index (e.g. 01_EPSG_32723_2023_06_30).
    coll = (ee.ImageCollection(cfg["dataset"])
            .filterBounds(bounds)
            .filter(ee.Filter.stringContains("system:index", year)))
    img = coll.mosaic()

    presence = img.select(b["presence"])
    # Height averaged over BUILDING pixels only. Masking here (rather than
    # dividing later) means ee.Reducer.mean uses each band's own valid pixels,
    # so open ground does not drag the mean toward zero.
    height = img.select(b["height"]).updateMask(
        presence.gt(cfg["height_presence_threshold"]))

    return ee.Image.cat([
        img.select(b["count"]).rename("f_count"),
        presence.rename("f_presence"),
        height.rename("f_height"),
    ])


def _extract_at_radius(df: pd.DataFrame, radius: int, config: dict) -> pd.DataFrame:
    """Building metrics within one buffer radius, for all points."""
    gee_cfg = config["gee"]
    cfg = config["buildings"]
    suffix = f"{radius}m"
    indicator_name = f"{INDICATOR_NAME}_{suffix}"
    scale = cfg.get("scale_m", 2)
    native = cfg.get("native_scale_m", 0.5)
    buffer_area_m2 = math.pi * radius ** 2
    # Every band is reduced with MEAN, and the building count is recovered
    # analytically: the mean fractional count per native pixel, times the number
    # of native pixels in the buffer. Doing it this way makes the result
    # independent of the reduction scale — a plain sum is NOT, because GEE
    # averages on resampling, so a 2m sum comes out (2/0.5)^2 = 16x too small.
    native_pixels = buffer_area_m2 / (native ** 2)

    remaining = filter_remaining_points(
        df, load_checkpoint(indicator_name, config))
    progress = BatchProgress(len(remaining), label=f"{suffix} ")

    for city, city_df in remaining.groupby("city"):
        bounds = ee.Geometry.Rectangle([
            float(city_df["longitude"].min()), float(city_df["latitude"].min()),
            float(city_df["longitude"].max()), float(city_df["latitude"].max()),
        ])
        img = build_buildings_image(config, bounds)

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
            features = [
                ee.Feature(ee.Geometry.Point([r["longitude"], r["latitude"]])
                           .buffer(radius),
                           {"business_id": str(r["business_id"])})
                for _, r in batch.iterrows()]
            sampled = img.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.mean(), scale=scale)

            batch_rows = []
            for f in safe_getinfo(sampled)["features"]:
                props = f["properties"]
                mean_count = props.get("f_count")
                mean_presence = props.get("f_presence")
                row = {"business_id": props["business_id"]}

                count = (mean_count * native_pixels
                         if mean_count is not None else None)
                row[f"building_count_{suffix}"] = count

                if radius == max(cfg["buffer_radii_m"]):
                    row[f"building_height_mean_{suffix}"] = props.get("f_height")
                    # Mean footprint = built area / number of buildings.
                    # Undefined where there are no buildings to average over.
                    if (count and count > 0 and mean_presence is not None):
                        row[f"building_mean_area_{suffix}"] = (
                            mean_presence * buffer_area_m2 / count)
                    else:
                        row[f"building_mean_area_{suffix}"] = None
                batch_rows.append(row)

            append_checkpoint(batch_rows, indicator_name, config)
            progress.update(len(batch))

    return finish_indicator(indicator_name, config)


def extract_buildings(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Building count, height and typical footprint around each business."""
    cfg = config["buildings"]
    check_for_newer_year(config)

    result = df[["business_id"]].drop_duplicates().copy()
    for radius in cfg["buffer_radii_m"]:
        print(f"  Buffer radius: {radius}m...")
        result = result.merge(
            _extract_at_radius(df, radius, config), on="business_id", how="left")
    return result


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)
    print("Extracting building density (Open Buildings 2.5D)...")
    result = extract_buildings(df, config)
    save_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
