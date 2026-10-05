# CLAUDE.md

## Project overview

`cfi-environdata` is a Python utility that extracts remote-sensing environmental indicators from Google Earth Engine (GEE) for business GPS locations across five emerging market cities (Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos) as part of the CFI MAP2 Round 2 study of micro and small enterprises.

The utility has two pipelines:
1. **Point-level**: Extracts indicators at individual business GPS coordinates → `data/output/all_indicators.csv` (consumed by `cfi-map2r2-data`)

**16 of the 17 indicators read Google Earth Engine.** Indicator 14 (WorldPop R2025A) reads downloaded GeoTIFFs with `rasterio` instead, because that release is not in the GEE catalog — run `python3 fetch_worldpop.py` once before `run_all.py`, or it fails with a clear message naming the missing file. In the block pipeline it is dispatched by `LOCAL_RASTER_INDICATORS` in `block_indicators.py` to its own zonal function rather than `reduceRegions`; everything downstream (checkpointing, manifest, merge, registry validation) treats it identically to a GEE indicator.
2. **Block-level**: Computes zonal statistics over sampling frame block polygons → `data/output/blocks/all_block_indicators.csv` (for study-area-level spatial analysis)
3. **Yearly city panel**: `extract_heat_timeseries.py` → `data/output/heat_timeseries_yearly.csv`, one row per CITY x YEAR, each value a spatial mean over that city's whole sampling grid. A THIRD unit of analysis, for the long view back to 1940; it answers *when across decades*, where the block tables answer *where* and *when within two years*.

## Architecture

- **Language**: Python 3.12 (miniconda base environment at `/opt/miniconda3/bin/python`)
- **GEE project**: `ee-geogrids`
- **Config**: All parameters (thresholds, buffer radii, dataset IDs, batch sizes) are in `config.yaml`
- **Input**: CSV with columns `business_id`, `latitude`, `longitude`, `fieldwork_date`, `city`
- **Output**: Per-indicator CSVs + merged `all_indicators.csv` in `data/output/`

## File structure

```
config.yaml                  # All configurable parameters
requirements.txt             # earthengine-api, pandas, geopandas, pyyaml
python/
  utils.py                   # GEE auth, coordinate loading, batching, export
  prepare_gsmm_input.py      # Ingest: cfi-map2r2-data prepared coords -> data/input/gsmm_listings.csv
  make_registry.py           # Generates registry_environment.R for cfi-map2r2-data
  extract_elevation.py       # Indicator 1: SRTM 30m
  extract_heat.py            # Indicator 2: MODIS LST (per fieldwork_date)
  extract_flood.py           # Indicator 3: MERIT Hydro HAND + JRC surface water
  extract_canopy.py          # Indicator 4: ESA WorldCover 10m (50m + 150m buffers)
  extract_rainfall.py        # Indicator 5: CHIRPS daily (per city)
  extract_airquality.py      # Indicator 6: MODIS MAIAC AOD (per city)
  extract_nightlights.py     # Indicator 7: VIIRS monthly (per fieldwork_date)
  extract_builtup.py         # Indicator 8: JRC GHSL 10m (50m + 150m buffers)
  extract_population.py      # Indicator 9: WorldPop 100m density (50m + 150m buffers)
  extract_hrsl.py            # Indicator 10: Meta HRSL 31m density (50m + 150m buffers)
  extract_heatstress.py      # Indicator 11: ERA5-Land humid heat stress (sWBGT)
  extract_no2.py             # Indicator 12: Sentinel-5P tropospheric NO2
  extract_buildings.py       # Indicator 13: Open Buildings 2.5D count/height/size
  extract_pop2026.py         # Indicator 14: WorldPop R2025A 2026 (LOCAL raster, not GEE)
  extract_wind.py            # Indicator 15: ERA5-Land 10m wind (city-level control)
  extract_windgust.py        # Indicator 16: ERA5 hourly gusts (~28km, cross-city hazard)
  extract_utci.py            # Indicator 17: UTCI + mean radiant temp (ERA5-HEAT, 3rd-party)
  fetch_worldpop.py          # Downloads the 5 WorldPop R2025A national rasters
  worldpop2026.py            # Shared zonal engine for indicator 14 (points + blocks)
  run_all.py                 # Orchestrator: runs all 17 + merges + derives
  extract_heat_timeseries.py # YEARLY city x year heat panel (3rd unit of analysis)
  blocks/                    # Block-level aggregation pipeline
    utils_blocks.py          # Block polygon loading, batching, checkpoints
    block_indicators.py      # Specs reusing the POINT pipeline's image builders
    run_all_blocks.py        # Orchestrator: 10 indicators + merge
    make_block_registry.py   # Generates BOTH block registries (static + longitudinal)
    longitudinal_indicators.py # Per-period band builders (time-varying only)
    extract_longitudinal.py  # 45-day periodic block series -> long format
data/
  input/                     # Business coordinate CSVs
  input/worldpop/            # WorldPop R2025A national GeoTIFFs (~1.7 GB, git-ignored)
  input/blocks/              # Sampling frame GeoJSON files (from blockexplorer repo)
  output/                    # Point-level indicator CSVs + data_dictionary.md
  output/blocks/             # Block-level indicator CSVs + block_data_dictionary.md
registry_environment.R       # GENERATED business-level registry, ported to cfi-map2r2-data
registry_environment_blocks.R # GENERATED block-level registry, ported likewise
registry_environment_blocks_longitudinal.R # GENERATED block x period registry
inspect_indicators.ipynb     # Jupyter notebook for visual inspection (geemap)
plan.md                      # Implementation plan with design decisions
```

## Running the pipelines

**Point-level** (business GPS coordinates). Refresh the input from the latest
GSMM listing exports first, then extract:
```bash
cd python
python3 prepare_gsmm_input.py   # rebuilds data/input/gsmm_listings.csv
python3 fetch_worldpop.py       # one-off: WorldPop R2025A rasters for indicator 14
python3 run_all.py
```

`run_all.py` is **incremental**: a rerun extracts only businesses not already in
each indicator's output CSV, reusing the rest. Adding a city (or a newer GSMM
extract with more listings) costs only the new businesses, not the whole frame.

Reuse is gated on a **config fingerprint** per indicator, recorded in
`data/output/extraction_manifest.json`. When settings that affect an indicator's
*values* change, its cache and checkpoint are discarded and it recomputes in
full — so a file can never end up holding rows computed under two different
definitions. Performance-only keys (`batch_size`, `getinfo_timeout_sec`) are
excluded from the fingerprint, so tuning them does not force a rerun.

**The two pipelines keep SEPARATE manifests** — `data/output/extraction_manifest.json`
for points, `data/output/blocks/extraction_manifest.json` for blocks — and the
block pipeline must pass `block_config` (not `config`) to both `load_manifest`
and `save_manifest`. It passed `config` to the save until 2026-09-14, so it read
from `blocks/` but wrote to `data/output/`: block cache reuse never worked, and
every block run silently destroyed the point pipeline's fingerprints, forcing a
full 13-indicator recompute on the next `run_all.py`. Both failures were
invisible in the logs — the block run just said "Cache invalid" every time. If
either pipeline ever reports recomputing everything for no apparent reason,
check which manifest each is reading and writing first.

Within an indicator, each completed batch is checkpointed, so an interrupted run
also resumes mid-way. Useful flags:

```bash
python3 run_all.py --force              # ignore all caches, recompute everything
python3 run_all.py --only heat,rainfall # run a subset (skips the merge)
```

**Block-level** (sampling frame polygons):
```bash
cd python/blocks
python3 run_all_blocks.py
```

Each `extract_*.py` can also be run standalone. The working directory must be `python/` (or `python/blocks/` for block scripts) for relative imports to resolve.

## Key patterns

- **Batching**: All extraction scripts batch GEE API calls via `utils.batch_points()` (default 50 points per call) to avoid GEE memory limits.
- **GEE resilience**: Never call `.getInfo()` directly — use `utils.safe_getinfo()`, which adds a 300s client-side timeout (a stalled GEE `getInfo()` otherwise blocks forever) and 3 retries with exponential backoff. Every indicator appends each completed batch to `data/output/.checkpoint_{indicator}.csv` via `append_checkpoint()` and filters already-done points with `filter_remaining_points()`, then calls `finish_indicator()` to read the results back and delete the checkpoint. Buffer-based indicators (canopy, built-up) checkpoint per radius, e.g. `canopy_50m`. The same helpers exist in `blocks/utils_blocks.py` for the block pipeline; the two copies should stay in step.
- **Grouping strategy**: Time-series indicators (heat, nightlights) group by `fieldwork_date` to reuse the same image collection. Coarse-resolution indicators (rainfall at 5.5km, AOD at 1km) group by `city` instead for efficiency.
- **Buffer-based indicators**: Canopy and built-up compute zonal stats within circular buffers (50m, 150m). Nightlights use a 150m buffer. All others are point samples.
- **Column naming**: Buffer-dependent columns include the radius suffix (e.g., `canopy_fraction_50m`, `builtup_fraction_150m`).
- **GSMM ingestion**: `prepare_gsmm_input.py` consumes `../cfi-map2r2-data/data/processed/gsmm_coords_for_environdata.csv`. **That repo owns all preparation and cleaning** — export selection, de-duplication, date parsing, decimal normalisation — so those rules are not reimplemented here and cannot drift. This script only adapts the file to the input contract, and its one substantive job is the key: the source `business_id` is the bare Enterprise ID, unique only *within* a country (5 ids appear in two cities each), so it is rewritten as `<Country>_<Enterprise ID>` with the raw id kept as `enterprise_id`. It fails loudly rather than de-duplicating if a collision survives. `gsmm.include_cities` restricts the ingest.
- **Registry**: `make_registry.py` generates `registry_environment.R`, drop-in registry rows for the analysis app in `cfi-map2r2-data`. It fails if any `all_indicators.csv` column is neither registered nor explicitly excluded, so it cannot drift. Regenerate after adding indicators; never hand-edit the `.R`.
- **Population sources**: indicators 9 (WorldPop) and 10 (Meta HRSL) measure the same construct by different methods. They rank neighbourhoods similarly *within* a city (r = 0.73–0.95) but disagree sharply on level (Addis Ababa 12,314 vs 26,443 people/km²; Delhi 27,288 vs 66,336 — a factor of 2.4), so neither supports absolute or cross-city density claims. A THIRD was added 2026-09-21: indicator 14 (`pop2026_density_*`), WorldPop Global2 R2025A for **2026** — the only layer contemporaneous with fieldwork, the only one with no missing values at either radius, and the only one read from a local download rather than GEE. **But only 31% of its variance is within-city, against 76% for WorldPop G1 and 59% for HRSL**, exactly as WorldPop's own release statement warns for Global2 ("less spatially detailed than Global1... not capturing high urban population densities well"). Use it for level, currency and coverage; use G1 or HRSL to rank businesses within a city. It disagrees with both in Sao Paulo (r = +0.05 / +0.09) and Delhi (+0.22 / **-0.17**), so check all three before believing a within-city population result in those two cities. At BLOCK level the verdict flips — it ties HRSL on variance (62% vs 63%) and beats it on coverage and quantisation, so it is the better block map. All three are extracted deliberately as a sensitivity check. **HRSL is still the better default, but its margin narrowed as cities were added.** At the 150m radius HRSL has no missing values against WorldPop's 28 (North Jakarta coast, which HRSL shows are densely populated); at 50m HRSL now has 100 gaps of its own (86 of them Delhi) against WorldPop's 101, so the coverage advantage is a 150m result, not a general one. The independence argument weakened too: HRSL's raw pooled correlation with `builtup_fraction_150m` went -0.05 (three cities) → +0.19 (four) → **+0.17** (five), against WorldPop's 0.41 → 0.34 → 0.32 — HRSL is no longer meaningfully *uncorrelated*, only less correlated. Sao Paulo is the one city where the two sources nearly agree on level (18,174 vs 20,802), which is itself a caution: agreement is a property of the city, not of the products. Never put both in one model. HRSL is a **community-catalog** asset (`projects/sat-io/...`). With indicator 17's ERA5-HEAT (`projects/climate-engine-pro/...`) and indicator 14's local rasters, these are the pipeline's three dependencies outside the main GEE catalog — indicator 14 being the only one outside GEE entirely. Both GEE community assets can be moved or withdrawn by their owners; indicator 17 checks readability and fails loudly rather than writing nulls.
- **Fire and wind were the last two survey hazards without an environmental counterpart**, added 2026-09-30. They are opposite cases and should be read very differently. `building_spacing_m` / `building_spacing_ratio` (derived from the Open Buildings columns, no new extraction) are among the most spatially informative variables here — 89% and 75% within-city variance, and r = -0.02 with population density, so they add something the crowding measures do not. `wind_*` (ERA5-Land, indicator 15) is the opposite: an ~11km reanalysis with **no gust band**, 4-17% within-city variance, and winds so light that conventional damage thresholds return zero everywhere. Indicator 16 (`gust_*`, ERA5 hourly) fixes the MAGNITUDE problem - gusts reach 27.3 m/s in Sao Paulo, which records 114 gale-force hours against 0-1 everywhere else - but at ~28km it makes the RESOLUTION problem worse (1-8% within-city). **Both wind indicators rank cities; neither supports a within-city gradient**, and their within-city correlation is actually negative (r = -0.33), which is two near-constant fields disagreeing about misaligned grid boundaries, not signal. There is deliberately NO satellite fire product — FIRMS at 1km would miss every market-stall fire while catching the rare industrial one, and that failure is differential, so a spread-susceptibility proxy is used instead of pretending to observe events.
- **Two NIGHT-heat measures, and they disagree harder than the day ones.** Indicator 2's `heat_nights_*` count night LAND SURFACE temperature; indicator 11's `tropical_nights_gt*` count nights whose minimum 2m AIR temperature exceeds 20/25C - the standard ETCCDI index, gap-free at 730 nights in every city where the LST counts rest on denominators of 163-823. At the 25C threshold they give OPPOSITE rankings for the top two cities, by more than tenfold: night-LST puts Jakarta (0.49) above Lagos (0.36), air temperature gives Lagos 418 hot nights against Jakarta's 39. Explicable, not noise - Jakarta's nights are warmer at the SURFACE (25.6C v 24.7C) but cooler in the AIR (23.7C v 25.3C). Use air temperature for human exposure, LST for the surface energy balance, and never mix them in one argument. `tropical_nights_gt20c` saturates at 730 for both tropical cities, so rank with the 25C column.
- **A satellite joining mid-series is a trend trap, and the yearly panel is built around it.** Indicator 2 merges Terra and Aqua, which is right for a fixed two-year window and WRONG for a trend: Aqua starts mid-2002 and its ~13:30 overpass catches peaks Terra's ~10:30 never reaches, by 2.6-8.2C. A merged yearly series therefore STEPS UP in 2003 for instrumental reasons, by more than the climate trend it would sit inside. `heat_timeseries_yearly.csv` emits the LST metrics twice for this reason: `*_terra` (2001 on, one instrument throughout - USE FOR TRENDS) and unsuffixed Terra+Aqua (2003 on, better absolute peaks, not a consistent series). The ERA5 products have no such break, being reanalyses, but carry the opposite caveat: they are MODELLED, so 1940s values rest on far less observational input than recent ones while looking equally seamless.
- **Two humid-heat measures, and they disagree for a reason.** Indicator 11 (`wbgt_*`, ERA5-Land 11km) uses temperature and humidity only; indicator 17 (`utci_*`, ERA5-HEAT 28km) adds WIND and MEAN RADIANT TEMPERATURE. Keep both — `wbgt_*` for continuity, UTCI preferred on physics — and expect them to reorder the cities: on `wbgt_days_gt31c` Lagos leads Delhi, on `utci_days_gt38c` Delhi leads Lagos, because Lagos is the windiest city and sWBGT cannot see wind. UTCI also resolves a caveat `wbgt_days_gt31c` could only describe: it is 0 for both Addis Ababa and Sao Paulo "for different reasons", and UTCI measures that difference (Sao Paulo 180 strong-stress days, Addis Ababa 0). `mrt_*` is a genuinely new variable, not a restatement — it does not track air temperature, since high-altitude Addis Ababa gets the same radiant load as warmer Sao Paulo.
- **Threshold counts over HOURLY collections need a different idiom.** The daily-resolution indicators map one collection per threshold and `.sum()`. Over ERA5 hourly (17,520 images for a 2-year window) that costs a full pass per threshold and times out - three passes over one year exceeded 10 minutes. Indicator 16 instead uses ONE map producing a multi-band indicator image, summed once: same answer (verified identical to `fixedHistogram`), ~44s. Do not "simplify" it back.
- **Two ERA5 indicators, one coastal fill.** Indicators 11 and 15 both read ERA5-Land, which is masked over water; at 11km a coastal cell reads as sea while the businesses in it are on land. Both apply `focal_mean(radius=3, units="pixels", iterations=3)` then `unmask`, and `units="pixels"` is only safe because both reduce at ERA5's NATIVE scale. Indicator 15 shipped without it initially and had 520 gaps (512 Lagos, 8 Jakarta) that indicator 11 did not — **two indicators from one source disagreeing on which businesses exist.** Keep the two copies in step.
- **The config fingerprint hashes CONFIG, not CODE.** Changing an extractor's logic does not invalidate its cache, so a rerun silently reuses rows computed by the old code. After editing extraction logic, force that indicator explicitly (`run_all.py --only <name> --force`). This is how the wind coastal fill had to be applied.
- **Indicator 2 reads BOTH MODIS satellites.** Terra alone until 2026-10-02, which cost coverage *and* systematically missed the afternoon peak: Terra overpasses ~10:30 local, Aqua ~13:30. Merging roughly doubled valid observations (Lagos tripled, 65 to 199) and raised `lst_max_c` by 2.4-8.0C, with Aqua supplying the maximum in **every** city. It also reordered the cities and lifted `lst_max_c` within-city variance from 19% to 31% at points and 18% to 48% at blocks, so the column is a much better map than it was. The merged collection is built by `extract_heat.lst_collection()`, **shared by all three pipelines** so they cannot drift on which satellites they read. CONSEQUENCE: the exceedance columns count OBSERVATIONS, not days, and are named `heat_obs_gt*` / `heat_nights_obs_gt*` for that reason; `lst_valid_obs` now tops out near 1,460 rather than 730. The `*_frac_*` columns are unchanged in meaning.
- **The longitudinal block pipeline had no cache fingerprint until 2026-10-02.** It reused an output on nothing but file existence and row count, so a change to how a column is COMPUTED silently kept the old values — the Aqua merge would have updated the point and static-block tables while `long_heat_blocks.csv` held Terra-only numbers under the same names. It now fingerprints like the other two, with entries keyed `long_<name>` in the BLOCK manifest because the longitudinal indicators share names with the static ones and would otherwise overwrite their fingerprints.
- **Cross-city day-counts need the rate columns.** `heat_obs_gt*` and `aod_days_gt*` count exceedances among *observed* days, and cloud cover makes that denominator range 404–40 (LST) and 347–91 (AOD) across cities. `run_all.py` derives `*_frac_gt*` companions (`utils.add_exceedance_rates`) — always compare on those. Using raw AOD counts reverses the city ranking, putting Lagos last on air pollution when the rate puts it first. Rainfall needs no rate (CHIRPS is gap-filled, `rain_valid_obs` = 730 everywhere).
- **Density conversions must reduce at the source's native scale.** These datasets store a count per cell; `ee.Image.pixelArea()` reports area at the *requested* scale, so reducing finer than native inflates density (WorldPop at 30m vs 93m: 9.4x too high).
- **Coordinates are sensitive**: `data/input/gsmm_listings.csv` holds exact business locations and is git-ignored. `data/input/` is otherwise tracked, so never remove that rule, and never copy the file into `cfi-map2r2-data`. Only the derived indicators are safe to share back.
- **Block pipeline**: zonal means over sampling-grid polygons, for citywide maps. `block_indicators.py` **calls the point pipeline's image builders** (`_build_heat_image`, `build_no2_image`, `build_buildings_image`, `build_density_image`) rather than reimplementing them — the eight `extract_*_blocks.py` modules it replaced had drifted to a different window and indicator set. Both pipelines share `time_window.analysis_end_date`. Block IDs are prefixed with the city name.
- **Three registries, three units of analysis**: `registry_environment.R` (businesses, `frame = "Enumeration"`), `registry_environment_blocks.R` (blocks, `frame = "Block"`) and `registry_environment_blocks_longitudinal.R` (block-periods, `frame = "Block-period"`). Keep them separate unless the consuming app can distinguish units — an indicator sharing a name across them is not the same quantity.
- **Two block tables**: `all_block_indicators.csv` answers *where* (static, 10 indicators); `all_block_indicators_longitudinal.csv` answers *when* (6 time-varying indicators over 16 x 45-day periods, 1,925,024 rows on the complete five-city frame). Rainfall, ERA5 heat stress and AOD are dropped from the static table for low spatial variation and included in the longitudinal one for high temporal variation.
- **`reduceRegions` returns NULL when the reduction scale exceeds the polygon.** Blocks are ~149m, so CHIRPS (5,566m) and ERA5 (11,132m) yield entirely empty columns at native scale — the longitudinal pipeline caps the scale at 100m. Note this is the OPPOSITE hazard to `pixelArea`-derived densities, which inflate when reduced finer than native. Both fail silently; check coverage after adding any indicator.
- **Pixel-denominated operations are coupled to the reduction scale.** `focal_mean(units="pixels")` and `ee.Image.pixelArea()` both change meaning with scale. The ERA5 coastal fill reprojects to the native grid first for exactly this reason.
- **Block ids**: `all_block_indicators.csv` carries `block_id` (the RAW grid id, matching `final_sampling_grid_2026.geojson` and `enum_data`'s `BlockID`) and `block_uid` (city-prefixed). **Join on `city` + `block_id`** — raw ids restart at 1 in every city, so a bare join fans rows out.
- **The block set is a deliberate SUBSET of the 13 point indicators**, chosen on native resolution and measured within-city variance: a block map can only show what varies between blocks, and an 11km source gives one value per ~5,400 blocks. ERA5 heat stress, CHIRPS rainfall, night LST and most AOD are dropped for that reason (0-6% within-city variance on the five-city frame). `elevation_m` was dropped too, at 0.4%, and ADDED BACK on 2026-10-05: a pooled variance share is the right test for an indicator meant to vary everywhere and the wrong one for an indicator meant to vary somewhere. Elevation's 0.4% is dominated by a 2,300m between-city range and says nothing about the gradient inside a city - Jakarta's blocks span -9 to 82m, and the `coastal_lowland` flag derived from it reaches a near-maximal binary split there (46% of blocks, variance 0.2487 of 0.25) while being flat by construction in three cities. `slope_degrees` from the same DEM has 84%. **These shares are a property of the CITY SET, not of the data** — every city added has been extreme on some axis (Delhi denser and hotter, Sao Paulo brighter, steeper and taller), which enlarges the between-city term and shrinks the within-city share with nothing changing locally. Nightlights went 82% → 77% → 54% across the three frames on that mechanism alone, and buildings 98% → 98% → 80%. No indicator has ever changed side, so the selection is stable; but re-measure rather than quoting these across frames. See `data/output/blocks/block_data_dictionary.md`.

## Related repos

- `cfi-map2r2-data` — R analysis pipeline (fixest, ggplot2) that consumes the output CSV
- `cfi-map2-blockexplorer2026` — Shiny app with sampling grid GeoJSONs (source for synthetic test coordinates)

## Conventions

- Config changes go in `config.yaml`, not hardcoded in scripts
- GEE dataset IDs and band names are always in config, not in code
- New indicators follow the pattern: `extract_{name}.py` with a `extract_{name}(df, config)` function and a `main()` entrypoint
- The data dictionary (`data/output/data_dictionary.md`) must be updated when columns are added or changed
