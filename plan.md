# Implementation Plan: Remote-Sensing Environmental Indicators for CFI MAP2 Business Locations

## Overview

This utility will take point coordinates for surveyed businesses across five cities (São Paulo, Addis Ababa, Delhi, Jakarta, Lagos) and return four environmental indicators derived from publicly available satellite/geospatial data. The output will be a tabular dataset joinable to existing MAP2 survey data via `block_id` or coordinate match.

---

## Input Data

The existing GeoJSON sampling grids (in `cfi-map2-blockexplorer2026/data/` and `cfi-map2r2-data/resources/`) contain **polygons** (150m × 150m blocks) in WGS84/EPSG:4326, not individual business point locations. Two options for how coordinates enter this pipeline:

- **Option A — Block centroids**: Derive a representative point (centroid) from each sampled block polygon. Simpler, but assigns the same environmental value to all businesses within a block.
- **Option B — Business-level GPS coordinates**: Use actual GPS coordinates collected during enumeration. More precise, but requires linking to survey microdata and handling GPS noise (typical ±5–10m for consumer-grade devices).

**Recommendation**: If the survey captured business-level GPS, use Option B — the additional precision matters most for Indicator 4 (tree canopy), which varies at fine spatial scales. Option A is a reasonable fallback and could serve as a first pass.

---

## Indicator 1: Elevation Above Sea Level

| Aspect | Details |
|---|---|
| **Preferred source** | NASA SRTM 30m (USGS/SRTMGL1_003) via GEE, or Copernicus DEM GLO-30 |
| **Resolution** | 30m |
| **Method** | Point extraction — sample raster value at each coordinate |

### Decision point: SRTM vs. Copernicus DEM

- **SRTM** (Shuttle Radar Topography Mission): The workhorse standard. Collected in 2000, well-validated, available globally between 60°N–56°S. All five cities fall within coverage. Available directly in GEE as `USGS/SRTMGL1_003`.
- **Copernicus GLO-30**: Newer (2021 release), derived from TanDEM-X. Slightly better vertical accuracy in some contexts (~1m vs ~5m for SRTM in flat terrain). Available in GEE as `COPERNICUS/DEM/GLO30`.

### Analytical consequences

For urban flat terrain (most of the five cities), the two are functionally equivalent. The Copernicus DEM has a known advantage in areas with significant land-use change since 2000 (e.g., landfill, reclamation) since SRTM reflects the 2000 surface. For consistency with the broadest literature, **SRTM is the safer default**. Could provide both for robustness.

---

## Indicator 2: Number of Extreme Heat Days (Surface Temperature > X°C)

| Aspect | Details |
|---|---|
| **Preferred source** | MODIS Land Surface Temperature (LST): `MODIS/061/MOD11A1` (daytime) and/or `MODIS/061/MYD11A1` |
| **Resolution** | 1km |
| **Method** | Time-series filter over trailing 2 years, count days exceeding threshold |

### Decision point 1: Land Surface Temperature (LST) vs. Air Temperature

- **LST (MODIS)**: Measures the radiative temperature of the land surface. In urban areas with impervious surfaces, LST can be 10–20°C higher than air temperature. This is actually *more relevant* for studying heat exposure of ground-level businesses (particularly outdoor or poorly ventilated ones) than station-based air temperature.
- **ERA5-Land reanalysis air temperature** (~9km resolution, available in GEE): Closer to what a weather station would report, but very coarse resolution — a single pixel could cover an entire district.
- **Recommendation**: Use **MODIS LST** as primary. It captures the urban heat island effect that differentiates exposure *between* businesses within the same city. Optionally provide ERA5 air temperature as a supplementary variable for context.

### Decision point 2: Threshold X — what value?

- This is domain-dependent. Common thresholds in heat-health literature: 35°C air temp, 40°C air temp. For LST, thresholds are typically higher (45–50°C for severe surface heat stress in tropical cities).
- **Recommendation**: Make X a **configurable parameter**. Provide the raw count at multiple thresholds (e.g., 40°C, 45°C, 50°C for LST) so sensitivity can be explored in analysis. Also consider providing the **mean and max LST** over the period as continuous alternatives to the binary threshold.

### Decision point 3: Daytime vs. nighttime LST

- Daytime LST (Terra overpass ~10:30 local) captures peak heat exposure during business hours. Nighttime LST captures heat retention, relevant for residential but less so for business operations.
- **Recommendation**: Use **daytime LST** as the primary measure.

### Decision point 4: MODIS 1km resolution limitation

- At 1km, many businesses within the same neighbourhood will share a pixel. This limits within-city variation. An alternative is **Landsat-derived LST** (~30–100m thermal band), but Landsat has a 16-day revisit, making daily threshold counts infeasible.
- **Recommendation**: Accept the 1km limitation for daily counts. Optionally supplement with a single **Landsat-derived mean LST** at 100m for the study period to capture finer spatial variation in average heat exposure.

### Decision point 5: Cloud/quality masking

- MODIS LST has a built-in QC band. Cloudy pixels return no data. In tropical cities (Lagos, Jakarta, São Paulo), cloud cover can cause 30–50% data loss. The "number of days exceeding X" will be **biased downward** — it's really "number of clear-sky days exceeding X."
- **Recommendation**: Also compute a **valid observation count** per point so results can be normalized or low-coverage locations flagged in analysis.

---

## Indicator 3: Flood Vulnerability (Binary / Index)

| Aspect | Details |
|---|---|
| **Preferred source(s)** | Multiple — see options below |
| **Resolution** | Varies (30m–250m) |
| **Method** | Spatial overlay / zonal classification |

This is the most complex indicator because there is no single authoritative global flood-risk raster.

### Option A — JRC Global Surface Water

- `JRC/GSW1_4/GlobalSurfaceWater` in GEE: 30m resolution, based on Landsat archive 1984–2021. The `occurrence` and `recurrence` bands show how frequently water was detected at each pixel.
- Good for identifying areas that *have historically flooded*, but doesn't model fluvial/pluvial flood probability per se.

### Option B — Fathom modelled floodplain data

- Fathom Global Flood Map (used by World Bank, GFDRR): Provides return-period flood depth (1-in-5yr, 1-in-100yr, etc.) at ~30m for fluvial, pluvial, and coastal flooding separately. **Not freely available** — requires a licence (free for academic/humanitarian use on request).
- This is the gold standard for flood vulnerability classification.

### Option C — MERIT Hydro pre-computed HAND (selected)

- **MERIT Hydro** (`MERIT/Hydro/v1_0_1`, band `hnd`): Pre-computed global HAND at ~90m resolution (Yamazaki et al., 2019). HAND < 5m is a common proxy for floodplain membership.
- Available directly in GEE. No manual hydro-routing needed. Well-established in the literature (Nobre et al. 2011).

### Option D — JRC Flood Hazard Maps (EU)

- The Joint Research Centre provides return-period flood hazard maps, but coverage for the Global South is inconsistent.

### Recommendation

- **Primary**: Use **MERIT Hydro pre-computed HAND** (`MERIT/Hydro/v1_0_1`). Create a binary variable (HAND ≤ 5m = flood-vulnerable) and also retain the continuous HAND value. This is reproducible, free, and well-cited.
- **Supplement**: Overlay JRC Global Surface Water `max_extent` and `recurrence` to flag locations where water has been historically observed.
- **If licence available**: Fathom data would be the strongest single source. Worth pursuing given the World Bank/CGAP adjacency of this project.

### Coastal flooding note

For Lagos and Jakarta (coastal cities), consider also flagging locations below a **low-elevation coastal zone threshold** (e.g., elevation < 10m above sea level, from Indicator 1). This is a simple derivative that captures storm-surge exposure.

---

## Indicator 4: Tree Canopy Cover / Shade Index

| Aspect | Details |
|---|---|
| **Preferred source** | Multiple options at different resolutions |
| **Resolution** | 10m–30m target |
| **Method** | Zonal statistic (mean within buffer around business point) |

### Option A — Hansen Global Forest Change (UMD)

- `UMD/hansen/global_forest_change_2023_v1_11` in GEE. 30m resolution. Provides `treecover2000` (baseline) and annual `loss`/`gain` bands.
- Can compute current approximate tree cover as: `treecover2000 - cumulative_loss + gain`.
- Well-established, frequently cited. But: calibrated for *forest*, not urban trees. May undercount scattered urban trees and small canopy patches.

### Option B — ESA WorldCover / Google Dynamic World

- **ESA WorldCover** (2020, 2021): 10m resolution land cover classification including a "trees" class. GEE: `ESA/WorldCover/v200`.
- **Google Dynamic World**: 10m, near-real-time land cover from Sentinel-2. GEE: `GOOGLE/DYNAMICWORLD/V1`. Provides per-pixel probability of "trees" class.
- 10m resolution is much better for capturing urban tree canopy.

### Option C — High-Resolution Tree Canopy Height (Meta/WRI)

- Meta's 1m canopy height map (2023) derived from high-res imagery. Available via GEE or direct download. Provides actual canopy height, not just presence.
- Extremely high resolution but large data volume.

### Decision point: Buffer radius

- Tree canopy at the exact business coordinate is less meaningful than canopy in the **surrounding area** (which provides shade, microclimate moderation).
- **Recommendation**: Compute mean canopy cover within a **50m and 150m radius** buffer around each point. The 150m buffer matches the block size, providing a neighbourhood-level shade index. The 50m buffer captures immediate surroundings.

### Recommendation

- **Primary**: Use **ESA WorldCover 10m** to compute fraction of "trees" pixels within the buffer. This balances resolution, availability, and simplicity.
- **Supplement**: If canopy *height* is desired (a better proxy for actual shade), use the **Meta canopy height map** at 1m.
- Avoid Hansen for this purpose — 30m resolution and forest-calibration make it a poor fit for urban shade assessment.

---

## Implementation Architecture

```
cfi-environdata/
├── python/
│   ├── 01_load_coordinates.py      # Load business points or block centroids
│   ├── 02_extract_elevation.py     # SRTM / Copernicus DEM extraction
│   ├── 03_extract_heat.py          # MODIS LST time-series processing
│   ├── 04_extract_flood.py         # HAND computation + JRC overlay
│   ├── 05_extract_canopy.py        # Tree canopy zonal stats
│   ├── run_all.py                  # Orchestrator script
│   └── utils.py                    # Shared helpers (GEE auth, buffer, export)
├── data/
│   ├── input/                      # Coordinate files per city
│   └── output/                     # Extracted indicator CSVs
├── config.yaml                     # Thresholds, buffer radii, date ranges
├── requirements.txt
└── plan.md                         # This document
```

### Language choice: R vs. Python

- The existing MAP2 ecosystem (`cfi-map2r2-data`) is **heavily R-based** (fixest, ggplot2, sf, terra).
- GEE has mature APIs for both R (`rgee`) and Python (`earthengine-api`). The Python API is more stable and better documented. `rgee` works but has more setup friction (reticulate dependency).
- **Recommendation**: Use **Python for GEE extraction** (more robust, better GEE community support), export to CSV/GeoParquet, then consume in the R analysis pipeline. This keeps the boundary clean. Alternatively, if a single-language stack is strongly preferred, `rgee` is viable.

---

## Decisions (Locked In)

| # | Decision | Selection |
|---|---|---|
| 1 | Input coordinates | Business-level GPS from enumeration |
| 2 | DEM source | SRTM 30m (`USGS/SRTMGL1_003`) |
| 3 | Heat metric source | MODIS daytime LST (`MODIS/061/MOD11A1`) |
| 4 | Heat thresholds | Multiple (40/45/50°C) + mean/max continuous |
| 5 | Flood vulnerability | HAND + JRC Global Surface Water |
| 6 | Canopy source | ESA WorldCover 10m |
| 7 | Canopy buffer radius | 150m |
| 8 | Implementation language | Python (GEE extraction) → CSV → R (analysis) |
| 9 | Temporal window for heat | Trailing 2 years from per-record fieldwork date |

---

# Block-Level Aggregation Pipeline

## Motivation

The point-level pipeline (above) extracts environmental indicators at individual business GPS locations to serve as covariates in the MAP2 survey analysis. The block-level pipeline serves a distinct analytical purpose: **characterising the full spatial distribution of environmental conditions across each study area's sampling frame**. This enables:

- Study-area-level analysis (e.g., geospatial correlation between heat exposure and shade/canopy)
- Maps and spatial statistics across the full extent of each city's sampling blocks
- Comparative analysis across cities at the block level
- Identification of environmental "hotspot" blocks (high heat + low canopy, low elevation + low HAND, etc.)

The two pipelines share the same GEE data sources and `config.yaml` parameters but are otherwise independent. The block-level pipeline operates on **polygon geometries** (sampling frame blocks) rather than point coordinates, and computes **zonal statistics** (aggregations over all pixels within each block) rather than point samples.

---

## Input Data

The input is the set of sampling frame block polygons from the MAP2 study, stored as GeoJSON files in `cfi-map2-blockexplorer2026/data/`. Each block is a ~150m × 150m polygon in WGS84/EPSG:4326, identified by a unique `block_id`.

The pipeline expects one GeoJSON file per city, or a single file containing all blocks with a `city` attribute. Required properties per feature:

- `block_id` (string): Unique block identifier
- `city` (string): City name

Geometry: Polygon (the block boundary). All zonal computations use the block polygon directly — no buffers are applied.

### Ingestion

A utility function will load GeoJSON block polygons into a GeoDataFrame and convert them to GEE `FeatureCollection`s for server-side reduction. Blocks will be processed in batches (as in the point pipeline) to stay within GEE memory limits, though the optimal batch size will likely be smaller (10–25 blocks) since polygon reductions are more expensive than point samples.

---

## Indicator Design: Point vs. Block Differences

The block pipeline reuses the same remote sensing datasets but differs in three key ways:

1. **Spatial aggregation**: Instead of sampling a single pixel (point) or computing stats within a circular buffer, each indicator is reduced over the full block polygon using `ee.Image.reduceRegion` or `reduceRegions`. This yields distribution statistics (mean, min, max, std, count) rather than a single value.

2. **No fieldwork_date dependency**: The point pipeline ties temporal indicators (heat, rainfall, AOD) to each record's fieldwork date. The block pipeline uses a **fixed analysis period** common to all blocks within a city (configurable in `config.yaml`), since blocks have no associated survey date. A sensible default is the 2-year window ending at the city's median fieldwork date, or a fixed reference date.

3. **No buffer radii**: The block polygon itself is the analysis unit. Canopy and built-up fractions are computed directly over the block footprint rather than within circular buffers around a centroid.

---

## Block-Level Indicators

### Indicator 1: Elevation

| Output column | Type | Description |
|---|---|---|
| `elev_mean_m` | float | Mean SRTM elevation across block pixels |
| `elev_min_m` | float | Minimum elevation in block |
| `elev_max_m` | float | Maximum elevation in block |
| `elev_std_m` | float | Standard deviation of elevation (terrain roughness proxy) |
| `elev_range_m` | float | Elevation range (max − min) within block |

**Method**: `reduceRegions` with combined reducer (mean, min, max, stdDev) at 30m scale.

### Indicator 2: Extreme Heat Days

| Output column | Type | Description |
|---|---|---|
| `heat_days_gt40c_mean` | float | Mean count of days > 40°C LST across block pixels |
| `heat_days_gt45c_mean` | float | Mean count of days > 45°C LST across block pixels |
| `heat_days_gt50c_mean` | float | Mean count of days > 50°C LST across block pixels |
| `lst_mean_c` | float | Mean daytime LST across block pixels and time |
| `lst_max_c` | float | Maximum daytime LST observed in block over analysis period |
| `lst_valid_obs_mean` | float | Mean valid observation count across block pixels |

**Method**: Same temporal compositing as point pipeline (threshold binary images → sum over time), then reduce the resulting image over each block polygon with `ee.Reducer.mean()` at 1000m scale. At 1km MODIS resolution, most 150m blocks will fall within a single pixel, so block-level values will often match the pixel value. The aggregation is still meaningful because blocks near pixel boundaries will get area-weighted values, and the pipeline is forward-compatible with higher-resolution thermal data.

### Indicator 3: Flood Vulnerability

| Output column | Type | Description |
|---|---|---|
| `hand_mean_m` | float | Mean HAND across block |
| `hand_min_m` | float | Minimum HAND in block (worst-case flood exposure) |
| `hand_flood_frac` | float | Fraction of block area with HAND ≤ 5m |
| `jrc_max_extent_frac` | float | Fraction of block within JRC max water extent |
| `jrc_recurrence_mean` | float | Mean JRC water recurrence across block |
| `coastal_lowland` | integer | 1 if coastal city and mean elevation < 10m |

**Method**: HAND sampled at 30m. The `hand_flood_frac` is derived by converting HAND to a binary mask (≤ 5m → 1) and taking the mean over the block polygon.

### Indicator 4: Tree Canopy Cover

| Output column | Type | Description |
|---|---|---|
| `canopy_fraction` | float | Fraction of block area classified as tree cover |
| `canopy_pixel_count` | integer | Total valid 10m pixels in block |
| `canopy_tree_pixels` | integer | Count of tree-classified pixels in block |

**Method**: ESA WorldCover binary tree mask, reduced over block polygon with mean/count/sum at 10m scale. No buffer needed — the block polygon is the zone. For a 150m × 150m block, expect ~225 pixels.

**Analytical note**: This is the key variable for the heat–shade correlation analysis. At the block level, canopy fraction directly represents the proportion of the block with overhead tree cover, which modulates surface temperature. Correlating `canopy_fraction` with `lst_mean_c` block-by-block within each city will reveal the strength of the urban cooling effect of tree cover.

### Indicator 5: Rainfall

| Output column | Type | Description |
|---|---|---|
| `rain_days_gt20mm` | integer | Days with precipitation > 20mm |
| `rain_days_gt50mm` | integer | Days with precipitation > 50mm |
| `rain_total_mm` | float | Total accumulated precipitation |
| `rain_mean_daily_mm` | float | Mean daily precipitation |
| `rain_max_day_mm` | float | Maximum single-day precipitation |

**Method**: CHIRPS daily reduced at 5566m scale. At ~5.5km resolution, all blocks within the same neighbourhood will share identical values. The primary variation is between cities and between city quadrants. Still included for completeness and cross-indicator analysis.

### Indicator 6: Air Quality

| Output column | Type | Description |
|---|---|---|
| `aod_mean` | float | Mean AOD at 470nm over analysis period |
| `aod_max` | float | Maximum AOD observed |
| `aod_days_gt0p4` | integer | Days with AOD > 0.4 |
| `aod_days_gt0p8` | integer | Days with AOD > 0.8 |
| `aod_days_gt1p5` | integer | Days with AOD > 1.5 |

**Method**: MODIS MAIAC at 1000m scale. As with heat, most blocks fall within a single AOD pixel, so block-level values approximate point-level values. Useful for cross-indicator analysis (e.g., AOD vs. canopy, AOD vs. built-up).

### Indicator 7: Nighttime Lights

| Output column | Type | Description |
|---|---|---|
| `ntl_mean_radiance` | float | Mean VIIRS radiance across block pixels and time |
| `ntl_max_radiance` | float | Maximum monthly radiance observed in block |

**Method**: VIIRS monthly composites at 500m. Mean of temporal composite reduced over block polygon. The 150m block fits within a single 500m pixel, so block values approximate pixel values.

### Indicator 8: Built-up Surface Fraction

| Output column | Type | Description |
|---|---|---|
| `builtup_fraction` | float | Mean built-up surface fraction across block |
| `builtup_pixel_count` | integer | Valid 10m pixels in block |

**Method**: GHSL 10m, reduced with mean/count at 10m scale over block polygon. Like canopy, no buffer needed.

---

> **Superseded 2026-09-05.** The eight `extract_*_blocks.py` modules described below were replaced by `block_indicators.py` + a rewritten `run_all_blocks.py`, which reuse the point pipeline's image builders. See `data/output/blocks/block_data_dictionary.md` for the current block schema.

## File Structure

```
python/
  blocks/                          # Block-level pipeline (separate from point pipeline)
    __init__.py
    utils_blocks.py                # Block polygon loading, GeoJSON→FeatureCollection, batching
    extract_elevation_blocks.py
    extract_heat_blocks.py
    extract_flood_blocks.py
    extract_canopy_blocks.py
    extract_rainfall_blocks.py
    extract_airquality_blocks.py
    extract_nightlights_blocks.py
    extract_builtup_blocks.py
    run_all_blocks.py              # Orchestrator: runs all 8 + merges
data/
  input/
    blocks/                        # Sampling frame GeoJSON files per city
  output/
    blocks/                        # Block-level indicator CSVs
      all_block_indicators.csv     # Merged output (one row per block)
      block_data_dictionary.md     # Data dictionary for block-level outputs
```

The `python/blocks/` scripts import shared utilities from `python/utils.py` (GEE auth, config loading, save_output) and add block-specific helpers in `utils_blocks.py` (GeoJSON loading, polygon-to-FeatureCollection conversion, block batching).

---

## Configuration

New block-level config section in `config.yaml`:

```yaml
# ---------- Block-Level Pipeline ----------
blocks:
  # Input GeoJSON files (one per city, or a single merged file)
  input_dir: "data/input/blocks"
  output_dir: "data/output/blocks"
  # Fixed analysis period for time-series indicators (heat, rainfall, AOD, nightlights)
  # Used instead of per-record fieldwork_date
  analysis_end_date: "2026-03-01"
  # Properties in GeoJSON features
  block_id_field: "block_id"
  city_field: "city"
  # Batch size (smaller than point pipeline due to polygon reduction cost)
  batch_size: 25
```

Indicator-specific parameters (datasets, thresholds, scale factors) are shared with the point pipeline via the existing config sections. The `blocks.analysis_end_date` combined with each indicator's `trailing_years` / `trailing_months` defines the temporal window.

---

## Implementation Order

1. **`utils_blocks.py`** — GeoJSON loading, polygon-to-FeatureCollection, block batching, output saving
2. **`extract_elevation_blocks.py`** — Simplest indicator, validates the zonal reduction pattern
3. **`extract_canopy_blocks.py`** — High-resolution (10m), many pixels per block, tests performance
4. **`extract_builtup_blocks.py`** — Same pattern as canopy (10m zonal stats)
5. **`extract_flood_blocks.py`** — Multi-source (HAND + JRC), fractional coverage computation
6. **`extract_heat_blocks.py`** — Time-series processing + zonal reduction
7. **`extract_rainfall_blocks.py`** — Time-series, coarse resolution
8. **`extract_airquality_blocks.py`** — Time-series, coarse resolution
9. **`extract_nightlights_blocks.py`** — Time-series, moderate resolution
10. **`run_all_blocks.py`** — Orchestrator + merge
11. **`block_data_dictionary.md`** — Documentation

---

## Key Design Decisions

| # | Decision | Selection | Rationale |
|---|---|---|---|
| B1 | Separate pipeline | `python/blocks/` subdirectory | Keeps point-level extraction intact; different input format, analysis unit, and use case |
| B2 | Input format | GeoJSON block polygons | Native format from sampling frame; preserves polygon geometry for zonal stats |
| B3 | Temporal window | Fixed per-city analysis period | Blocks have no fieldwork date; a common window ensures comparability across blocks |
| B4 | Spatial reduction | `reduceRegions` over block polygon | The block itself is the analysis unit — no buffers, no centroids |
| B5 | Output key | `block_id` | One row per block in output CSV |
| B6 | Shared config | Same `config.yaml`, new `blocks:` section | Reuses dataset IDs, thresholds, scale factors; adds block-specific settings |
| B7 | Batch size | 25 blocks (default) | Polygon reductions are more compute-intensive than point samples |
| B8 | Shared utilities | Import from `python/utils.py` | GEE auth, config loading, save_output are reusable; block-specific helpers in `utils_blocks.py` |

