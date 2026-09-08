# Data Dictionary: `all_block_indicators.csv`

Zonal statistics over the **sampling-grid block polygons**, for mapping environmental indicators across a whole city. One row per block. Produced by `python/blocks/run_all_blocks.py`.

**Last generated:** 2026-09-05 — **51,417 blocks** across Addis Ababa (15,842), Jakarta (26,293) and Lagos (9,282). Blocks are the full sampling grid, not the ~100 per city flagged `in_final_sample` — a citywide map needs the grid. Median block area ~22,000 m² (roughly 150 m square).

**Relationship to the business-level dataset.** Same GEE sources, same builders, same analysis window — `python/blocks/block_indicators.py` calls the point pipeline's image builders directly rather than reimplementing them, so the two cannot drift. What differs is the geometry: a zonal mean over the block polygon instead of a buffer around a point.

> **The window is shared.** Both pipelines read `time_window.analysis_end_date` (2026-07-31). Until 2026-09-05 the block pipeline had its own `blocks.analysis_end_date` of 2026-03-01, which silently put block maps and business-level values on **different periods**.

---

## Columns

| Column | Type | Units | Description |
|---|---|---|---|
| `block_id` | string | | **RAW grid id**, matching `final_sampling_grid_2026.geojson` and `enum_data`'s `BlockID`. **Not unique on its own** — ids restart at 1 in every city. |
| `block_uid` | string | | City-prefixed id (`Lagos_1234`), unique across all cities. Convenience for single-key joins. |
| `city` | string | | One of Addis Ababa, Jakarta, Lagos. |
| `slope_degrees` | float | degrees | Mean terrain slope (SRTM 30 m). Landslide proxy and runoff term. |
| `lst_max_c` | float | °C | Maximum daytime land surface temperature over the window (MODIS 1 km). |
| `hand_m` | float | metres | Mean Height Above Nearest Drainage (MERIT Hydro ~90 m). Lower = more flood-susceptible. |
| `canopy_fraction` | float | proportion (0–1) | Share of block area classified tree cover (ESA WorldCover 10 m). |
| `builtup_fraction` | float | proportion (0–1) | Share of block area covered by built surface (GHSL 100 m). |
| `ntl_mean_radiance` | float | nW/cm²/sr | Mean nighttime radiance over the trailing 12 months (VIIRS 500 m). |
| `hrsl_density` | float | people per km² | Mean population density (Meta HRSL ~31 m). |
| `building_height_mean` | float | metres | Mean height of buildings in the block (Open Buildings 2.5D, 0.5 m). |
| `building_fractional_count` | float | buildings per 0.5 m pixel | Mean fractional building count. **Not a building count** — see below. |
| `heat_exposure_index` | float | z-score | Within-city composite heat exposure. 0 is the city mean. |

## Values by city — mean (SD)

| Indicator | Addis Ababa | Jakarta | Lagos |
|---|---|---|---|
| `slope_degrees` | 5.22 (2.84) | 3.0 (1.56) | 2.73 (1.16) |
| `lst_max_c` | 34.48 (1.8) | 40.55 (1.15) | 34.78 (1.94) |
| `hand_m` | 30.5 (27.54) | 3.24 (3.15) | 2.13 (1.96) |
| `canopy_fraction` | 0.061 (0.126) | 0.115 (0.164) | 0.053 (0.144) |
| `builtup_fraction` | 0.267 (0.132) | 0.392 (0.103) | 0.359 (0.196) |
| `ntl_mean_radiance` | 39.81 (36.35) | 28.19 (10.47) | 22.51 (15.68) |
| `hrsl_density` | 23045.0 (16303.0) | 20003.0 (2725.0) | 10091.0 (12280.0) |
| `building_height_mean` | 7.48 (4.91) | 8.01 (6.13) | 6.42 (3.74) |
| `no2_mean` | 39.18 (13.29) | 122.71 (22.79) | 55.49 (14.47) |
| `heat_exposure_index` | -0.0 (0.64) | 0.0 (0.73) | 0.0 (0.77) |

`hand_m` is the clearest discriminator: highland Addis Ababa sits 30 m above drainage on average against 2.1 m in coastal Lagos, and it retains large *within*-city spread (Addis SD 27.5, range 0–276 m).

> ### Merging back onto the sampling frame
>
> **Join on `city` + `block_id`.** Raw grid ids restart at 1 in every city, so a join on `block_id` alone fans rows out — the same trap as the business frame's `country` + `enterprise_id`. Use `block_uid` if a single-column key is needed.
>
> ```r
> grid <- st_read("final_sampling_grid_2026.geojson")     # block_id is character
> blocks <- read_csv("all_block_indicators.csv")
> grid |> left_join(filter(blocks, city == "Lagos"), by = "block_id")
> ```
>
> Verified against the source grid: Addis Ababa 15,842, Jakarta 26,293 and Lagos 9,282 blocks all merge one-to-one with no fan-out.

---

## Which indicators are here, and which are deliberately not

The block set is a **subset** of the 13 run at business level, chosen on native resolution and measured within-city variance. **A block map can only show what varies between blocks.** At ~150 m blocks a 1 km source gives one value per ~44 blocks and an 11 km source one per ~5,400 — mapping those renders an upsampled raster, not spatial pattern.

**Kept, fine-grained** (85–98% of variance is within-city): buildings 0.5 m, canopy and built-up 10 m, slope 30 m, HRSL 31 m, HAND 90 m, nightlights 500 m.

**Kept despite being coarse**, because the hazard matters and nothing finer exists: `lst_max_c` (1 km, 22% within-city) and `no2_mean` (1.1 km, 14%). **Expect smooth surfaces from these two, not block-level detail.**

**Dropped:**

| Dropped | Native | Within-city variance |
|---|---|---|
| ERA5 humid heat stress (`wbgt_*`, `t2m_*`, `rh_*`) | 11 km | 0–5% |
| CHIRPS rainfall | 5.5 km | 4–13% |
| Night LST, `heat_nights_*` | 1 km | 0–1% |
| Most AOD columns | 1 km | 6–9% |
| `elevation_m` | 30 m | **0.4%** |

Elevation is the instructive case: fine resolution but almost no *within*-city variance, because the between-city range (Addis Ababa 2,300 m vs Lagos 9 m) swamps anything local. `slope_degrees`, from the same DEM, has 93%. Use the business-level dataset for the dropped indicators — they remain excellent for comparing cities, just not for mapping within one.

---

## Caveats

**`building_fractional_count` is not a building count.** It is the mean fractional-count value per 0.5 m pixel. The business-level pipeline converts this to a count by multiplying by the pixels in a fixed-radius buffer, but blocks vary in area, so no single constant applies. Derive density downstream using each block's own area: `count ≈ building_fractional_count × block_area_m² / 0.25`. Storing a "count" that silently assumed a fixed area would have been wrong.

**`heat_exposure_index` is a THREE-component analogue**, not the business-level index. Blocks extract `lst_max_c` but not `lst_mean_c`, so it is the mean of signed within-city z-scores of `lst_max_c`, `builtup_fraction` and minus `canopy_fraction`. Conceptually parallel to the four-component business-level index, **not numerically comparable to it**. As with that index, levels are **not comparable across cities** — every city has mean 0 by construction.

**`hrsl_density` is quantised into modes.** HRSL disaggregates census counts, allocating uniformly across detected buildings within a census unit, so blocks inside one unit share a density. Jakarta's values cluster tightly (1st–99th percentile 17,275–25,143) while Addis Ababa's span 10,602–86,224. This is a property of the product, not of the extraction: the business-level pipeline reproduces the same percentiles to within ~1 person/km².

**Missing values** (of 51,417 blocks):

| Column | Missing | Cause |
|---|---|---|
| `lst_max_c` | 662 | cloud-masked MODIS pixels |
| `hand_m` | 9 | outside product coverage |
| `hrsl_density` | 540 | outside product coverage |
| `building_height_mean` | 376 | no buildings detected in the block |
| `heat_exposure_index` | 662 | derived from lst_max_c |

---

## Reproduction

```bash
cd python/blocks
python3 run_all_blocks.py                      # all configured indicators
python3 run_all_blocks.py --only canopy,flood  # subset (skips the merge)
python3 run_all_blocks.py --force              # ignore caches
```

Per-indicator outputs are written as `<name>_blocks.csv` and merged into `all_block_indicators.csv`. Each completed batch is checkpointed, so an interrupted run resumes; the checkpoint is cleared only **after** the output is safely written.

Reuse of a cached per-indicator CSV is gated on a **config fingerprint** (`extraction_manifest.json` in the block output directory), so changing the analysis window or a dataset recomputes rather than silently reusing stale output. A `--only` run **never** rewrites `all_block_indicators.csv`, since a partial merge would drop every column it did not just compute.

**Scope** is controlled by `blocks.include_cities` (currently the three complete cities) and `blocks.final_sample_only` (false — the flag marks only ~100 blocks per city).


---

# Companion table: `all_block_indicators_longitudinal.csv`

The static table above answers **where**; this one answers **when**. Same blocks, same two-year window, but each indicator computed over successive **45-day periods**.

**822,672 rows** = 51,417 blocks x 16 periods, long format, one row per block-period.

| Column | Description |
|---|---|
| `block_id` | RAW grid id — **join on `city` + `block_id` + `period_index`** |
| `block_uid` | City-prefixed unique block key |
| `city` | Addis Ababa, Jakarta or Lagos |
| `period_index` | 0–15 |
| `period_start`, `period_end` | Period bounds (YYYY-MM-DD) |
| `lst_max_c`, `lst_mean_c`, `lst_valid_obs` | Land surface temperature; clear-sky observation count |
| `rain_total_mm`, `rain_days_dry`, `rain_max_day_mm` | Precipitation |
| `aod_mean`, `aod_valid_obs` | Aerosol optical depth; valid retrievals |
| `ntl_mean_radiance` | Nighttime lights |
| `wbgt_mean_c`, `rh_mean_pct` | Humid heat stress; relative humidity |
| `no2_mean` | Tropospheric NO2 |

**Periods:** 16 of 45 days, 2024-07-31 to 2026-07-21. 730 / 45 = 16.2, so only **whole** periods are emitted; the 10-day remainder is dropped because a short final period would have sums and counts not comparable with the rest.

## Which indicators, and why these

**Only TIME-VARYING indicators.** Slope, HAND, canopy (WorldCover 2021), built-up (GHSL 2020), HRSL and buildings (2023) are single-epoch rasters — per-period values would be 16 identical copies, waste that also *looks* like data. They stay in the static table.

**Three of the six were dropped from the static block map for low SPATIAL variation and return here on their TEMPORAL variation**: rainfall, ERA5 heat stress and AOD. That is the purpose of this table.

## Seasonality — Lagos, by period

| # | Starts | Rain (mm) | LST max (°C) | AOD | NO2 | WBGT (°C) |
|---|---|---|---|---|---|---|
| 0 | 2024-07-31 | 62 | 31.9 | 0.27 | 28 | 29.3 |
| 1 | 2024-09-14 | 430 | 31.5 | 0.31 | 45 | 30.3 |
| 2 | 2024-10-29 | 86 | 34.5 | 0.61 | 87 | 31.5 |
| 3 | 2024-12-13 | 12 | 32.3 | 0.82 | 81 | 31.1 |
| 4 | 2025-01-27 | 95 | 31.6 | 0.79 | 53 | 32.6 |
| 5 | 2025-03-13 | 250 | 33.6 | 0.41 | 43 | 32.6 |
| 6 | 2025-04-27 | 327 | 31.5 | 0.38 | 41 | 31.7 |
| 7 | 2025-06-11 | 420 | 26.8 | 0.33 | 39 | 29.6 |
| 8 | 2025-07-26 | 160 | 27.6 | 0.34 | 31 | 28.6 |
| 9 | 2025-09-09 | 366 | 28.3 | 0.28 | 41 | 29.9 |
| 10 | 2025-10-24 | 175 | 30.8 | 0.48 | 57 | 31.4 |
| 11 | 2025-12-08 | 147 | 30.3 | 0.54 | 64 | 31.8 |
| 12 | 2026-01-22 | 60 | 29.9 | 0.74 | 62 | 32.0 |
| 13 | 2026-03-08 | 211 | 32.0 | 0.40 | 46 | 32.5 |
| 14 | 2026-04-22 | 341 | 30.7 | 0.39 | 41 | 32.0 |
| 15 | 2026-06-06 | 599 | 26.2 | 0.48 | 60 | 30.4 |

Rainfall swings **12 to 599 mm** across periods, AOD **0.27 to 0.82** with peaks in the Harmattan dust season, NO2 **28 to 87**. Each varies far more over time than across blocks — the reason they were excluded from the static map and included here.

## Caveats

**Resolution relative to a block.** Only `lst_max_c` (1km) approaches block scale; rainfall is 5.5km (~37 blocks wide) and ERA5 heat stress 11km (~74 blocks). **Read this table along the TIME axis**; use the static table for spatial pattern. ERA5 is nonetheless *not* constant within a city — 61–249 distinct values per city-period, with up to 2.47°C spread across Addis Ababa, since its grid spans 2–3 cells and picks up elevation.

**Reduction scale is capped at 100m** (`blocks_longitudinal.max_reduce_scale_m`). `reduceRegions` evaluates at the requested scale, so a scale coarser than the ~149m block returns NULL for every block: CHIRPS at 5,566m and ERA5 at 11,132m both produced entirely empty columns before this cap. Safe here because every metric is a mean or a per-pixel temporal statistic, never a `pixelArea`-derived density.

**Missing values** (of 822,672 block-periods):

| Column | Missing | Cause |
|---|---|---|
| `lst_max_c`, `lst_mean_c`, `lst_valid_obs` | 202,804 (25%) | **Seasonal cloud — and itself a signal.** Coverage falls to 46–57% in Dec–Mar and Oct–Jan, recovering to 84–99% otherwise; Addis Ababa 100%, Jakarta 65%, Lagos 62%. `lst_valid_obs` makes this measurable rather than hidden. |
| `aod_mean`, `aod_valid_obs` | 51,271 (6%) | Cloud screening on MAIAC retrievals. |
| `wbgt_mean_c`, `rh_mean_pct` | 23,568 (3%) | 1,473 Lagos blocks x 16 periods, all on Lagos Island / Victoria Island / the lagoon, which ERA5-Land masks as water. A focal fill from neighbouring land recovers Jakarta entirely and most of Lagos, but not blocks this deep inside the lagoon. Purely spatial: the same blocks in every period. |
| `no2_mean` | 962 (0.1%) | Sparse Sentinel-5P retrievals in a few block-periods. |

## Reproduction

```bash
cd python/blocks
python3 extract_longitudinal.py                      # all six
python3 extract_longitudinal.py --only rainfall,no2  # subset (skips the merge)
python3 extract_longitudinal.py --force              # ignore caches
```

Each indicator is assembled into ONE multi-band image holding (metric x period) bands, so a single request per block batch returns every period. Total server-side work is about that of the static pipeline rather than 16x it, because summing 730 days costs roughly what summing 16 chunks of 45 days costs.
