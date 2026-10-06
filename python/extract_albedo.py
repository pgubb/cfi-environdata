"""Indicator 18: Surface albedo from MODIS MCD43A3.

The share of incoming solar radiation a surface reflects rather than absorbs —
the property UPSTREAM of every heat indicator here, since it governs how much
energy reaches the surface at all, and the one that "cool roof" interventions
are designed to change.

TWO BANDS, BECAUSE NEITHER IS "THE" ALBEDO. White-sky albedo assumes fully
diffuse illumination, black-sky fully direct. The real figure sits between
them, weighted by the diffuse fraction of the incoming light, which varies with
sun angle and aerosol. Both are carried so that choice can be made downstream
rather than silently made here; white-sky is the usual single summary.

IT IS NOT A COOLING PROXY ON THIS FRAME — CHECK THE SIGN BEFORE MODELLING IT.
Measured within city over the block grids, albedo correlates POSITIVELY with
lst_max_c (+0.28). That is the opposite of the naive reading, in which a
brighter surface absorbs less and runs cooler. The likely explanation is that
the brightest surfaces in these cities are bare soil rather than pale roofs,
and bare ground is both bright AND hot — no evaporative cooling, low thermal
inertia, the classic desert signature. Worth testing properly before it is
relied on; the point is that a negative coefficient is a hypothesis here, not
a prior.

At 463m this is a NEIGHBOURHOOD value, not a premises one: a 50m buffer sits
deep inside one cell, so the point sample is taken at the pixel containing the
business rather than over buffers, as for the other coarse indicators.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points, batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "albedo"


def build_albedo_image(config: dict, start_date: str, end_date: str):
    """Mean white-sky and black-sky shortwave albedo. Returns (image, names)."""
    a = config["albedo"]
    b = a["bands"]
    col = ee.ImageCollection(a["dataset"]).filterDate(start_date, end_date)
    bands, names = [], []
    for key, out in (("wsa", "albedo_wsa"), ("bsa", "albedo_bsa")):
        bands.append(col.select(b[key]).mean()
                     .multiply(a["scale_factor"]).rename(out))
        names.append(out)
    return ee.Image.cat(bands).rename(names), names


def extract_albedo(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Albedo per business, grouped by city."""
    gee_cfg = config["gee"]
    a = config["albedo"]
    scale = a.get("scale_m", 463)
    batch_size = a.get("batch_size", gee_cfg["batch_size"])
    timeout = a.get("getinfo_timeout_sec")

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=a["trailing_years"])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}", flush=True)
        stacked, names = build_albedo_image(config, start_date, end_date)

        for batch in batch_points(city_df, batch_size):
            features = [
                ee.Feature(ee.Geometry.Point([r["longitude"], r["latitude"]]),
                           {"business_id": str(r["business_id"])})
                for _, r in batch.iterrows()]
            sampled = stacked.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.first(), scale=scale)

            rows = []
            got = (safe_getinfo(sampled, timeout=timeout) if timeout
                   else safe_getinfo(sampled))
            for f in got["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for nm in names:
                    row[nm] = props.get(nm)
                rows.append(row)
            append_checkpoint(rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)
    print("Extracting surface albedo (MODIS MCD43A3)...")
    result = extract_albedo(df, config)
    save_output(result, INDICATOR_NAME, config)
    print(result.describe().to_string())


if __name__ == "__main__":
    main()
