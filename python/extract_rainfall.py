"""Indicator 5: Heavy rainfall days from CHIRPS Daily precipitation."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window, GETINFO_TIMEOUT_SEC,
)


def max_dry_spell(collection: ee.ImageCollection, threshold: float) -> ee.Image:
    """Longest run of consecutive days below `threshold` mm, per pixel.

    Walks the time-ordered collection keeping a running streak: each dry day
    adds one, and multiplying by the dry mask resets the streak to zero on any
    wet day. The maximum ever reached is the answer.

    This is a materially different hazard from the dry-day COUNT: 415 dry days
    scattered through a year is not the same exposure as a single 60-day dry
    period, and only the spell distinguishes them. It is the measure that maps
    onto the survey's clim_event_drought item.

    CAVEAT: spells are truncated at the window edges. A dry period already
    underway on the start date, or still running on the end date, is cut off, so
    the true maximum can be longer than reported.
    """
    def step(img, state):
        state = ee.Dictionary(state)
        current = ee.Image(state.get("cur"))
        longest = ee.Image(state.get("max"))
        is_dry = ee.Image(img).lt(threshold)
        current = current.add(1).multiply(is_dry)
        return ee.Dictionary({"cur": current, "max": longest.max(current)})

    init = ee.Dictionary({"cur": ee.Image(0), "max": ee.Image(0)})
    ordered = collection.sort("system:time_start")
    return ee.Image(ee.Dictionary(ordered.iterate(step, init)).get("max"))

INDICATOR_NAME = "rainfall"


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
    # The dry-spell iterate walks 730 images, making each request ~5x costlier
    # while the cost stays independent of how many points it carries - the same
    # profile as air quality. Batch large.
    batch_size = rain_cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = rain_cfg.get("getinfo_timeout_sec", GETINFO_TIMEOUT_SEC)

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        # Fixed-length window (see utils.get_city_window). Previously this
        # spanned min(date)-2yr to max(date), which is ~4 weeks LONGER than two
        # years and differed per city — inflating the *_days_gt* counts and
        # making them non-comparable across cities.
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=trailing_years)

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

        # Dry days. Two definitions because they disagree materially - see the
        # config comment and the data dictionary.
        dry_thr = rain_cfg.get("dry_day_threshold_mm", 1.0)
        bands.append(chirps.map(lambda img, d=dry_thr: img.lt(d)).sum())
        band_names.append("rain_days_dry")
        bands.append(chirps.map(lambda img: img.eq(0)).sum())
        band_names.append("rain_days_zero")
        if rain_cfg.get("compute_dry_spell", True):
            bands.append(max_dry_spell(chirps, dry_thr))
            band_names.append("rain_max_dry_spell")

        bands.append(chirps.sum())
        band_names.append("rain_total_mm")
        bands.append(chirps.max())
        band_names.append("rain_max_day_mm")
        bands.append(chirps.mean())
        band_names.append("rain_mean_daily_mm")
        bands.append(chirps.count())
        band_names.append("rain_valid_obs")

        stacked = ee.Image.cat(bands).rename(band_names)

        for batch in batch_points(city_df, batch_size):
            batch_rows = []
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

            for f in safe_getinfo(sampled, timeout=timeout)["features"]:
                props = f["properties"]
                row = {"business_id": props["business_id"]}
                for bn in band_names:
                    row[bn] = props.get(bn)
                row["rain_window_start"] = start_date
                row["rain_window_end"] = end_date
                batch_rows.append(row)

            append_checkpoint(batch_rows, INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


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
