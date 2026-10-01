"""Indicator 17: Universal Thermal Climate Index (UTCI) and mean radiant temperature.

A COMPLEMENT to indicator 11 (sWBGT), not a replacement. Both are kept and
`wbgt_*` stays the continuity measure; UTCI is the preferred one on physics.

WHY BOTH. sWBGT uses air temperature and humidity ONLY. UTCI is the
state-of-the-art human thermal comfort index and integrates four terms -
temperature, humidity, WIND (which cools) and MEAN RADIANT TEMPERATURE (which
heats) - so it is the proper version of a quantity this pipeline currently
holds as separate crude pieces. Three things it measures that sWBGT provably
cannot on this frame:

  1. IT SEPARATES THE TWO CITIES sWBGT PUTS AT ZERO. wbgt_days_gt31c is exactly
     0 for both Addis Ababa and Sao Paulo, and the registry has to explain that
     they are at zero for different reasons - Addis Ababa dry, Sao Paulo cool.
     UTCI measures the difference instead: Sao Paulo 180 days above strong heat
     stress and 494 above moderate, against Addis Ababa's 0 and 314.
  2. IT FINDS DELHI'S EXTREME TAIL. On sWBGT, Lagos (421 days) looks worse than
     Delhi (223). UTCI agrees Lagos has more VERY STRONG days (403 v 269) but
     shows Delhi is the ONLY city of the five reaching EXTREME heat stress at
     all - 19 days above 46C, peaking at 48.2C. A different hazard profile,
     invisible to a single sWBGT threshold.
  3. MEAN RADIANT TEMPERATURE IS A NEW VARIABLE, not a restatement. It runs
     46.7-54.5C here, far above air temperature, and is the radiant load a
     street-front trader actually stands in. sWBGT ignores radiation entirely.

TWO CEILINGS, BOTH IMPORTANT.

  RESOLUTION. ERA5-HEAT is the ~28km ERA5 single-levels grid, 2.5x COARSER than
  the ERA5-Land grid behind indicator 11. This is a CITY-LEVEL control with
  effectively no within-city variation. The trade is accepted because the
  measure it sits beside is already city-level (0-4% within-city variance), so
  no spatial information is lost - the same reasoning as indicator 16.

  DEPENDENCY. This is a THIRD-PARTY asset, not an official GEE catalog entry.
  With indicator 10's HRSL it is one of two such dependencies, and if Climate
  Engine moves or withdraws it this indicator breaks. The fallback is computing
  UTCI from ERA5 directly - radiation fluxes give mean radiant temperature, and
  UTCI itself is a published 6th-order polynomial in four variables - which is
  feasible but a lot of error-prone code to maintain against a hosted version.
  The extractor fails loudly rather than silently if the asset is unreadable.

UNITS: the source is in KELVIN. Everything here is converted to Celsius.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points, batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "utci"
KELVIN = 273.15


def _thr_name(thr) -> str:
    return f"utci_days_gt{str(thr).replace('.', 'p')}c"


def build_utci_image(config: dict, start_date: str, end_date: str):
    """Stack of UTCI/MRT summaries for one window. Returns (image, names)."""
    u_cfg = config["utci"]
    b = u_cfg["bands"]

    col = (ee.ImageCollection(u_cfg["dataset"])
           .filterDate(start_date, end_date))

    daily_max = col.select(b["utci_max"])
    bands, names = [], []

    # Day-counts are taken on the DAILY MAXIMUM: "a day with strong heat
    # stress" means the day's peak reached that category, not its average.
    thresholds = u_cfg.get("thresholds_c", [])
    if thresholds:
        thr_names = [_thr_name(t) for t in thresholds]

        # One map producing a multi-band indicator image, summed once - the
        # idiom indicator 16 had to adopt for hourly data. Cheaper here too,
        # and it keeps the two ERA5 extractors consistent.
        def indicators(img):
            c = img.subtract(KELVIN)
            return ee.Image.cat(
                [c.gt(t).rename(n) for t, n in zip(thresholds, thr_names)])

        bands.append(daily_max.map(indicators).sum())
        names.extend(thr_names)

    for src, red, nm in [
        (b["utci_mean"], "mean", "utci_mean_c"),
        (b["utci_max"],  "mean", "utci_dmax_mean_c"),
        (b["utci_max"],  "max",  "utci_max_c"),
        (b["mrt_max"],   "mean", "mrt_dmax_mean_c"),
        (b["mrt_max"],   "max",  "mrt_max_c"),
    ]:
        reducer = {"mean": ee.Reducer.mean(), "max": ee.Reducer.max()}[red]
        bands.append(col.select(src).reduce(reducer).subtract(KELVIN).rename(nm))
        names.append(nm)

    stacked = ee.Image.cat(bands).rename(names)
    return stacked, names


def extract_utci(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """UTCI and mean radiant temperature per business, grouped by city."""
    gee_cfg = config["gee"]
    u_cfg = config["utci"]
    scale = u_cfg.get("scale_m", 27830)
    batch_size = u_cfg.get("batch_size", gee_cfg["batch_size"])
    timeout = u_cfg.get("getinfo_timeout_sec")

    # Fail loudly on a third-party asset that has moved or lost read access,
    # rather than writing a column of nulls.
    try:
        n_images = ee.ImageCollection(u_cfg["dataset"]).limit(1).size().getInfo()
    except Exception as e:
        raise SystemExit(
            f"Cannot read {u_cfg['dataset']!r}: {e}\n"
            f"  This is a THIRD-PARTY asset (Climate Engine's ERA5-HEAT), not an "
            f"official GEE catalog entry. If it has moved or been withdrawn, see "
            f"the module docstring for the fallback.")
    if not n_images:
        raise SystemExit(f"{u_cfg['dataset']!r} is readable but empty.")

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=u_cfg["trailing_years"])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}", flush=True)
        stacked, names = build_utci_image(config, start_date, end_date)

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
    print("Extracting UTCI and mean radiant temperature (ERA5-HEAT)...")
    result = extract_utci(df, config)
    save_output(result, INDICATOR_NAME, config)
    print(result.describe().to_string())


if __name__ == "__main__":
    main()
