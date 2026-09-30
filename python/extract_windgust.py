"""Indicator 16: Wind GUSTS from ERA5 (not ERA5-Land).

Indicator 15 gives climatological windiness from daily-mean wind. This gives the
quantity that actually damages premises. They answer different questions and
both are kept.

WHY A SECOND WIND INDICATOR, ON A DIFFERENT COLLECTION. ERA5-Land has no gust
band at all. The gust field exists only in ERA5 single levels
(`ECMWF/ERA5/HOURLY`), which is a coarser grid, so this is a deliberate trade of
resolution for the right variable:

    indicator 15  ERA5-Land  ~11km   daily MEAN wind   climatological windiness
    indicator 16  ERA5       ~28km   hourly max GUST   damage-relevant extremes

WHAT THIS BUYS. On the daily-mean field nothing in the five-city frame exceeds
8.4 m/s, so no conventional damage threshold could ever be crossed and the
day-counts are "windier days" rather than hazard. Gusts reach Beaufort 6 in
four of five cities, gale force in Delhi, and 27.3 m/s (Beaufort 10, storm) in
Sao Paulo. The thresholds here are therefore REAL ones off the Beaufort scale,
not numbers reverse-engineered to make a column vary.

WHAT IT DOES NOT BUY. At ~28km this is 2.5x COARSER than indicator 15 and
roughly one value per city. It is a better CROSS-CITY hazard measure and no
help whatever for ranking businesses within a city. No gridded source can fix
that: gusts are a boundary-layer quantity no satellite observes over land, and
every available product is a reanalysis. Scatterometers are ocean-only, and the
Global Wind Atlas downscales to 250m but models mean wind resource, not gusts.

Unlike indicator 15 this needs NO COASTAL FILL: ERA5 single levels covers ocean
as well as land, so there is no water mask to punch holes in coastal cities.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points, batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "windgust"


def _thr_name(thr: float) -> str:
    return f"gust_hours_gt{str(thr).replace('.', 'p')}ms"


def build_windgust_image(config: dict, start_date: str, end_date: str):
    """Stack of gust summaries for one window. Returns (image, names)."""
    g_cfg = config["windgust"]
    band = g_cfg["band"]

    col = (ee.ImageCollection(g_cfg["dataset"])
           .filterDate(start_date, end_date)
           .select(band))

    bands, names = [], []

    thresholds = g_cfg.get("thresholds_ms", [])
    if thresholds:
        # ONE map producing a multi-band indicator image, summed once.
        #
        # DO NOT rewrite this as one mapped collection per threshold, the idiom
        # the daily-resolution indicators use. Over an HOURLY collection
        # (17,520 images for a 2-year window) that costs a full pass per
        # threshold and times out: three separate passes over a single year
        # exceeded 10 minutes, while this single pass over the same year takes
        # ~44s. ee.Reducer.fixedHistogram(thr, 1000, 1) gives identical counts
        # and is also fine, but returns an array per feature rather than a
        # scalar, which does not fit the reduceRegions plumbing here.
        thr_names = [_thr_name(t) for t in thresholds]

        def indicators(img):
            return ee.Image.cat(
                [img.gt(t).rename(n) for t, n in zip(thresholds, thr_names)])

        bands.append(col.map(indicators).sum())
        names.extend(thr_names)

    # Continuous summaries. These are built-in collection reducers, which are
    # cheap even on an hourly collection.
    stats = []
    stat_names = []
    if g_cfg.get("compute_mean", True):
        stats.append(ee.Reducer.mean()); stat_names.append("gust_mean_ms")
    stats.append(ee.Reducer.max()); stat_names.append("gust_max_ms")
    reducer = stats[0]
    for r in stats[1:]:
        reducer = reducer.combine(r, "", True)
    pcts = g_cfg.get("percentiles", [])
    if pcts:
        reducer = reducer.combine(ee.Reducer.percentile(pcts), "", True)
        stat_names.extend(f"gust_p{p}_ms" for p in pcts)
    bands.append(col.reduce(reducer))
    names.extend(stat_names)

    stacked = ee.Image.cat(bands).rename(names)
    return stacked, names


def extract_windgust(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Gust summaries per business, grouped by city."""
    gee_cfg = config["gee"]
    g_cfg = config["windgust"]
    scale = g_cfg.get("scale_m", 27830)
    # Cost is dominated by the hourly collection reduction, not the point
    # count, so batch large - same profile as rainfall, airquality and no2.
    batch_size = g_cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = g_cfg.get("getinfo_timeout_sec")

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=g_cfg["trailing_years"])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}", flush=True)
        stacked, names = build_windgust_image(config, start_date, end_date)

        for batch in batch_points(city_df, batch_size):
            features = [
                ee.Feature(ee.Geometry.Point([r["longitude"], r["latitude"]]),
                           {"business_id": str(r["business_id"])})
                for _, r in batch.iterrows()]
            sampled = stacked.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.first(), scale=scale)

            batch_rows = []
            got = (safe_getinfo(sampled, timeout=timeout) if timeout
                   else safe_getinfo(sampled))
            for f in got["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for nm in names:
                    row[nm] = props.get(nm)
                batch_rows.append(row)
            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)
    print("Extracting wind gusts (ERA5 hourly)...")
    result = extract_windgust(df, config)
    save_output(result, INDICATOR_NAME, config)
    print(result.describe().to_string())


if __name__ == "__main__":
    main()
