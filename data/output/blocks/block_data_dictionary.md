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
