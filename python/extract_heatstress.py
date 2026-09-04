"""Indicator 11: Humid heat stress from ERA5-Land reanalysis.

Land surface temperature (indicator 2) measures the radiative temperature of
the ground and ignores humidity entirely. For HUMAN heat stress that is a
material omission: dry highland air at 30C and saturated coastal air at 30C are
not the same exposure, so LST alone misranks these cities. This adds 2m air
temperature, relative humidity, and a simplified Wet Bulb Globe Temperature.

RESOLUTION CAVEAT: ERA5-Land is an ~11km reanalysis grid, coarser than any of
these cities. Expect only a handful of distinct values per city. Treat these as
CITY-LEVEL controls, not within-city variation.
"""

import ee
import pandas as pd

from utils import (
    load_config, init_gee, load_business_points,
    batch_points, save_output,
    safe_getinfo, load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress, get_city_window,
)

INDICATOR_NAME = "heatstress"


def _saturation_vapour_pressure(temp_c: ee.Image) -> ee.Image:
    """Magnus formula, hPa. Applied to dewpoint it gives actual vapour pressure."""
    return temp_c.multiply(17.67).divide(temp_c.add(243.5)).exp().multiply(6.112)


def build_heatstress_image(config: dict, start_date: str, end_date: str):
    """Stack of humid-heat summaries for one window. Returns (image, names)."""
    hs_cfg = config["heatstress"]
    b = hs_cfg["bands"]

    era5 = (ee.ImageCollection(hs_cfg["dataset"])
            .filterDate(start_date, end_date))

    def to_metrics(img):
        t = img.select(b["temp"]).subtract(273.15).rename("t2m_c")
        tmax = img.select(b["temp_max"]).subtract(273.15).rename("t2m_max_c")
        td = img.select(b["dewpoint"]).subtract(273.15)
        e = _saturation_vapour_pressure(td).rename("vp_hpa")       # actual
        es = _saturation_vapour_pressure(t)                        # saturation
        rh = e.divide(es).multiply(100).rename("rh_pct")
        # Simplified WBGT (Australian BoM approximation), degrees C:
        #   sWBGT = 0.567*Ta + 0.393*e + 3.94
        # Uses daily MEAN temperature with daily MEAN vapour pressure — pairing
        # daily maxima of both would combine extremes that need not co-occur.
        wbgt = (t.multiply(0.567)
                 .add(e.multiply(0.393))
                 .add(3.94)
                 .rename("wbgt_c"))
        return (t.addBands([tmax, rh, wbgt])
                 .copyProperties(img, ["system:time_start"]))

    daily = era5.map(to_metrics)

    bands, names = [], []
    for thr in hs_cfg.get("thresholds_wbgt", []):
        bands.append(daily.select("wbgt_c").map(
            lambda img, thr=thr: img.gt(thr)).sum())
        names.append(f"wbgt_days_gt{thr}c")

    for src, red, nm in [
        ("t2m_c", "mean", "t2m_mean_c"),
        ("t2m_max_c", "max", "t2m_max_c"),
        ("rh_pct", "mean", "rh_mean_pct"),
        ("wbgt_c", "mean", "wbgt_mean_c"),
        ("wbgt_c", "max", "wbgt_max_c"),
    ]:
        coll = daily.select(src)
        bands.append(coll.mean() if red == "mean" else coll.max())
        names.append(nm)

    stacked = ee.Image.cat(bands).rename(names)

    # ERA5-Land is masked over water. At an ~11km grid a coastal cell can be
    # classified as sea while the businesses inside it are plainly on land, so
    # without this whole coastal blocks come back empty (observed in Lagos).
    # Fill masked cells from neighbouring land cells; at this resolution the
    # nearest land value is the best available estimate, and the field varies
    # slowly enough that it is a reasonable one.
    filled = stacked.focal_mean(radius=3, kernelType="square",
                                units="pixels", iterations=3)
    return stacked.unmask(filled), names


def extract_heatstress(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Humid heat stress per business, grouped by city."""
    gee_cfg = config["gee"]
    hs_cfg = config["heatstress"]
    scale = hs_cfg.get("scale_m", 11132)

    remaining = filter_remaining_points(
        df, load_checkpoint(INDICATOR_NAME, config))
    progress = BatchProgress(len(remaining))

    for city, city_df in remaining.groupby("city"):
        start_date, end_date = get_city_window(
            city_df, config, trailing_years=hs_cfg["trailing_years"])
        print(f"  {city}: {len(city_df)} businesses, "
              f"window {start_date} to {end_date}")
        stacked, names = build_heatstress_image(config, start_date, end_date)

        for batch in batch_points(city_df, gee_cfg["batch_size"]):
            features = [
                ee.Feature(ee.Geometry.Point([r["longitude"], r["latitude"]]),
                           {"business_id": str(r["business_id"])})
                for _, r in batch.iterrows()]
            sampled = stacked.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.first(), scale=scale)

            batch_rows = []
            for f in safe_getinfo(sampled)["features"]:
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
    print("Extracting humid heat stress (ERA5-Land)...")
    result = extract_heatstress(df, config)
    save_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
