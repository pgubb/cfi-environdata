"""Indicator 15: Near-surface wind speed from ERA5-Land.

The environmental counterpart to the survey's clim_event_wind /
clim_damage_wind / clim_closure_wind items, which had none.

READ THE CEILING ON THIS INDICATOR BEFORE USING IT. It is a city-level
climatological control and nothing more:

  - ERA5-Land is an ~11km REANALYSIS grid, coarser than any of these cities, so
    expect a handful of distinct values per city and effectively no within-city
    variation. This is the same limitation that keeps the other ERA5 variables
    out of the block table.
  - It has NO GUST BAND, and gusts are what damage premises. ERA5-Land carries
    daily means and per-component daily extremes only; the gust field lives in
    ERA5 single-levels at ~31km, coarser still.
  - A reanalysis has no urban canopy. 10m wind over a modelled land surface is
    not what a shopkeeper experiences in a street canyon, and it cannot
    represent funnelling between buildings.
  - MEASURED ON THIS FRAME the winds are light: city mean daily-mean speeds run
    1.3-2.1 m/s and the windiest single day anywhere reaches 8.4 m/s. Nothing
    approaches a gale. Day-counts above meaningful damage thresholds would be
    zero everywhere, which is why the configured thresholds are low and are
    calibrated to separate cities rather than to mark hazard.

Use it to rank CITIES on windiness, or as a control. Do not use it to identify
windstorm events, and do not read a within-city gradient into it.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points, batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "wind"


def build_wind_image(config: dict, start_date: str, end_date: str):
    """Stack of wind summaries for one window. Returns (image, names)."""
    w_cfg = config["wind"]
    b = w_cfg["bands"]

    era5 = ee.ImageCollection(w_cfg["dataset"]).filterDate(start_date, end_date)

    def to_metrics(img):
        # Daily MEAN speed from the daily mean components.
        speed = (img.select(b["u"]).hypot(img.select(b["v"]))).rename("spd")

        # An UPPER BOUND on the day's peak speed, from the per-component daily
        # extremes. The largest magnitude of each component is max(|max|,|min|)
        # because u and v are signed (direction), and they are combined in
        # quadrature. THIS IS NOT A GUST AND NOT A TRUE DAILY MAXIMUM: the two
        # components need not peak in the same hour, so combining their
        # separate extremes overstates any real instantaneous speed. It is
        # carried only because the daily mean understates peaks so badly, and
        # is named `_bound` to keep that visible at the point of use.
        au = img.select(b["u_max"]).abs().max(img.select(b["u_min"]).abs())
        av = img.select(b["v_max"]).abs().max(img.select(b["v_min"]).abs())
        peak = au.hypot(av).rename("peak")

        return speed.addBands(peak).copyProperties(img, ["system:time_start"])

    daily = era5.map(to_metrics)

    bands, names = [], []
    for thr in w_cfg.get("thresholds_ms", []):
        bands.append(daily.select("spd").map(
            lambda img, thr=thr: img.gt(thr)).sum())
        names.append(f"wind_days_gt{str(thr).replace('.', 'p')}ms")

    for src, red, nm in [
        ("spd", "mean", "wind_mean_ms"),
        ("spd", "max", "wind_max_daily_mean_ms"),
        ("peak", "max", "wind_peak_bound_ms"),
    ]:
        reducer = {"mean": ee.Reducer.mean(), "max": ee.Reducer.max()}[red]
        bands.append(daily.select(src).reduce(reducer).rename(nm))
        names.append(nm)

    pct = w_cfg.get("percentile")
    if pct is not None:
        bands.append(daily.select("spd")
                     .reduce(ee.Reducer.percentile([pct]))
                     .rename(f"wind_p{pct}_ms"))
        names.append(f"wind_p{pct}_ms")

    stacked = ee.Image.cat(bands).rename(names)

    # SAME COASTAL FILL AS INDICATOR 11, and for the same reason. ERA5-Land is
    # masked over water, so at an ~11km grid a coastal cell reads as sea while
    # the businesses inside it are plainly on land. Without this, wind came
    # back empty for 512 Lagos and 8 Jakarta businesses that heatstress — the
    # same collection, the same points — covers fine. Two indicators from one
    # source disagreeing on which businesses exist is the kind of gap that
    # quietly drops rows from a model.
    #
    # units="pixels" is only safe because this indicator reduces at ERA5's
    # NATIVE scale (wind.scale_m = 11132), making the reach ~33km. Reduce finer
    # and the fill silently shrinks with the scale. Keep the two copies in step.
    filled = stacked.focal_mean(radius=3, kernelType="square",
                                units="pixels", iterations=3)
    return stacked.unmask(filled), names


def extract_wind(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Wind summaries per business, grouped by city.

    Grouped by city, not by listing date, for the same reason as heat stress:
    at an 11km grid the per-date precision buys nothing and costs ~10x.
    """
    gee_cfg = config["gee"]
    w_cfg = config["wind"]
    scale = w_cfg.get("scale_m", 11132)
    # See the config note: cost is per-request, not per-point, so batch large.
    batch_size = w_cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = w_cfg.get("getinfo_timeout_sec")

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=w_cfg["trailing_years"])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")
        stacked, names = build_wind_image(config, start_date, end_date)

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
    print("Extracting near-surface wind (ERA5-Land)...")
    result = extract_wind(df, config)
    save_output(result, INDICATOR_NAME, config)
    print(result.describe().to_string())


if __name__ == "__main__":
    main()
