"""Generate registry_environment.R — the indicator registry for cfi-map2r2-data.

The analysis app in cfi-map2r2-data drives labelling, formatting and captions
off its REGISTRY (R/registry.R). Environmental indicators produced here are
invisible to it until they have registry rows, so this emits a drop-in R file
matching that tribble's schema exactly:

    id, label, domain, type, source_q, source_col, notes, description
    ... then %>% mutate(frame = "Enumeration")

Generated rather than hand-written so it cannot drift from the data: every
column of all_indicators.csv must be either registered or explicitly excluded,
and the script fails if one is neither.

    cd python && python3 make_registry.py
"""

import sys
from pathlib import Path

import pandas as pd

from utils import load_config

REPO_ROOT = Path(__file__).parent.parent
OUT_PATH = REPO_ROOT / "registry_environment.R"

# Columns that are deliberately NOT indicators: join keys, coordinates, and
# constant provenance metadata. Listing them here (rather than ignoring silently)
# is what lets the script assert full coverage.
EXCLUDED = {
    "business_id":     "join key",
    "enterprise_id":   "join key (with country)",
    "country":         "join key (with enterprise_id)",
    "city":            "already a GROUPS entry in registry.R",
    "latitude":        "SENSITIVE - exact business location, must not reach enum_data",
    "longitude":       "SENSITIVE - exact business location, must not reach enum_data",
    "fieldwork_date":  "listing date; already on enum_data",
    "heat_window_start": "constant provenance metadata",
    "heat_window_end":   "constant provenance metadata",
    "rain_window_start": "constant provenance metadata",
    "rain_window_end":   "constant provenance metadata",
    "aod_window_start":  "constant provenance metadata",
    "aod_window_end":    "constant provenance metadata",
    "pop_year":          "constant provenance metadata (WorldPop vintage)",
}

# (id, label, domain, type, notes, description)
ROWS = [
    # ---- terrain ----
    ("elevation_m", "Elevation (m)", "env_terrain", "continuous",
     "GEE: USGS/SRTMGL1_003",
     "Metres above sea level at the business location, sampled from SRTM 30m (2000 vintage). Feeds the coastal_lowland flag. Differs sharply between cities by construction - Addis Ababa sits above 2,000m while Lagos and Jakarta are near sea level - so it is a geography control, not a finding."),

    # ---- heat ----
    ("heat_days_gt40c", "Days above 40C", "env_heat", "continuous",
     "GEE: MODIS/061/MOD11A1 | count over OBSERVED days",
     "Number of days in a fixed 730-day window where daytime land surface temperature exceeded 40C. NOT COMPARABLE ACROSS CITIES as a raw count: it counts only clear-sky days, and cloud cover makes that denominator range from ~404 observed days in Addis Ababa to ~40 in Lagos. Use heat_frac_gt40c for any comparison."),
    ("heat_frac_gt40c", "Share of observed days above 40C", "env_heat", "continuous",
     "Derived: heat_days_gt40c / lst_valid_obs",
     "Share of this location's OBSERVED days whose land surface temperature exceeded 40C, in 0-1. This is the cross-city comparable form of heat_days_gt40c, normalising away the 10x difference in clear-sky observation counts between cities. Missing where no valid observations exist, never zero."),
    ("heat_days_gt45c", "Days above 45C", "env_heat", "continuous",
     "GEE: MODIS/061/MOD11A1 | count over OBSERVED days",
     "As heat_days_gt40c at a 45C threshold. Not comparable across cities as a raw count; use heat_frac_gt45c."),
    ("heat_frac_gt45c", "Share of observed days above 45C", "env_heat", "continuous",
     "Derived: heat_days_gt45c / lst_valid_obs",
     "Share of observed days exceeding 45C land surface temperature, in 0-1. Cross-city comparable form of heat_days_gt45c."),
    ("heat_days_gt50c", "Days above 50C", "env_heat", "continuous",
     "GEE: MODIS/061/MOD11A1 | count over OBSERVED days",
     "As heat_days_gt40c at a 50C threshold. Very rare in these cities - near zero almost everywhere - so it will not support a subgroup analysis. Use heat_frac_gt50c for comparison."),
    ("heat_frac_gt50c", "Share of observed days above 50C", "env_heat", "continuous",
     "Derived: heat_days_gt50c / lst_valid_obs",
     "Share of observed days exceeding 50C land surface temperature, in 0-1. Near zero almost everywhere in these cities."),
    ("lst_mean_c", "Mean land surface temperature (C)", "env_heat", "continuous",
     "GEE: MODIS/061/MOD11A1",
     "Mean daytime LAND SURFACE temperature in Celsius over a fixed 730-day window. This is the radiative temperature of the ground, not air temperature: in built-up areas it runs 10-20C above what a weather station would report, which is what makes it useful for localised heat exposure. Terra overpasses around 10:30 local solar time, so it is mid-morning surface heat, not the afternoon peak. Unlike the day-counts, this is comparable across cities."),
    ("lst_max_c", "Maximum land surface temperature (C)", "env_heat", "continuous",
     "GEE: MODIS/061/MOD11A1",
     "Highest daytime land surface temperature observed in the 730-day window. Biased downward where clear-sky coverage is sparse (Lagos, Jakarta), since fewer observations means fewer chances to catch an extreme."),
    ("lst_valid_obs", "Clear-sky observations (LST)", "env_heat", "continuous",
     "Diagnostic, not a substantive indicator",
     "Number of clear-sky MODIS observations at this location within the 730-day window, of 730 possible. DATA QUALITY DIAGNOSTIC - its mean is not a finding. It is the denominator behind every heat_frac_* column and the reason raw heat day-counts cannot be compared across cities: city means run ~404 (Addis Ababa), ~86 (Jakarta), ~40 (Lagos). Use it to filter low-coverage locations."),

    # ---- flood ----
    ("hand_m", "Height above nearest drainage (m)", "env_flood", "continuous",
     "GEE: MERIT/Hydro/v1_0_1",
     "Vertical distance in metres from the business to the nearest stream channel along the hydrological flow path. Lower means more flood-susceptible. A topographic proxy, not a flood model: it knows nothing about drainage infrastructure, levees or rainfall-driven pluvial flooding."),
    ("hand_flood_vulnerable", "Flood-vulnerable location", "env_flood", "binary",
     "Derived: hand_m <= 5m",
     "Business sits within 5 metres above the nearest drainage channel, the standard floodplain proxy. Discriminates poorly in flat coastal cities where most of the urban area qualifies - it is TRUE for about 87% of Lagos businesses - so it separates cities better than it separates businesses within one."),
    ("jrc_max_extent", "Ever-observed surface water", "env_flood", "binary",
     "GEE: JRC/GSW1_4/GlobalSurfaceWater",
     "Surface water was detected at this exact location at least once in the 1984-2021 Landsat record. Very rare at business locations (well under 1%), so it identifies a handful of waterside premises rather than supporting a subgroup analysis."),
    ("jrc_recurrence", "Water recurrence (%)", "env_flood", "continuous",
     "GEE: JRC/GSW1_4/GlobalSurfaceWater | ~99.8% MISSING",
     "Percentage of months with water detected, 1984-2021. ALMOST ENTIRELY MISSING at business locations (99.8%) because JRC masks recurrence outside water bodies, and every non-missing value observed so far is exactly 100. Not usable as a continuous variable here - prefer jrc_max_extent, and do not impute its missingness."),
    ("coastal_lowland", "Coastal lowland", "env_flood", "binary",
     "Derived: coastal city AND elevation < 10m",
     "Business is in a designated coastal city (Lagos or Jakarta) and sits below 10 metres elevation - the standard Low-Elevation Coastal Zone definition, a proxy for storm-surge and tidal exposure. FALSE for every Addis Ababa business by construction, since the flag is only applied to coastal cities, so never read it as a within-Addis finding."),

    # ---- green ----
    ("canopy_fraction_50m", "Tree canopy within 50m", "env_green", "continuous",
     "GEE: ESA/WorldCover/v200",
     "Share of land within 50 metres classified as tree cover, in 0-1. Very low at business locations across all three cities (city means 0.3%-3.5%), so it is heavily right-skewed and a mean will be dominated by a few green outliers."),
    ("canopy_fraction_150m", "Tree canopy within 150m", "env_green", "continuous",
     "GEE: ESA/WorldCover/v200",
     "Share of land within 150 metres classified as tree cover, in 0-1. The 150m radius matches the MAP2 sampling block size, making this the neighbourhood-scale greenness measure. A proxy for shade and microclimate moderation, not a measurement of shade at the premises."),
    ("canopy_pixel_count_50m", "Valid canopy pixels (50m)", "env_green", "continuous",
     "Diagnostic, not a substantive indicator",
     "Count of valid 10m WorldCover pixels inside the 50m buffer, about 98 when complete. DATA QUALITY DIAGNOSTIC for confirming full buffer coverage."),
    ("canopy_pixel_count_150m", "Valid canopy pixels (150m)", "env_green", "continuous",
     "Diagnostic, not a substantive indicator",
     "Count of valid 10m WorldCover pixels inside the 150m buffer, about 760 when complete. DATA QUALITY DIAGNOSTIC."),
    ("canopy_tree_pixels_50m", "Tree pixels (50m)", "env_green", "continuous",
     "Diagnostic; canopy_fraction_50m is the analysis form",
     "Count of tree-classified 10m pixels within 50 metres. The numerator of canopy_fraction_50m - use the fraction for analysis."),
    ("canopy_tree_pixels_150m", "Tree pixels (150m)", "env_green", "continuous",
     "Diagnostic; canopy_fraction_150m is the analysis form",
     "Count of tree-classified 10m pixels within 150 metres. The numerator of canopy_fraction_150m - use the fraction for analysis."),

    # ---- rainfall ----
    ("rain_days_gt20mm", "Heavy rain days (>20mm)", "env_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT",
     "Days in a fixed 730-day window with more than 20mm of rainfall. UNLIKE the heat and air-quality day-counts this IS directly comparable across cities: CHIRPS is gap-filled rather than cloud-masked, so every location has all 730 days observed. At 5.5km resolution it varies almost entirely between cities, not within them."),
    ("rain_days_gt50mm", "Very heavy rain days (>50mm)", "env_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT",
     "Days in the 730-day window exceeding 50mm of rainfall, a threshold commonly associated with urban flood events. Directly comparable across cities. Near zero in Addis Ababa, which almost never sees daily totals that high."),
    ("rain_total_mm", "Total rainfall (mm)", "env_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT",
     "Total accumulated precipitation over the fixed 730-day window. Halve it for an annual figure. Varies almost entirely between cities at 5.5km resolution."),
    ("rain_max_day_mm", "Wettest day (mm)", "env_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT",
     "Highest single-day rainfall in the 730-day window - the extreme-event measure rather than the accumulation."),
    ("rain_mean_daily_mm", "Mean daily rainfall (mm)", "env_rain", "continuous",
     "GEE: UCSB-CHC/CHIRPS/V3/DAILY_SAT",
     "Mean daily precipitation over the 730-day window. A linear rescaling of rain_total_mm, so it carries no additional information."),
    ("rain_valid_obs", "Days with rainfall data", "env_rain", "continuous",
     "Diagnostic, not a substantive indicator",
     "Days with valid CHIRPS data in the window. Exactly 730 for every location because CHIRPS is gap-filled - which is precisely why the rainfall day-counts need no normalisation, unlike heat and AOD. DATA QUALITY DIAGNOSTIC with no variance."),

    # ---- air ----
    ("aod_days_gt0p4", "Days AOD above 0.4", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES | count over OBSERVED days",
     "Days in the 730-day window with aerosol optical depth above 0.4 (roughly PM2.5 ~35 ug/m3). NOT COMPARABLE ACROSS CITIES as a raw count, and the error is not subtle: ranking cities on this puts Lagos LAST for pollution, while the observation-normalised rate puts it FIRST. Use aod_frac_gt0p4."),
    ("aod_frac_gt0p4", "Share of observed days AOD above 0.4", "env_air", "continuous",
     "Derived: aod_days_gt0p4 / aod_valid_obs",
     "Share of this location's OBSERVED days with AOD above 0.4, in 0-1. The cross-city comparable form: city means are Lagos 77%, Jakarta 57%, Addis Ababa 26%, a ranking corroborated by aod_mean and the reverse of what raw day-counts suggest."),
    ("aod_days_gt0p8", "Days AOD above 0.8", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES | count over OBSERVED days",
     "Days with AOD above 0.8 (high pollution, roughly PM2.5 ~70 ug/m3). Not comparable across cities as a raw count; use aod_frac_gt0p8."),
    ("aod_frac_gt0p8", "Share of observed days AOD above 0.8", "env_air", "continuous",
     "Derived: aod_days_gt0p8 / aod_valid_obs",
     "Share of observed days with AOD above 0.8, in 0-1. Cross-city comparable form of aod_days_gt0p8."),
    ("aod_days_gt1p5", "Days AOD above 1.5", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES | count over OBSERVED days",
     "Days with AOD above 1.5 (very high / hazardous, roughly PM2.5 ~130 ug/m3). Rare outside Lagos. Not comparable across cities as a raw count; use aod_frac_gt1p5."),
    ("aod_frac_gt1p5", "Share of observed days AOD above 1.5", "env_air", "continuous",
     "Derived: aod_days_gt1p5 / aod_valid_obs",
     "Share of observed days with AOD above 1.5, in 0-1. Cross-city comparable form of aod_days_gt1p5."),
    ("aod_mean", "Mean aerosol optical depth", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES",
     "Mean aerosol optical depth at 470nm over the 730-day window - the most widely used satellite proxy for ground-level PM2.5. Needs no observation-count normalisation, so it is the safest air-quality measure for cross-city comparison. Read it as a relative exposure ranking, not an absolute PM2.5 estimate: the AOD-to-PM2.5 relationship shifts with humidity, aerosol type and boundary layer height."),
    ("aod_max", "Maximum aerosol optical depth", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES",
     "Highest AOD observed in the window - the pollution-episode measure. Biased downward where clear-sky retrievals are sparse."),
    ("aod_median", "Median aerosol optical depth", "env_air", "continuous",
     "GEE: MODIS/061/MCD19A2_GRANULES",
     "Median AOD over the window, less sensitive than the mean to a few severe pollution episodes. Prefer it to aod_mean when the question is about typical conditions rather than including extremes."),
    ("aod_valid_obs", "Clear-sky observations (AOD)", "env_air", "continuous",
     "Diagnostic, not a substantive indicator",
     "Number of days with a valid AOD retrieval in the 730-day window. DATA QUALITY DIAGNOSTIC - its mean is not a finding. It is the denominator behind every aod_frac_* column; city means run ~347 (Addis Ababa), ~202 (Jakarta), ~91 (Lagos)."),

    # ---- nightlights ----
    ("ntl_mean_radiance", "Mean nighttime radiance", "env_light", "continuous",
     "GEE: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
     "Mean nighttime light radiance (nW/cm2/sr) within 150 metres, averaged over 12 monthly composites. A well-established proxy for economic activity and infrastructure density at the NEIGHBOURHOOD level - it is not a measure of this business's revenue or activity, and should be used as a context control rather than an outcome."),
    ("ntl_median_radiance", "Median nighttime radiance", "env_light", "continuous",
     "GEE: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
     "Median monthly nighttime radiance within 150 metres over 12 months, less sensitive than the mean to one unusual month such as a festival or construction lighting."),
    ("ntl_max_radiance", "Maximum nighttime radiance", "env_light", "continuous",
     "GEE: NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
     "Brightest monthly composite within 150 metres over the 12-month window. In Lagos, gas flaring can inflate this in some areas - a real feature of the economic landscape, but worth knowing when interpreting high outliers."),

    # ---- built ----
    ("builtup_fraction_50m", "Built-up surface within 50m", "env_built", "continuous",
     "GEE: JRC/GHSL/P2023A/GHS_BUILT_S/2020",
     "Share of land within 50 metres covered by built structures, in 0-1, from GHSL 10m (2020 epoch). Near-inverse of canopy_fraction_50m in urban settings."),
    ("builtup_fraction_150m", "Built-up surface within 150m", "env_built", "continuous",
     "GEE: JRC/GHSL/P2023A/GHS_BUILT_S/2020",
     "Share of land within 150 metres covered by built structures, in 0-1. A primary driver of the urban heat island and of stormwater runoff, so it links the heat and flood indicators. NOTE it is correlated with pop_density_150m (r = 0.41), which is partly by construction since WorldPop uses built-up surface as a covariate; it is effectively uncorrelated with hrsl_density_150m (r = -0.05)."),

    # ---- population ----
    ("pop_density_50m", "Population density within 50m (WorldPop)", "env_pop", "continuous",
     "GEE: WorldPop/GP/100m/pop, 2020 | sub-pixel",
     "Residents per square kilometre within 50 metres, from WorldPop 100m (2020). SUB-PIXEL: a 50m buffer is smaller than one ~93m WorldPop cell, so this is effectively the containing cell's value and correlates with pop_density_150m at r = 0.9987. Prefer the 150m column, which also has fewer missing values."),
    ("pop_density_150m", "Population density within 150m (WorldPop)", "env_pop", "continuous",
     "GEE: WorldPop/GP/100m/pop, 2020 | see hrsl_density_150m",
     "Residents per square kilometre within 150 metres, from WorldPop 100m (2020). RESIDENTIAL population - it disaggregates census counts, i.e. where people sleep - so it understates commercial districts with heavy daytime footfall. Missing for 28 businesses on the North Jakarta coast where WorldPop's land mask excludes settled land; do NOT impute those as zero, and note hrsl_density_150m covers them. Disagrees substantially with hrsl_density_150m on level (Addis Ababa 12,326 vs 26,486) while ranking neighbourhoods similarly within a city (r = 0.73-0.95), so treat absolute and cross-city density claims with caution."),
    ("hrsl_density_50m", "Population density within 50m (Meta HRSL)", "env_pop", "continuous",
     "Community GEE asset: projects/sat-io/open-datasets/hrsl/hrslpop",
     "Residents per square kilometre within 50 metres, from Meta's High Resolution Settlement Layer (~31m, building-footprint constrained). Despite the finer grid it still correlates with hrsl_density_150m at r = 0.9974 - the redundancy comes from the spatial autocorrelation of population, not pixel size - so prefer the 150m column."),
    ("hrsl_density_150m", "Population density within 150m (Meta HRSL)", "env_pop", "continuous",
     "Community GEE asset: projects/sat-io/open-datasets/hrsl/hrslpop | PREFERRED population measure",
     "Residents per square kilometre within 150 metres, from Meta's High Resolution Settlement Layer. THE PREFERRED population indicator: finest resolution (~31m), no missing values, and uncorrelated with builtup_fraction_150m (r = -0.05) so it introduces no collinearity. Population is allocated only to cells where a CNN detected a building, which is why it covers settled North Jakarta coast that WorldPop's land mask misses. Use pop_density_150m as a robustness check - any population result that flips between the two is not robust to source choice. Census vintage is roughly 2015-2020, so it is higher-resolution than WorldPop but not more recent."),
]


def r_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main():
    config = load_config()
    out_dir = REPO_ROOT / config["output_dir"]
    df = pd.read_csv(out_dir / "all_indicators.csv", nrows=1)
    actual = list(df.columns)

    registered = [r[0] for r in ROWS]
    dupes = {c for c in registered if registered.count(c) > 1}
    if dupes:
        raise SystemExit(f"Duplicate registry ids: {sorted(dupes)}")

    unaccounted = [c for c in actual if c not in registered and c not in EXCLUDED]
    phantom = [c for c in registered if c not in actual]
    if unaccounted:
        raise SystemExit(
            f"{len(unaccounted)} column(s) in all_indicators.csv are neither "
            f"registered nor excluded: {unaccounted}\n"
            f"Add them to ROWS or EXCLUDED in this script.")
    if phantom:
        raise SystemExit(
            f"Registry rows with no matching column: {phantom}")

    lines = []
    for cid, label, domain, rtype, notes, desc in ROWS:
        notes_r = f'"{r_escape(notes)}"' if notes else "NA"
        lines.append(
            f'  "{cid}", "{r_escape(label)}", "{domain}", "{rtype}", '
            f'NA, "{cid}", {notes_r}, "{r_escape(desc)}",')

    excl = "\n".join(f"#   {c:<22} {why}" for c, why in EXCLUDED.items())
    body = "\n".join(lines)

    OUT_PATH.write_text(f'''# =============================================================================
# registry_environment.R - registry rows for the environmental indicators.
#
# GENERATED by cfi-environdata/python/make_registry.py. Do not edit by hand
# there or here; edit the generator, which validates that every column of
# all_indicators.csv is either registered or explicitly excluded.
#
# Source data: cfi-environdata/data/output/all_indicators.csv, produced by a
# Python + Google Earth Engine pipeline that samples remote-sensing rasters at
# each listed business's coordinates. Column-level detail, provenance and
# caveats: that repo's data/output/data_dictionary.md.
#
# FRAME. These attach to the ENUMERATION frame: the GSMM listing is the census
# of business locations, so every listed business has coordinates whether or
# not it was selected or interviewed. They reach all_data through the existing
# GSMM linkage (prep_cto.R records gsmm_business_id).
#
# ID CONVENTION - A DELIBERATE DEVIATION. Enumeration-frame ids in registry.R
# are prefixed `enum_`. These are not, because the id must match the column name
# in all_indicators.csv, which is fixed by the producing pipeline and its data
# dictionary. Renaming on import would work but would break that correspondence.
# Worth a decision before merging.
#
# JOIN. On country + enterprise_id, NOT enterprise_id alone: GSMM ids are unique
# only within a country (5 collide across countries in the five-city frame).
# The source file's business_id is already "<Country>_<EnterpriseID>".
#
# NOT REGISTERED (and why):
{excl}
#
# latitude/longitude are excluded as SENSITIVE. They must never reach
# enum_snapshot.rds, which is committed and shipped to the deployed app. Only
# the derived indicators below are safe: they describe the neighbourhood, not
# the address.
#
# TO USE: source this file after registry.R and bind the rows, e.g.
#   REGISTRY <- bind_rows(REGISTRY, REGISTRY_ENVIRONMENT)
# =============================================================================

REGISTRY_ENVIRONMENT <- tribble(
  ~id, ~label, ~domain, ~type, ~source_q, ~source_col, ~notes, ~description,
{body}
) %>% mutate(frame = "Enumeration")
''')
    print(f"Wrote {len(ROWS)} registry rows to {OUT_PATH}")
    print(f"  columns in all_indicators.csv: {len(actual)}")
    print(f"  registered: {len(registered)} | excluded: {len(EXCLUDED)}")
    by_domain = {}
    for r in ROWS:
        by_domain[r[2]] = by_domain.get(r[2], 0) + 1
    for d, n in sorted(by_domain.items()):
        print(f"    {d:<14} {n}")


if __name__ == "__main__":
    sys.exit(main())
