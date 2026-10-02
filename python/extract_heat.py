"""Indicator 2: Extreme heat days from MODIS Land Surface Temperature."""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "heat"


def lst_collection(config: dict, start_date: str, end_date: str,
                   band_key: str = "band"):
    """Terra+Aqua MODIS LST for one window, as a single merged collection.

    SHARED BY ALL THREE PIPELINES - the point extractor, the static block
    indicators (via _build_heat_image) and the longitudinal block indicators -
    so the three cannot drift on which satellites they read.

    WHY BOTH SATELLITES. Terra overpasses at ~10:30/22:30 local and Aqua at
    ~13:30/01:30, and until 2026-10-02 this pipeline read Terra alone. That
    cost two things, both measured over the 730-day window:

      COVERAGE. Terra-only valid observations ran 65 (Lagos) to 414 (Addis
      Ababa). Adding Aqua gives 199 to 715 - roughly double everywhere and
      TRIPLE in Lagos, the worst-covered city, where Aqua alone (134) beats
      Terra alone (65). The cross-city spread narrows from 6.4x to 4.9x.

      THE PEAK ITSELF. Terra's mid-morning overpass never catches the
      afternoon maximum. Aqua's max exceeded Terra's in EVERY city, by 2.6C
      (Lagos) to 8.2C (Sao Paulo), and merged max equals Aqua max everywhere -
      Terra contributed no maximum at all. Worse, the shortfall is uneven, so
      Terra-only reordered the cities: it put Delhi level with Jakarta and both
      above Sao Paulo, where the merged data puts Sao Paulo clearly first.

    CONSEQUENCE FOR THE COUNT COLUMNS. With two overpasses a day, a count of
    images above a threshold is a count of OBSERVATIONS, not of days - both
    satellites can exceed it on the same date. The count columns are named
    heat_obs_gt*/heat_nights_obs_gt* for that reason; they were heat_days_gt*
    while Terra alone made one observation per day. The *_frac_* columns are
    unaffected in meaning, being counts over lst_valid_obs either way, and
    remain the ones to use for any cross-city comparison.
    """
    heat_cfg = config["heat"]
    datasets = heat_cfg.get("datasets") or [heat_cfg["dataset"]]
    band = heat_cfg[band_key]
    merged = None
    for ds in datasets:
        col = ee.ImageCollection(ds).filterDate(start_date, end_date).select(band)
        merged = col if merged is None else merged.merge(col)
    return merged


def _build_heat_image(config: dict, start_date: str, end_date: str):
    """Build the stacked heat-summary image for one time window.

    Built ONCE PER CITY rather than once per batch: the reduction runs over
    ~730 MODIS images, so rebuilding it for every 50 points was the dominant
    cost of this indicator.

    Returns (stacked_image, band_names).
    """
    heat_cfg = config["heat"]
    thresholds = heat_cfg["thresholds_celsius"]
    scale_factor = heat_cfg["scale_factor"]
    offset = heat_cfg["offset_kelvin_to_celsius"]

    modis = lst_collection(config, start_date, end_date, "band")

    # Convert raw DN to Celsius: DN * scale_factor + offset
    def to_celsius(img):
        return (
            img.multiply(scale_factor)
            .add(offset)
            .copyProperties(img, ["system:time_start"])
        )

    modis_c = modis.map(to_celsius)

    bands = []
    band_names = []

    # Threshold counts: for each threshold, count images where LST > threshold
    for t in thresholds:
        bands.append(modis_c.map(lambda img, t=t: img.gt(t)).sum())
        band_names.append(f"heat_obs_gt{t}c")

    # Mean and max LST
    if heat_cfg.get("compute_continuous", True):
        bands.append(modis_c.mean())
        band_names.append("lst_mean_c")
        bands.append(modis_c.max())
        band_names.append("lst_max_c")

    # Valid observation count (non-masked pixels)
    bands.append(modis_c.count())
    band_names.append("lst_valid_obs")

    # Night-time LST from the same product. Nights that stay hot are what deny
    # physiological recovery, so they track heat morbidity better than daytime
    # peaks alone; the survey's clim_heat_* items ask about exactly that.
    night_band = heat_cfg.get("night_band")
    if night_band:
        modis_n = lst_collection(
            config, start_date, end_date, "night_band").map(to_celsius)
        for nt in heat_cfg.get("night_thresholds_celsius", []):
            bands.append(modis_n.map(lambda img, nt=nt: img.gt(nt)).sum())
            band_names.append(f"heat_nights_obs_gt{nt}c")
        bands.append(modis_n.mean())
        band_names.append("lst_night_mean_c")
        bands.append(modis_n.min())
        band_names.append("lst_night_min_c")
        bands.append(modis_n.count())
        band_names.append("lst_night_valid_obs")

    return ee.Image.cat(bands).rename(band_names), band_names


def _sample_heat_batch(batch_df, stacked, band_names, start_date, end_date,
                       timeout=None):
    """Sample the stacked heat image at one batch of points."""
    features = []
    for _, row in batch_df.iterrows():
        geom = ee.Geometry.Point([row["longitude"], row["latitude"]])
        features.append(ee.Feature(geom, {
            "business_id": str(row["business_id"]),
        }))
    fc = ee.FeatureCollection(features)

    # MODIS LST is 1km, so sample at 1000m
    sampled = stacked.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.first(),
        scale=1000,
    )

    results = []
    got = safe_getinfo(sampled, timeout=timeout) if timeout else safe_getinfo(sampled)
    for f in got["features"]:
        props = f["properties"]
        row = {"business_id": props["business_id"]}
        for bn in band_names:
            row[bn] = props.get(bn)
        row["heat_window_start"] = start_date
        row["heat_window_end"] = end_date
        results.append(row)
    return results


def extract_heat(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Extract heat indicators for all businesses, grouped by city.

    Each city gets one fixed-length window (see utils.get_city_window and the
    time_window section of config.yaml). NOTE the exceedance columns are
    `heat_obs_gt*` - counts of OBSERVATIONS above the threshold, not of days,
    since Terra and Aqua can both exceed it on one date. They are NOT directly
    comparable across cities, because clear-sky coverage still varies ~5x;
    use the derived `heat_frac_gt*` rates for that.
    """
    gee_cfg = config["gee"]
    heat_cfg = config["heat"]
    # See the config note: cost is per-request, not per-point, so batch large.
    batch_size = heat_cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = heat_cfg.get("getinfo_timeout_sec")
    trailing_years = config["heat"]["trailing_years"]

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=trailing_years)
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")

        stacked, band_names = _build_heat_image(config, start_date, end_date)

        for batch in batch_points(city_df, batch_size):
            append_checkpoint(
                _sample_heat_batch(batch, stacked, band_names,
                                   start_date, end_date, timeout),
                INDICATOR_NAME, config)
            progress.update(len(batch))

    return finish_indicator(INDICATOR_NAME, config)


def main():
    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    print("Extracting extreme heat days (MODIS LST)...")
    result = extract_heat(df, config)
    save_output(result, "heat", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
