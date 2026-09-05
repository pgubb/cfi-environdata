# Data Dictionary: `all_indicators.csv`

Output of the `cfi-environdata` remote sensing extraction pipeline. One row per **listed business** from the GSMM enumeration, built by `python/prepare_gsmm_input.py` and extracted by `python/run_all.py`. 86 columns: 7 passthrough from the input, 70 GEE-derived, 8 derived exceedance rates, and 1 composite index.

**Last generated:** 2026-09-04 (13 indicators), 11,468 businesses across Addis Ababa (4,301), Jakarta (4,072) and Lagos (3,095) — the three cities whose listing is complete. Delhi (7,357) and Sao Paulo (3,508) are present in the source file but excluded via `gsmm.include_cities` in `config.yaml` pending completion; set that key to `null` to extract all 22,333.

**Input provenance changed 2026-09-04.** The pipeline now consumes `cfi-map2r2-data/data/processed/gsmm_coords_for_environdata.csv` rather than reading the raw GSMM `.xlsx` exports itself. That repo owns every preparation and cleaning step — authoritative export selection, de-duplication, date parsing, decimal normalisation — so those rules live in one place instead of being reimplemented here. Validation of the switch: for the 10,989 businesses extracted under the old path, the prepared coordinates are byte-identical (max difference 0.00000000) with all listing dates matching.

> **These rows carry exact business coordinates.** `data/input/gsmm_listings.csv` and any file derived from it are git-ignored and must not be copied into `cfi-map2r2-data`. Only the derived indicator columns are safe to share back — they describe the neighbourhood, not the address. See the header of `cfi-map2r2-data/R/prep_enumeration.R`.

---

## Input Passthrough Columns

| Column | Type | Description |
|---|---|---|
| `business_id` | string | **Composite key: `<Country>_<Enterprise ID>`** (e.g. `Nigeria_12641538`). GSMM enterprise IDs are unique only *within* a country — 5 IDs are reused across two countries in the five-city frame — so a bare ID would silently fan out rows on merge. |
| `latitude` | float | WGS84 latitude of the business (decimal degrees). |
| `longitude` | float | WGS84 longitude of the business (decimal degrees). |
| `city` | string | City name (one of: Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos). Determines the analysis window group and coastal-flag eligibility. |
| `country` | string | Source country. **Join back onto `enum_data` on `country` + `enterprise_id`, never `enterprise_id` alone.** |
| `enterprise_id` | string | The raw GSMM `Enterprise ID`, unprefixed. Not unique on its own — see `business_id`. |
| `fieldwork_date` | string | **Date the business was listed** during GSMM enumeration (YYYY-MM-DD), from the export's `Date time` column. Descriptive only — **it no longer defines any indicator's temporal window** (see below). |

---

## The analysis window (applies to indicators 2, 5, 6, 7)

Four indicators reduce an image collection over a trailing window and sample the result per point. Two properties of that window matter for interpretation:

**Grouping is by city, not by listing date.** Two businesses listed a week apart share >99% of a two-year window, and at MODIS (1 km) / CHIRPS (5.5 km) resolution the per-date precision buys nothing while costing ~10x more computation (29 distinct listing dates vs 3 cities). **Consequence: every business in a city receives the same window, so these indicators vary only *spatially* within a city, never temporally.**

**The window is a fixed length.** It ends at `time_window.analysis_end_date` in `config.yaml` (currently **2026-07-31**) and runs back exactly `trailing_years` / `trailing_months`. Set that key to `null` to anchor each city at its own latest listing date instead (lengths stay equal, calendar periods become city-specific).

Fixed length matters because the `*_days_gt*` columns are **counts**. An earlier version widened the window to span all listing dates (`min(date) − 2yr → max(date)`), producing 755–761 days depending on the city's fieldwork spread — which inflated those counts and made them non-comparable across cities. All windows are now exactly **730 days** (2024-07-31 → 2026-07-31), or 365 for nightlights.

`analysis_end_date` is set to 2026-07-31 because that is the last date with complete CHIRPS v3 coverage. Listing runs to 2026-08-15, so the final ~2 weeks are excluded deliberately: including them would leave rainfall with no data over a period the other indicators covered.

---

## Indicator 1: Elevation

| Column | Type | Units | Description |
|---|---|---|---|
| `elevation_m` | integer | metres above sea level | Elevation at the business point location. |
| `slope_degrees` | float | degrees | Terrain slope, from `ee.Terrain.slope` on the same DEM. A landslide-susceptibility proxy (the survey asks about `clim_*_landslide`) and a surface-runoff term linking terrain to flood exposure. City means: Addis Ababa 3.9°, Lagos 2.9°, Jakarta 2.6°. |

**Data source:** NASA Shuttle Radar Topography Mission (SRTM) Version 3, 1 arc-second (~30m) global elevation model.
- GEE asset: `USGS/SRTMGL1_003`, band `elevation`
- Reference: Farr, T.G. et al. (2007). "The Shuttle Radar Topography Mission." *Reviews of Geophysics*, 45(2).

**Processing:** The SRTM raster value is sampled at each business point coordinate using `ee.Image.reduceRegions` with `ee.Reducer.first()` at a scale of 30m. No interpolation, smoothing, or temporal filtering is applied — the value is the raw SRTM pixel value at the point.

**Coverage note:** SRTM covers latitudes 60°N to 56°S. All five study cities fall within this range. The elevation surface dates from February 2000; it reflects bare-earth radar returns and may differ from current ground level in areas with significant land-use change (e.g., reclamation, excavation) since 2000.

---

## Indicator 2: Extreme Heat Days (Land Surface Temperature)

| Column | Type | Units | Description |
|---|---|---|---|
| `heat_days_gt40c` | integer | count of days | Number of days in the trailing 2-year window where daytime land surface temperature exceeded 40°C. |
| `heat_days_gt45c` | integer | count of days | Number of days in the trailing 2-year window where daytime land surface temperature exceeded 45°C. |
| `heat_days_gt50c` | integer | count of days | Number of days in the trailing 2-year window where daytime land surface temperature exceeded 50°C. |
| `heat_frac_gt40c` | float | proportion (0–1) | **Share of OBSERVED days** exceeding 40°C = `heat_days_gt40c / lst_valid_obs`. **Use this, not the raw count, for any cross-city comparison.** |
| `heat_frac_gt45c` | float | proportion (0–1) | Share of observed days exceeding 45°C. |
| `heat_frac_gt50c` | float | proportion (0–1) | Share of observed days exceeding 50°C. |
| `heat_nights_gt20c` | integer | count of nights | Nights in the window whose land surface temperature stayed above 20°C. Same clear-sky caveat as the day counts — normalise with `heat_nights_frac_gt20c` for cross-city comparison. |
| `heat_nights_frac_gt20c` | float | proportion (0–1) | Share of OBSERVED nights above 20°C. Cross-city comparable. |
| `heat_nights_gt25c` | integer | count of nights | Nights above 25°C. |
| `heat_nights_frac_gt25c` | float | proportion (0–1) | Share of observed nights above 25°C. |
| `lst_night_mean_c` | float | °C | Mean NIGHT-TIME land surface temperature (Aqua/Terra night overpass). |
| `lst_night_min_c` | float | °C | Coolest night-time land surface temperature observed in the window. |
| `lst_night_valid_obs` | integer | count of nights | Clear-sky night observations, of 730 possible. Denominator for the `heat_nights_frac_*` columns. Diagnostic, not a substantive indicator. |
| `lst_mean_c` | float | °C | Mean daytime land surface temperature across all valid observations in the trailing 2-year window. |
| `lst_max_c` | float | °C | Maximum daytime land surface temperature observed in the trailing 2-year window. |
| `lst_valid_obs` | integer | count of days | Number of clear-sky (non-masked) MODIS observations at the point within the trailing 2-year window. |
| `heat_window_start` | string | date (YYYY-MM-DD) | Start of the window. Constant across all rows (2024-07-31). |
| `heat_window_end` | string | date (YYYY-MM-DD) | End of the window. Constant across all rows (2026-07-31). |

**Data source:** MODIS/Terra Land Surface Temperature and Emissivity Daily Global 1km (MOD11A1), Collection 6.1.
- GEE asset: `MODIS/061/MOD11A1`, band `LST_Day_1km`
- Satellite: Terra (descending node, ~10:30 local solar time overpass)
- Reference: Wan, Z. (2014). "New refinements and validation of the collection-6 MODIS land-surface temperature/emissivity product." *Remote Sensing of Environment*, 140, 36–45.

**Processing:**

1. **Temporal filtering:** The MODIS collection is filtered to a fixed 730-day window per city (see *The analysis window* above) — **not** to a per-business window. The stacked summary image is built once per city and sampled for every batch in that city. Businesses within a city therefore differ only by location, never by listing date.

2. **Unit conversion:** Raw MODIS LST_Day_1km values are stored as scaled integers in Kelvin (digital number × 0.02 = temperature in Kelvin). Each image is converted to Celsius: `(DN × 0.02) − 273.15`.

3. **Threshold counts (`heat_days_gt{X}c`):** For each threshold (40, 45, 50°C), each daily image is converted to a binary mask (1 where LST > threshold, 0 otherwise). These binary images are summed across the time series to produce a count of exceedance days.

4. **Continuous summaries (`lst_mean_c`, `lst_max_c`):** The pixel-wise temporal mean and maximum are computed across all valid images in the window.

5. **Valid observation count (`lst_valid_obs`):** The number of non-masked (clear-sky) images at the point. MODIS applies a built-in quality control mask; cloudy or low-quality pixels are excluded automatically.

6. **Spatial sampling:** All summary bands are stacked into a single image and sampled at each business point using `ee.Image.reduceRegions` with `ee.Reducer.first()` at a scale of 1000m (matching MODIS native resolution).

**Analytical notes:**

- **Land Surface Temperature vs. Air Temperature:** LST measures the radiative temperature of the land surface, not the ambient air temperature. In urban areas with impervious surfaces, LST can be 10–20°C higher than air temperature measured at weather stations. LST is more relevant for characterising localised heat exposure of ground-level businesses and captures urban heat island variation within a city.
- **Cloud bias — `heat_days_gt*` are NOT comparable across cities as raw counts.** These are counts of *clear-sky* exceedance days, and clear-sky coverage differs enormously by city. Observed in the 2026-08-26 run, out of 730 possible days:

  | City | mean `lst_valid_obs` | coverage |
  |---|---|---|
  | Addis Ababa | 404 | 55% |
  | Jakarta | 86 | 12% |
  | Lagos | 40 | 6% |

  Lagos's `heat_days_gt40c = 0` means "0 of ~40 observed days"; Addis's `0` means "0 of ~404". A 10x difference in denominator. **Normalise before comparing across cities** — `heat_days_gt40c / lst_valid_obs` gives the fraction of observed days exceeding the threshold. `lst_mean_c` and `lst_max_c` are unaffected by this (they are averages over whatever was observed), though `lst_max_c` is still biased low where coverage is sparse.
- **Resolution:** At 1km, multiple businesses within the same neighbourhood will share a MODIS pixel and receive identical values. This limits within-city spatial variation for this indicator.
- **Overpass time:** The Terra satellite passes over at ~10:30 local solar time. This captures mid-morning surface temperature, which is typically lower than the afternoon peak. Values should not be interpreted as daily maximum air temperature.

---

## Indicator 3: Flood Vulnerability

| Column | Type | Units | Description |
|---|---|---|---|
| `hand_m` | float | metres | Height Above Nearest Drainage (HAND) — the vertical distance from the business location to the nearest stream channel along the hydrological flow path. Lower values indicate greater proximity to drainage channels and higher flood susceptibility. |
| `hand_flood_vulnerable` | integer | binary (0/1) | 1 if `hand_m` ≤ 5 metres, 0 otherwise. A HAND value ≤ 5m is a standard proxy for floodplain membership in the hydrological literature. |
| `jrc_max_extent` | integer | binary (0/1) | 1 if the location falls within the maximum observed water extent (1984–2021), 0 otherwise. Indicates whether surface water has *ever* been detected at this location in the Landsat archive. |
| `jrc_recurrence` | float | percentage (0–100) | Water recurrence: percentage of months with water detection, 1984–2021. `NaN` where the pixel has never been observed as water — which is **almost everywhere**: in the 2026-08-26 run this column was null for **10,970 of 10,989 rows (99.8%)**, and all 19 non-null values were exactly 100.0. Effectively unusable as a continuous variable at business locations. Use `jrc_max_extent` (fully populated binary) instead. |
| `coastal_lowland` | integer | binary (0/1) | 1 if the business is in a designated coastal city (Lagos or Jakarta) **and** its SRTM elevation is below 10 metres above sea level. 0 otherwise. A proxy for storm-surge and tidal flood exposure. |

### HAND

**Data source:** MERIT Hydro — Global Hydrography Datasets, version 1.0.1.
- GEE asset: `MERIT/Hydro/v1_0_1`, band `hnd`
- Resolution: ~90m (3 arc-seconds)
- Reference: Yamazaki, D. et al. (2019). "MERIT Hydro: A high-resolution global hydrography map based on latest topography datasets." *Water Resources Research*, 55(6), 5053–5073.

**Processing:** The pre-computed HAND raster value is sampled at each business point using `ee.Image.reduceRegions` with `ee.Reducer.first()` at a scale of 30m. The binary `hand_flood_vulnerable` flag is computed client-side by applying the ≤ 5m threshold.

**Analytical notes:**
- HAND is a topographic proxy for flood susceptibility, not a hydrodynamic flood model. It does not account for drainage infrastructure, levees, or pluvial (rainfall-driven) flooding. It is most reliable for identifying fluvial (river) floodplain exposure.
- The 5m threshold is a widely used default (Nobre et al., 2011) but is not universally appropriate. In flat coastal cities like Lagos, most of the urban area may fall below 5m HAND, reducing discriminatory power. Consider exploring alternative thresholds (e.g., 2m, 3m) for coastal contexts.

### JRC Global Surface Water

**Data source:** European Commission Joint Research Centre (JRC) Global Surface Water dataset, based on Landsat 5, 7, and 8 imagery (1984–2021).
- GEE asset: `JRC/GSW1_4/GlobalSurfaceWater`, bands `max_extent` and `recurrence`
- Resolution: 30m
- Reference: Pekel, J.-F. et al. (2016). "High-resolution mapping of global surface water and its long-term changes." *Nature*, 540(7633), 418–422.

**Processing:** The `max_extent` and `recurrence` bands are sampled at each business point using `ee.Image.reduceRegions` with `ee.Reducer.first()` at a scale of 30m. No buffering is applied — values reflect the exact pixel at the point coordinate.

**Analytical notes:**
- `jrc_max_extent` captures the historical maximum water footprint. A value of 1 means water was detected at least once at this location over 37 years of Landsat observations. It does not indicate current water presence or flood frequency.
- `jrc_recurrence` is `NaN` for pixels never classified as water. **In practice this means it is ~99.8% missing at business locations** — businesses are on land, so the column carries almost no information here. It is retained for completeness; prefer `jrc_max_extent`. Consider dropping it from analysis datasets rather than treating its nulls as missing data to impute.
- JRC surface water detection is based on optical imagery and can be affected by cloud cover, urban surface reflectance, and shadows. It may undercount flood events in persistently cloudy regions.

### Coastal Lowland Flag

**Data source:** Derived from SRTM elevation (see Indicator 1) combined with a city-level designation.

**Processing:** The flag is set to 1 if two conditions are both met: (a) the `city` field is "Lagos" or "Jakarta" (the two coastal study cities, as configured in `config.yaml`), and (b) the SRTM elevation at the business point is below 10 metres above sea level. The 10m threshold corresponds to the standard Low-Elevation Coastal Zone (LECZ) definition used in climate vulnerability assessments (McGranahan et al., 2007).

---

## Indicator 4: Tree Canopy Cover

| Column | Type | Units | Description |
|---|---|---|---|
| `canopy_fraction_50m` | float | proportion (0–1) | Fraction of 10m pixels classified as "tree cover" within a 50m radius buffer around the business point. Captures immediate-surroundings canopy. |
| `canopy_pixel_count_50m` | integer | count of pixels | Total number of valid 10m ESA WorldCover pixels within the 50m buffer. Expected ~80 pixels. |
| `canopy_tree_pixels_50m` | float | count of pixels | Number of tree-classified pixels within the 50m buffer. |
| `canopy_fraction_150m` | float | proportion (0–1) | Fraction of 10m pixels classified as "tree cover" within a 150m radius buffer around the business point. A value of 0.25 means 25% of the area within 150m is tree-covered. |
| `canopy_pixel_count_150m` | integer | count of pixels | Total number of valid 10m ESA WorldCover pixels within the 150m buffer. Expected ~700–800 pixels. |
| `canopy_tree_pixels_150m` | float | count of pixels | Number of tree-classified pixels within the 150m buffer. |

**Data source:** ESA WorldCover 2021, version 200.
- GEE asset: `ESA/WorldCover/v200`, band `Map`
- Resolution: 10m
- Classification: Derived from Sentinel-1 and Sentinel-2 imagery for the year 2021
- Tree cover class value: 10 (in ESA WorldCover classification scheme)
- Reference: Zanaga, D. et al. (2022). "ESA WorldCover 10m 2021 v200." Zenodo. doi:10.5281/zenodo.7254221

**Processing:**

1. **Binary tree mask:** The WorldCover `Map` band (a categorical land cover classification) is converted to a binary raster where pixels with value 10 ("Tree cover") are set to 1 and all other classes to 0.

2. **Buffering:** Two circular buffers are constructed around each business point: 50m (immediate surroundings) and 150m (neighbourhood scale, matching the MAP2 block size).

3. **Zonal reduction:** Three reducers are applied simultaneously within each buffer at 10m scale:
   - `ee.Reducer.mean()` → `canopy_fraction_{r}m` (mean of the binary mask = proportion of tree pixels)
   - `ee.Reducer.count()` → `canopy_pixel_count_{r}m` (total valid pixels in buffer)
   - `ee.Reducer.sum()` → `canopy_tree_pixels_{r}m` (sum of binary mask = count of tree pixels)

**Analytical notes:**
- The 50m buffer captures the immediate surroundings of the business (roughly one street block). The 150m buffer matches the approximate block size (150m × 150m) used in the MAP2 sampling design, providing a neighbourhood-level shade/canopy assessment. Comparing the two reveals whether canopy is localised (e.g., a single street tree) or broadly distributed.
- ESA WorldCover classifies "tree cover" as areas where tree canopy covers more than 15% of the 10m pixel. It includes forest, woodland, and scattered trees in urban and peri-urban settings. It does *not* distinguish tree height — a 3m shrubby tree and a 20m shade tree both count equally.
- The classification reflects 2021 land cover. Urban tree planting or removal between 2021 and the fieldwork date will not be captured.
- In densely built urban areas, `canopy_fraction` may be very low (< 0.05). Consider whether a log transformation or categorisation is appropriate for analysis, as the distribution is likely right-skewed.
- The canopy fraction values serve as a proxy for shade availability and microclimate moderation in the area around each business, not a direct shade measurement. Actual shade at a specific point depends on canopy height, building shadows, and solar angle, which are not captured here.

---

## Indicator 5: Heavy Rainfall Days

| Column | Type | Units | Description |
|---|---|---|---|
| `rain_days_gt20mm` | integer | count of days | Number of days in the trailing 2-year window where daily precipitation exceeded 20mm (heavy rain). |
| `rain_days_gt50mm` | integer | count of days | Number of days in the trailing 2-year window where daily precipitation exceeded 50mm (very heavy rain / potential flood trigger). |
| `rain_total_mm` | float | mm | Total accumulated precipitation over the trailing 2-year window. |
| `rain_max_day_mm` | float | mm | Maximum single-day precipitation recorded in the trailing 2-year window. |
| `rain_mean_daily_mm` | float | mm/day | Mean daily precipitation over the trailing 2-year window. |
| `rain_valid_obs` | integer | count of days | Number of days with valid CHIRPS data in the window. CHIRPS is gap-filled, so this should be close to the total number of days (~730). |
| `rain_window_start` | string | date (YYYY-MM-DD) | Start date of the precipitation window. |
| `rain_window_end` | string | date (YYYY-MM-DD) | End date of the precipitation window. |

**Data source:** CHIRPS version 3, daily, "sat" variant.
- GEE asset: `UCSB-CHC/CHIRPS/V3/DAILY_SAT`, band `precipitation`
- Resolution: 0.05° (~5.5km)
- Coverage: this asset holds 10,439 daily images from 1998-01-01 to 2026-07-31 (the catalog page quotes 1981 for the CHIRPS family)
- Reference: Funk, C. et al. (2015). "The climate hazards infrared precipitation with stations — a new environmental record for monitoring extremes." *Scientific Data*, 2, 150066.

**Changed 2026-08-26** from `UCSB-CHG/CHIRPS/DAILY` (v2.0 Final, station-blended, 1981–). Same band name and same 5,566 m grid, so no column or scale changes.

**What `_SAT` means — it is *not* satellite-only.** DAILY_SAT partitions **station-blended pentadal CHIRPS-v3 totals** into daily amounts using NASA IMERG Late V07. Station observations still inform the pentad totals; only the daily disaggregation is satellite-driven. Gauge calibration is therefore retained, not discarded. (`UCSB-CHC/CHIRPS/V3/DAILY` — a blended daily variant — does not exist in the catalog; `DAILY_SAT` is the only V3 daily product.)

**Processing:**

1. **Temporal filtering:** Filtered to the fixed 730-day window per city (see *The analysis window* above). Businesses are grouped by city and processed against a single CHIRPS aggregation, since at 5.5 km resolution businesses in the same city share very few unique pixels.

2. **Threshold counts (`rain_days_gt{X}mm`):** For each threshold (20mm, 50mm), each daily image is converted to a binary mask (1 where precipitation > threshold, 0 otherwise). These binary images are summed across the time series.

3. **Continuous summaries:** Total precipitation (`.sum()`), maximum single-day rainfall (`.max()`), and mean daily precipitation (`.mean()`) are computed pixel-wise across the time series.

4. **Spatial sampling:** All summary bands are sampled at each business point using `ee.Image.reduceRegions` with `ee.Reducer.first()` at a scale of 5566m (CHIRPS native resolution).

**Analytical notes:**

- **Resolution limitation:** At ~5.5km, CHIRPS cannot capture localised convective rainfall differences within a city. Most or all businesses in the same urban area will receive identical or near-identical values. The primary variation is **between cities**, not within them.
- **Threshold interpretation:** 20mm/day is widely used in meteorological literature as the boundary for "heavy" rainfall. 50mm/day represents "very heavy" rainfall and is commonly associated with urban flood events in tropical cities. These thresholds can be adjusted in `config.yaml`.
- **CHIRPS methodology:** CHIRPS blends satellite cold-cloud-duration estimates with weather station data. It is well-validated for tropical regions and is the standard precipitation dataset for climate hazard monitoring in the Global South.
- **Temporal window:** Fixed at exactly 730 days per city rather than per-business. Businesses in the same city share the same rainfall values, so this indicator varies almost entirely *between* cities.
- **`rain_valid_obs` is 730 for every row.** CHIRPS is gap-filled and not cloud-masked, so unlike heat and AOD there is no coverage bias: **`rain_days_gt20mm` and `rain_days_gt50mm` ARE directly comparable across cities.** This is the only day-count indicator for which that holds.
- **Observed in the 2026-08-26 run** (2-year totals, annualised in brackets): Jakarta 5,525 mm (2,762/yr), Lagos 3,686 mm (1,843/yr), Addis Ababa 2,304 mm (1,152/yr).

---

## Indicator 6: Air Quality (Aerosol Optical Depth)

| Column | Type | Units | Description |
|---|---|---|---|
| `aod_days_gt0p4` | integer | count of days | Number of days in the trailing 2-year window where AOD at 470nm exceeded 0.4 (moderate pollution). |
| `aod_days_gt0p8` | integer | count of days | Number of days where AOD exceeded 0.8 (high pollution). |
| `aod_days_gt1p5` | integer | count of days | Number of days where AOD exceeded 1.5 (very high / hazardous pollution). |
| `aod_frac_gt0p4` | float | proportion (0–1) | **Share of OBSERVED days** exceeding AOD 0.4 = `aod_days_gt0p4 / aod_valid_obs`. **Use this, not the raw count** — the two give opposite city rankings (see below). |
| `aod_frac_gt0p8` | float | proportion (0–1) | Share of observed days exceeding AOD 0.8. |
| `aod_frac_gt1p5` | float | proportion (0–1) | Share of observed days exceeding AOD 1.5. |
| `aod_mean` | float | dimensionless | Mean AOD at 470nm across all valid observations in the trailing 2-year window. |
| `aod_max` | float | dimensionless | Maximum AOD observed in the trailing 2-year window. |
| `aod_median` | float | dimensionless | Median AOD in the trailing 2-year window. Less sensitive to extreme events than the mean. |
| `aod_valid_obs` | integer | count of days | Number of cloud-free observations with valid AOD retrievals. |
| `aod_window_start` | string | date (YYYY-MM-DD) | Start date of the AOD window. |
| `aod_window_end` | string | date (YYYY-MM-DD) | End date of the AOD window. |

**Data source:** MODIS Multi-Angle Implementation of Atmospheric Correction (MAIAC) Land Aerosol Optical Depth, Collection 6.1.
- GEE asset: `MODIS/061/MCD19A2_GRANULES`, band `Optical_Depth_047`
- Resolution: 1km
- Satellites: Terra and Aqua (combined, providing up to two observations per day)
- Coverage: Global, 2000–present (near-real-time)
- Reference: Lyapustin, A. et al. (2018). "MODIS Collection 6 MAIAC algorithm." *Atmospheric Measurement Techniques*, 11(10), 5741–5765.

**Processing:**

1. **Temporal filtering:** Grouped by city over the fixed 730-day window (see *The analysis window* above). The collection is **also filtered spatially** with `filterBounds` on the city's bounding box. This is essential and specific to this indicator: `MCD19A2_GRANULES` is a *granule* collection with many overlapping swaths per day, so `filterDate` alone leaves **1,019,444** images to reduce over, against **55,099** once restricted to one city. (Heat and rainfall read daily *gridded* composites — one global image per day, 730 total — so they need no spatial filter.) Verified bit-identical output before and after adding it: granules that do not intersect a point contribute masked pixels, which the mean/sum/count reducers skip.

2. **Unit conversion:** Raw MAIAC AOD values are stored as scaled integers (digital number × 0.001 = AOD). Each image is converted to actual AOD values.

3. **Threshold counts (`aod_days_gt{X}`):** Thresholds are applied to the scaled AOD values. The thresholds (0.4, 0.8, 1.5) roughly correspond to PM2.5 concentrations of ~35, ~70, and ~130 µg/m³ respectively, though the AOD-to-PM2.5 relationship varies with atmospheric conditions, aerosol type, and boundary layer height.

4. **Continuous summaries:** Mean, max, and median AOD are computed pixel-wise across the time series.

5. **Spatial sampling:** Sampled at each business point at 1000m scale.

**Analytical notes:**

- **AOD as a PM2.5 proxy:** Aerosol Optical Depth measures the total columnar aerosol loading in the atmosphere. It is the most widely used satellite-derived proxy for ground-level PM2.5 particulate pollution (van Donkelaar et al., 2016). However, the relationship is not 1:1 — AOD is affected by aerosol vertical distribution, humidity, and aerosol composition. Use as a relative exposure ranking rather than an absolute PM2.5 estimate.
- **Why not direct PM2.5?** Global satellite-derived PM2.5 products (e.g., van Donkelaar V5) are calibrated and validated but only available as annual composites through 2022. MAIAC AOD provides daily, 1km data up to the present, enabling temporal coverage matching the study's 2024–2026 fieldwork period.
- **Cloud/quality masking — `aod_days_gt*` are NOT comparable across cities as raw counts,** for the same reason as the heat day-counts. Observed in the 2026-08-26 run, of 730 possible days: Addis Ababa 347 valid retrievals, Jakarta 202, Lagos 91. Lagos's `aod_days_gt0p4 = 69` is out of 91 observations (76% of observed days); Addis's `93` is out of 347 (27%) — so the city with the *lower* raw count has the *higher* exceedance rate. **Normalise by `aod_valid_obs` before any cross-city comparison.** `aod_mean`, `aod_median` and `aod_max` are unaffected.
- **Cross-city interpretation:** AOD values are strongly city-dependent. Observed in the 2026-08-26 run: Lagos `aod_mean` 0.648 (`aod_max` 3.17), Jakarta 0.480, Addis Ababa 0.306. Within-city variation at 1km can capture gradients near industrial zones, traffic corridors, or open burning areas. Delhi and São Paulo were not in this run.
- **Performance (this indicator is the pipeline bottleneck).** Request cost is dominated by the collection reduction and is nearly **independent of how many points the request carries** — measured on Addis: 10 points 167s, 200 points 167s, 1,000 points 280s. Smaller batches are therefore strictly *worse*. `airquality.batch_size: 1000` in `config.yaml` overrides the global `gee.batch_size: 50` for this reason (11 requests instead of 220). GEE still returns `Computation timed out.` server-side on roughly every other request; the retry in `utils.safe_getinfo()` absorbs it. If further speedup is needed, `aod_median` is the prime suspect — median must retain and sort values across all 55,099 granules, whereas mean/max/count stream.
- **Wavelength:** The 470nm band (`Optical_Depth_047`) is used rather than the 550nm band because it has better sensitivity to fine-mode aerosols (combustion, vehicle emissions) typical of urban pollution.

---

## Indicator 7: Nighttime Lights (Economic Activity Proxy)

| Column | Type | Units | Description |
|---|---|---|---|
| `ntl_mean_radiance` | float | nW/cm²/sr | Mean nighttime radiance within a 150m buffer, averaged across the trailing 12 monthly composites. Higher values indicate greater economic activity, urbanisation, and infrastructure density. |
| `ntl_median_radiance` | float | nW/cm²/sr | Median monthly radiance within the 150m buffer. Less sensitive to outlier months (e.g., festivals, temporary construction lighting). |
| `ntl_max_radiance` | float | nW/cm²/sr | Maximum monthly radiance within the 150m buffer over the trailing 12 months. |
| `ntl_sd_radiance` | float | nW/cm²/sr | Standard deviation of radiance across the 12 monthly composites. |
| `ntl_cv_radiance` | float | ratio | Coefficient of variation (`sd / mean`), so a dim street and a bright one are comparable. NaN where mean radiance is ≤ 0. **A lighting-STABILITY measure, only weakly a power-outage proxy.** City means: Jakarta 0.57, Lagos 0.30, Addis Ababa 0.28. |

> **On reading `ntl_cv_radiance` as power reliability.** It was added with the survey's `clim_adapt_generator` item in mind, but be careful: VIIRS composites are **monthly**, so a multi-hour or multi-day outage is averaged away and leaves no trace. What this measures is month-to-month instability in lighting, which mixes sustained grid problems with seasonal patterns, economic change and compositing artefacts from cloud cover. It is suggestive, not a measurement of outage frequency. Daily VIIRS (`NOAA/VIIRS/DNB/VNP46A2`) would be the product to use for genuine outage detection.

**Data source:** NOAA/NASA VIIRS Day/Night Band (DNB) Monthly Cloud-Free Composites, version 1.
- GEE asset: `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG`, band `avg_rad`
- Resolution: ~500m (15 arc-seconds)
- Coverage: Global, April 2012–present (monthly updates)
- Reference: Elvidge, C.D. et al. (2017). "VIIRS night-time lights." *International Journal of Remote Sensing*, 38(21), 5860–5879.

**Processing:**

1. **Temporal filtering:** Filtered to a fixed 12-month window per city (2025-07-31 → 2026-07-31), **not** to each record's listing date — see *The analysis window* above.

2. **Temporal composites:** Mean, median, and max radiance images are computed from the monthly series.

3. **Buffering and zonal reduction:** A 150m circular buffer is constructed around each business point. The mean radiance *within* each buffer is computed using `ee.Image.reduceRegions` with `ee.Reducer.mean()` at 500m scale. This produces a spatially averaged radiance for the business's neighbourhood.

**Analytical notes:**

- **Interpretation:** Nighttime lights are a well-established proxy for economic activity, infrastructure density, and urbanisation intensity (Henderson et al., 2012). They are **not** a direct measure of business revenue or employment. Use as a neighbourhood-level control variable characterising the economic environment around each business.
- **Saturation:** VIIRS DNB can saturate in very bright urban cores (radiance > ~200 nW/cm²/sr). For the five MAP2 cities, which include peri-urban and peripheral sampling areas, saturation is unlikely to affect most observations. Observed in the 2026-08-26 run, `ntl_mean_radiance` reached 215 in Addis Ababa (city mean 45.8, range 4.5–215), so a small number of bright-core observations may be near saturation; Jakarta (mean 27.2, range 10–60) and Lagos (mean 23.3, range 6–72) are well clear of it.
- **Temporal stability:** Nighttime lights at 500m resolution change slowly. The 12-month mean captures the stable economic character of the neighbourhood, smoothing over seasonal effects (e.g., Ramadan, monsoon, holidays).
- **Gas flaring:** In Lagos, gas flaring from industrial operations can contribute to elevated nighttime radiance in some areas. This is a genuine feature of the economic landscape but should be noted when interpreting high outlier values.

---

## Indicator 8: Built-up Surface Fraction

| Column | Type | Units | Description |
|---|---|---|---|
| `builtup_fraction_50m` | float | proportion (0–1) | Mean fraction of built-up (impervious) surface within a 50m radius buffer around the business point. |
| `builtup_fraction_150m` | float | proportion (0–1) | Mean fraction of built-up surface within a 150m radius buffer. A value of 0.5 means 50% of the area within 150m is classified as built-up. |

**Data source:** JRC Global Human Settlement Layer (GHSL), Built-up Surface 2020, release P2023A.
- GEE asset: `JRC/GHSL/P2023A/GHS_BUILT_S/2020`, band `built_surface`
- Resolution: 10m
- Reference: Pesaresi, M. et al. (2023). "GHS-BUILT-S R2023A — GHS built-up surface grid, derived from Sentinel-2 composite and Landsat, multitemporal (1975–2030)." European Commission, Joint Research Centre.

**Processing:**

1. **Normalisation:** The GHSL `built_surface` band contains built-up surface percentage values (0–100). These are divided by 100 to produce a 0–1 fraction.

2. **Buffering:** Two circular buffers (50m and 150m) are constructed around each business point, matching the canopy cover buffers.

3. **Zonal reduction:** The mean built-up fraction within each buffer is computed using `ee.Image.reduceRegions` with `ee.Reducer.mean()` at 10m scale.

**Analytical notes:**

- **Complementarity with canopy cover:** Built-up fraction and tree canopy fraction are near-inverses in urban settings — pixels classified as built-up are unlikely to also be classified as tree cover. Together they characterise the neighbourhood's physical environment: high built-up + low canopy = dense impervious urban core; low built-up + high canopy = green/peri-urban area.
- **Impervious surface and heat:** Built-up surface fraction is a primary driver of the urban heat island effect. It also drives stormwater runoff, connecting this indicator to flood vulnerability — areas with high impervious fraction and low HAND values are at compounded risk.
- **Temporal reference:** The 2020 epoch is the most recent available in GHSL P2023A. Urban expansion between 2020 and the fieldwork date (2026) will not be captured, though for established urban areas within the sampling frame the difference is likely small.
- **Relationship to existing data:** The MAP2 sampling grids already contain a `built_share` property per block. The GHSL-derived `builtup_fraction` provides a point-level measure at configurable buffer radii rather than a block-level aggregate, offering finer spatial resolution and consistency across the two buffer scales (50m and 150m).

---

## Indicator 9: Population Density

| Column | Type | Units | Description |
|---|---|---|---|
| `pop_density_50m` | float | people per km² | Mean residential population density within a 50m radius buffer. **Sub-pixel** — see the note below. |
| `pop_density_150m` | float | people per km² | Mean residential population density within a 150m radius buffer (~8 WorldPop cells). The buffer to prefer for spatial analysis. |
| `pop_year` | integer | year | WorldPop vintage the values came from. Constant across all rows (2020). |

**Data source:** WorldPop Global Project, unconstrained global mosaic, 100m.
- GEE asset: `WorldPop/GP/100m/pop`, band `population`
- Resolution: 0.000833333° ≈ 92.77m at the equator
- Coverage: **2000–2020 in Earth Engine.** The catalog page's prose mentions 2021, but `aggregate_array("year")` on the collection returns a maximum of 2020 (verified 2026-09-04). All five study countries have a 2020 image.
- Reference: Stevens, F.R., Gaughan, A.E., Linard, C., Tatem, A.J. (2015). "Disaggregating census data for population mapping using Random Forests with remotely-sensed and ancillary data." *PLOS ONE*, 10(2), e0107042.

**Processing:**

1. **Year and area filtering:** The collection is filtered to `population.year` and to the city's bounding box, then mosaicked. WorldPop ships **one image per country per year**, so `filterBounds` is required — without it the mosaic spans every country in the collection.

2. **Count → density.** The `population` band is the *estimated number of people residing in each grid cell*, i.e. a **count, not a density**. It is converted with `population / ee.Image.pixelArea() × 1e6` to give people per km². `pixelArea()` is used rather than a constant ~92.77m cell size because WorldPop is on a geographic (lat/lon) grid whose cells narrow toward the poles — a constant would bias Addis Ababa (9°N) relative to Jakarta (6°S). Verified against a manual computation at a Lagos point: 48.6291 people/cell ÷ 8,538.4 m² × 1e6 = 5,695.3 people/km², matching the pipeline exactly.

3. **Zonal reduction:** `ee.Reducer.mean()` within each buffer at 93m scale.

**Analytical notes:**

- **`pop_density_50m` is sub-pixel.** A 50m-radius buffer covers 7,854 m², smaller than one ~8,600 m² WorldPop cell, so this column is effectively the value of the containing cell rather than a spatial average. It is retained for consistency with the canopy and built-up buffer pairs, but **`pop_density_150m` (~8 cells) is the one carrying real neighbourhood averaging.** Measured correlation between the two on the 2026-09-04 run: **r = 0.9987** — the 50m column carries essentially no independent information. Prefer the 150m column, and note it also has far fewer missing values (see *Missing data*).
- **Residential, not daytime, population.** WorldPop disaggregates *census* counts, which record where people sleep. For a business's customer catchment this understates commercial districts and overstates dormitory areas — a market with few residents but heavy footfall will read as low density. Treat it as a measure of residential context, not of foot traffic.
- **Modelled, not observed.** Values come from a Random Forest dasymetric redistribution of census totals using geospatial covariates (including built-up surface). It inherits the age and accuracy of each country's underlying census, which differs substantially across the five study countries. Within-city *relative* differences are more defensible than cross-country absolute comparisons.
- **Related to `builtup_fraction`, but not redundant.** Built-up surface is among the covariates WorldPop uses to redistribute census counts, so the two are not independent by construction. Measured on the 2026-09-04 run, `pop_density_150m` vs `builtup_fraction_150m` correlate at **r = 0.41** — moderate. Both can reasonably enter one model; check VIF rather than assuming either way.
- **2020 vintage vs 2026 fieldwork.** A six-year gap. Areas that urbanised after 2020 will be understated.
- **Deriving a headcount:** the estimated residents within a buffer is `pop_density_150m × π × 0.150²` = `pop_density_150m × 0.0706858` (km²). Not stored as a column since it is an exact linear transform.

**On the pinned year.** `population.year` is set explicitly rather than resolved to "latest" at runtime. Runtime resolution would change the extracted values *without changing the config fingerprint*, so a rerun after WorldPop published a new year would silently mix vintages in one file. The extractor instead **warns** when a newer year exists, leaving the decision (and the cache invalidation) explicit. Bumping the year changes the fingerprint and triggers a clean recompute of this indicator only.

---

## Indicator 10: Population Density — Meta HRSL

A **second, independent** population estimate alongside indicator 9. Read both together; see *Choosing between the two population sources* below.

| Column | Type | Units | Description |
|---|---|---|---|
| `hrsl_density_50m` | float | people per km² | Mean residential population density within a 50m radius buffer. Not sub-pixel (a 50m buffer covers ~8 HRSL cells), but see the note on buffer redundancy below. |
| `hrsl_density_150m` | float | people per km² | Mean residential population density within a 150m radius buffer. |

**Data source:** Meta / CIESIN High Resolution Settlement Layer (HRSL), "general" population, v1.5.x.
- GEE asset: `projects/sat-io/open-datasets/hrsl/hrslpop`, band `b1`
- Resolution: 0.000277778° ≈ **30.9m** — the finest of the gridded population products, ~3x finer than WorldPop or GHS-POP
- Licence: CC-BY, distributed via CIESIN at Columbia University
- Reference: Facebook Connectivity Lab and CIESIN (2016). *High Resolution Settlement Layer (HRSL)*.

> **This is a COMMUNITY-CATALOG asset**, not the official Earth Engine catalog. It is maintained by the [awesome-gee-community-catalog](https://gee-community-catalog.org/projects/hrsl/) project under a `projects/sat-io/...` path, which is a third-party dependency that can be moved or re-versioned without notice. If this indicator suddenly fails to resolve, that is the first thing to check. Indicators 1–9 all use official catalog assets.

**Processing:**

1. **Tile filtering:** HRSL ships as 237 global COG tiles, so the collection is restricted with `filterBounds` before `.mosaic()` — one tile covers each study city. Without the filter the mosaic spans every tile on Earth.
2. **Count → density:** the band is a count per cell, converted with `b1 / ee.Image.pixelArea() × 1e6`.
3. **Zonal reduction:** `ee.Reducer.mean()` within each buffer at **31m** — the native scale.

> **The count→density conversion is only valid at the dataset's native scale.** `ee.Image.pixelArea()` reports the area of a pixel *at the requested reduction scale*, while the band still holds a count per *native* cell. Reducing at a finer scale shrinks the denominator without shrinking the numerator. Measured: reducing WorldPop at 30m instead of its native 93m inflates density **9.4x** (63,718 vs 6,772 people/km²). Any new population source must set `scale_m` to its own native grid.

**Analytical notes:**

- **Building-footprint constrained.** A CNN detects individual buildings in satellite imagery, and census population is allocated only to cells containing structures. This differs fundamentally from WorldPop (Random Forest over geospatial covariates) and GHS-POP (disaggregation over built-up surface).
- **Independent of GHSL.** Unlike GHS-POP — which is disaggregated *using* GHS-BUILT-S, the same product behind `builtup_fraction_*` — HRSL shares no inputs with the built-up indicator, so it can serve as a genuinely separate signal in a model.
- **Higher resolution, NOT more recent.** HRSL's population totals come from census projections circa 2015–2020 depending on country. It does not supersede WorldPop 2020 on vintage; it improves on spatial detail.
- **The two buffer radii are still near-redundant, despite the finer grid.** Measured on the full 10,989-business run: `hrsl_density_50m` vs `hrsl_density_150m` correlate at **r = 0.9974**, essentially the same redundancy as WorldPop's 0.9987. The finer grid does *not* fix this, because the redundancy is driven by the spatial autocorrelation of population — the neighbourhood 50m and 150m around a point is largely the same place — not by pixel size. **Use the 150m column** (it also has zero missing values against 13 at 50m).
- **Effectively uncorrelated with built-up surface** (`builtup_fraction_150m`): **r = -0.05**, against 0.41 for WorldPop. Despite being building-footprint-derived, HRSL shares no variance with the GHSL built-up product at this scale, so it introduces no collinearity into a model containing both.

### Choosing between the two population sources

Full-sample means over all 10,989 businesses, 150m buffers (GHS-POP column is from a 300-point probe, not extracted):

| City | `hrsl_density_150m` | `pop_density_150m` (WorldPop) | GHS-POP 2025 (probe only) |
|---|---|---|---|
| Addis Ababa | 26,486 | 12,326 | ~21,100 |
| Jakarta | 19,935 | 18,407 | ~21,900 |
| Lagos | 12,876 | 14,391 | ~7,400 |

**The two extracted sources rank neighbourhoods similarly but disagree sharply on level.** Within-city correlation between `hrsl_density_150m` and `pop_density_150m` is high — Addis Ababa **0.95**, Jakarta **0.82**, Lagos **0.73** — yet Addis Ababa's *level* differs by 2.1x (26,486 vs 12,326) and Lagos even reverses sign of the gap. Pooled across cities the correlation drops to **0.74**, because between-city level disagreement swamps the within-city agreement. Practically: either source supports *within-city* relative comparisons; neither should be trusted for absolute density or for cross-city level comparisons.

**These products disagree substantially, and the disagreement is not noise.** Addis Ababa spans a 3x range across the three estimates while Jakarta is comparatively tight — consistent with published findings that gridded population products diverge most where census infrastructure is weakest ([Uncovering large inconsistencies between ML-derived gridded settlement datasets](https://arxiv.org/pdf/2404.13127)).

Practical guidance:
- **HRSL is the better default**: finest resolution, non-redundant buffer radii, independent of GHSL, and it sits between the other two products while correlating better with both than they do with each other.
- **Use WorldPop as the robustness check.** Any population result that flips between `hrsl_density_150m` and `pop_density_150m` is not robust to source choice and should be reported with that caveat.
- **Treat cross-city and absolute-level population claims with caution everywhere**, and Addis Ababa most of all (2.1x between the two extracted sources). Within-city relative comparisons are far better supported (r = 0.73–0.95).
- **HRSL covers ground the others do not.** At the 101 North Jakarta businesses where WorldPop (and GHS-POP) return no data, HRSL reports a mean of **24,661 people/km²** — a densely populated area. Verified directly: 19.28 people per 949 m² cell = 20,308 people/km². The building-footprint method detects settlement on coastal land that the other products' land masks exclude. `hrsl_density_150m` has **zero** missing values across all 10,989 businesses.
- Do **not** put both in one model; they measure the same construct.

---

## Indicator 11: Humid Heat Stress (ERA5-Land)

| Column | Type | Units | Description |
|---|---|---|---|
| `t2m_mean_c` | float | °C | Mean daily 2-metre AIR temperature over the fixed 730-day window. |
| `t2m_max_c` | float | °C | Highest daily maximum air temperature in the window. |
| `rh_mean_pct` | float | % | Mean relative humidity, from air temperature and dewpoint. |
| `wbgt_mean_c` | float | °C | Mean simplified Wet Bulb Globe Temperature. |
| `wbgt_max_c` | float | °C | Highest daily sWBGT in the window. |
| `wbgt_days_gt28c` | integer | count of days | Days above sWBGT 28°C — ISO 7243 "high risk for heavy work". |
| `wbgt_days_gt31c` | integer | count of days | Days above sWBGT 31°C — "very high risk, rest breaks advised". |

**Data source:** ECMWF ERA5-Land daily aggregates (`ECMWF/ERA5_LAND/DAILY_AGGR`), bands `temperature_2m`, `temperature_2m_max`, `dewpoint_temperature_2m`.

**Why this exists.** Land surface temperature (indicator 2) is the radiative temperature of the ground and carries **no humidity information**, which misranks these cities for HUMAN heat stress. Measured on the full run:

| City | `lst_mean_c` (surface) | `t2m_mean_c` (air) | `rh_mean_pct` | `wbgt_days_gt31c` |
|---|---|---|---|---|
| Addis Ababa | 26.4 | 15.2 | 64% | **0** |
| Jakarta | 35.1 | 26.6 | 81% | 85 |
| Lagos | 29.5 | 27.1 | 83% | **421** |

**Lagos has the LOWER surface temperature of the two coastal cities yet 5x Jakarta's heat-stress days**, because humidity at 83% removes the body's ability to cool by evaporation. Addis Ababa, tropical but dry highland at 15°C mean air temperature, records zero. Any analysis of the survey's `clim_heat_*` items should prefer these columns to the LST day-counts.

**Processing.** Daily sWBGT uses the Australian BoM approximation `0.567*Ta + 0.393*e + 3.94`, with vapour pressure `e` from dewpoint via the Magnus formula. It pairs each day's MEAN temperature with that day's MEAN vapour pressure — pairing the two daily maxima would assume temperature and humidity peak together, which they generally do not, and would overstate stress.

**Analytical notes:**

- **~11km grid — this is a CITY-LEVEL control, not within-city variation.** ERA5-Land is coarser than any of these cities, so expect only a handful of distinct values per city. Do not read differences between neighbourhoods from it.
- **Reanalysis, not observation.** ERA5-Land is a model reconstruction assimilating observations, so it has no cloud gaps — every day of the window is present, which is why these columns need no observation-count normalisation.
- **Coastal cells are filled from neighbouring land.** ERA5-Land masks water; at 11km some coastal cells covering real business locations are classified as sea (this blanked Lagos entirely before it was handled). Masked cells are filled with a focal mean of nearby land cells.
- **sWBGT is an approximation.** True WBGT needs radiation and wind. The simplified form is standard for heat-stress screening but should be read as a relative index, not an occupational-safety measurement.

---

## Indicator 12: Traffic-related Air Pollution (Sentinel-5P NO2)

| Column | Type | Units | Description |
|---|---|---|---|
| `no2_mean` | float | µmol/m² | Mean tropospheric NO2 column density over the fixed 730-day window. |
| `no2_max` | float | µmol/m² | Highest single-observation NO2 column density. |
| `no2_median` | float | µmol/m² | Median NO2, less sensitive than the mean to individual pollution episodes. |
| `no2_valid_obs` | integer | count | Number of valid retrievals in the window. Diagnostic, not a substantive indicator. |

**Data source:** Sentinel-5P TROPOMI offline NO2 (`COPERNICUS/S5P/OFFL/L3_NO2`), band `tropospheric_NO2_column_number_density`, ~1.1km, from 2018-06-28. Raw values are mol/m², scaled by 1e6 to µmol/m².

**Why this exists alongside AOD.** Aerosol Optical Depth is column-integrated **particulate** loading, mixing traffic exhaust with dust, sea salt and biomass haze. NO2 is specific to **combustion** — vehicles, generators, industry. They rank the cities differently, which is the point:

| City | `aod_mean` (particulates) | `no2_mean` (combustion) |
|---|---|---|
| Lagos | **0.648** (worst) | 65.3 |
| Jakarta | 0.480 | **127.3** (worst) |
| Addis Ababa | 0.306 | 41.7 |

Lagos leads on total aerosol; Jakarta leads on combustion gases by roughly 2x. Reporting either alone would give a different answer to "which city has the worst air".

**Analytical notes:**

- **Column density, not surface concentration.** TROPOMI measures the vertically integrated tropospheric column. Ground-level exposure depends on boundary-layer depth, so treat this as a relative ranking rather than a concentration a person breathes.
- **~1.1km resolution** — finer than the ~5.5km rainfall grid, so it does carry some within-city gradient near traffic corridors, but far coarser than the 10m built-up and canopy layers.
- **Request cost is dominated by the collection reduction**, not the point count (~10,200 images in a 2-year window over one city), so this indicator uses the same large-batch override as air quality: `batch_size: 1000`, `getinfo_timeout_sec: 600`.

---

## Indicator 13: Building Density (Google Open Buildings 2.5D)

| Column | Type | Units | Description |
|---|---|---|---|
| `building_count_50m` | float | buildings | Number of buildings within a 50m radius. |
| `building_count_150m` | float | buildings | Number of buildings within a 150m radius. |
| `building_height_mean_150m` | float | metres | Mean height of BUILDINGS within 150m (averaged over building pixels only, not diluted by open ground). |
| `building_mean_area_150m` | float | m² | Typical building footprint within 150m, derived as built area ÷ building count. |

**Data source:** Google Open Buildings 2.5D Temporal v1 (`GOOGLE/Research/open-buildings-temporal/v1`), year **2023**, bands `building_fractional_count`, `building_height`, `building_presence`. Native resolution **0.5m** — the finest data in this pipeline by a wide margin.

**Why this exists alongside `builtup_fraction`.** GHSL measures the SHARE OF GROUND covered by built surface and cannot distinguish one large warehouse from forty small kiosks at the same coverage. All three cities sit near 42% built-up, yet they differ sharply once structures are counted:

| City | `building_count_150m` | `building_height_mean_150m` | `building_mean_area_150m` |
|---|---|---|---|
| Addis Ababa | 394 | 7.5 m | 64 m² |
| Jakarta | 454 | 7.1 m | 83 m² |
| Lagos | 347 | 6.4 m | 92 m² |

Addis Ababa has the most buildings and the smallest footprints — dense small-plot development — while Lagos has the fewest and largest. That axis is invisible in `builtup_fraction`.

> ### These are indices, not censuses — validated, and biased in level
>
> Validated against Open Buildings **v3 polygons** (a different product: actual building outlines with measured areas) counted inside the identical 150m buffers, 36 businesses across all three cities:
>
> | Metric | Correlation with polygons | Median ratio raster/polygon |
> |---|---|---|
> | Building count | **0.900** | **1.25** (raster ~25% HIGHER) |
> | Mean footprint area | **0.845** | **0.63** (raster ~37% LOWER) |
>
> The bias is consistent across cities (count 1.17–1.26, area 0.60–0.68), so it behaves as a roughly constant scaling factor rather than a city-specific distortion, and **the city rank order is preserved exactly** in both metrics.
>
> **Use these for relative comparison — between businesses, neighbourhoods or cities — where they are well supported. Do NOT quote the absolute values**, e.g. "331 buildings within 150m" or "mean footprint 100 m²": the polygon product says 257 and 150 m² for the same Lagos buffers. If an analysis needs defensible absolute counts or areas, query the v3 polygons directly.

**Processing:**

1. **Year and area filtering:** the collection is tiled by UTM zone and year, so it is filtered to `buildings.year` and the city bounds, then mosaicked.
2. **All three bands are reduced with `ee.Reducer.mean()`**, and the count is recovered analytically as `mean_fractional_count × (buffer_area / 0.5²)`.

> **Why mean-and-derive rather than a plain sum.** A `sum` reducer is NOT scale-independent here: GEE averages values when resampling, so summing at 2m returns exactly (2/0.5)² = 16x less than summing at native 0.5m (measured: 20.85 vs 333.63 on the same buffers). Deriving the count from the MEAN removes that dependence, which lets the reduction run at 2m for a ~10x speedup with an identical result — 18.4s vs 1.8s per 50 points. Any change to `buildings.scale_m` is therefore safe; changing the reducer to `sum` would not be.

3. **Height is masked** to pixels whose `building_presence` exceeds `height_presence_threshold` (0.5), so the mean is over buildings rather than over the whole buffer.
4. **Mean footprint** is `mean_presence × buffer_area ÷ count`, and NaN where the buffer contains no buildings — undefined rather than zero.

**Analytical notes:**

- **All four columns are largely INDEPENDENT of `builtup_fraction_150m`**, which was not the expected result. Measured on the full run: `building_count_150m` r = +0.32, `building_count_50m` +0.17, `building_mean_area_150m` +0.14, `building_height_mean_150m` **−0.15**. Counting discrete structures turns out to measure something quite different from the share of ground they cover, so these do not merely restate the built-up indicator — they can reasonably enter a model alongside it.
- **`building_height_mean_150m` is the only vertical measure in the pipeline** — built-up fraction, canopy, population and nightlights are all planar. Its slight negative correlation with built-up fraction is interesting in itself: the most densely *covered* ground here tends to carry lower buildings.
- **2023 vintage against 2026 fieldwork** — three years stale, but the most recent building data available and newer than GHSL's 2020 built-up surface.
- **Only the 150m buffer carries height and area.** At 50m the buffer holds too few buildings for a stable average; the count is still reported at both radii.

---

## A dataset that was tested and REJECTED: the Global Flood Database

Worth recording so it is not proposed again without new evidence.

`GLOBAL_FLOOD_DB/MODIS_EVENTS/V1` maps satellite-observed inundation during recorded flood events, which sounds like the ideal counterpart to the survey's `clim_event_flood` / `clim_damage_flood` items — observed flooding rather than the topographic proxy in indicator 3. It was implemented, tested, and dropped on 2026-09-04 because **it returns zero for essentially every business**.

The evidence, on Lagos:

| Sample | Flooded | Mean events per pixel |
|---|---|---|
| 400 random **business locations** | **0 of 400** | 0.000 |
| 400 random points in the **same bounding box** | 124 of 400 | 1.310 |

The extractor was verified correct — at a known flooded pixel it returns the expected count. The problem is a resolution/semantics mismatch: MODIS at 250m detects **large open-water inundation** — lagoons, wetlands, open floodplain — which in a city is precisely the unbuilt land where businesses are not. It cannot see water in streets between buildings, which is what urban flooding means for an enterprise.

A column of zeros would have been worse than no column: it reads as "no business was ever flooded", which is a false finding rather than an absent one. Use `hand_m`, `hand_flood_vulnerable` and `coastal_lowland` for flood exposure — they do discriminate (87% of Lagos businesses flagged vulnerable). Any future attempt at observed urban flooding should start from Sentinel-1 SAR, though SAR has its own difficulties in dense built-up areas from layover and shadow.

---

## Derived exceedance rates (`*_frac_gt*`)

Computed after the merge in `run_all.py` (`utils.add_exceedance_rates`) as pure client-side arithmetic on already-extracted columns. They are **not** in the per-indicator CSVs (`heat.csv`, `airquality.csv`) — only in `all_indicators.csv` — and are recomputed every run, so they cannot go stale.

**Why they exist.** The `*_days_gt*` columns count exceedances *among days that were observed*, and cloud masking makes that denominator vary enormously. Over the same 730-day window:

| City | `lst_valid_obs` | `aod_valid_obs` |
|---|---|---|
| Addis Ababa | 404 | 347 |
| Jakarta | 86 | 202 |
| Lagos | 40 | 91 |

A 10x range for MODIS LST. Lagos's `heat_days_gt40c = 0` means "0 of ~40 observed days"; Addis Ababa's `0` means "0 of ~404".

**This reverses conclusions, it does not merely adjust them.** Ranking the cities by air-pollution exceedance:

| Measure | Ranking |
|---|---|
| `aod_days_gt0p4` (raw count) | Jakarta (116) > Addis Ababa (93) > Lagos (69) |
| `aod_frac_gt0p4` (rate) | **Lagos (77.0%) > Jakarta (57.4%) > Addis Ababa (26.0%)** |

Lagos moves from last to first. The rate ranking is the correct one, corroborated independently by `aod_mean` (Lagos 0.648 > Jakarta 0.480 > Addis Ababa 0.306), which needs no normalisation. Comparing raw AOD day-counts across these cities would say Lagos has the cleanest air of the three — the opposite of the truth.

Night-time heat counts get the same treatment: `heat_nights_frac_gt20c` and `heat_nights_frac_gt25c` normalise by `lst_night_valid_obs`, which has its own cloud denominator (city means: Addis Ababa 373, Lagos 154, Jakarta 78 clear nights of 730).

**Deliberately absent:**

- **No WBGT or NO2 rates.** ERA5-Land is a reanalysis with no cloud gaps — every day of the window is present — so `wbgt_days_gt*` are already comparable. The NO2 columns are means rather than day-counts.
- **No rainfall rates.** CHIRPS is gap-filled rather than cloud-masked, so `rain_valid_obs` is exactly 730 for every row; a fraction would be a constant rescaling carrying no information, and `rain_days_gt*` are already directly comparable.
- **Not annualised.** `fraction x 365` would read as "expected days per year" but extrapolates the clear-sky exceedance rate onto cloudy days, which are systematically cooler and less polluted — overstating exposure most in the cloudiest cities, reintroducing the same bias less visibly.

**Missing values.** A rate is `NaN` where the observation count is zero or missing, never 0: an unobserved point has an undefined rate, not a rate of zero. This affects the same 24 Lagos businesses whose MODIS pixel is permanently masked.

---

## Composite: `heat_exposure_index`

| Column | Type | Units | Description |
|---|---|---|---|
| `heat_exposure_index` | float | z-score | Within-city composite heat exposure. 0 is the city average; +1 is one standard deviation more exposed than other businesses **in the same city**. |

Computed after the merge (`utils.add_heat_exposure_index`) as the mean of signed z-scores, each standardised **within city**:

```
mean( z(lst_mean_c) + z(lst_max_c) + z(builtup_fraction_150m) − z(canopy_fraction_150m) )
```

Components and signs are configurable under `derived.heat_exposure_index` in `config.yaml`.

> ### Levels are NOT comparable across cities
>
> Every city has mean 0 by construction. `heat_exposure_index = 0.8` means the same thing in Lagos and Addis Ababa — "more exposed than most businesses in this city" — and says nothing about whether Lagos is hotter than Addis Ababa. **For between-city heat comparison use `wbgt_days_gt31c`** (Lagos 421 days, Jakarta 85, Addis Ababa 0), which integrates temperature and humidity and needs no composite.

**Why within-city standardisation, and why only these four components.** A variance decomposition over the extracted data shows the heat variables split into two incompatible spatial scales:

| Variable | Share of variance that is within-city |
|---|---|
| `canopy_fraction_150m` | 93% |
| `builtup_fraction_150m` | 47% |
| `lst_max_c` | 22% |
| `lst_mean_c` | 8% |
| `wbgt_days_gt31c` | **4%** |
| `lst_night_mean_c`, `t2m_mean_c`, `rh_mean_pct` | **~1%** |
| `heat_nights_frac_gt20c` | **0%** |

The humid-heat and night-heat variables are effectively **city constants** — ERA5-Land is an ~11km grid and night LST is spatially smooth. Pooling them into one index would yield a city fixed effect in disguise, ranking cities rather than businesses. The four components are the heat variables with real within-city variance *and* a physical mechanism: surface heat load, the built surface that generates it, and the canopy that mitigates it.

`building_height_mean_150m` was excluded despite having 98% within-city variance: it correlates ~0 with every thermal measure here (−0.10 with the index), so the data gives no support for including it.

**Validation.**

- Correlates with its components as intended: `lst_mean_c` +0.75, `lst_max_c` +0.72, `canopy_fraction_150m` −0.67, `builtup_fraction_150m` +0.55.
- **Convergent validity:** correlates **+0.42** with within-city `lst_night_mean_c`, which is *not* a component — it tracks real thermal signal rather than only its own inputs.
- Extremes are physically coherent. Comparing the most and least exposed decile within each city:

| City | `lst_mean_c` (low → high decile) | Canopy | Built-up |
|---|---|---|---|
| Addis Ababa | 25.1 → 27.5 °C | 14.0% → 0.6% | 26% → 38% |
| Jakarta | 33.6 → 35.6 °C | 22.9% → 0.3% | 33% → 48% |
| Lagos | 28.8 → 33.1 °C | 6.6% → 0.0% | 39% → 67% |

**Analytical notes:**

- **NaN if ANY component is missing** (25 businesses, those with no MODIS LST), rather than averaging over whatever is present — an index from two components is not on the same scale as one from four, and silently mixing them would be worse than a gap.
- **For regression, prefer the four components separately.** A composite imposes equal weights you have not estimated and discards information. Its value is descriptive: ranking, targeting, and communication ("the most heat-exposed quintile of businesses in each city").
- Recomputed on every run from already-extracted columns, so it cannot go stale.

---

## Missing data

Observed in the 2026-08-26 three-city run (10,989 rows). Every other column is fully populated.

| Column(s) | Missing | Cause |
|---|---|---|
| `jrc_recurrence` | 11,449 (99.8%) | JRC masks recurrence outside water bodies. Expected — see Indicator 3. |
| `heat_days_gt40c`, `heat_days_gt45c`, `heat_days_gt50c`, `lst_mean_c`, `lst_max_c`, `lst_valid_obs` | 25 (0.2%) | One MODIS pixel permanently masked. See below. |
| `heat_frac_gt40c`, `heat_frac_gt45c`, `heat_frac_gt50c` | 25 (0.2%) | Derived from the masked heat columns above. |
| `pop_density_50m` | 101 (0.9%) | WorldPop unmapped on the North Jakarta coast. See below. |
| `pop_density_150m` | 28 (0.25%) | Same cause; the wider buffer recovers 73 of the 101. |
| `hrsl_density_50m` | 13 (0.1%) | HRSL has no value at 13 points (10 Addis Ababa, 3 Jakarta); these do not overlap the WorldPop gaps. `hrsl_density_150m` has **no** missing values. |

**The 24 masked heat rows.** All 24 are Lagos businesses at 17 distinct coordinates within a ~200 m cluster near 6.5050°N, 3.5780°E — the Lekki/Lagos lagoon fringe — all at 3 m elevation. `lst_valid_obs` is `NaN` rather than `0`, meaning the 1 km MODIS pixel was masked in *every* image across the full two years, not that no hot days occurred.

The coordinates are sound, and the cause is a resolution mismatch rather than bad data:

- SRTM returned a valid 3 m elevation for all 24.
- MAIAC returned **full AOD data** for the same points (mean `aod_valid_obs` = 96, zero nulls), so the pixel is not masked by every MODIS product.
- JRC's 30 m mask says `jrc_max_extent = 0` — not water at the point.
- But all 24 are `hand_flood_vulnerable = 1` and `coastal_lowland = 1`, with mean HAND 1.7 m.

`MOD11A1` is a **land** surface temperature product operating on a 1 km land mask. A business on a narrow strip of land fringed by lagoon reads as land at 30 m but sits inside a 1 km pixel that is majority water. Treat these as structurally missing, not as zeros.

**HRSL covers these points.** At all 101, `hrsl_density_150m` (indicator 10) returns a value, averaging 24,661 people/km². So the area is *not* empty — WorldPop's and GHS-POP's land masks exclude settlement that Meta's building-footprint method detects. If a complete population column matters more than WorldPop's independence, use `hrsl_density_150m`, which has no missing values.

**The masked WorldPop cells (North Jakarta coast).** All 101 affected businesses are in Jakarta, inside a ~1.4 x 3.2 km coastal strip (lat -6.1605 to -6.1476, lon 106.8052 to 106.8341, 98 distinct coordinates). Their profile is distinctive: mean elevation 6.6 m against 919 m for the rest of the sample, mean HAND 1.6 m, 85% flagged `coastal_lowland`, and roughly two-thirds sitting on JRC-detected water (`jrc_max_extent = 1`).

**These are masked, not zero.** Sampling the raw `population` band at these points returns no value at all rather than 0, i.e. WorldPop did not estimate a population there — it is not a finding that nobody lives there. **Do not impute 0**; that would assert an empty neighbourhood in what is in fact densely built-up land (`builtup_fraction_150m` averages 42.6% at these points, indistinguishable from the rest of the sample).

The cause is WorldPop's land/coastline mask at 100 m failing to cover reclaimed or newly built coastal land in North Jakarta — confirmed by HRSL, which detects buildings and dense population across the same strip. Supporting evidence: the 150 m buffer recovers 73 of the 101, exactly what an edge-of-mask artefact predicts as the buffer overlaps neighbouring valid cells. These are a different set of businesses from the 24 Lagos points missing heat data — the two gaps do not overlap at all.

---

## Provenance and reproduction

```bash
cd python
python3 prepare_gsmm_input.py    # GSMM exports -> data/input/gsmm_listings.csv
python3 run_all.py               # 8 indicators -> data/output/all_indicators.csv
```

**Input.** `prepare_gsmm_input.py` reads the `Business Data` sheet of the latest GSMM export per country from `../cfi-map2r2-data/data/gsmm/`. File choice is by **kind first, then date** — a country team's cleaned `GSMM_Analysis_*` beats the vendor's daily `GSMM_Report_*` even when the Report is newer (ported from `gsmm_snapshot_path()` in that repo's `R/prep_cto.R`; newest-overall would silently swap the study's listing back to the uncleaned vendor file). Rows are de-duplicated on `Enterprise ID`, keeping the first.

Sources used for the 2026-08-26 run:

| City | Source file | Listed | Usable |
|---|---|---|---|
| Addis Ababa | `GSMM_Report_20260818_034733_Ethiopia.xlsx` | 4,263 | 4,262 (−1 dup id) |
| Jakarta | `GSMM_Report_20260818_034736_Indonesia.xlsx` | 3,714 | 3,714 |
| Lagos | `GSMM_Report_20260824_034726_Nigeria.xlsx` | 3,015 | 3,013 (−2 dup id) |

**Incremental reruns.** `run_all.py` extracts only businesses missing from each indicator's output CSV and reuses the rest, so adding a city or a newer GSMM extract costs only the new rows. Within an indicator, every completed batch is appended to `data/output/.checkpoint_<indicator>.csv` and deleted on success, so an interrupted run also resumes rather than restarting. Buffer indicators checkpoint per radius (`canopy_50m`, `builtup_150m`, …). `--force` ignores all caches; `--only heat,rainfall` runs a subset and skips the merge.

**Cache validity is enforced by a config fingerprint**, recorded per indicator in `data/output/extraction_manifest.json` (git-ignored). The fingerprint covers the config sections that affect that indicator's *values* — so changing `time_window` invalidates heat, rainfall, AOD and nightlights but leaves elevation, flood, canopy and built-up intact, while changing `canopy.buffer_radii_m` invalidates only canopy. When a fingerprint changes, that indicator's cached rows **and** its checkpoint are discarded and it recomputes in full, which is what prevents an output file from silently holding rows computed under two different definitions.

Performance-only keys (`batch_size`, `getinfo_timeout_sec`) are deliberately excluded, so tuning AOD's batch size does not trigger a multi-hour recompute.

**One data-dependent case:** if `time_window.analysis_end_date` is set to `null`, each city's window ends at its own latest listing date, so *adding businesses can move the window* and invalidate every existing row for that city. The fingerprint folds in the per-city maximum listing dates in that mode so the shift is detected. With a fixed `analysis_end_date` (the current setting) this does not arise.


---

## Registry for the analysis app

`registry_environment.R` at the root of this repo holds drop-in registry rows for `cfi-map2r2-data`, matching its `R/registry.R` tribble schema (`id, label, domain, type, source_q, source_col, notes, description`, then `frame = "Enumeration"`). 46 indicators across 9 domains (`env_heat`, `env_air`, `env_flood`, `env_green`, `env_rain`, `env_light`, `env_built`, `env_pop`, `env_terrain`).

It is **generated** by `python/make_registry.py`, which fails if any column of `all_indicators.csv` is neither registered nor explicitly excluded — so it cannot drift as indicators are added. Regenerate after any column change; do not hand-edit the `.R` file.

To use, after sourcing `registry.R`:

```r
source("registry_environment.R")
REGISTRY <- bind_rows(REGISTRY, REGISTRY_ENVIRONMENT)
```

Three things to settle before merging it there:

1. **ID convention.** Enumeration-frame ids in `registry.R` are prefixed `enum_`; these are not, because the id must match the column name in `all_indicators.csv`, which this pipeline's data dictionary fixes. Renaming on import would work but breaks that correspondence.
2. **New domains.** The nine `env_*` domains are new to that registry.
3. **`latitude` / `longitude` are deliberately unregistered** as sensitive — they must never reach `enum_snapshot.rds`, which is committed and shipped to the deployed app.
