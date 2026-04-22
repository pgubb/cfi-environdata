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

