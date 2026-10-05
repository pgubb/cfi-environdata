"""Yearly heat time series per city, averaged over the whole sampling grid.

A THIRD UNIT OF ANALYSIS, separate from the business and block tables: one row
per CITY x YEAR, each value a spatial mean over that city's entire sampling
grid. Its purpose is the long view — how heat in these five cities has moved
over the decades each instrument covers — not within-city pattern, which the
block tables already carry.

    data/output/heat_timeseries_yearly.csv

EACH INSTRUMENT STARTS AT A DIFFERENT TIME, so the table is ragged by design:

    ERA5-HEAT (UTCI, MRT)     1940 ->   ~28km
    ERA5-Land (air, sWBGT)    1951 ->   ~11km
    MODIS Terra (LST)         2001 ->     1km   (collection starts 2000-02-24)
    MODIS Terra+Aqua (LST)    2003 ->     1km   (Aqua starts 2002-07-04)

ONLY COMPLETE CALENDAR YEARS ARE EMITTED. 2026 is excluded although all four
instruments carry data into it: the day- and observation-counts would be
depressed by a partial year and would read as a sharp fall at the end of every
trend, which is exactly the artefact this table must not manufacture.

--------------------------------------------------------------------------
THE TRAP THIS TABLE IS BUILT AROUND: A SATELLITE JOINING MID-SERIES
--------------------------------------------------------------------------
Indicators 2 merges MODIS Terra and Aqua, which is right for a fixed two-year
window. For a TREND it is a trap. Aqua only starts in mid-2002, and its ~13:30
overpass catches afternoon peaks that Terra's ~10:30 never reaches — by 2.6C
to 8.2C depending on the city. A merged series therefore STEPS UP in 2003 for
reasons that have nothing to do with climate, and the step is larger than most
of the trend it would sit inside.

So the LST metrics are emitted TWICE:

    *_terra   Terra only, 2001 onward — ONE INSTRUMENT THROUGHOUT.
              USE THIS FOR ANY TREND, SLOPE OR BEFORE/AFTER CLAIM.
    (plain)   Terra+Aqua, 2003 onward — matches indicator 2, better absolute
              peaks, NOT a consistent series. Use for levels, not trends.

AND A SECOND INSTRUMENT PROBLEM, AFTER 2020: BOTH PLATFORMS ARE DRIFTING.
Terra's last maintaining maneuver was in 2020 and it now drifts EARLIER —
10:15 MLT by Oct 2022, ~09:00 by Dec 2025. Aqua's was in Mar 2021 and it
drifts LATER — past 13:45 by Feb 2023, ~15:50 by Aug 2026. They move in
opposite directions but both AWAY FROM PEAK SURFACE HEATING, so maximum LST
falls in the Terra-only AND the merged series alike: 3-8C below baseline by
2025 in all five cities, while ERA5 air temperature does not fall. This is a
SAMPLING artefact, not a calibration failure — the surface really is cooler at
09:00, the instrument is simply no longer measuring the same time of day.
Spurious cooling from orbital drift is the classic artefact of the NOAA-AVHRR
record; no correction is applied here. RESTRICT ANY LST TREND TO 2001-2020.

The ERA5 products have no equivalent break: both are reanalyses, internally
consistent across their whole record by construction. They have the opposite
caveat — they are MODELLED, so early decades rest on far less observational
input than recent ones even though the series looks seamless.
"""

import argparse

import ee
import pandas as pd
import shapely

from utils import load_config, init_gee, save_output
from extract_heatstress import _saturation_vapour_pressure

OUTPUT_NAME = "heat_timeseries_yearly"
KELVIN = 273.15

# Reduction scale, metres. Capped at 1km even for the 11km and 28km products:
# the Lagos grid is ~200 km2, smaller than a single 28km cell, and a reduction
# coarser than the geometry risks returning nothing (the same hazard that left
# whole columns empty in the block pipeline). Sampling a coarse product finely
# only repeats cell values across the polygon — safe here because every metric
# is a mean or a per-pixel count, never a pixelArea-derived density.
SCALE_M = 1000

# Simplification tolerance for the dissolved grid, degrees (~100m). Cuts the
# vertex count roughly in half with no measurable change in area.
SIMPLIFY_DEG = 0.001


def city_geometries(config: dict) -> dict:
    """Dissolve each city's sampling grid into one simplified GEE geometry."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "blocks"))
    from utils_blocks import load_blocks

    blocks = load_blocks(config)
    out = {}
    for city, g in blocks.groupby("city"):
        union = shapely.simplify(
            shapely.union_all(g.geometry.to_numpy()), SIMPLIFY_DEG)
        out[city] = ee.Geometry(shapely.geometry.mapping(union),
                                proj=None, geodesic=False)
        print(f"  {city}: {len(g):,} blocks -> "
              f"{shapely.get_num_coordinates(union):,} vertices")
    return out


def _lst_metrics(year, datasets, suffix, config):
    """Per-pixel LST metrics for one calendar year, from one or both satellites."""
    hc = config["heat"]
    y = ee.Number(year)
    start = ee.Date.fromYMD(y, 1, 1)
    end = start.advance(1, "year")

    def band(name):
        merged = None
        for ds in datasets:
            c = ee.ImageCollection(ds).filterDate(start, end).select(name)
            merged = c if merged is None else merged.merge(c)
        return merged.map(lambda i: i.multiply(hc["scale_factor"])
                          .add(hc["offset_kelvin_to_celsius"]))

    day = band(hc["band"])
    night = band(hc["night_band"])
    # Fractions are formed PER PIXEL and then averaged over the grid. The other
    # order — summing exceedances and observations across the city first — would
    # weight each pixel by how often it happened to be cloud-free.
    return ee.Image.cat([
        day.map(lambda i: i.gt(40)).sum().divide(day.count())
           .rename(f"lst_frac_gt40c{suffix}"),
        day.max().rename(f"lst_max_c{suffix}"),
        night.map(lambda i: i.gt(25)).sum().divide(night.count())
             .rename(f"lst_nights_frac_gt25c{suffix}"),
        day.count().rename(f"lst_day_obs{suffix}"),
        night.count().rename(f"lst_night_obs{suffix}"),
    ])


def _era5land_metrics(year, config):
    """Per-pixel air-temperature and sWBGT metrics for one calendar year."""
    hs = config["heatstress"]
    b = hs["bands"]
    y = ee.Number(year)
    start = ee.Date.fromYMD(y, 1, 1)
    end = start.advance(1, "year")
    col = ee.ImageCollection(hs["dataset"]).filterDate(start, end)

    def to_metrics(img):
        t = img.select(b["temp"]).subtract(KELVIN)
        tmax = img.select(b["temp_max"]).subtract(KELVIN).rename("t2m_max_c")
        e = _saturation_vapour_pressure(img.select(b["dewpoint"]).subtract(KELVIN))
        # Same simplified WBGT as indicator 11: daily MEAN temperature with
        # daily MEAN vapour pressure, never the two maxima together.
        wbgt = t.multiply(0.567).add(e.multiply(0.393)).add(3.94).rename("wbgt_c")
        return tmax.addBands(wbgt)

    daily = col.map(to_metrics)
    return ee.Image.cat([
        daily.select("t2m_max_c").max().rename("t2m_max_c"),
        daily.select("wbgt_c").max().rename("wbgt_max_c"),
        daily.select("wbgt_c").map(lambda i: i.gt(28)).sum()
             .rename("wbgt_days_gt28c"),
    ])


def _utci_metrics(year, config):
    """Per-pixel UTCI and mean-radiant-temperature metrics for one year."""
    uc = config["utci"]
    b = uc["bands"]
    y = ee.Number(year)
    start = ee.Date.fromYMD(y, 1, 1)
    end = start.advance(1, "year")
    col = ee.ImageCollection(uc["dataset"]).filterDate(start, end)
    dmax = col.select(b["utci_max"])

    # ONE map producing a two-band indicator image, summed once - the idiom
    # indicator 16 had to adopt for hourly data. Here it matters because this
    # runs 86 times per city: a separate mapped pass per threshold doubled the
    # work over 365 daily images a year, for no benefit.
    def thresholds(img):
        c = img.subtract(KELVIN)
        return ee.Image.cat([c.gt(38).rename("utci_days_gt38c"),
                             c.gt(46).rename("utci_days_gt46c")])

    return ee.Image.cat([
        dmax.max().subtract(KELVIN).rename("utci_max_c"),
        dmax.map(thresholds).sum(),
        col.select(b["mrt_max"]).mean().subtract(KELVIN)
           .rename("mrt_dmax_mean_c"),
    ])


# name -> (builder, first complete year). Last year is resolved at run time.
GROUPS = {
    "utci":       (lambda y, c: _utci_metrics(y, c), 1940),
    "era5land":   (lambda y, c: _era5land_metrics(y, c), 1951),
    "lst_terra":  (lambda y, c: _lst_metrics(
        y, [c["heat"]["datasets"][0]], "_terra", c), 2001),
    "lst_merged": (lambda y, c: _lst_metrics(
        y, c["heat"]["datasets"], "", c), 2003),
}


def run_group(name, geom, config, last_year, chunk=25):
    """Yearly spatial means for one metric group over one city."""
    builder, first_year = GROUPS[name]
    rows = []
    for lo in range(first_year, last_year + 1, chunk):
        hi = min(lo + chunk - 1, last_year)
        fc = ee.FeatureCollection(ee.List.sequence(lo, hi).map(
            lambda y: ee.Feature(None, builder(y, config)
                                 .reduceRegion(ee.Reducer.mean(), geom,
                                               SCALE_M, maxPixels=int(1e9))
                                 .set("year", y))))
        for f in fc.getInfo()["features"]:
            rows.append(f["properties"])
        print(f"      {name} {lo}-{hi} done", flush=True)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--last-year", type=int, default=None,
                    help="Last COMPLETE calendar year (default: last year).")
    ap.add_argument("--cities", help="Comma-separated subset.")
    ap.add_argument("--groups", help="Comma-separated subset of "
                                     + ",".join(GROUPS))
    args = ap.parse_args()

    config = load_config()
    init_gee(config)
    last_year = args.last_year or (pd.Timestamp.today().year - 1)
    groups = ([g.strip() for g in args.groups.split(",")] if args.groups
              else list(GROUPS))

    print(f"Dissolving sampling grids (last complete year: {last_year})")
    geoms = city_geometries(config)
    if args.cities:
        wanted = [c.strip() for c in args.cities.split(",")]
        geoms = {c: g for c, g in geoms.items() if c in wanted}

    frames = []
    for city, geom in geoms.items():
        print(f"\n=== {city} ===", flush=True)
        per_city = None
        for name in groups:
            df = run_group(name, geom, config, last_year)
            per_city = df if per_city is None else per_city.merge(
                df, on="year", how="outer")
        per_city.insert(0, "city", city)
        frames.append(per_city)

    out = pd.concat(frames, ignore_index=True).sort_values(["city", "year"])
    lead = ["city", "year"]
    out = out[lead + [c for c in out.columns if c not in lead]]
    save_output(out, OUTPUT_NAME, config)
    print(f"\n{len(out):,} city-years, {out.year.min()}-{out.year.max()}")


if __name__ == "__main__":
    main()
