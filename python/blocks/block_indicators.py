"""Block-level indicator specs, built on the POINT pipeline's image builders.

Each spec returns a GEE image whose bands are reduced with a zonal mean over
every block polygon. Wherever the point pipeline already exposes a
geometry-agnostic builder (`build_heat_image`, `build_no2_image`,
`build_buildings_image`, ...) this module CALLS IT rather than reimplementing
the maths, so the two pipelines cannot drift. That drift is exactly what
happened to the eight `extract_*_blocks.py` modules this file replaces: they
rebuilt each collection independently and, by the time they were revisited, had
a different analysis window and a different indicator set from the point
pipeline.

A spec is `(name, builder, output_columns)` where
`builder(config, bounds) -> ee.Image` returns an image whose band names are
exactly `output_columns`.
"""

import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract_heat import _build_heat_image                      # noqa: E402
from extract_no2 import build_no2_image                         # noqa: E402
from extract_buildings import build_buildings_image             # noqa: E402
from extract_hrsl import build_density_image as build_hrsl_density  # noqa: E402
from utils_blocks import get_analysis_window                    # noqa: E402


def _terrain(config, bounds):
    """Elevation and slope, from one SRTM read.

    ELEVATION WAS EXCLUDED UNTIL 2026-10-05, on the grounds that it has 0.4%
    within-city variance because the between-city range (Addis Ababa 2,300m vs
    Lagos 9m) swamps anything local. That reasoning is sound for the five-city
    pooled statistic and WRONG as a reason to omit the column, because it is
    not the question a coastal-flood map asks. Measured over the block grids of
    the two coastal cities:

        Jakarta   mean 17.7m, p10-p90 3-44m,  47.7% of blocks below 10m
        Lagos     mean  5.6m, p10-p90 2-9m,   93.4% of blocks below 10m

    Jakarta spans a real 3-44m gradient that the pooled figure hides entirely.
    Elevation costs nothing extra here - slope already reads this image - so it
    is emitted alongside, and coastal_lowland is derived from it after the
    merge. Still near-useless for comparing CITIES; read it within one.
    """
    srtm = ee.Image(config["elevation"]["dataset"]).select(
        config["elevation"]["band"])
    return ee.Image.cat([
        srtm.rename("elevation_m"),
        ee.Terrain.slope(srtm).rename("slope_degrees"),
    ])


def _heat(config, bounds):
    """Peak daytime land surface temperature.

    lst_max_c is the only thermal band kept: at 1km it carries 22% within-city
    variance, while lst_mean_c manages 8% and the night bands 0-1%.
    """
    if not config["heat"].get("compute_continuous", True):
        raise ValueError(
            "Block indicator 'heat' needs lst_max_c, which _build_heat_image "
            "only emits when heat.compute_continuous is true. Enable it or "
            "drop 'heat' from blocks.indicators.")
    start, end = get_analysis_window(
        config, trailing_years=config["heat"]["trailing_years"])
    img, _ = _build_heat_image(config, start, end)
    return img.select(["lst_max_c"])


def _flood(config, bounds):
    """Height Above Nearest Drainage — the flood mechanism itself, and the only
    flood measure with real within-block variance (66%)."""
    hand_cfg = config["flood"]["hand"]
    return ee.Image(hand_cfg["dataset"]).select(hand_cfg["band"]).rename("hand_m")


def _canopy(config, bounds):
    """Tree-cover fraction. A zonal mean of the binary tree mask IS the fraction,
    so no separate count/sum bands are needed at block level."""
    cfg = config["canopy"]
    worldcover = ee.ImageCollection(cfg["dataset"]).mosaic().select(cfg["band"])
    return worldcover.eq(cfg["tree_class_value"]).rename("canopy_fraction")


def _builtup(config, bounds):
    """Proportion of ground covered by built surface, 0-1.

    The band is square metres of built surface per native pixel, so the
    proportion is built_surface / native_pixel_area — NOT /100, which would
    give a percentage and put this on a different scale from canopy_fraction.
    """
    cfg = config["builtup"]
    native = cfg.get("native_scale_m", 100)
    return (ee.Image(cfg["dataset"]).select(cfg["band"])
            .divide(native ** 2).rename("builtup_fraction"))


def _nightlights(config, bounds):
    cfg = config["nightlights"]
    start, end = get_analysis_window(
        config, trailing_months=cfg["trailing_months"])
    viirs = (ee.ImageCollection(cfg["dataset"])
             .filterDate(start, end).select(cfg["band"]))
    return viirs.mean().rename("ntl_mean_radiance")


def _hrsl(config, bounds):
    return build_hrsl_density(config, bounds).rename("hrsl_density")


def _buildings(config, bounds):
    """Building height and typical footprint.

    Building COUNT is omitted at block level: the point pipeline recovers it
    from the mean by multiplying by the pixel count in a fixed-radius buffer,
    but blocks vary in area, so the count would have to be rescaled per block.
    Density (count per hectare) is derivable downstream from the fractional
    count band, which is kept.
    """
    img = build_buildings_image(config, bounds)
    return img.select(["f_height", "f_count"]).rename(
        ["building_height_mean", "building_fractional_count"])


def _albedo(config, bounds):
    """Shortwave albedo, white-sky and black-sky.

    463m against ~149m blocks, so it would ordinarily be too coarse to map —
    except that the five city means are packed into 0.123-0.144, leaving almost
    no between-city term, and 69% of the variance is WITHIN city. Higher than
    builtup (57%) or hrsl (59%). See block_scale: this must reduce finer than
    native or reduceRegions returns NULL for every block.
    """
    from extract_albedo import build_albedo_image
    a = config["albedo"]
    start, end = get_analysis_window(config, trailing_years=a["trailing_years"])
    img, _ = build_albedo_image(config, start, end)
    return img.select(["albedo_wsa", "albedo_bsa"])


def _no2(config, bounds):
    """Tropospheric NO2. Kept despite only 14% within-city variance because it
    is the sole combustion-specific pollution measure; expect a smooth surface
    at block level rather than block-to-block detail."""
    start, end = get_analysis_window(
        config, trailing_years=config["no2"]["trailing_years"])
    img, _ = build_no2_image(config, bounds, start, end)
    return img.select(["no2_mean"])


# Indicators computed from LOCAL RASTERS rather than a GEE image. These have no
# builder and no reduction scale: run_all_blocks.py dispatches them to their own
# zonal function instead of reduceRegions. Keeping them in BLOCK_INDICATORS (with
# a None builder) means the merge, caching, manifest and registry validation all
# treat them like any other indicator.
LOCAL_RASTER_INDICATORS = {"pop2026"}


# name -> (builder, output columns). Order is the run order.
BLOCK_INDICATORS = {
    "terrain":     (_terrain,     ["elevation_m", "slope_degrees"]),
    "heat":        (_heat,        ["lst_max_c"]),
    "flood":       (_flood,       ["hand_m"]),
    "canopy":      (_canopy,      ["canopy_fraction"]),
    "builtup":     (_builtup,     ["builtup_fraction"]),
    "nightlights": (_nightlights, ["ntl_mean_radiance"]),
    "hrsl":        (_hrsl,        ["hrsl_density"]),
    "buildings":   (_buildings,   ["building_height_mean",
                                   "building_fractional_count"]),
    "no2":         (_no2,         ["no2_mean"]),
    # Local raster (WorldPop R2025A 2026), no GEE builder.
    "pop2026":     (None,         ["pop2026_density"]),
    "albedo":      (_albedo,      ["albedo_wsa", "albedo_bsa"]),
}

# Config sections whose values affect each block indicator, for fingerprinting.
BLOCK_CONFIG_KEYS = {
    "terrain":     ["elevation"],
    "heat":        ["heat", "time_window"],
    "flood":       ["flood"],
    "canopy":      ["canopy"],
    "builtup":     ["builtup"],
    "nightlights": ["nightlights", "time_window"],
    "hrsl":        ["hrsl"],
    "buildings":   ["buildings"],
    "no2":         ["no2", "time_window"],
    "pop2026":     ["pop2026"],
    "albedo":      ["albedo", "time_window"],
}

# Reduction scale per indicator, read FROM CONFIG so the two pipelines cannot
# diverge on it. Only terrain and flood are literals: both sample a plain
# elevation band with no pixelArea term, so the scale is a cost choice
# rather than a correctness one, and neither has a scale_m of its own in config.
#
# Scale matters wherever a density is derived by dividing by
# ee.Image.pixelArea(): that reports area at the REQUESTED scale while the band
# holds a value per NATIVE cell, so reducing finer than native inflates the
# result (WorldPop reduced at 30m reads 9.4x its value at the native 93m).
def block_scale(name: str, config: dict) -> int:
    if name in LOCAL_RASTER_INDICATORS:
        raise ValueError(
            f"{name} is read from a local raster, not a GEE image; it has no "
            f"reduction scale. run_all_blocks.py should not reach here.")
    literals = {"terrain": 30, "flood": 90}   # flood: MERIT Hydro native ~90m
    if name in literals:
        return literals[name]
    section = {"heat": "heat", "canopy": "canopy", "builtup": "builtup",
               "nightlights": "nightlights", "hrsl": "hrsl",
               "buildings": "buildings", "no2": "no2", "albedo": "albedo"}[name]
    if name == "heat":
        return 1000          # MODIS LST native grid; heat has no scale_m
    if name == "albedo":
        # CAPPED BELOW NATIVE, deliberately. MCD43A3 is 463m and blocks are
        # ~149m, so reducing at native returns NULL for every block - verified,
        # not theorised. Safe because this is a plain mean with no pixelArea
        # term. Same hazard and same fix as the longitudinal pipeline.
        return int(config["albedo"]["block_scale_m"])
    return int(config[section]["scale_m"])
