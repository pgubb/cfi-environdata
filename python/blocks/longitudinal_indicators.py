"""Per-period band builders for the longitudinal block pipeline.

Each spec returns an image of the indicator's metrics computed over ONE period.
`extract_longitudinal.py` calls it once per period and concatenates the results
into a single multi-band image, so one request per block batch returns every
period at once.

Only TIME-VARYING indicators appear here. Single-epoch rasters (canopy, built-up,
HAND, slope, HRSL, buildings) would emit identical values in every period.
"""

import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract_heatstress import _saturation_vapour_pressure  # noqa: E402


def _heat(config, bounds, start, end):
    cfg = config["heat"]
    coll = (ee.ImageCollection(cfg["dataset"]).filterDate(start, end)
            .select(cfg["band"]))
    celsius = coll.map(lambda i: i.multiply(cfg["scale_factor"])
                       .add(cfg["offset_kelvin_to_celsius"]))
    return ee.Image.cat([celsius.max(), celsius.mean(), celsius.count()])


def _rainfall(config, bounds, start, end):
    cfg = config["rainfall"]
    coll = (ee.ImageCollection(cfg["dataset"]).filterDate(start, end)
            .select(cfg["band"]))
    dry = cfg.get("dry_day_threshold_mm", 1.0)
    return ee.Image.cat([
        coll.sum(),
        coll.map(lambda i, d=dry: i.lt(d)).sum(),
        coll.max(),
    ])


def _airquality(config, bounds, start, end):
    cfg = config["airquality"]
    coll = (ee.ImageCollection(cfg["dataset"]).filterDate(start, end)
            .filterBounds(bounds).select(cfg["band"]))
    scaled = coll.map(lambda i: i.multiply(cfg["scale_factor"]))
    return ee.Image.cat([scaled.mean(), scaled.count()])


def _nightlights(config, bounds, start, end):
    cfg = config["nightlights"]
    # VIIRS is MONTHLY, so a 45-day period holds only 1-2 composites — this is
    # the coarsest series here in time, not just in space.
    coll = (ee.ImageCollection(cfg["dataset"]).filterDate(start, end)
            .select(cfg["band"]))
    return ee.Image.cat([coll.mean()])


def _heatstress(config, bounds, start, end):
    cfg = config["heatstress"]
    b = cfg["bands"]
    era5 = ee.ImageCollection(cfg["dataset"]).filterDate(start, end)

    def metrics(img):
        t = img.select(b["temp"]).subtract(273.15)
        td = img.select(b["dewpoint"]).subtract(273.15)
        e = _saturation_vapour_pressure(td)
        rh = e.divide(_saturation_vapour_pressure(t)).multiply(100)
        wbgt = t.multiply(0.567).add(e.multiply(0.393)).add(3.94)
        return t.rename("t").addBands(rh.rename("rh")).addBands(wbgt.rename("w"))

    daily = era5.map(metrics)
    stacked = ee.Image.cat([daily.select("w").mean(), daily.select("rh").mean()])
    # ERA5-Land masks water; fill coastal cells from neighbouring land.
    #
    # REPROJECT TO ERA5'S NATIVE GRID FIRST. focal_mean with units="pixels"
    # operates at whatever scale the request uses, and this pipeline caps that
    # at 100m — so a 3-pixel radius reaches 300m rather than the ~33km it spans
    # on the native 11,132m grid, leaving coastal blocks unfilled (Lagos 76%,
    # Jakarta 87% before this). Pinning the projection makes the reach a
    # property of the data, not of the caller's scale.
    #
    # Specifying the radius in METRES instead does not work: at a 100m request
    # scale a 40km radius needs an 801-pixel kernel, over GEE's 512 limit.
    native = int(cfg.get("scale_m", 11132))
    base = stacked.reproject(crs="EPSG:4326", scale=native)
    # 6 iterations of a 3-pixel radius on the 11km grid reaches ~200km. Three
    # iterations left 16% of Lagos blocks unfilled: the lagoon and its seaward
    # blocks sit far enough from an ERA5 land cell that a shorter reach does not
    # get there.
    filled = base.focal_mean(radius=3, kernelType="square",
                             units="pixels", iterations=6)
    return base.unmask(filled)


def _no2(config, bounds, start, end):
    cfg = config["no2"]
    coll = (ee.ImageCollection(cfg["dataset"]).filterDate(start, end)
            .filterBounds(bounds).select(cfg["band"]))
    return ee.Image.cat([coll.mean().multiply(cfg["scale_factor"])])


# name -> (per-period builder, metric column names, reduction scale key)
LONGITUDINAL_INDICATORS = {
    "heat":        (_heat,        ["lst_max_c", "lst_mean_c", "lst_valid_obs"], 1000),
    "rainfall":    (_rainfall,    ["rain_total_mm", "rain_days_dry",
                                   "rain_max_day_mm"], 5566),
    "airquality":  (_airquality,  ["aod_mean", "aod_valid_obs"], 1000),
    "nightlights": (_nightlights, ["ntl_mean_radiance"], 500),
    "heatstress":  (_heatstress,  ["wbgt_mean_c", "rh_mean_pct"], 11132),
    "no2":         (_no2,         ["no2_mean"], 1113),
}
