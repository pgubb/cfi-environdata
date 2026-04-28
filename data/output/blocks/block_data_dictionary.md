# Data Dictionary: `all_block_indicators.csv`

Output of the block-level aggregation pipeline. Each row corresponds to one sampling frame block (~150m × 150m polygon). All indicator values are **zonal statistics** computed over all pixels within the block polygon, rather than point samples.

This pipeline is separate from the business-level point extraction (`all_indicators.csv`). It serves study-area-level spatial analysis — characterising environmental conditions across the full extent of each city's sampling frame, and enabling cross-indicator analysis (e.g., geospatial correlation between heat and shade).

---

## Identification Columns

| Column | Type | Description |
|---|---|---|
| `block_id` | string | Unique block identifier, prefixed with city name (e.g., `Sao Paulo_1234`). Derived from the sampling frame GeoJSON `block_id` property. |
| `city` | string | City name (one of: Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos). Derived from the source GeoJSON file's country directory. |

---

## Indicator 1: Elevation

| Column | Type | Units | Description |
|---|---|---|---|
| `elev_mean_m` | float | metres | Mean SRTM elevation across all 30m pixels in the block. |
| `elev_min_m` | float | metres | Minimum elevation within the block. |
| `elev_max_m` | float | metres | Maximum elevation within the block. |
| `elev_std_m` | float | metres | Standard deviation of elevation within the block (a proxy for terrain roughness). |
| `elev_range_m` | float | metres | Elevation range within the block (max − min). |

**Data source:** NASA SRTM 30m (`USGS/SRTMGL1_003`).

**Processing:** `reduceRegions` with combined mean/min/max/stdDev reducers at 30m scale. Each ~150m × 150m block contains approximately 25 SRTM pixels.

---

## Indicator 2: Extreme Heat Days (Land Surface Temperature)

| Column | Type | Units | Description |
|---|---|---|---|
| `heat_days_gt40c_mean` | float | count of days | Mean count of days where daytime LST exceeded 40°C, averaged across pixels in the block. |
| `heat_days_gt45c_mean` | float | count of days | Mean count of days where daytime LST exceeded 45°C. |
| `heat_days_gt50c_mean` | float | count of days | Mean count of days where daytime LST exceeded 50°C. |
| `lst_mean_c` | float | °C | Mean daytime LST across block pixels and time. |
| `lst_max_c` | float | °C | Maximum daytime LST observed in the block over the analysis period. |
| `lst_valid_obs_mean` | float | count of days | Mean valid (clear-sky) observation count across block pixels. |
| `heat_window_start` | string | date | Start date of the analysis window. |
| `heat_window_end` | string | date | End date of the analysis window. |

**Data source:** MODIS/Terra LST Daily 1km (`MODIS/061/MOD11A1`).

**Processing:** Same temporal compositing as the point pipeline (threshold binary images → sum over time), then the resulting multi-band image is reduced over each block polygon with `ee.Reducer.mean()` at 1000m scale. At 1km resolution, most 150m blocks fall within a single MODIS pixel.

**Temporal window:** Fixed analysis period defined by `blocks.analysis_end_date` minus `heat.trailing_years` (default: 2 years).

---

## Indicator 3: Flood Vulnerability

| Column | Type | Units | Description |
|---|---|---|---|
| `hand_mean_m` | float | metres | Mean Height Above Nearest Drainage (HAND) across the block. |
| `hand_min_m` | float | metres | Minimum HAND in the block — represents the most flood-exposed point. |
| `hand_flood_frac` | float | proportion (0–1) | Fraction of block area with HAND ≤ 5m (flood-vulnerable). |
| `jrc_max_extent_frac` | float | proportion (0–1) | Fraction of block within JRC maximum observed water extent (1984–2021). |
| `jrc_recurrence_mean` | float | percentage (0–100) | Mean JRC water recurrence across the block. |
| `coastal_lowland` | integer | binary (0/1) | 1 if coastal city (Lagos/Jakarta) and mean block elevation < 10m. |

**Data sources:** MERIT Hydro HAND (`MERIT/Hydro/v1_0_1`), JRC Global Surface Water (`JRC/GSW1_4/GlobalSurfaceWater`), SRTM elevation.

**Processing:** Multiple `reduceRegions` calls at 30m scale. `hand_flood_frac` is the mean of a binary mask (HAND ≤ 5m → 1), equivalent to the fraction of pixels meeting the threshold. `jrc_max_extent_frac` is similarly the mean of the binary `max_extent` band.

---

## Indicator 4: Tree Canopy Cover

| Column | Type | Units | Description |
|---|---|---|---|
| `canopy_fraction` | float | proportion (0–1) | Fraction of the block area classified as tree cover. A value of 0.15 means 15% of the block's 10m pixels are trees. |
| `canopy_pixel_count` | integer | count | Total number of valid 10m ESA WorldCover pixels within the block. Expected ~225 for a 150m × 150m block. |
| `canopy_tree_pixels` | integer | count | Number of tree-classified pixels within the block. |

**Data source:** ESA WorldCover 2021, 10m (`ESA/WorldCover/v200`).

**Processing:** The WorldCover `Map` band is converted to a binary tree mask (class 10 → 1, all others → 0), then reduced over each block polygon with mean/count/sum reducers at 10m scale. No buffer is applied — the block polygon itself is the analysis unit.

**Analytical note:** This is the primary variable for heat–shade correlation analysis. At the block level, `canopy_fraction` directly represents the proportion of the block with overhead tree cover, which modulates surface temperature. Correlating `canopy_fraction` with `lst_mean_c` across blocks within each city reveals the strength of the urban cooling effect.

---

## Indicator 5: Heavy Rainfall Days

| Column | Type | Units | Description |
|---|---|---|---|
| `rain_days_gt20mm` | float | count of days | Mean days with precipitation > 20mm across block pixels. |
| `rain_days_gt50mm` | float | count of days | Mean days with precipitation > 50mm. |
| `rain_total_mm` | float | mm | Mean total accumulated precipitation across block pixels. |
| `rain_max_day_mm` | float | mm | Mean maximum single-day precipitation. |
| `rain_mean_daily_mm` | float | mm/day | Mean daily precipitation. |
| `rain_valid_obs` | float | count of days | Mean valid observation count. |
| `rain_window_start` | string | date | Start of analysis window. |
| `rain_window_end` | string | date | End of analysis window. |

**Data source:** CHIRPS Daily v2.0 (~5.5km, `UCSB-CHG/CHIRPS/DAILY`).

**Processing:** Time-series composites reduced at 5566m scale. At ~5.5km resolution, all blocks within the same neighbourhood share identical values. Variation is primarily between cities and city quadrants.

---

## Indicator 6: Air Quality (Aerosol Optical Depth)

| Column | Type | Units | Description |
|---|---|---|---|
| `aod_days_gt0p4` | float | count of days | Mean days with AOD > 0.4 (moderate pollution). |
| `aod_days_gt0p8` | float | count of days | Mean days with AOD > 0.8 (high pollution). |
| `aod_days_gt1p5` | float | count of days | Mean days with AOD > 1.5 (very high pollution). |
| `aod_mean` | float | dimensionless | Mean AOD at 470nm over the analysis period. |
| `aod_max` | float | dimensionless | Maximum AOD observed. |
| `aod_valid_obs` | float | count of days | Mean valid observation count. |
| `aod_window_start` | string | date | Start of analysis window. |
| `aod_window_end` | string | date | End of analysis window. |

**Data source:** MODIS MAIAC AOD 1km (`MODIS/061/MCD19A2_GRANULES`).

**Processing:** Scaled AOD composites reduced at 1000m scale. Most blocks fall within a single AOD pixel.

---

## Indicator 7: Nighttime Lights

| Column | Type | Units | Description |
|---|---|---|---|
| `ntl_mean_radiance` | float | nW/cm²/sr | Mean nighttime radiance, averaged across block pixels and the trailing 12 monthly composites. |
| `ntl_max_radiance` | float | nW/cm²/sr | Maximum monthly radiance observed in the block. |

**Data source:** VIIRS DNB Monthly Composites (~500m, `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG`).

**Processing:** Mean and max temporal composites reduced over block polygons at 500m scale. The 150m block fits within a single VIIRS pixel.

---

## Indicator 8: Built-up Surface Fraction

| Column | Type | Units | Description |
|---|---|---|---|
| `builtup_fraction` | float | proportion (0–1) | Mean built-up surface fraction across the block. |
| `builtup_pixel_count` | integer | count | Number of valid 10m GHSL pixels within the block. |

**Data source:** JRC GHSL Built-up Surface 2020, 10m (`JRC/GHSL/P2023A/GHS_BUILT_S/2020`).

**Processing:** GHSL `built_surface` band (0–100%) normalised to 0–1, then reduced with mean/count at 10m scale. No buffer — the block polygon is the analysis unit.

**Analytical note:** Together with `canopy_fraction`, `builtup_fraction` characterises the block's physical land cover composition. High built-up + low canopy blocks are expected to show elevated LST (urban heat island), while low built-up + high canopy blocks represent greener, cooler areas.
