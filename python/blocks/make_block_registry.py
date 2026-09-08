"""Generate the two BLOCK-family registries for cfi-map2r2-data.

  registry_environment_blocks.R              one row per BLOCK
  registry_environment_blocks_longitudinal.R one row per BLOCK x 45-day PERIOD

Block analogues of ../make_registry.py, matching R/registry.R's tribble schema.
Generated, not hand-written, so each fails if any column of its source CSV is
neither registered nor explicitly excluded.

    cd python/blocks && python3 make_block_registry.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import load_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "registry_environment_blocks.R"
OUT_PATH_LONG = REPO_ROOT / "registry_environment_blocks_longitudinal.R"

EXCLUDED = {
    "block_id":  "join key (with city)",
    "block_uid": "city-prefixed unique key; convenience only",
    "city":      "already a GROUPS entry in registry.R",
}

# (id, label, domain, type, notes, description)
ROWS = [
    ("slope_degrees", "Terrain slope (degrees)", "envblk_terrain", "continuous",
     "GEE: ee.Terrain.slope on USGS/SRTMGL1_003, 30m",
     "Mean terrain slope across the block. A landslide-susceptibility proxy - the survey asks about clim_event_landslide - and a surface-runoff term for flooding. City means: Addis Ababa 5.2, Jakarta 3.0, Lagos 2.7 degrees. Elevation itself is deliberately NOT extracted at block level: it has only 0.4% within-city variance because the between-city range (Addis Ababa 2,300m vs Lagos 9m) swamps anything local, while slope from the same DEM has 93%."),

    ("lst_max_c", "Maximum land surface temperature (C)", "envblk_heat", "continuous",
     "GEE: MODIS/061/MOD11A1, 1km | COARSE relative to a block",
     "Highest daytime LAND SURFACE temperature in the block over a fixed 730-day window. Surface temperature, not air temperature: in built-up areas it runs 10-20C above what a weather station reports. AT 1km THIS IS COARSER THAN A BLOCK - one MODIS pixel spans roughly 44 blocks - so expect a smooth surface rather than block-to-block detail. It is retained because it is the only direct thermal measure with any within-city variance (22%); the humid-heat and night-heat variables have 0-5% and are business-level only."),

    ("hand_m", "Height above nearest drainage (m)", "envblk_flood", "continuous",
     "GEE: MERIT/Hydro/v1_0_1, ~90m | the strongest block-level discriminator",
     "Mean vertical distance from the block to the nearest stream channel along the hydrological flow path. Lower means more flood-susceptible. THE BEST FLOOD VARIABLE FOR MAPPING: 66% of its variance is within-city, and it separates cities sharply too - Addis Ababa averages 30.5m above drainage against 2.1m in coastal Lagos, while retaining large local spread (Addis Ababa SD 27.5, range 0-276m). A topographic proxy, not a hydrodynamic model: it knows nothing about drainage infrastructure or rainfall-driven pluvial flooding."),

    ("canopy_fraction", "Tree canopy cover", "envblk_green", "continuous",
     "GEE: ESA/WorldCover/v200, 10m",
     "Share of the block classified as tree cover, 0-1. A zonal mean of the binary tree mask IS the fraction. Blocks reach the full 0-1 range - unlike business points, which sit on built plots and are heavily zero-inflated - so this is far more informative at block level than at business level. City means: Jakarta 0.115, Addis Ababa 0.061, Lagos 0.053."),

    ("builtup_fraction", "Built-up surface", "envblk_built", "continuous",
     "GEE: JRC/GHSL/P2023A/GHS_BUILT_S/2020, 100m | UNITS CORRECTED 2026-09-05",
     "Share of the block covered by built surface, 0-1. NOTE the band holds SQUARE METRES of built surface per native 100m pixel, so the proportion is built_surface divided by pixel area; dividing by 100 instead (as this did until 2026-09-05) yields a PERCENTAGE and puts it on a scale 100x from canopy_fraction, its conceptual near-inverse. City means: Jakarta 0.392, Lagos 0.359, Addis Ababa 0.267."),

    ("ntl_mean_radiance", "Nighttime radiance", "envblk_light", "continuous",
     "GEE: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG, 500m",
     "Mean nighttime light radiance (nW/cm2/sr) across the block, averaged over the trailing 12 monthly composites. A well-established proxy for economic activity and infrastructure density at neighbourhood scale - not a measure of any individual business. Surprisingly strong within-city variance for a 500m product (82%). City means: Addis Ababa 39.8, Jakarta 28.2, Lagos 22.5."),

    ("hrsl_density", "Population density (people/km2)", "envblk_pop", "continuous",
     "Community GEE asset: projects/sat-io/open-datasets/hrsl/hrslpop, ~31m",
     "Mean residential population density from Meta's High Resolution Settlement Layer, which allocates census counts only to cells where a CNN detected a building. QUANTISED INTO MODES: because allocation is uniform across detected buildings within a census unit, blocks inside one unit share a density - Jakarta's 1st-99th percentiles span only 17,275-25,143 while Addis Ababa's span 10,602-86,224. That is a property of the product, not the extraction; the business-level pipeline reproduces the same percentiles to within ~1 person/km2. Residential population - where people sleep - so it understates commercial districts with heavy daytime footfall."),

    ("building_height_mean", "Mean building height (m)", "envblk_built", "continuous",
     "GEE: GOOGLE/Research/open-buildings-temporal/v1, 2023, 0.5m",
     "Mean height of buildings in the block, averaged over building pixels only so open ground does not drag it toward zero. THE ONLY VERTICAL MEASURE in either pipeline - canopy, built-up and population are all planar - and the highest within-city variance of any indicator (98%). Range 0.5-93m across blocks. Missing where a block contains no detected buildings."),

    ("building_fractional_count", "Building fractional count", "envblk_built", "continuous",
     "GEE: GOOGLE/Research/open-buildings-temporal/v1, 2023 | NOT a building count",
     "Mean fractional-building-count value per 0.5m pixel. THIS IS NOT A COUNT OF BUILDINGS. The business-level pipeline converts the equivalent value to a count by multiplying by the pixels in a fixed-radius buffer, but blocks vary in area so no single constant applies. Derive density downstream using each block's own area: count is approximately building_fractional_count * block_area_m2 / 0.25. Storing a 'count' that silently assumed a fixed block area would have been wrong."),

    ("no2_mean", "Tropospheric NO2 (micromol/m2)", "envblk_air", "continuous",
     "GEE: COPERNICUS/S5P/OFFL/L3_NO2, ~1.1km | COARSE relative to a block",
     "Mean tropospheric NO2 column density across the block. Specific to COMBUSTION - vehicles, generators, industry - unlike aerosol optical depth, which mixes traffic with dust and biomass haze; the two rank these cities differently. AT ~1.1km THIS IS COARSER THAN A BLOCK, so expect a smooth surface rather than block-level detail (14% within-city variance). A column density, not a surface concentration, so read it as a relative ranking. City means: Jakarta 122.7, Lagos 55.5, Addis Ababa 39.2."),

    ("heat_exposure_index", "Heat exposure index (within-city)", "envblk_heat", "continuous",
     "Derived: mean of signed within-city z-scores | NOT comparable across cities or to the business-level index",
     "Composite within-city heat exposure: the mean of signed z-scores of lst_max_c, builtup_fraction and minus canopy_fraction, each standardised WITHIN city. Zero is the city mean; +1 is one standard deviation more exposed than other blocks in the same city. LEVELS ARE NOT COMPARABLE ACROSS CITIES - every city has mean zero by construction. It is also a THREE-component analogue of the business-level heat_exposure_index, which has four (blocks extract lst_max_c but not lst_mean_c), so the two are conceptually parallel but NOT numerically comparable. For between-city heat comparison use the business-level wbgt_days_gt31c, which integrates temperature and humidity. Missing wherever any component is missing, rather than averaged over a partial set."),
]


EXCLUDED_LONG = {
    "block_id":     "join key (with city and period_index)",
    "block_uid":    "city-prefixed unique block key",
    "city":         "already a GROUPS entry in registry.R",
    "period_index": "join key; the time dimension itself",
    "period_start": "period bound, descriptive",
    "period_end":   "period bound, descriptive",
}

ROWS_LONG = [
    ("lst_max_c", "Maximum land surface temperature (C)", "envlong_heat", "continuous",
     "GEE: MODIS/061/MOD11A1, 1km | per 45-day period",
     "Highest daytime land surface temperature in the block during this period. Surface temperature, not air temperature. ~25% missing overall, which is SEASONAL CLOUD and itself informative: coverage falls to 46-57% in Dec-Mar and Oct-Jan against 84-99% otherwise, and by city runs Addis Ababa 100%, Jakarta 65%, Lagos 62%. Check lst_valid_obs before reading a period's value."),
    ("lst_mean_c", "Mean land surface temperature (C)", "envlong_heat", "continuous",
     "GEE: MODIS/061/MOD11A1, 1km | per 45-day period",
     "Mean daytime land surface temperature in the block during this period. Same seasonal cloud gaps as lst_max_c."),
    ("lst_valid_obs", "Clear-sky observations", "envlong_heat", "continuous",
     "Diagnostic, but ALSO a seasonal signal",
     "Number of clear-sky MODIS observations in this block-period, of up to 45. Unlike most diagnostics this carries real information: a period with few observations is a CLOUDY period, so the column doubles as a wet-season indicator. Always check it before comparing lst_* across periods."),

    ("rain_total_mm", "Total rainfall (mm)", "envlong_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT, 5.5km | per 45-day period",
     "Total precipitation in the block during this period. THE STRONGEST SEASONAL SIGNAL IN THE DATASET: Lagos ranges 11 to 594mm across the 16 periods. Rainfall was excluded from the static block table for low spatial variation (4-13% within-city) and appears here precisely because its temporal variation is so large. At 5.5km — about 37 blocks wide — read it along the TIME axis, not as spatial pattern."),
    ("rain_days_dry", "Dry days (<1mm)", "envlong_rain", "continuous",
     "GEE: CHIRPS | WMO dry-day threshold | per 45-day period",
     "Days in this 45-day period with rainfall below 1mm, the WMO convention for a day without meaningful rain. Directly comparable across periods and cities: CHIRPS is gap-filled, so every block-period has all 45 days."),
    ("rain_max_day_mm", "Wettest day (mm)", "envlong_rain", "continuous",
     "GEE: CHIRPS | per 45-day period",
     "Highest single-day rainfall in this period — the extreme-event measure rather than the accumulation."),

    ("aod_mean", "Mean aerosol optical depth", "envlong_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES, 1km | per 45-day period",
     "Mean aerosol optical depth in the block during this period, the standard satellite proxy for particulate pollution. STRONGLY SEASONAL: Lagos ranges 0.24 to 0.81 across periods, peaking in the Harmattan dust season, a swing far larger than its spatial variation (which is why AOD is absent from the static block table). ~6% missing from cloud screening."),
    ("aod_valid_obs", "Valid AOD retrievals", "envlong_air", "continuous",
     "Diagnostic, but also a cloudiness signal",
     "Number of valid MAIAC retrievals in this block-period. Like lst_valid_obs it is partly a seasonal cloud indicator, and should be checked before comparing aod_mean across periods."),

    ("ntl_mean_radiance", "Nighttime radiance", "envlong_light", "continuous",
     "GEE: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG, 500m | per 45-day period",
     "Mean nighttime radiance in the block during this period. NOTE VIIRS composites are MONTHLY, so a 45-day period contains only 1-2 of them — this is the coarsest series here in TIME as well as being coarse in space. A proxy for economic activity at neighbourhood scale, not for any individual business."),

    ("wbgt_mean_c", "Heat stress index (sWBGT, C)", "envlong_heatstress", "continuous",
     "Derived from ECMWF/ERA5_LAND, 11km | per 45-day period | CITY-SCALE",
     "Mean simplified Wet Bulb Globe Temperature in this block-period, combining air temperature and humidity. ERA5 heat stress was excluded from the static block table for near-zero within-city variance and appears here for its seasonality (Lagos 28.6 to 32.6C across periods). AT 11km THIS IS ~74 BLOCKS WIDE - read it along TIME, not space - though it is NOT constant within a city either: 61-249 distinct values per city-period, with up to 2.47C spread across Addis Ababa, since the grid spans 2-3 cells and picks up elevation. Missing for 1,473 Lagos blocks in every period (Lagos Island, Victoria Island and the lagoon, which ERA5-Land masks as water)."),
    ("rh_mean_pct", "Mean relative humidity (%)", "envlong_heatstress", "continuous",
     "Derived from ERA5-Land temperature and dewpoint, 11km | per 45-day period",
     "Mean relative humidity in this block-period. The variable that makes heat dangerous, and the reason wbgt_mean_c ranks these cities differently from land surface temperature. Same 11km resolution caveat and the same Lagos lagoon gap as wbgt_mean_c."),

    ("no2_mean", "Tropospheric NO2 (micromol/m2)", "envlong_air", "continuous",
     "GEE: COPERNICUS/S5P/OFFL/L3_NO2, ~1.1km | per 45-day period",
     "Mean tropospheric NO2 column density in this block-period. Specific to combustion - vehicles, generators, industry - where AOD mixes traffic with dust and biomass haze, and the two peak in different periods. Lagos ranges 30 to 90 across the window. A column density, not a surface concentration."),
]


def r_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _validate(actual, rows, excluded, label):
    registered = [r[0] for r in rows]
    unaccounted = [c for c in actual if c not in registered and c not in excluded]
    phantom = [c for c in registered if c not in actual]
    if unaccounted:
        raise SystemExit(f"{label}: columns neither registered nor excluded: "
                         f"{unaccounted}")
    if phantom:
        raise SystemExit(f"{label}: registry rows with no matching column: "
                         f"{phantom}")
    return registered


def _tribble(rows):
    return "\n".join(
        f'  "{cid}", "{r_escape(label)}", "{domain}", "{rtype}", '
        f'NA, "{cid}", "{r_escape(notes)}", "{r_escape(desc)}",'
        for cid, label, domain, rtype, notes, desc in rows)


def write_longitudinal(config, out_dir):
    path = out_dir / config["blocks_longitudinal"]["output_file"]
    actual = list(pd.read_csv(path, nrows=1).columns)
    registered = _validate(actual, ROWS_LONG, EXCLUDED_LONG, "longitudinal")
    excl = "\n".join(f"#   {c:<14} {why}" for c, why in EXCLUDED_LONG.items())
    OUT_PATH_LONG.write_text(f'''# =============================================================================
# registry_environment_blocks_longitudinal.R - registry rows for the
# BLOCK x PERIOD environmental indicators.
#
# GENERATED by cfi-environdata/python/blocks/make_block_registry.py. Edit the
# generator, not this file.
#
# Source: cfi-environdata/data/output/blocks/all_block_indicators_longitudinal.csv
# — 51,417 blocks x 16 periods of 45 days spanning 2024-07-31 to 2026-07-21.
# Column detail and caveats: that repo's
# data/output/blocks/block_data_dictionary.md
#
# A THIRD UNIT OF ANALYSIS. registry_environment.R describes BUSINESSES,
# registry_environment_blocks.R describes BLOCKS, and these describe
# BLOCK-PERIODS. Never mix them in one estimate. An indicator sharing a name
# across the three is not the same quantity: a 150m buffer around a business,
# the block containing it, and that block during one 45-day window are three
# different regions of space-time.
#
# HOW TO MERGE. JOIN ON city + block_id + period_index. `block_id` is the RAW
# grid id matching final_sampling_grid_2026.geojson and enum_data's BlockID; it
# restarts at 1 in every city, so a join on it alone fans rows out.
#
# READ THIS TABLE ALONG THE TIME AXIS. It exists because three of these
# indicators — rainfall, ERA5 heat stress and AOD — were EXCLUDED from the
# static block table for low SPATIAL variation, and carry large TEMPORAL
# variation instead (Lagos rainfall 11-594mm across periods, AOD 0.24-0.81).
# Only lst_max_c approaches block scale; rainfall is 5.5km (~37 blocks wide) and
# ERA5 heat stress 11km (~74 blocks). For spatial pattern use the static table.
#
# THE *_valid_obs COLUMNS ARE NOT ONLY DIAGNOSTICS here. Clear-sky coverage is
# itself seasonal, so a period with few observations is a statement about that
# season. Check them before comparing lst_* or aod_mean across periods.
#
# NOT REGISTERED (and why):
{{excl}}
#
# TO USE: source after registry.R and keep SEPARATE from both other registries
# unless the app can distinguish units of analysis.
# =============================================================================

REGISTRY_ENVIRONMENT_BLOCKS_LONGITUDINAL <- tribble(
  ~id, ~label, ~domain, ~type, ~source_q, ~source_col, ~notes, ~description,
{{body}}
) %>% mutate(frame = "Block-period")
'''.format(excl=excl, body=_tribble(ROWS_LONG)))
    print(f"Wrote {len(ROWS_LONG)} longitudinal registry rows to {OUT_PATH_LONG}")
    print(f"  columns: {len(actual)} | registered: {len(registered)} | "
          f"excluded: {len(EXCLUDED_LONG)}")


def main():
    config = load_config()
    out_dir = REPO_ROOT / config["blocks"]["output_dir"]
    actual = list(pd.read_csv(out_dir / "all_block_indicators.csv", nrows=1).columns)
    registered = _validate(actual, ROWS, EXCLUDED, "blocks")

    body = _tribble(ROWS)
    excl = "\n".join(f"#   {c:<12} {why}" for c, why in EXCLUDED.items())

    OUT_PATH.write_text(f'''# =============================================================================
# registry_environment_blocks.R - registry rows for BLOCK-LEVEL environmental
# indicators.
#
# GENERATED by cfi-environdata/python/blocks/make_block_registry.py. Edit the
# generator, not this file; it validates that every column of
# all_block_indicators.csv is either registered or explicitly excluded.
#
# Source: cfi-environdata/data/output/blocks/all_block_indicators.csv - zonal
# means over the sampling-grid polygons, for mapping indicators across a whole
# city. {len(ROWS)} indicators over 51,417 blocks (Addis Ababa, Jakarta, Lagos).
# Column detail and caveats: that repo's data/output/blocks/block_data_dictionary.md
#
# THIS IS A DIFFERENT UNIT OF ANALYSIS from registry_environment.R. Those rows
# describe BUSINESSES (one row per listed enterprise, buffers around a point);
# these describe BLOCKS (one row per grid polygon, zonal means). Do not mix them
# in one estimate, and note that indicators sharing a name are not numerically
# identical - a 150m buffer around a business is not the same region as the
# block containing it.
#
# HOW TO MERGE. `block_id` is the RAW grid id, matching
# final_sampling_grid_2026.geojson and enum_data's BlockID.
#
#   JOIN ON city + block_id, NOT block_id alone. Raw grid ids restart at 1 in
#   every city, so a bare join fans rows out - the same trap as the business
#   frame's country + enterprise_id. A `block_uid` column ("Lagos_1234") is
#   provided for cases wanting a single unique key.
#
# WHY FEWER INDICATORS THAN THE BUSINESS-LEVEL REGISTRY. A block map can only
# show what varies between blocks. At ~150m blocks a 1km source gives one value
# per ~44 blocks and an 11km source one per ~5,400, so ERA5 humid heat stress
# (0-5% within-city variance), CHIRPS rainfall (4-13%), night LST (0-1%) and
# most AOD (6-9%) are business-level only. They remain excellent for comparing
# CITIES - just not for mapping within one.
#
# NOT REGISTERED (and why):
{excl}
#
# TO USE: source after registry.R and bind, e.g.
#   REGISTRY_BLOCKS <- REGISTRY_ENVIRONMENT_BLOCKS
# Keep it SEPARATE from REGISTRY unless the app can distinguish units of
# analysis - binding blocks into a business-frame registry would let a caller
# estimate a block indicator on the enumeration frame, which is meaningless.
# =============================================================================

REGISTRY_ENVIRONMENT_BLOCKS <- tribble(
  ~id, ~label, ~domain, ~type, ~source_q, ~source_col, ~notes, ~description,
{body}
) %>% mutate(frame = "Block")
''')
    print(f"Wrote {len(ROWS)} block registry rows to {OUT_PATH}")
    print(f"  columns: {len(actual)} | registered: {len(registered)} | "
          f"excluded: {len(EXCLUDED)}")

    write_longitudinal(config, out_dir)


if __name__ == "__main__":
    sys.exit(main())
