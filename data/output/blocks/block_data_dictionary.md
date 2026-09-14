# Data Dictionary: `all_block_indicators.csv`

Zonal statistics over the **sampling-grid block polygons**, for mapping environmental indicators across a whole city. One row per block. Produced by `python/blocks/run_all_blocks.py`.

**Last generated:** 2026-09-14 — **120,314 blocks across all five cities**: Sao Paulo (38,017), Delhi (30,880), Jakarta (26,293), Addis Ababa (15,842) and Lagos (9,282). Sao Paulo was added on 2026-09-14, completing the frame; the other four cities' values were reused unchanged, so only Sao Paulo's blocks were recomputed. Blocks are the full sampling grid, not the ~100 per city flagged `in_final_sample` — a citywide map needs the grid. Median block area ~22,000 m² (roughly 150 m square).

**Relationship to the business-level dataset.** Same GEE sources, same builders, same analysis window — `python/blocks/block_indicators.py` calls the point pipeline's image builders directly rather than reimplementing them, so the two cannot drift. What differs is the geometry: a zonal mean over the block polygon instead of a buffer around a point.

> **The window is shared.** Both pipelines read `time_window.analysis_end_date` (2026-07-31). Until 2026-09-05 the block pipeline had its own `blocks.analysis_end_date` of 2026-03-01, which silently put block maps and business-level values on **different periods**.

---

## Columns

| Column | Type | Units | Description |
|---|---|---|---|
| `block_id` | string | | **RAW grid id**, matching `final_sampling_grid_2026.geojson` and `enum_data`'s `BlockID`. **Not unique on its own** — ids restart at 1 in every city. |
| `block_uid` | string | | City-prefixed id (`Lagos_1234`), unique across all cities. Convenience for single-key joins. |
| `city` | string | | One of Addis Ababa, Delhi, Jakarta, Lagos, Sao Paulo. |
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

| Indicator | Addis Ababa | Delhi | Jakarta | Lagos | Sao Paulo |
|---|---|---|---|---|---|
| `slope_degrees` | 5.22 (2.84) | 3.30 (1.27) | 3.00 (1.56) | 2.73 (1.16) | **6.16 (2.85)** |
| `lst_max_c` | 34.5 (1.8) | 41.5 (1.2) | 40.5 (1.2) | 34.8 (1.9) | 37.6 (2.3) |
| `hand_m` | 30.5 (27.5) | 2.6 (3.0) | 3.2 (3.1) | 2.1 (2.0) | 20.6 (16.3) |
| `canopy_fraction` | 0.061 (0.126) | 0.146 (0.199) | 0.115 (0.164) | 0.053 (0.144) | 0.100 (0.158) |
| `builtup_fraction` | 0.267 (0.132) | 0.355 (0.156) | 0.392 (0.103) | 0.359 (0.196) | **0.408 (0.109)** |
| `ntl_mean_radiance` | 39.8 (36.3) | 40.8 (18.7) | 28.2 (10.5) | 22.5 (15.7) | **59.2 (21.9)** |
| `hrsl_density` | 23,045 (16,303) | 62,084 (41,778) | 20,003 (2,725) | 10,091 (12,280) | 18,246 (20,658) |
| `building_height_mean` | 7.5 (4.9) | 8.7 (4.6) | 8.0 (6.1) | 6.4 (3.7) | **10.3 (8.5)** |
| `no2_mean` | 39.2 (13.3) | 110.6 (19.6) | 122.7 (22.8) | 55.5 (14.5) | **144.2 (25.7)** |
| `heat_exposure_index` | -0.00 (0.64) | -0.00 (0.73) | 0.00 (0.73) | 0.00 (0.77) | -0.00 (0.80) |

`hand_m` is the clearest discriminator: highland Addis Ababa sits 30 m above drainage on average against 2.1 m in coastal Lagos, 2.6 m in Delhi and 3.2 m in Jakarta, and it retains large *within*-city spread (Addis SD 27.5, range 0–276 m).

**Delhi is the outlier on density and greenness.** Its `hrsl_density` mean of 62,084/km² is 2.7x the next city's and carries the widest spread (SD 41,778), and at 0.146 it has the highest `canopy_fraction` of the five — Delhi's grid includes substantial green space that the others' sampling frames do not.

**Sao Paulo leads four of the ten columns** — steepest, most built-up, brightest and worst on NO₂ — and is second on building height. It is also the largest city in the frame at 38,017 blocks, 32% of all rows. Like Delhi, it enlarges the between-city variance term, which is why several within-city variance shares fell again when it was added (see below).

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
> Verified against the source grid: Addis Ababa 15,842, Delhi 30,880, Jakarta 26,293, Lagos 9,282 and Sao Paulo 38,017 blocks all merge one-to-one with no fan-out.

---

## Which indicators are here, and which are deliberately not

The block set is a **subset** of the 13 run at business level, chosen on native resolution and measured within-city variance. **A block map can only show what varies between blocks.** At ~150 m blocks a 1 km source gives one value per ~44 blocks and an 11 km source one per ~5,400 — mapping those renders an upsampled raster, not spatial pattern.

**Kept, fine-grained** (54–93% of variance is within-city): canopy and built-up 10 m, slope 30 m, buildings 0.5 m, HRSL 31 m, HAND 90 m, nightlights 500 m.

**Kept despite being coarse**, because the hazard matters and nothing finer exists: `lst_max_c` (1 km, 19% within-city) and `no2_mean` (1.1 km, 13%). **Expect smooth surfaces from these two, not block-level detail.**

> ### These shares are a property of the city set, not of the data
>
> They are measured at business points on whatever frame is current, and every city added so far has been extreme on some axis — Delhi denser, hotter and more polluted; Sao Paulo brighter, steeper and taller. Each addition enlarges the *between*-city term and mechanically shrinks the within-city share **without anything changing locally**. Tracked across the three frames:
>
> | Indicator | 3 cities | 4 cities | 5 cities |
> |---|---|---|---|
> | Nightlights | 82% | 77% | **54%** |
> | Buildings (height) | 98% | 98% | **80%** |
> | Slope | 93% | 94% | **84%** |
> | HRSL | 86% | 60% | **59%** |
> | Built-up | 47% | 57% | **59%** |
> | HAND | 66% | 64% | **64%** |
> | `lst_max_c` | 22% | 16% | **19%** |
>
> HAND is the only one that barely moves. **No indicator has changed side** across any frame, and the three tiers stay cleanly separated (54–93% / 13–19% / 0.4–6%), so the selection below still stands. But re-measure rather than quoting these after any change to the city set, and never compare a figure from one frame with a figure from another.

**Dropped:**

| Dropped | Native | Within-city variance |
|---|---|---|
| ERA5 humid heat stress (`wbgt_*`, `t2m_*`, `rh_*`) | 11 km | 0–3% |
| CHIRPS rainfall | 5.5 km | 6% |
| Night LST, `heat_nights_*` | 1 km | 2% |
| Most AOD columns | 1 km | 2% |
| `elevation_m` | 30 m | **0.4%** |

Elevation is the instructive case: fine resolution but almost no *within*-city variance, because the between-city range (Addis Ababa 2,300 m vs Lagos 9 m) swamps anything local. `slope_degrees`, from the same DEM, has 84%. Use the business-level dataset for the dropped indicators — they remain excellent for comparing cities, just not for mapping within one.

---

## Caveats

**`building_fractional_count` is not a building count.** It is the mean fractional-count value per 0.5 m pixel. The business-level pipeline converts this to a count by multiplying by the pixels in a fixed-radius buffer, but blocks vary in area, so no single constant applies. Derive density downstream using each block's own area: `count ≈ building_fractional_count × block_area_m² / 0.25`. Storing a "count" that silently assumed a fixed area would have been wrong.

**`heat_exposure_index` is a THREE-component analogue**, not the business-level index. Blocks extract `lst_max_c` but not `lst_mean_c`, so it is the mean of signed within-city z-scores of `lst_max_c`, `builtup_fraction` and minus `canopy_fraction`. Conceptually parallel to the four-component business-level index, **not numerically comparable to it**. As with that index, levels are **not comparable across cities** — every city has mean 0 by construction.

**`hrsl_density` is quantised into modes.** HRSL disaggregates census counts, allocating uniformly across detected buildings within a census unit, so blocks inside one unit share a density. Jakarta's values cluster tightly (1st–99th percentile 17,275–25,143) while Addis Ababa's span 10,602–86,224, Delhi's 10,688–169,258 and Sao Paulo's 467–91,631 — Sao Paulo's 1st percentile is by far the lowest, so it contributes genuinely near-empty blocks no other city has. This is a property of the product, not of the extraction: the business-level pipeline reproduces the same percentiles to within ~1 person/km².

**Missing values** (of 120,314 blocks):

| Column | Missing | Cause |
|---|---|---|
| `lst_max_c` | 662 | cloud-masked MODIS pixels (Lagos 554, Jakarta 108) — Sao Paulo adds none |
| `hand_m` | 9 | outside product coverage (all Lagos) |
| `hrsl_density` | 1,576 | outside product coverage (Delhi 782, Addis Ababa 267, Sao Paulo 254, Lagos 192, Jakarta 81) |
| `building_height_mean` | 812 | no buildings detected in the block (Delhi 317, Lagos 216, Sao Paulo 119, Jakarta 105, Addis Ababa 55) |
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

**1,925,024 rows** = 120,314 blocks x 16 periods, long format, one row per block-period.

| Column | Description |
|---|---|
| `block_id` | RAW grid id — **join on `city` + `block_id` + `period_index`** |
| `block_uid` | City-prefixed unique block key |
| `city` | Addis Ababa, Delhi, Jakarta, Lagos or Sao Paulo |
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

## Seasonality — Delhi, by period

Delhi has the sharpest seasonal cycle of the five cities and is the clearest illustration of what this table is for:

| # | Starts | Rain (mm) | LST max (°C) | AOD | NO2 | WBGT (°C) |
|---|---|---|---|---|---|---|
| 0 | 2024-07-31 | 478 | 31.4 | 0.47 | 59 | 32.5 |
| 1 | 2024-09-14 | 16 | 35.1 | 0.81 | 106 | 28.9 |
| 2 | 2024-10-29 | 3 | 31.5 | 1.14 | 128 | 21.5 |
| 3 | 2024-12-13 | 11 | 19.7 | 0.99 | **167** | **16.2** |
| 4 | 2025-01-27 | 10 | 29.8 | 0.51 | 114 | 19.2 |
| 5 | 2025-03-13 | 2 | 39.5 | 0.56 | 107 | 24.4 |
| 6 | 2025-04-27 | 43 | 40.5 | 0.91 | 98 | 30.3 |
| 7 | 2025-06-11 | 261 | 35.5 | **1.24** | 76 | **33.3** |
| 8 | 2025-07-26 | 419 | 29.2 | 0.45 | 54 | 32.3 |
| 9 | 2025-09-09 | 73 | 34.4 | 0.81 | 81 | 28.8 |
| 10 | 2025-10-24 | 28 | 27.8 | 1.15 | 123 | 20.0 |
| 11 | 2025-12-08 | 2 | 18.5 | 0.77 | 164 | 16.3 |
| 12 | 2026-01-22 | 12 | 29.7 | 0.52 | 116 | 19.2 |
| 13 | 2026-03-08 | 62 | 36.2 | 0.39 | 92 | 24.0 |
| 14 | 2026-04-22 | 43 | 41.5 | 0.58 | 98 | 29.0 |
| 15 | 2026-06-06 | 182 | 38.3 | 0.85 | 78 | 32.9 |

**Every column moves, and they do not move together.** sWBGT swings **16.2 to 33.3 °C** — a 17 °C annual range against Jakarta's 1.3 °C — while NO2 peaks at 167 in the *coldest* periods (winter inversion traps combustion products) and bottoms out at 54 in the monsoon. AOD peaks twice, once in the post-monsoon crop-burning window (1.14–1.15) and once in June (1.24). A single annual mean for Delhi averages across states that have almost nothing in common; the business-level table, which reports exactly that annual mean, cannot show this.

**The five cities split into two seasonal regimes.** Delhi (sWBGT 16.2–33.3 °C) and Sao Paulo (17.7–26.2 °C) have real annual cycles; Jakarta (29.5–30.8) and Lagos (28.6–32.6) are effectively aseasonal; Addis Ababa (15.0–17.9) sits between. **An annual mean is a reasonable summary for the equatorial pair and a poor one for the other three** — which is the single most useful thing this table tells you about when the business-level columns can be trusted at face value.

Sao Paulo is also worth noting on pollution: its NO2 peaks at **194**, the highest any city reaches in any period, while its AOD floor of **0.08** is the lowest — the same city at opposite ends of the two measures, and its AOD ceiling (0.45) sits below Delhi's floor (0.39), so the two never overlap.

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

**Resolution relative to a block.** Only `lst_max_c` (1km) approaches block scale; rainfall is 5.5km (~37 blocks wide) and ERA5 heat stress 11km (~74 blocks). **Read this table along the TIME axis**; use the static table for spatial pattern. ERA5 is nonetheless *not* constant within a city — 56–439 distinct values per city-period, with up to 2.47°C spread across Addis Ababa and 2.45°C across Sao Paulo, since its grid spans several cells and picks up elevation. Delhi has many distinct values (360–395) but the *smallest* spatial spread (0.38°C): many grid cells, all nearly identical, because the terrain is flat. Sao Paulo has both the most cells (385–439) and a large spread, being both big and hilly.

**Reduction scale is capped at 100m** (`blocks_longitudinal.max_reduce_scale_m`). `reduceRegions` evaluates at the requested scale, so a scale coarser than the ~149m block returns NULL for every block: CHIRPS at 5,566m and ERA5 at 11,132m both produced entirely empty columns before this cap. Safe here because every metric is a mean or a per-pixel temporal statistic, never a `pixelArea`-derived density.

**Missing values** (of 1,925,024 block-periods):

| Column | Missing | Cause |
|---|---|---|
| `lst_max_c`, `lst_mean_c`, `lst_valid_obs` | 205,749 (11%) | **Seasonal cloud — and itself a signal.** Coverage falls to 77–82% in the cloudiest periods, recovering to 93–99% otherwise; Addis Ababa 100%, Sao Paulo 100%, Delhi 99%, Jakarta 65%, Lagos 62%. The overall rate has fallen 25% → 16% → 11% purely because the cities added were cloud-free — **the absolute count has not changed at all since Delhi, and Jakarta and Lagos have not improved by a single block-period**. Never read the headline rate as coverage getting better. `lst_valid_obs` makes this measurable rather than hidden. |
| `aod_mean`, `aod_valid_obs` | 66,435 (3%) | Cloud screening on MAIAC retrievals, very unevenly: Lagos 9%, Jakarta 6%, Addis Ababa 5%, Delhi 3%, **Sao Paulo 0%** — the only city with complete AOD coverage. |
| `wbgt_mean_c`, `rh_mean_pct` | 23,568 (3%) | 1,473 Lagos blocks x 16 periods, all on Lagos Island / Victoria Island / the lagoon, which ERA5-Land masks as water. A focal fill from neighbouring land recovers Jakarta entirely and most of Lagos, but not blocks this deep inside the lagoon. Purely spatial: the same blocks in every period. |
| `no2_mean` | 1,182 (0.1%) | Sparse Sentinel-5P retrievals in a few block-periods (Jakarta 962, Sao Paulo 220). |

## Reproduction

```bash
cd python/blocks
python3 extract_longitudinal.py                      # all six
python3 extract_longitudinal.py --only rainfall,no2  # subset (skips the merge)
python3 extract_longitudinal.py --force              # ignore caches
```

Each indicator is assembled into ONE multi-band image holding (metric x period) bands, so a single request per block batch returns every period. Total server-side work is about that of the static pipeline rather than 16x it, because summing 730 days costs roughly what summing 16 chunks of 45 days costs.


---

## Registry

`registry_environment_blocks_longitudinal.R` at the repo root holds drop-in registry rows for this table: **12 indicators across 5 `envlong_*` domains**, `frame = "Block-period"`, schema matching `R/registry.R`. Generated together with the static block registry by `python/blocks/make_block_registry.py`, which fails if any column is neither registered nor explicitly excluded.

**This is a third unit of analysis.** `registry_environment.R` describes businesses, `registry_environment_blocks.R` describes blocks, and this describes block-periods. Never mix them in one estimate: a 150m buffer around a business, the block containing it, and that block during one 45-day window are three different regions of space-time, even where an indicator name is shared.
